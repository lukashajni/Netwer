"""Wi-Fi information and nearby access-point scans."""
import os
import re
import shutil
import subprocess
import sys

from . import windows_network

used_os = sys.platform


def _nmcli(*args):
    env = os.environ.copy()
    env["LC_ALL"] = "C"
    result = subprocess.run(
        ["nmcli", *args], capture_output=True, text=True, env=env)
    return result.stdout.strip()


def _terse_fields(line):
    """Split nmcli terse output, accounting for escaped colons."""
    fields = re.split(r'(?<!\\):', line)
    return [f.replace('\\:', ':').replace('\\\\', '\\') for f in fields]


def _wifi_device_name():
    for line in _nmcli("-t", "-f", "DEVICE,TYPE", "device", "status").splitlines():
        device, _, dtype = line.partition(":")
        if dtype == "wifi":
            return device
    return None


def get_wifi_info_linux():
    def _radio_standard(device):
        if not shutil.which("iw"):
            return None
        try:
            out = subprocess.run(
                ["iw", "dev", device, "link"],
                capture_output=True, text=True).stdout
        except Exception:
            return None
        if "HE-MCS" in out or "HE-NSS" in out:
            return "802.11ax"
        if "VHT-MCS" in out:
            return "802.11ac"
        if re.search(r'\bMCS\b', out):
            return "802.11n"
        return None

    def _band_label(freq_field, radio):
        digits = re.sub(r'\D', '', str(freq_field))
        freq = int(digits) if digits else None
        if freq is None:
            base = "Unknown"
        elif freq < 2500:
            base = "2.4 GHz"
        elif freq < 5925:
            base = "5 GHz"
        else:
            base = "6 GHz"
        gen = {
            "802.11ax": "Wi-Fi 6/6E",
            "802.11ac": "Wi-Fi 5",
            "802.11n": "Wi-Fi 4",
        }.get(radio)
        return f"{base} ({gen})" if gen else base

    try:
        if not shutil.which("nmcli"):
            return {"error": "nmcli not found. Install NetworkManager."}
        if _nmcli("radio", "wifi").lower() != "enabled":
            return {"error": "WiFi is turned off."}
        device = _wifi_device_name()
        if not device:
            return {"error": "No WiFi adapter found."}
        state = _nmcli("-t", "-f", "GENERAL.STATE", "device", "show", device)
        code = state.split(":", 1)[-1].strip().split()[0]
        if code != "100":
            return {"ssid": "Unknown"}

        ap_fields = None
        listing = _nmcli(
            "-t", "-f", "ACTIVE,SSID,BSSID,CHAN,FREQ,RATE,SIGNAL,SECURITY",
            "dev", "wifi", "list", "ifname", device)
        for line in listing.splitlines():
            fields = _terse_fields(line)
            if len(fields) >= 8 and fields[0] == "yes":
                ap_fields = fields
                break
        if ap_fields is None:
            return {"ssid": "Unknown"}

        _, ssid, bssid, channel, freq, rate, signal, security = ap_fields[:8]
        ssid = ssid or "Unknown"
        bssid = bssid or "Unknown"
        channel = channel or "Unknown"
        auth = security if security and security != "--" else "Open"
        link_speed = rate or "Unknown"
        signal_display = f"{signal}%" if signal else "Unknown"
        radio = _radio_standard(device)
        band = _band_label(freq, radio)
        conn_name = _nmcli(
            "-t", "-f", "GENERAL.CONNECTION", "device", "show", device
        ).split(":", 1)[-1].strip()
        cipher = "Unknown"
        if conn_name and conn_name != "--":
            sec_raw = _nmcli(
                "-t", "-f",
                "802-11-wireless-security.pairwise,"
                "802-11-wireless-security.group,"
                "802-11-wireless-security.key-mgmt",
                "connection", "show", conn_name)
            for line in sec_raw.splitlines():
                key, _, value = line.partition(":")
                if key == "802-11-wireless-security.pairwise" and value and value != "--":
                    cipher = value
                    break
        return {
            "ssid": ssid, "bssid": bssid, "signal": signal_display,
            "radio": radio or "Unknown", "band": band, "auth": auth,
            "channel": channel, "cipher": cipher, "link_speed": link_speed,
            "rx_rate": rate, "tx_rate": rate,
        }
    except Exception as e:
        return {"error": str(e)}


def scan_wifi_networks_linux():
    def _auth_encryption(security, wpa_flags, rsn_flags):
        security = (security or "").strip()
        flags = f"{wpa_flags or ''} {rsn_flags or ''}".lower()
        if not security or security == "--":
            return "Open", "None"
        sec_lower = security.lower()
        if "wep" in sec_lower:
            return "WEP", "WEP"
        suffix = "Enterprise" if "802.1x" in flags else "Personal"
        if "wpa3" in sec_lower or "sae" in flags:
            auth = f"WPA3-{suffix}"
        elif "wpa2" in sec_lower:
            auth = f"WPA2-{suffix}"
        elif "wpa" in sec_lower:
            auth = f"WPA-{suffix}"
        else:
            auth = security
        if "ccmp" in flags:
            encryption = "AES"
        elif "tkip" in flags:
            encryption = "TKIP"
        else:
            encryption = "Unknown"
        return auth, encryption

    try:
        if not shutil.which("nmcli"):
            return {"error": "nmcli not found. Install NetworkManager."}
        if _nmcli("radio", "wifi").lower() != "enabled":
            return {"error": "No WiFi adapter found or it is turned off."}
        device = _wifi_device_name()
        if not device:
            return {"error": "No WiFi adapter found or it is turned off."}
        env = os.environ.copy()
        env["LC_ALL"] = "C"
        result = subprocess.run(
            ["nmcli", "-t", "-f",
             "SSID,CHAN,FREQ,SIGNAL,SECURITY,WPA-FLAGS,RSN-FLAGS",
             "dev", "wifi", "list", "ifname", device, "--rescan", "yes"],
            capture_output=True, text=True, timeout=25, env=env)
        out = result.stdout
        if not out.strip():
            return {"error": "No WiFi adapter found or it is turned off."}
        by_ssid = {}
        for line in out.splitlines():
            if not line:
                continue
            fields = _terse_fields(line)
            if len(fields) < 7:
                continue
            ssid, channel, freq, signal, security, wpa_flags, rsn_flags = fields[:7]
            name = ssid.strip() or "(hidden network)"
            try:
                pct = int(signal)
            except ValueError:
                pct = 0
            existing = by_ssid.get(name)
            if existing and existing["signal"] >= pct:
                continue
            auth, encryption = _auth_encryption(security, wpa_flags, rsn_flags)
            digits = re.sub(r'\D', '', freq or "")
            f = int(digits) if digits else None
            if f is None:
                band = ""
            elif f < 2500:
                band = "2.4 GHz"
            elif f < 5925:
                band = "5 GHz"
            else:
                band = "6 GHz"
            by_ssid[name] = {
                "ssid": name, "auth": auth, "encryption": encryption,
                "signal": pct, "signal_dbm": round(pct / 2.0 - 100),
                "channel": channel.strip() if channel else "", "band": band,
                "radio": "Unknown",
            }
        networks = list(by_ssid.values())
        networks.sort(key=lambda n: n["signal"], reverse=True)
        return {"networks": networks, "count": len(networks)}
    except subprocess.TimeoutExpired:
        return {"error": "WiFi scan timed out"}
    except Exception as e:
        return {"error": str(e)}


def get_wifi_info():
    if used_os == "linux":
        return get_wifi_info_linux()
    if sys.platform == "win32":
        return windows_network.current_wifi()
    return {"error": "Wi-Fi information is unavailable on this platform."}


def scan_wifi_networks():
    if used_os == "linux":
        return scan_wifi_networks_linux()
    if sys.platform == "win32":
        return windows_network.scan_wifi_networks()
    return {"error": "Wi-Fi scanning is unavailable on this platform."}
