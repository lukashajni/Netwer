"""
NETWER core: pure Python backend logic, no web framework dependency.

This module contains every diagnostic/monitoring function as plain
functions and generators. Designed to be imported directly by any
frontend (PyQt, CLI, Flask, etc.), nothing here depends on Flask,
request objects, or HTTP at all.

Conventions used throughout:
- Functions that return one result return a dict.
- Functions that produce a stream of updates (ping sweep, monitor,
  speed test) are Python generators that `yield` dicts, so the caller
  decides how to consume them (Qt signal emission, SSE, print, etc.)
- All functions handle their own errors and return {"error": "..."}
  rather than raising, so callers don't need try/except everywhere.
"""

import os
import sys
import re
import sys
import json
import time
import shutil
import socket
import platform
import ipaddress
import subprocess
import urllib.request
from pathlib import Path
from datetime import datetime

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False


# Platform detection: "win32" on Windows, "linux" on Linux, "darwin" on macOS.
# Used to route adapter/network calls to the right OS-specific implementation.
used_os = sys.platform


def _no_window():
    """Keep Windows from flashing a console window for each subprocess."""
    if platform.system() == "Windows":
        return {"creationflags": 0x08000000}   # CREATE_NO_WINDOW
    return {}


def friendly_error(exc):
    """Turn a raw exception (or message) into a short, human message suitable
    for showing in the app, never the raw 'Command [...] timed out' text that
    looks like a console dump."""
    msg = str(exc) if not isinstance(exc, str) else exc
    low = msg.lower()
    if "timed out" in low or "timeout" in low:
        return ("This took too long to respond. It usually works on the next "
                "try — check that you're connected and try again.")
    if "powershell" in low or "get-net" in low:
        return ("Couldn't read your network adapter details. Try running the "
                "scan again.")
    if "no active network" in low or "no network" in low:
        return "No active network connection was found."
    if "wireless interface" in low or "no wifi" in low:
        return "No Wi-Fi adapter was found, or Wi-Fi is turned off."
    if "permission" in low or "access is denied" in low or "denied" in low:
        return ("This action needs administrator rights. Try running NETWER "
                "as administrator.")
    if "invalid mac" in low:
        return "This device doesn't have a MAC address we can use for this."
    # Fallback: a trimmed, non-technical version.
    clean = msg.strip()
    if len(clean) > 140:
        clean = clean[:137] + "…"
    return clean or "Something went wrong. Please try again."



# Helpers

def prefix_to_mask(prefix):
    masks = [0, 128, 192, 224, 240, 248, 252, 254, 255]
    result = []
    p = int(prefix)
    for _ in range(4):
        if p >= 8:
            result.append(255)
            p -= 8
        else:
            result.append(masks[p])
            p = 0
    return ".".join(map(str, result))


def get_ip_class(ip):
    try:
        first = int(ip.split(".")[0])
    except (ValueError, IndexError):
        return "Unknown"
    if first <= 126:
        return "A"
    if first <= 191:
        return "B"
    if first <= 223:
        return "C"
    return "Unknown"


def is_private(ip):
    try:
        return ipaddress.ip_address(ip).is_private
    except ValueError:
        return False


def ping_host(host, timeout_ms=1000):
    """Returns round-trip time in ms, or None if unreachable."""
    try:
        if platform.system() == "Windows":
            cmd = ["ping", "-n", "1", "-w", str(timeout_ms), host]
        else:
            cmd = ["ping", "-c", "1", "-W", str(max(timeout_ms // 1000, 1)), host]
        result = subprocess.run(cmd, capture_output=True, text=True,
                                 timeout=timeout_ms / 1000 + 2)
        if result.returncode == 0:
            m = re.search(r'[Tt]ime[=<](\d+)', result.stdout)
            return int(m.group(1)) if m else 1
        return None
    except Exception:
        return None


def scan_port(ip, port, timeout=0.5):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        result = s.connect_ex((ip, int(port)))
        s.close()
        return result == 0
    except Exception:
        return False


def run_powershell(command, timeout=10):
    """Runs a PowerShell command and returns stdout, or raises on failure.
    Returns empty string on non-Windows platforms (callers should branch)."""
    if platform.system() != "Windows":
        return ""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True, text=True, timeout=timeout, **_no_window()
    )
    return result.stdout.strip()


def _windows_ipconfig_config():
    """Fast native adapter config via `ipconfig /all`, no PowerShell, so it
    returns instantly and works reliably on Wi-Fi where the Get-Net* cmdlets
    are slow to cold-start (they were timing out at 8-12s). Parses the FIRST
    adapter block that has an IPv4 address and a default gateway (the active
    connection, Wi-Fi or Ethernet). Returns a cfg dict or None."""
    try:
        out = subprocess.run(["ipconfig", "/all"], capture_output=True,
                             text=True, timeout=6, **_no_window()).stdout
    except Exception:
        return None
    if not out:
        return None

    # Split into "Adapter ...:" blocks. Each block is a header line (no leading
    # whitespace, ends with ':') followed by indented "Key . . . : value" lines.
    blocks = re.split(r'\n(?=[^\s].*:\s*\n)', out)
    best = None
    for block in blocks:
        def field(*labels):
            for lab in labels:
                m = re.search(r'^\s*' + lab + r'[ .]*:\s*(.+)$',
                              block, re.MULTILINE)
                if m:
                    return m.group(1).strip()
            return ""
        # IPv4 (Windows appends "(Preferred)"/"(Povlašteno)")
        ipv4 = field(r'IPv4 Address', r'IPv4 adresa', r'IP Address')
        ipv4 = re.sub(r'\(.*?\)', '', ipv4).strip()
        if not re.match(r'^\d{1,3}(\.\d{1,3}){3}$', ipv4 or ""):
            continue
        gateway = field(r'Default Gateway', r'Zadani pristupnik',
                        r'Zadani gateway')
        gw_ip = ""
        gm = re.search(r'\d{1,3}(\.\d{1,3}){3}', gateway or "")
        if gm:
            gw_ip = gm.group(0)
        mask = field(r'Subnet Mask', r'Maska podmreže')
        mac = field(r'Physical Address', r'Fizička adresa')
        mac = mac.replace("-", ":").upper() if mac else ""
        dns = field(r'DNS Servers', r'DNS poslužitelji')
        dns_ip = ""
        dm = re.search(r'\d{1,3}(\.\d{1,3}){3}', dns or "")
        if dm:
            dns_ip = dm.group(0)
        # Adapter name from the block header, e.g.
        # "Wireless LAN adapter Wi-Fi:" -> "Wi-Fi"
        header = block.strip().splitlines()[0] if block.strip() else ""
        alias = re.sub(r'^.*adapter\s+', '', header, flags=re.I).rstrip(":").strip()
        prefix = _mask_to_prefix(mask) if mask else 24

        cfg = {"ip": ipv4, "prefix": prefix, "gateway": gw_ip or "N/A",
               "dns": dns_ip or "N/A", "mac": mac or "N/A",
               "adapter": alias or "Network"}
        # Prefer an adapter that actually has a gateway (the internet-facing
        # one). Keep the first IPv4 block as a fallback.
        if gw_ip:
            return cfg
        if best is None:
            best = cfg
    return best


def _mask_to_prefix(mask):
    """'255.255.255.0' -> 24. Returns 24 on anything unparseable."""
    try:
        return sum(bin(int(o)).count("1") for o in mask.split("."))
    except Exception:
        return 24


# MAC vendor lookup (OUI), offline, no API dependency.

# Minimal built-in OUI table covering the vendors you'll actually see on a
# home/office network. Keys are the first 6 hex chars of the MAC (no
# separators, uppercase). Kept small on purpose, add entries as needed
# rather than shipping a multi-MB IEEE database.
OUI_TABLE = {
    "001A11": "Google", "3C5AB4": "Google", "F4F5D8": "Google",
    "A45C2C": "ASUSTek", "AC9E17": "ASUSTek", "D8501A": "ASUSTek",
    "B827EB": "Raspberry Pi", "DCA632": "Raspberry Pi", "E45F01": "Raspberry Pi",
    "001E58": "Synology", "0011D8": "Synology", "001132": "Synology",
    "B0A4E8": "MikroTik", "4C5E0C": "MikroTik", "6C3B6B": "MikroTik", "DC2C6E": "MikroTik",
    "00163C": "TP-Link", "1C61B4": "TP-Link", "50C7BF": "TP-Link", "F4F26D": "TP-Link",
    "6C4CBC": "TP-Link", "6C4CBB": "TP-Link", "AC84C6": "TP-Link", "5091E3": "TP-Link",
    "9C5322": "TP-Link", "EC086B": "TP-Link", "60A4B7": "TP-Link",
    "C46E1F": "TP-Link", "A42BB0": "TP-Link", "003192": "TP-Link", "B0BE76": "TP-Link",
    "10FEED": "TP-Link", "54AF97": "TP-Link", "98DAC4": "TP-Link", "E848B8": "TP-Link",
    "001D7E": "Cisco", "0050F2": "Microsoft", "7C1E52": "Microsoft",
    "DCA632": "Apple", "A85C2C": "Apple", "F0DBE2": "Apple", "BC9264": "Apple",
    "001CB3": "Apple", "3C0754": "Apple", "88665A": "Apple",
    "00E04C": "Realtek", "525400": "QEMU/Virtual",
    "000C29": "VMware", "001C14": "VMware", "005056": "VMware",
    "080027": "VirtualBox",
    "F8F005": "Netgear", "A0040F": "Netgear", "B0B984": "Netgear",
    "8C8590": "Espressif (IoT)", "240AC4": "Espressif (IoT)",
    "00408C": "HP Inc.", "3C4A92": "HP Inc.", "D4C9EF": "HP Inc.",
    "001143": "Canon", "0080770": "Canon",
}


_ONLINE_VENDOR_CACHE = {}


def lookup_vendor(mac_address, allow_online=False):
    """Vendor name from a MAC address.

    First checks the local OUI table (fast, offline). If not found and
    allow_online=True, queries a free online API (like real network tools
    do) and caches the result. Online lookups only happen inside the
    device-scan worker, never on the UI thread.
    """
    if not mac_address:
        return "Unknown"
    cleaned = re.sub(r'[^0-9A-Fa-f]', '', mac_address).upper()
    if len(cleaned) < 6:
        return "Unknown"
    prefix = cleaned[:6]

    # A user-taught vendor always wins, even over the randomized-MAC label,
    # since the user explicitly corrected it.
    try:
        from core import vendor_learning
        taught = vendor_learning.lookup(prefix)
    except Exception:
        taught = None
    if taught:
        return taught

    # Locally-administered / randomized MAC (2nd nibble is 2, 6, A or E).
    # Modern phones/laptops randomize their MAC for privacy, so there's no
    # real manufacturer to look up, so label it honestly instead of "Unknown".
    try:
        second_nibble = int(cleaned[1], 16)
        if second_nibble & 0x2:
            return "Private (randomized)"
    except ValueError:
        pass

    # 1) Local built-in table
    vendor = OUI_TABLE.get(prefix)
    if vendor:
        return vendor

    # 2) (Learned DB already checked above.) Cache from earlier online lookups.
    if prefix in _ONLINE_VENDOR_CACHE:
        return _ONLINE_VENDOR_CACHE[prefix]

    # 4) Online lookup (opt-in, worker only)
    if allow_online:
        try:
            from core.oui_extended import online_vendor_lookup
            name = online_vendor_lookup(mac_address)
            if name:
                _ONLINE_VENDOR_CACHE[prefix] = name
                # Persist it so next time we know it even offline.
                try:
                    from core import vendor_learning
                    vendor_learning.remember(prefix, name)
                except Exception:
                    pass
                return name
        except Exception:
            pass
        # Cache the miss so we don't retry every scan
        _ONLINE_VENDOR_CACHE[prefix] = "Unknown"

    return "Unknown"


def teach_vendor(mac_address, vendor):
    """Teach NETWER the vendor for a device's MAC (user correction). Persisted
    across sessions and preferred over online guesses."""
    try:
        from core import vendor_learning
        return vendor_learning.teach(mac_address, vendor)
    except Exception:
        return False


# Network config (Ethernet Info source of truth)

def get_network_config():
    """Returns the active adapter's IP config as a dict, or {"error": ...}.

    On Windows we try the fast native `ipconfig /all` first (instant, works
    on Wi-Fi), and only fall back to the slower Get-Net* PowerShell cmdlets
    if that didn't yield a usable result. This fixes the Network Map / Top
    Devices panels timing out on Wi-Fi connections."""
    try:
        if platform.system() == "Windows":
            # 1) Fast path: ipconfig /all
            fast = _windows_ipconfig_config()
            if fast and fast.get("ip") and fast["ip"] != "N/A":
                return fast

            # 2) Fallback: PowerShell Get-NetIPConfiguration
            ps_cmd = r"""
$c = Get-NetIPConfiguration | Where-Object { $_.IPv4Address -ne $null -and $_.NetAdapter.Status -eq 'Up' } | Select-Object -First 1
if (-not $c) { Write-Output '{}'; exit }
$ip      = $c.IPv4Address.IPAddress
$prefix  = [int]$c.IPv4Address.PrefixLength
$gw      = if ($c.IPv4DefaultGateway) { $c.IPv4DefaultGateway.NextHop } else { 'N/A' }
$dnsList = @()
foreach ($d in $c.DNSServer) {
    if ($d.AddressFamily -eq 2 -and $d.ServerAddresses) {
        $dnsList += $d.ServerAddresses
    }
}
if ($dnsList.Count -eq 0) {
    foreach ($d in $c.DNSServer) {
        if ($d.ServerAddresses) { $dnsList += $d.ServerAddresses }
    }
}
$dnsList = $dnsList | Where-Object { $_ -match '^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$' }
$dns     = if ($dnsList.Count -gt 0) { ($dnsList -join ', ') } else { 'N/A' }
$mac     = $c.NetAdapter.MacAddress
$adapter = $c.InterfaceAlias
[pscustomobject]@{ ip=$ip; prefix=$prefix; gateway=$gw; dns=$dns; mac=$mac; adapter=$adapter } | ConvertTo-Json
"""  # noqa: W605 (regex backslashes are for PowerShell, not Python)
            raw = run_powershell(ps_cmd, timeout=12)
            data = json.loads(raw or "{}")
            if not data:
                return {"error": "No active network connection found"}

            ip = data.get("ip") or "N/A"
            prefix = data.get("prefix") or 24
            try:
                prefix = int(prefix)
            except (TypeError, ValueError):
                prefix = 24

            return {
                "ip": ip,
                "prefix": prefix,
                "gateway": data.get("gateway") or "N/A",
                "dns": data.get("dns") or "N/A",
                "mac": data.get("mac") or "N/A",
                "adapter": data.get("adapter") or "N/A",
            }

        # Non-Windows fallback using psutil/socket
        if PSUTIL_AVAILABLE:
            for name, addrs in psutil.net_if_addrs().items():
                stats = psutil.net_if_stats().get(name)
                if not stats or not stats.isup:
                    continue
                ip = mac = None
                for a in addrs:
                    if a.family == socket.AF_INET and not a.address.startswith("127."):
                        ip = a.address
                    if a.family == psutil.AF_LINK:
                        mac = a.address
                if ip:
                    return {
                        "ip": ip, "prefix": 24, "gateway": "N/A",
                        "dns": "N/A", "mac": mac or "N/A", "adapter": name,
                    }
        return {"error": "No active network connection found"}

    except Exception as e:
        return {"error": str(e)}


def get_public_ip():
    try:
        import urllib.request
        return urllib.request.urlopen("https://api.ipify.org", timeout=3).read().decode()
    except Exception:
        return "Unavailable"


def get_ethernet_info():
    """Full Ethernet Info screen data, same shape as before, unchanged."""
    cfg = get_network_config()
    if "error" in cfg:
        return cfg

    ip = cfg["ip"]
    mask = prefix_to_mask(cfg["prefix"])
    ip_class = get_ip_class(ip)
    ip_type = "PRIVATE" if is_private(ip) else "PUBLIC"

    return {
        "adapter": cfg["adapter"],
        "ip": ip,
        "public_ip": get_public_ip(),
        "ip_class": ip_class,
        "mac": cfg["mac"],
        "subnet_mask": mask,
        "gateway": cfg["gateway"],
        "dns": cfg["dns"],
        "ip_type": ip_type,
    }


# Wi-Fi info
def _nmcli(*args):
    env = os.environ.copy()
    env["LC_ALL"] = "C"
    result = subprocess.run(
        ["nmcli", *args], capture_output=True, text=True, env=env)
    return result.stdout.strip()


def _terse_fields(line):
    """Split one line of `nmcli -t -f ...` output into fields, using
    nmcli's backslash-escaping of ':' inside a value (e.g. a BSSID)."""
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
        """802.11 generation via `iw`. Not every distro ships with iw,
        and not every driver reports these fields, so this can
        come back as None - callers should treat that as 'unknown'"""
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
        """example: '5 GHz (Wi-Fi 5)' from a nmcli FREQ value like '5180 MHz' plus
        an optional 802.11 standard string."""
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

        #find the AP we're actually on, from the visible-networks list
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
        link_speed = rate or "Unknown"          # nmcli already appends "Mbit/s"
        signal_display = f"{signal}%" if signal else "Unknown"

        radio = _radio_standard(device)
        band = _band_label(freq, radio)

        # `dev wifi list` doesn't expose cipher/key-mgmt; pull that from the
        #  active connection profile instead
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
            "ssid": ssid,
            "bssid": bssid,
            "signal": signal_display,
            "radio": radio or "Unknown",
            "band": band,
            "auth": auth,
            "channel": channel,
            "cipher": cipher,
            "link_speed": link_speed,
            "rx_rate": rate,
            "tx_rate": rate,
        }

    except Exception as e:
        return {"error": str(e)}

def scan_wifi_networks_linux():
    """Scan for nearby wireless networks (nmcli dev wifi list).

    This returns {"networks": [...]} where each entry has ssid, signal (%),
    signal_dbm (approx), auth, encryption, band and channel - matching
    scan_wifi_networks()'s Windows/netsh output shape exactly. nmcli
    reports signal as a percentage too, so the same percent -> dBm
    approximation is reused for consistency between platforms.

    Takes a few seconds (the adapter has to sweep the channels), so call it
    from a worker not on the UI thread.
    """
    # -- scan --

    def _auth_encryption(security, wpa_flags, rsn_flags):
        """Map nmcli's SECURITY/WPA-FLAGS/RSN-FLAGS columns onto the same
        'WPA2-Personal' / 'AES' style strings netsh reports. Best-effort:
        nmcli doesn't split auth and cipher as cleanly as netsh does."""
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

            # Keep the strongest BSSID seen for this SSID
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
                "ssid": name,
                "auth": auth,
                "encryption": encryption,
                "signal": pct,
                # nmcli % -> approximate dBm (0% = -100, 100% = -50), same
                # conversion the Windows version uses
                "signal_dbm": round(pct / 2.0 - 100),
                "channel": channel.strip() if channel else "",
                "band": band,
                "radio": "Unknown",  # not available per-SSID from a scan on Linux
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

    try:
        result = subprocess.run(["netsh", "wlan", "show", "interfaces"],
                                 capture_output=True, text=True, timeout=8)
        wifi = result.stdout

        if "There is no wireless interface" in wifi or "Nema" in wifi:
            return {"error": "No WiFi adapter found or it is turned off."}

        def extract(pattern):
            m = re.search(pattern, wifi, re.MULTILINE)
            return m.group(1).strip() if m else "Unknown"

        ssid = extract(r'^\s*SSID\s*:\s*(.+)$')
        signal = extract(r'^\s*Signal\s*:\s*(.+)$')
        radio = extract(r'^\s*(?:Radio type|Vrsta radija)\s*:\s*(.+)$')
        auth = extract(r'^\s*(?:Authentication|Autentifikacija)\s*:\s*(.+)$')
        cipher = extract(r'^\s*(?:Cipher|Šifra)\s*:\s*(.+)$')
        channel = extract(r'^\s*(?:Channel|Kanal)\s*:\s*(\d+)')
        rx_rate = extract(r'^\s*(?:Receive rate \(Mbps\)|Brzina primanja)\s*:\s*(.+)$')
        tx_rate = extract(r'^\s*(?:Transmit rate \(Mbps\)|Brzina slanja)\s*:\s*(.+)$')

        bssid_m = re.search(r'([0-9a-fA-F]{2}[: -]){5}[0-9a-fA-F]{2}', wifi)
        bssid = bssid_m.group(0).strip() if bssid_m else "Unknown"

        band = "Unknown"
        if "802.11ax" in radio:
            band = "5 GHz / 6 GHz (Wi-Fi 6/6E)"
        elif "802.11ac" in radio:
            band = "5 GHz (Wi-Fi 5)"
        elif "802.11n" in radio:
            band = "5 GHz (Wi-Fi 4)" if channel.isdigit() and int(channel) > 14 else "2.4 GHz (Wi-Fi 4)"
        elif "802.11g" in radio or "802.11b" in radio:
            band = "2.4 GHz (Legacy)"
        elif "802.11a" in radio:
            band = "5 GHz (Legacy)"

        # Link speed: prefer the receive rate; fall back to transmit
        link_speed = "Unknown"
        rate = rx_rate if rx_rate != "Unknown" else tx_rate
        if rate != "Unknown":
            link_speed = f"{rate} Mbps"

        return {
            "ssid": ssid, "bssid": bssid, "signal": signal,
            "radio": radio, "band": band, "auth": auth, "channel": channel,
            "cipher": cipher, "link_speed": link_speed,
            "rx_rate": rx_rate, "tx_rate": tx_rate,
        }
    except Exception as e:
        return {"error": str(e)}

def scan_wifi_networks():
    """Scan for nearby wireless networks (netsh wlan show networks).

    Returns {"networks": [...]} where each entry has ssid, signal (%),
    signal_dbm (approx), auth, encryption, band and channel. Windows reports
    signal as a percentage; we convert to an approximate dBm for display,
    since dBm is what network tools conventionally show.

    Takes a few seconds (the adapter has to sweep the channels), so call it
    from a worker, never on the UI thread.
    """
    if used_os == "linux":
        return scan_wifi_networks_linux()

    try:
        result = subprocess.run(
            ["netsh", "wlan", "show", "networks", "mode=bssid"],
            capture_output=True, text=True, timeout=25)
        out = result.stdout

        if "There is no wireless interface" in out or not out.strip():
            return {"error": "No WiFi adapter found or it is turned off."}

        networks = []
        current = None

        for line in out.splitlines():
            line = line.strip()

            m = re.match(r'^SSID\s+\d+\s*:\s*(.*)$', line)
            if m:
                if current and current.get("ssid"):
                    networks.append(current)
                name = m.group(1).strip()
                current = {
                    "ssid": name or "(hidden network)",
                    "auth": "Unknown", "encryption": "Unknown",
                    "signal": 0, "signal_dbm": -100,
                    "channel": "", "band": "", "radio": "",
                }
                continue

            if current is None:
                continue

            m = re.match(r'^(?:Authentication|Autentifikacija)\s*:\s*(.+)$', line)
            if m:
                current["auth"] = m.group(1).strip()
                continue

            m = re.match(r'^(?:Encryption|Šifriranje)\s*:\s*(.+)$', line)
            if m:
                current["encryption"] = m.group(1).strip()
                continue

            m = re.match(r'^(?:Signal|Signal)\s*:\s*(\d+)%', line)
            if m:
                pct = int(m.group(1))
                # Keep the strongest BSSID seen for this SSID
                if pct > current["signal"]:
                    current["signal"] = pct
                    # Windows % -> approximate dBm (0% = -100, 100% = -50)
                    current["signal_dbm"] = round(pct / 2.0 - 100)
                continue

            m = re.match(r'^(?:Channel|Kanal)\s*:\s*(\d+)', line)
            if m and not current["channel"]:
                ch = int(m.group(1))
                current["channel"] = str(ch)
                current["band"] = "2.4 GHz" if ch <= 14 else "5 GHz"
                continue

            m = re.match(r'^(?:Radio type|Vrsta radija)\s*:\s*(.+)$', line)
            if m and not current["radio"]:
                current["radio"] = m.group(1).strip()
                continue

        if current and current.get("ssid"):
            networks.append(current)

        networks.sort(key=lambda n: n["signal"], reverse=True)
        return {"networks": networks, "count": len(networks)}

    except subprocess.TimeoutExpired:
        return {"error": "WiFi scan timed out"}
    except Exception as e:
        return {"error": str(e)}


# System info (static snapshot: name/CPU model/OS/uptime)

def get_system_info():
    try:
        ps_cmd = """
$cpu  = (Get-CimInstance Win32_Processor).Name
$ram  = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 2)
$os   = (Get-CimInstance Win32_OperatingSystem).Caption
$boot = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime
$up   = New-TimeSpan -Start $boot -End (Get-Date)
[pscustomobject]@{
    computer = $env:COMPUTERNAME
    cpu      = $cpu
    ram      = $ram
    os       = $os
    days     = $up.Days
    hours    = $up.Hours
    minutes  = $up.Minutes
} | ConvertTo-Json
"""
        raw = run_powershell(ps_cmd, timeout=15)
        if raw:
            return json.loads(raw)

        # Non-Windows fallback
        if PSUTIL_AVAILABLE:
            boot = psutil.boot_time()
            uptime_s = time.time() - boot
            return {
                "computer": socket.gethostname(),
                "cpu": platform.processor() or "Unknown",
                "ram": round(psutil.virtual_memory().total / (1024 ** 3), 2),
                "os": f"{platform.system()} {platform.release()}",
                "days": int(uptime_s // 86400),
                "hours": int((uptime_s % 86400) // 3600),
                "minutes": int((uptime_s % 3600) // 60),
            }
        return {"error": "psutil not available and not on Windows"}
    except Exception as e:
        return {"error": str(e)}


def get_system_details():
    """Extended system information for the System Information page.

    Builds on get_system_info() (computer/CPU/RAM/OS/uptime) and adds
    hardware detail: core counts, CPU frequency, architecture, OS build,
    Python version, disk layout. Uses platform/psutil rather than more
    PowerShell so it's testable and fast.
    """
    details = {}

    # Start from the existing snapshot (name, CPU model, RAM, OS, uptime)
    base = get_system_info()
    if isinstance(base, dict) and "error" not in base:
        details.update(base)

    try:
        details["architecture"] = platform.machine() or "Unknown"
        details["python_version"] = platform.python_version()
        details["hostname"] = socket.gethostname()

        # OS build/version detail
        if platform.system() == "Windows":
            details["os_build"] = platform.version() or "Unknown"
            details["os_release"] = platform.release() or ""
        else:
            details["os_build"] = platform.version() or "Unknown"
            details["os_release"] = platform.release() or ""

        if PSUTIL_AVAILABLE:
            details["cores_physical"] = psutil.cpu_count(logical=False) or 0
            details["cores_logical"] = psutil.cpu_count(logical=True) or 0

            freq = psutil.cpu_freq()
            if freq:
                details["cpu_freq_current"] = round(freq.current)
                details["cpu_freq_max"] = round(freq.max) if freq.max else 0

            mem = psutil.virtual_memory()
            details["ram_total_gb"] = round(mem.total / (1024 ** 3), 2)
            details["ram_used_gb"] = round(mem.used / (1024 ** 3), 2)
            details["ram_available_gb"] = round(mem.available / (1024 ** 3), 2)

            # Disk partitions
            disks = []
            for part in psutil.disk_partitions(all=False):
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                    disks.append({
                        "device": part.device,
                        "mountpoint": part.mountpoint,
                        "fstype": part.fstype,
                        "total_gb": round(usage.total / (1024 ** 3), 2),
                        "used_gb": round(usage.used / (1024 ** 3), 2),
                        "percent": round(usage.percent, 1),
                    })
                except (PermissionError, OSError):
                    continue
            details["disks"] = disks

            boot = psutil.boot_time()
            details["boot_time"] = boot

        return details
    except Exception as e:
        details["error"] = str(e)
        return details


# System resources: live CPU / RAM / Disk for dashboard gauges
# (this is the "System Resources" card from the dashboard mockup)

def get_system_resources():
    """A live snapshot of CPU%, RAM%, and Disk% usage, call this on a
    timer (e.g. every 1-2s) from the PyQt side to drive the dashboard
    gauges. Lightweight by design, no subprocess calls."""
    if not PSUTIL_AVAILABLE:
        return {"error": "psutil is required for system resource monitoring. pip install psutil"}

    try:
        cpu_percent = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage(os.path.abspath(os.sep))

        return {
            "cpu_percent": round(cpu_percent, 1),
            "ram_percent": round(mem.percent, 1),
            "ram_used_gb": round(mem.used / (1024 ** 3), 2),
            "ram_total_gb": round(mem.total / (1024 ** 3), 2),
            "disk_percent": round(disk.percent, 1),
            "disk_used_gb": round(disk.used / (1024 ** 3), 2),
            "disk_total_gb": round(disk.total / (1024 ** 3), 2),
        }
    except Exception as e:
        return {"error": str(e)}


def stream_system_resources(interval_s=1.5, max_samples=600):
    """Generator version for continuous dashboard updates. Caller breaks
    the loop (e.g. by closing the dashboard tab); this doesn't run forever
    on its own past max_samples, which is just a safety net."""
    for _ in range(max_samples):
        yield get_system_resources()
        time.sleep(interval_s)


# Ping: quick / stability / custom

def ping_quick():
    """Pings 3 well-known DNS servers once each (4 pings), returns a list
    of per-server results. Used for the dashboard's "Internet Status" card
    and the standalone Network Test screen."""
    targets = [
        {"label": "Google DNS", "ip": "8.8.8.8"},
        {"label": "Cloudflare", "ip": "1.1.1.1"},
        {"label": "Quad9", "ip": "9.9.9.9"},
    ]
    results = []
    for t in targets:
        times, lost = [], 0
        for _ in range(4):
            ms = ping_host(t["ip"], 1000)
            (times.append(ms) if ms is not None else None)
            if ms is None:
                lost += 1
        if times:
            results.append({
                "label": t["label"], "ip": t["ip"],
                "avg": round(sum(times) / len(times)),
                "min": min(times), "max": max(times),
                "loss": round((lost / 4) * 100),
            })
        else:
            results.append({"label": t["label"], "ip": t["ip"], "unreachable": True})
    return results


def ping_stability_stream(target="8.8.8.8", count=20):
    """Generator: yields one dict per ping, then a final summary dict with
    'done': True. Same contract whether consumed by Qt signals or print()."""
    times, lost = [], 0
    for i in range(1, count + 1):
        ms = ping_host(target, 1000)
        if ms is not None:
            times.append(ms)
            yield {"i": i, "ms": ms, "status": "ok"}
        else:
            lost += 1
            yield {"i": i, "status": "timeout"}
        time.sleep(0.2)

    if times:
        avg = round(sum(times) / len(times), 1)
        jitter = round(
            sum(abs(times[j] - times[j - 1]) for j in range(1, len(times))) / max(len(times) - 1, 1), 1
        )
        yield {"done": True, "avg": avg, "min": min(times), "max": max(times),
               "loss": round((lost / count) * 100), "jitter": jitter}
    else:
        yield {"done": True, "error": "All packets lost"}


def ping_custom_stream(target="8.8.8.8", count=4, interval_ms=500):
    """Ping a target, yielding one result per packet.

    count=0 means CONTINUOUS: run until the caller stops iterating (the
    worker's cancel flag closes the generator). Running stats (avg/min/max/
    jitter/loss) are emitted alongside each packet so the UI can update live
    rather than only at the end.
    """
    times, lost, sent = [], 0, 0
    i = 0
    continuous = (count == 0)

    while continuous or i < count:
        i += 1
        sent += 1
        ms = ping_host(target, 2000)

        if ms is not None:
            times.append(ms)
            status = "ok"
        else:
            lost += 1
            status = "timeout"

        # Jitter: mean deviation between consecutive replies
        jitter = 0.0
        if len(times) > 1:
            deltas = [abs(times[j] - times[j - 1]) for j in range(1, len(times))]
            jitter = round(sum(deltas) / len(deltas), 1)

        yield {
            "i": i,
            "ms": ms,
            "status": status,
            "avg": round(sum(times) / len(times), 1) if times else None,
            "min": min(times) if times else None,
            "max": max(times) if times else None,
            "jitter": jitter,
            "loss": round((lost / sent) * 100, 1),
            "sent": sent,
        }

        if continuous or i < count:
            time.sleep(interval_ms / 1000)

    if times:
        deltas = [abs(times[j] - times[j - 1]) for j in range(1, len(times))]
        jitter = round(sum(deltas) / len(deltas), 1) if deltas else 0.0
        yield {"done": True, "avg": round(sum(times) / len(times), 1),
               "min": min(times), "max": max(times), "jitter": jitter,
               "loss": round((lost / sent) * 100, 1), "sent": sent}
    else:
        yield {"done": True, "error": "All packets lost", "sent": sent}


# Port scanner

# Well-known service map: port -> (service name, transport/protocol note).
# Covers the ports a real scanner flags by default plus common extras.
PORT_SERVICES = {
    20: ("FTP-Data", "TCP"), 21: ("FTP", "TCP"), 22: ("SSH", "TCP"),
    23: ("Telnet", "TCP"), 25: ("SMTP", "TCP"), 53: ("DNS", "TCP/UDP"),
    67: ("DHCP", "UDP"), 68: ("DHCP", "UDP"), 69: ("TFTP", "UDP"),
    80: ("HTTP", "TCP"), 110: ("POP3", "TCP"), 111: ("RPCbind", "TCP"),
    123: ("NTP", "UDP"), 135: ("MS-RPC", "TCP"), 137: ("NetBIOS-NS", "UDP"),
    138: ("NetBIOS-DGM", "UDP"), 139: ("NetBIOS-SSN", "TCP"),
    143: ("IMAP", "TCP"), 161: ("SNMP", "UDP"), 162: ("SNMP-Trap", "UDP"),
    389: ("LDAP", "TCP"), 443: ("HTTPS", "TCP"), 445: ("SMB", "TCP"),
    465: ("SMTPS", "TCP"), 500: ("IKE/IPsec", "UDP"), 514: ("Syslog", "UDP"),
    515: ("LPD/Printer", "TCP"), 587: ("SMTP-Submission", "TCP"),
    631: ("IPP/Printer", "TCP"), 636: ("LDAPS", "TCP"), 993: ("IMAPS", "TCP"),
    995: ("POP3S", "TCP"), 1080: ("SOCKS", "TCP"), 1194: ("OpenVPN", "UDP"),
    1433: ("MSSQL", "TCP"), 1521: ("Oracle", "TCP"), 1723: ("PPTP", "TCP"),
    1883: ("MQTT", "TCP"), 1900: ("SSDP/UPnP", "UDP"), 2049: ("NFS", "TCP"),
    3128: ("Squid-Proxy", "TCP"), 3306: ("MySQL", "TCP"),
    3389: ("RDP", "TCP"), 3690: ("SVN", "TCP"), 4444: ("Metasploit", "TCP"),
    5000: ("UPnP/Flask", "TCP"), 5060: ("SIP", "TCP/UDP"),
    5432: ("PostgreSQL", "TCP"), 5555: ("ADB/Android", "TCP"),
    5672: ("AMQP/RabbitMQ", "TCP"), 5900: ("VNC", "TCP"),
    5985: ("WinRM-HTTP", "TCP"), 5986: ("WinRM-HTTPS", "TCP"),
    6379: ("Redis", "TCP"), 6667: ("IRC", "TCP"), 8000: ("HTTP-Alt", "TCP"),
    8008: ("HTTP-Alt", "TCP"), 8080: ("HTTP-Proxy", "TCP"),
    8443: ("HTTPS-Alt", "TCP"), 8888: ("HTTP-Alt", "TCP"),
    9000: ("HTTP-Alt/PHP-FPM", "TCP"), 9090: ("HTTP-Alt", "TCP"),
    9100: ("JetDirect/Printer", "TCP"), 9200: ("Elasticsearch", "TCP"),
    11211: ("Memcached", "TCP"), 27017: ("MongoDB", "TCP"),
    32400: ("Plex", "TCP"), 51820: ("WireGuard", "UDP"),
}

# Curated scan profiles (which ports to probe).
PORT_PROFILES = {
    "common": [21, 22, 23, 25, 53, 80, 110, 135, 139, 143, 443, 445, 993,
               995, 3306, 3389, 5900, 8080, 8443],
    "top100": sorted(PORT_SERVICES.keys()),
    "web": [80, 443, 8000, 8008, 8080, 8443, 8888, 9000, 9090, 3000, 5000],
    "database": [1433, 1521, 3306, 5432, 6379, 9200, 11211, 27017],
    "remote": [22, 23, 3389, 5900, 5985, 5986],
}

# Backwards-compatible alias (older callers used PORT_NAMES).
PORT_NAMES = {p: v[0] for p, v in PORT_SERVICES.items()}


def port_service(port):
    """Return (service_name, protocol) for a port, or ('Unknown', 'TCP')."""
    return PORT_SERVICES.get(int(port), ("Unknown", "TCP"))


def _clean_banner(text):
    """Strip control/non-printable characters from a raw banner so protocols
    like Telnet (which send binary IAC negotiation bytes) don't leave garbage
    on screen. Keeps normal printable ASCII/Latin text, drops the rest."""
    if not text:
        return ""
    # Keep printable chars (space..~) plus common accented letters; drop the
    # rest (control codes, Telnet IAC 0xFF sequences, replacement chars).
    cleaned = []
    for ch in text:
        o = ord(ch)
        if 32 <= o <= 126:            # printable ASCII
            cleaned.append(ch)
        elif o in (9,):              # tab becomes a space
            cleaned.append(" ")
    result = "".join(cleaned).strip()
    # Collapse runs of spaces left behind by stripped bytes.
    result = " ".join(result.split())
    return result


def _grab_banner(sock, port, timeout):
    """Best-effort banner grab on an already-open socket. Returns a short,
    cleaned version/identification string, or "" if nothing useful comes back.

    For quiet protocols that expect the client to speak first (HTTP) we send a
    minimal probe; for chatty ones (SSH, FTP, SMTP, POP3, IMAP) we just read
    what the server volunteers on connect. Telnet and other binary protocols
    get their control bytes stripped so only readable text remains.
    """
    http_ports = (80, 8080, 8000, 8008, 8888, 9090, 5000, 443, 8443)
    try:
        sock.settimeout(min(timeout, 1.5))
        if port in http_ports:
            try:
                sock.sendall(b"HEAD / HTTP/1.0\r\n\r\n")
            except Exception:
                pass
        data = sock.recv(256)
        if not data:
            return ""
        text = data.decode("utf-8", errors="replace")

        if port in http_ports:
            for line in text.splitlines():
                if line.lower().startswith("server:"):
                    return _clean_banner(line.split(":", 1)[1])[:60]
            first = next((l for l in text.splitlines() if l.strip()), "")
            return _clean_banner(first)[:60]

        # Non-HTTP: return the first line that still has readable content
        # after cleaning (SSH-2.0-..., "220 FTP ready", etc).
        for line in text.splitlines():
            cleaned = _clean_banner(line)
            if cleaned:
                return cleaned[:60]
        return ""
    except Exception:
        return ""


def _classify_port(ip, port, timeout, grab_banner=True):
    """Probe a single TCP port and classify the result the way a real
    scanner does:
        open:     connection succeeded (service is listening)
        closed:   host actively refused (RST), port reachable, nothing there
        filtered: no response within timeout (firewall dropping packets)
    When the port is open and grab_banner is set, also try to read a service
    banner (e.g. "OpenSSH_8.9", "nginx/1.24.0"). Returns a dict with port,
    service, protocol, state, and banner.
    """
    service, proto = port_service(port)
    state = "filtered"
    banner = ""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        result = s.connect_ex((ip, int(port)))
        if result == 0:
            state = "open"
            if grab_banner:
                banner = _grab_banner(s, int(port), timeout)
        elif result in (111, 10061):        # ECONNREFUSED (Linux / Windows)
            state = "closed"
        else:
            state = "filtered"              # timeout / unreachable
        s.close()
    except socket.timeout:
        state = "filtered"
    except Exception:
        state = "filtered"
    return {"port": int(port), "service": service, "protocol": proto,
            "state": state, "banner": banner}


def _parse_port_spec(spec):
    """Turn a user port spec into a sorted unique list of ints.
    Accepts a profile name ('common', 'web', ...), a comma list ('22,80,443'),
    ranges ('1-1024'), or a mix ('22,80,8000-8100'). Returns [] if invalid."""
    spec = (spec or "").strip().lower()
    if not spec:
        return PORT_PROFILES["common"]
    if spec in PORT_PROFILES:
        return PORT_PROFILES[spec]
    ports = set()
    for chunk in spec.replace(" ", "").split(","):
        if not chunk:
            continue
        if "-" in chunk:
            try:
                a, b = chunk.split("-", 1)
                a, b = int(a), int(b)
                if a > b:
                    a, b = b, a
                a = max(1, a)
                b = min(65535, b)
                ports.update(range(a, b + 1))
            except ValueError:
                return []
        else:
            try:
                p = int(chunk)
                if 1 <= p <= 65535:
                    ports.add(p)
            except ValueError:
                return []
    return sorted(ports)


def port_scan_stream(ip, ports=None, timeout_ms=600, max_workers=100):
    """Generator: scan a host's ports IN PARALLEL and yield results live.

    ip: target host (IP or resolvable hostname)
    ports: profile name, spec string, or explicit list of ints,
        defaults to the 'common' profile.
    timeout_ms: per-port connect timeout.

    Yields:
        {"target": ip, "resolved": ip, "total": N}         (once, at start)
        {"port", "service", "protocol", "state", "scanned"} (per port)
        {"done": True, "open": n_open, "closed": n_closed,
         "filtered": n_filtered, "total": N}                (once, at end)
    Ports are streamed back as each probe completes, so the UI fills live.
    Only open ports are guaranteed interesting; closed/filtered are reported
    too so the user sees the full picture (like nmap's default output).
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    # Resolve hostname to an IP up front.
    try:
        resolved = socket.gethostbyname(ip)
    except Exception:
        yield {"error": f"Could not resolve host: {ip}"}
        return

    if isinstance(ports, str) or ports is None:
        port_list = _parse_port_spec(ports)
    else:
        port_list = sorted({int(p) for p in ports if 1 <= int(p) <= 65535})

    if not port_list:
        yield {"error": "No valid ports to scan."}
        return

    total = len(port_list)
    timeout = max(0.1, timeout_ms / 1000.0)
    yield {"target": ip, "resolved": resolved, "total": total}

    counts = {"open": 0, "closed": 0, "filtered": 0}
    scanned = 0
    workers = min(max_workers, total)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_classify_port, resolved, p, timeout): p
                   for p in port_list}
        for fut in as_completed(futures):
            res = fut.result()
            scanned += 1
            counts[res["state"]] = counts.get(res["state"], 0) + 1
            res["scanned"] = scanned
            yield res

    yield {"done": True, "open": counts["open"], "closed": counts["closed"],
           "filtered": counts["filtered"], "total": total}


def port_scan_quick_stream(ip):
    """Legacy helper kept for compatibility: quick common-port scan yielding
    the old {"port", "name", "open"} shape."""
    for res in port_scan_stream(ip, ports="common"):
        if "port" in res and "state" in res:
            yield {"port": res["port"], "name": res["service"],
                   "open": res["state"] == "open"}
        elif res.get("done"):
            yield {"done": True}


def port_scan_custom(ip, port):
    return {"port": port, "open": scan_port(ip, port, timeout=1.0)}


def wake_on_lan(mac, broadcast="255.255.255.255", port=9):
    """Send a Wake-on-LAN magic packet to a device by its MAC address.

    The magic packet is 6 bytes of 0xFF followed by the target MAC repeated
    16 times, broadcast over UDP. The device's NIC (if WoL is enabled in its
    BIOS/OS) powers the machine on.

    mac: target MAC ('AA:BB:CC:DD:EE:FF', with : - or none)
    broadcast: broadcast address (usually the subnet or 255.255.255.255)
    port: UDP port (7 or 9 conventionally)

    Returns {"ok": True} on success or {"error": "..."}.
    """
    # Normalize MAC to 12 hex chars.
    clean = re.sub(r"[^0-9A-Fa-f]", "", mac or "")
    if len(clean) != 12:
        return {"error": f"Invalid MAC address: {mac}"}
    try:
        mac_bytes = bytes.fromhex(clean)
        packet = b"\xff" * 6 + mac_bytes * 16
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        # Send a couple times to the broadcast + limited broadcast for reach.
        s.sendto(packet, (broadcast, int(port)))
        try:
            s.sendto(packet, ("255.255.255.255", int(port)))
        except Exception:
            pass
        s.close()
        return {"ok": True, "mac": ":".join(
            clean[i:i+2].upper() for i in range(0, 12, 2))}
    except Exception as e:
        return {"error": str(e)}


# Device type detection
# Infer what a device *is* from its open ports and vendor string. Used by
# the Ping Sweep (icon + label per device) and reports. Returns one of the
# type keys below; the UI maps these to icons.

_VENDOR_TYPE_HINTS = {
    "router": ["mikrotik", "tp-link", "netgear", "asus", "d-link", "ubiquiti",
               "cisco", "zyxel", "huawei", "linksys", "fritz"],
    "printer": ["hp", "canon", "epson", "brother", "lexmark", "xerox"],
    "nas": ["synology", "qnap", "western digital", "wd ", "drobo"],
    "tv": ["samsung", "lg electronics", "sony", "vizio", "roku", "hisense",
           "tcl"],
    "phone": ["apple", "xiaomi", "oneplus", "oppo", "vivo", "realme",
              "google", "motorola", "nokia"],
    "camera": ["hikvision", "dahua", "axis", "reolink", "wyze", "amcrest"],
    "console": ["nintendo", "sony interactive", "microsoft"],
}

# Strong signals: an open port that almost always identifies a device type.
_PORT_TYPE_HINTS = {
    9100: "printer", 631: "printer", 515: "printer",   # printing protocols
    32400: "media",                                     # Plex
    554: "camera", 8554: "camera",                      # RTSP
    5000: "nas", 5001: "nas",                           # Synology DSM
    445: "computer", 139: "computer", 3389: "computer",  # SMB / RDP
    62078: "phone",                                     # iPhone sync
    8009: "tv",                                         # Chromecast
}


def detect_device_type(open_ports=None, vendor="", is_gateway=False,
                        hostname=""):
    """Best-effort device classification.

    open_ports: iterable of open port numbers (ints), if a scan was run
    vendor: OUI vendor string (e.g. "MikroTik", "Apple")
    is_gateway: True if this is the default gateway (counts as a router)
    hostname: reverse-DNS hostname, used as a weak hint

    Returns a type key: router, printer, nas, tv, phone, camera, console,
    media, computer, or generic.
    """
    if is_gateway:
        return "router"

    ports = set(int(p) for p in (open_ports or []))
    # 1) Strong per-port signals win first.
    for port, dtype in _PORT_TYPE_HINTS.items():
        if port in ports:
            return dtype

    # 2) Vendor hints.
    v = (vendor or "").lower()
    for dtype, needles in _VENDOR_TYPE_HINTS.items():
        if any(n in v for n in needles):
            return dtype

    # 3) Hostname hints (weakest).
    h = (hostname or "").lower()
    for kw, dtype in (("printer", "printer"), ("cam", "camera"),
                      ("nas", "nas"), ("tv", "tv"), ("phone", "phone"),
                      ("desktop", "computer"), ("pc", "computer"),
                      ("laptop", "computer"), ("router", "router")):
        if kw in h:
            return dtype

    # 4) Web-only device, probably some appliance/computer.
    if ports & {80, 443, 8080}:
        return "computer"
    return "generic"


# Ping sweep / Top Devices / Network Map.
# These three share the same underlying scan, they're just different
# presentations of "what's alive on my LAN right now".

def _resolve_local_network_prefix():
    """Returns ('192.168.1', '192.168.1.1', cfg_dict) or raises."""
    cfg = get_network_config()
    if "error" in cfg:
        raise RuntimeError(cfg["error"])
    network = ".".join(cfg["ip"].split(".")[:3])
    gateway = cfg.get("gateway", f"{network}.1")
    return network, gateway, cfg


def _get_own_ip_and_mac():
    """Return (own_ip, own_mac) for the active adapter. ARP doesn't list
    your own machine, so we resolve it separately to identify/label it in
    scans."""
    try:
        info = get_ethernet_info()
        if isinstance(info, dict) and "error" not in info:
            ip = info.get("ip", "")
            mac = info.get("mac", "")
            if mac:
                mac = mac.replace("-", ":").upper()
            return ip, mac
    except Exception:
        pass
    return None, None


def _get_mac_for_ip(ip, own_ip=None, own_mac=None):
    """Best-effort MAC lookup. For your OWN IP, ARP returns nothing, so use
    the adapter's MAC passed in. Otherwise read the ARP table."""
    # Own machine: ARP won't have it, so use the adapter MAC.
    if own_ip and ip == own_ip and own_mac:
        return own_mac
    try:
        if platform.system() == "Windows":
            result = subprocess.run(["arp", "-a", ip], capture_output=True, text=True, timeout=3)
            m = re.search(r'([0-9A-Fa-f]{2}-){5}[0-9A-Fa-f]{2}', result.stdout)
            if m:
                return m.group(0).replace("-", ":").upper()
        else:
            result = subprocess.run(["arp", "-n", ip], capture_output=True, text=True, timeout=3)
            m = re.search(r'([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}', result.stdout)
            if m:
                return m.group(0).upper()
    except Exception:
        pass
    return None


def _read_arp_table():
    """Read the full ARP table into {ip: mac}. Devices that block ping (common
    on Windows firewalls) still show up here if they've communicated on the
    LAN recently. Real scanners cross-reference this so a silent host isn't
    invisible."""
    table = {}
    try:
        if platform.system() == "Windows":
            result = subprocess.run(["arp", "-a"], capture_output=True,
                                    text=True, timeout=5)
            for line in result.stdout.splitlines():
                m = re.search(
                    r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\s+'
                    r'(([0-9A-Fa-f]{2}[-:]){5}[0-9A-Fa-f]{2})', line)
                if m:
                    ip = m.group(1)
                    mac = m.group(2).replace("-", ":").upper()
                    # Skip broadcast/multicast placeholder entries
                    if mac not in ("FF:FF:FF:FF:FF:FF",) and not ip.endswith(".255"):
                        table[ip] = mac
        else:
            result = subprocess.run(["arp", "-n"], capture_output=True,
                                    text=True, timeout=5)
            for line in result.stdout.splitlines():
                m = re.search(
                    r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}).+?'
                    r'(([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2})', line)
                if m:
                    table[m.group(1)] = m.group(2).upper()
    except Exception:
        pass
    return table


def _parse_subnet_prefix(subnet):
    """Normalise a user-supplied subnet to a 3-octet prefix like
    '192.168.88'. Accepts '192.168.88.0/24', '192.168.88.0', '192.168.88.',
    or '192.168.88'. Only /24 (or an implied /24) is supported, returns
    None on anything invalid."""
    if not subnet:
        return None
    s = subnet.strip().split("/")[0].strip()
    parts = [p for p in s.split(".") if p != ""]
    if len(parts) < 3:
        return None
    try:
        octets = [int(p) for p in parts[:3]]
    except ValueError:
        return None
    if not all(0 <= o <= 255 for o in octets):
        return None
    return ".".join(str(o) for o in octets)


def ping_sweep_stream(timeout_ms=150, subnet=None):
    """Generator: scans a /24 range in PARALLEL (like Advanced IP Scanner /
    Angry IP Scanner). Yields per-host results as they come in, then a final
    summary. Powers Ping Sweep, Top Devices, and Network Map.

    subnet: optional CIDR or prefix to scan (e.g. "192.168.88.0/24" or
             "192.168.88"). When omitted, the local /24 is auto-detected
             and the gateway is highlighted (Top Devices / Network Map path).

    Parallel scanning cuts a full /24 sweep from ~60s (sequential) down to
    a few seconds by pinging many hosts at once via a thread pool.
    """
    if subnet:
        parsed = _parse_subnet_prefix(subnet)
        if parsed is None:
            yield {"error": f"Invalid subnet: {subnet}"}
            return
        network = parsed
        # Best-effort gateway guess for a user-supplied subnet; if it matches
        # the local network the real gateway still lines up.
        try:
            _, gateway, cfg = _resolve_local_network_prefix()
            if not gateway.startswith(network + "."):
                gateway = f"{network}.1"
        except RuntimeError:
            gateway = f"{network}.1"
    else:
        try:
            network, gateway, cfg = _resolve_local_network_prefix()
        except RuntimeError as e:
            yield {"error": str(e)}
            return

    yield {"network": network}

    import concurrent.futures

    # Resolve our own IP/MAC once. ARP won't list us, so we label our own
    # machine (and thus resolve its vendor) using the adapter's MAC.
    own_ip, own_mac = _get_own_ip_and_mac()

    def probe(i):
        ip = f"{network}.{i}"
        ms = ping_host(ip, timeout_ms)
        if ms is None:
            return None
        try:
            hostname = socket.gethostbyaddr(ip)[0]
        except Exception:
            hostname = "Unknown"
        # MAC is filled in AFTER the sweep from the ARP table (populated by
        # these very pings). Resolving it here per-host is unreliable, the
        # OS often hasn't written the ARP entry yet, giving "Unknown".
        return {
            "online": True,
            "ip": ip,
            "hostname": hostname,
            "mac": "Unknown",
            "vendor": "Unknown",
            "is_gateway": (ip == gateway),
            "is_self": (own_ip and ip == own_ip),
            "rtt_ms": ms,
        }

    found = 0
    scanned = 0
    seen_ips = set()
    pending = []          # hosts awaiting MAC/vendor from the ARP table
    # 64 workers scan the whole /24 in a few seconds
    with concurrent.futures.ThreadPoolExecutor(max_workers=64) as pool:
        futures = {pool.submit(probe, i): i for i in range(1, 255)}
        for fut in concurrent.futures.as_completed(futures):
            scanned += 1
            if scanned % 32 == 0:
                yield {"scanned": scanned}
            try:
                host = fut.result()
            except Exception:
                host = None
            if host:
                found += 1
                seen_ips.add(host["ip"])
                pending.append(host)

    # Now the ARP table is populated by the sweep, read it ONCE and fill in
    # every host's MAC/vendor. Give the OS a brief moment to flush entries,
    # then read; retry once if some are still missing.
    time.sleep(0.3)
    arp = _read_arp_table()
    missing = [h for h in pending
               if h["ip"] not in arp and not h["is_self"]]
    if missing:
        # Nudge stragglers into the ARP cache and re-read once.
        for h in missing:
            try:
                ping_host(h["ip"], 100)
            except Exception:
                pass
        time.sleep(0.3)
        arp = _read_arp_table() or arp

    for host in pending:
        ip = host["ip"]
        if host["is_self"] and own_mac:
            host["mac"] = own_mac
        elif ip in arp:
            host["mac"] = arp[ip]
        if host["mac"] and host["mac"] != "Unknown":
            host["vendor"] = lookup_vendor(host["mac"], allow_online=True)

    # Devices with a randomized MAC (every modern iPhone/Android) can't be
    # named from the OUI table, so ask them directly: Bonjour reverse lookup
    # first, then Apple port signatures. Done in parallel so it costs about a
    # second for the whole network, and only for the unidentified ones.
    _fingerprint_unknown_devices(pending)

    for host in pending:
        yield host

    # Second pass: the ping sweep populates the OS ARP table as a side
    # effect. Devices that block ping (typical Windows firewall default)
    # never answered above, but they're now in the ARP table, so pick them up
    # so a silent PC still appears, like a real scanner does.
    arp = _read_arp_table()
    for ip, mac in arp.items():
        if ip in seen_ips or ip == own_ip:
            continue
        # Only same-subnet addresses
        if not ip.startswith(network + "."):
            continue
        try:
            hostname = socket.gethostbyaddr(ip)[0]
        except Exception:
            hostname = "Unknown"
        vendor = lookup_vendor(mac, allow_online=True) if mac else "Unknown"
        found += 1
        seen_ips.add(ip)
        yield {
            "online": True,
            "ip": ip,
            "hostname": hostname,
            "mac": mac or "Unknown",
            "vendor": vendor,
            "is_gateway": (ip == gateway),
            "is_self": False,
            "rtt_ms": None,     # answered via ARP, not ping
            "via": "arp",
        }

    yield {"done": True, "found": found, "scanned": 254}


def _needs_fingerprint(host: dict) -> bool:
    """True when we couldn't name the device from its MAC: a randomized
    address or an OUI we don't know, and no useful hostname either."""
    if host.get("is_self") or host.get("is_gateway"):
        return False
    vendor = (host.get("vendor") or "").strip().lower()
    if vendor and vendor not in ("unknown", "private (randomized)", "private",
                                 "randomized"):
        return False
    hostname = (host.get("hostname") or "").strip()
    if hostname and hostname.lower() != "unknown" and hostname != host.get("ip"):
        return False
    return True


def _fingerprint_unknown_devices(hosts, max_workers=16):
    """Fill in hostname/vendor/kind for unidentified devices, in parallel.

    Best-effort: anything that stays silent is left exactly as it was."""
    import concurrent.futures
    try:
        from core import device_fingerprint
    except Exception:
        return

    targets = [h for h in hosts if _needs_fingerprint(h)]
    if not targets:
        return

    def work(host):
        try:
            return host, device_fingerprint.identify(
                host.get("ip", ""), host.get("hostname", ""),
                host.get("vendor", ""))
        except Exception:
            return host, {}

    workers = min(max_workers, len(targets))
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            for host, found in pool.map(work, targets):
                if not found:
                    continue
                name = found.get("hostname")
                if name:
                    host["hostname"] = name
                vendor = found.get("vendor")
                if vendor:
                    # Keep the privacy note visible, but say who made it.
                    was_private = "private" in (host.get("vendor") or "").lower()
                    host["vendor"] = (f"{vendor} (private address)"
                                      if was_private else vendor)
                kind = found.get("kind")
                if kind:
                    host["kind"] = kind
    except Exception:
        pass


def get_top_devices(limit=10):
    """Non-streaming convenience wrapper around ping_sweep_stream. Runs
    the full sweep and returns a sorted device list, for callers that
    just want a finished table (e.g. populating a Qt table widget once)
    rather than live progress updates."""
    devices = []
    error = None
    for event in ping_sweep_stream():
        if event.get("error"):
            error = event["error"]
            break
        if event.get("online"):
            devices.append(event)
        if event.get("done"):
            break

    if error:
        return {"error": error}

    # Gateway first, then by IP
    devices.sort(key=lambda d: (not d["is_gateway"], [int(x) for x in d["ip"].split(".")]))
    return {"devices": devices[:limit], "total_found": len(devices)}


def get_network_map():
    """Builds a simple two-level topology: internet -> gateway -> devices.
    Returns a structure a frontend can render as a tree/graph directly
    (this is the data source for the 'Network Map' dashboard panel)."""
    try:
        network, gateway, cfg = _resolve_local_network_prefix()
    except RuntimeError as e:
        return {"error": str(e)}

    result = get_top_devices(limit=64)
    if "error" in result:
        return result

    devices = result["devices"]
    gateway_device = next((d for d in devices if d["is_gateway"]), None)
    leaf_devices = [d for d in devices if not d["is_gateway"]]

    return {
        "internet": {"label": "Internet", "public_ip": get_public_ip()},
        "router": gateway_device or {"ip": gateway, "hostname": "Router", "vendor": "Unknown"},
        "devices": leaf_devices,
        "network_range": f"{network}.0/24",
    }


# Traceroute

_HOP_RE = re.compile(r'^\s*(\d{1,2})\s+(.*)$')
_IP_RE = re.compile(r'(\d{1,3}(?:\.\d{1,3}){3})')
_MS_RE = re.compile(r'(\d+(?:[.,]\d+)?)\s*ms', re.I)
_FROM_RE = re.compile(r'(?:reply from|from)\s+(\d{1,3}(?:\.\d{1,3}){3})', re.I)
_TIME_RE = re.compile(r'time[=<]\s*(\d+(?:[.,]\d+)?)', re.I)


def _parse_hop_line(line):
    """Parse one traceroute/tracert output line into a hop dict, or None if
    the line isn't a hop (headers, blank lines, 'Trace complete.').

    Handles both formats:
      Windows:  '  4    24 ms    23 ms    24 ms  213.242.116.9'
                '  3     *        *        *     Request timed out.'
      Linux:    ' 4  213.242.116.9  24.100 ms'
                ' 3  * * *'
    """
    m = _HOP_RE.match(line.rstrip())
    if not m:
        return None
    ttl = int(m.group(1))
    rest = m.group(2)
    ip_m = _IP_RE.search(rest)
    if not ip_m:
        return {"ttl": ttl, "timeout": True}
    times = [float(x.replace(",", ".")) for x in _MS_RE.findall(rest)]
    avg = round(sum(times) / len(times)) if times else None
    ip = ip_m.group(1)
    # Hostname: the token before "[ip]" (Windows) or "(ip)" (Linux), when the
    # tool resolved a name. This is what shows under each hop in the list.
    hostname = ip
    hm = re.search(r'([A-Za-z0-9][A-Za-z0-9.\-]*[A-Za-z0-9])\s*[\[(]\s*'
                   + re.escape(ip), rest)
    if hm and hm.group(1) != ip:
        hostname = hm.group(1)
    return {"ttl": ttl, "ip": ip, "hostname": hostname,
            "times": times, "avg": avg}


def _system_trace(resolved, max_hops):
    """Yield hop dicts using the OS traceroute/tracert. Yields nothing if the
    tool is missing or produced no usable hop lines (caller then falls back)."""
    if platform.system() == "Windows":
        cmd = ["tracert", "-h", str(max_hops), "-w", "1000", resolved]
    else:
        cmd = ["traceroute", "-m", str(max_hops), "-w", "2",
               "-q", "1", resolved]
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, errors="replace", **_no_window())
    except Exception:
        return

    seen = 0
    try:
        for line in proc.stdout:
            low = line.lower()
            if "trace complete" in low or "trace aborted" in low:
                break
            hop = _parse_hop_line(line)
            if hop is None or hop["ttl"] <= seen:
                continue
            seen = hop["ttl"]
            yield hop
            if hop.get("ip") == resolved:
                break
    except Exception:
        pass
    finally:
        for meth in ("terminate", "kill"):
            try:
                getattr(proc, meth)()
                break
            except Exception:
                pass


def _ping_trace(resolved, max_hops):
    """Fallback traceroute built on plain ping with an increasing TTL.

    Works on any machine that can ping (no admin rights, no raw sockets, no
    traceroute binary needed) which makes it a dependable backstop when the
    system tool is missing or blocked.
    """
    is_win = platform.system() == "Windows"
    for ttl in range(1, max_hops + 1):
        if is_win:
            cmd = ["ping", "-n", "1", "-i", str(ttl), "-w", "1500", resolved]
        else:
            cmd = ["ping", "-c", "1", "-t", str(ttl), "-W", "2", resolved]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               errors="replace", timeout=8, **_no_window())
            out = (r.stdout or "") + (r.stderr or "")
        except Exception:
            yield {"ttl": ttl, "timeout": True}
            continue

        m = _FROM_RE.search(out)
        if not m:
            yield {"ttl": ttl, "timeout": True}
            continue
        ip = m.group(1)
        t = _TIME_RE.search(out)
        avg = round(float(t.group(1).replace(",", "."))) if t else None
        yield {"ttl": ttl, "ip": ip, "hostname": ip,
               "times": [avg] if avg is not None else [], "avg": avg}
        if ip == resolved:
            break


def traceroute_stream(target, max_hops=30, auto=False):
    """Trace the network path to a host, yielding one event per hop.

    Events:
        {"resolved": ip, "target": name}   once, first
        {"ttl": n, "ip": .., "hostname": .., "times": [..], "avg": ms}
        {"ttl": n, "timeout": True}
        {"done": True, "reached": bool}    once, last
        {"error": "..."}                   on failure to resolve

    Uses the OS traceroute/tracert, falling back to a ping TTL-walk if that
    yields nothing. Always stops as soon as the destination answers.

    auto: when True, NETWER decides how far to go, it also gives up early
    after several hops in a row time out (the destination is unreachable /
    silently dropping probes), so an "Auto" trace doesn't crawl all the way
    to the ceiling on a dead route.
    """
    try:
        resolved = socket.gethostbyname(target)
    except Exception:
        yield {"error": f"Could not resolve: {target}"}
        return
    yield {"resolved": resolved, "target": target}

    produced = 0
    reached = False
    consecutive_timeouts = 0
    AUTO_TIMEOUT_LIMIT = 5   # give up after this many silent hops in Auto mode

    def _walk(source):
        nonlocal produced, reached, consecutive_timeouts
        for hop in source:
            produced += 1
            if hop.get("timeout"):
                consecutive_timeouts += 1
            else:
                consecutive_timeouts = 0
            yield hop
            if hop.get("ip") == resolved:
                reached = True
                return
            if auto and consecutive_timeouts >= AUTO_TIMEOUT_LIMIT:
                return

    yield from _walk(_system_trace(resolved, max_hops))

    if produced == 0:
        # System tool unavailable or silent, so use the ping fallback.
        yield from _walk(_ping_trace(resolved, max_hops))

    yield {"done": True, "reached": reached}


# Geolocation (for traceroute-on-map)

_GEO_CACHE = {}   # ip -> {lat, lon, city, country} (session cache)
_GEO_LAST_ERROR = None   # last geolocation failure reason (for the UI)
_OFFLINE_GEO = None      # lazily-loaded offline fallback table


def _load_offline_geo():
    global _OFFLINE_GEO
    if _OFFLINE_GEO is not None:
        return _OFFLINE_GEO
    try:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(base, "assets", "geoip_offline.json")
        with open(path, "r", encoding="utf-8") as f:
            _OFFLINE_GEO = json.load(f)
    except Exception:
        _OFFLINE_GEO = {"known": {}, "octet": {}, "names": {}}
    return _OFFLINE_GEO


def _offline_geolocate(ip):
    """Approximate location from a bundled table (no network). Returns
    {lat, lon, city, country} for ANY public IPv4. Falls back to a coarse
    guess for octets not explicitly mapped, so the map always has a point."""
    data = _load_offline_geo()
    known = data.get("known", {})
    if ip in known:
        lat, lon, country, city = known[ip]
        return {"lat": lat, "lon": lon, "city": city, "country": country}
    try:
        octets = [int(x) for x in ip.split(".")]
        first = octets[0]
    except Exception:
        return None
    rule = data.get("octet", {}).get(str(first))
    if rule:
        lat, lon, country = rule
    else:
        # Unmapped octet, place at the region centroid by first octet.
        if first < 64:
            lat, lon, country = 39, -98, "United States"
        elif first < 128:
            lat, lon, country = 48, 10, "Europe"
        elif first < 192:
            lat, lon, country = 35, 105, "Asia"
        else:
            lat, lon, country = 39, -98, "United States"
    return {"lat": lat, "lon": lon, "city": country, "country": country,
            "approx": True}


def geo_last_error():
    return _GEO_LAST_ERROR


def _is_private_ip(ip):
    try:
        return ipaddress.ip_address(ip).is_private
    except Exception:
        return False


def geolocate_ip(ip, timeout=4):
    """Return {lat, lon, city, country} for a public IP, or None.

    Tries ip-api.com (HTTP) then a HTTPS fallback (ipapi.co). Results are
    cached for the session. Private/reserved IPs return None.
    """
    if not ip or _is_private_ip(ip):
        return None
    if ip in _GEO_CACHE:
        return _GEO_CACHE[ip]

    # Provider 1: ip-api.com (fast, generous free tier, HTTP).
    try:
        url = (f"http://ip-api.com/json/{ip}"
               "?fields=status,lat,lon,city,country,regionName")
        req = urllib.request.Request(url, headers={"User-Agent": "NETWER"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8", errors="replace"))
        if data.get("status") == "success" and data.get("lat") is not None:
            geo = {"lat": data.get("lat"), "lon": data.get("lon"),
                   "city": data.get("city") or data.get("regionName") or "",
                   "country": data.get("country") or ""}
            _GEO_CACHE[ip] = geo
            return geo
    except Exception:
        pass

    # Provider 2: ipapi.co (HTTPS fallback).
    try:
        url = f"https://ipapi.co/{ip}/json/"
        req = urllib.request.Request(url, headers={"User-Agent": "NETWER"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8", errors="replace"))
        if data.get("latitude") is not None and not data.get("error"):
            geo = {"lat": data.get("latitude"), "lon": data.get("longitude"),
                   "city": data.get("city") or data.get("region") or "",
                   "country": data.get("country_name") or ""}
            _GEO_CACHE[ip] = geo
            return geo
    except Exception:
        pass

    # Offline fallback: approximate region from the bundled table so the map
    # still works with no internet / when the APIs are blocked.
    off = _offline_geolocate(ip)
    if off:
        _GEO_CACHE[ip] = off
        return off

    return None


def traceroute_geo_stream(target, max_hops=30, home_lat=None, home_lon=None):
    """Traceroute that yields the same events as traceroute_stream, marking
    private hops as local (and pinning them to the user's coordinates if
    known). Public hops are NOT geolocated here, that happens afterwards in
    geolocate_hops(), in parallel, so a slow or blocked geo provider can't
    stall the trace itself (one blocking HTTP call per hop used to make a
    30-hop trace take minutes on a network where the provider is blocked).
    """
    for ev in traceroute_stream(target, max_hops=max_hops):
        if "ip" in ev and not ev.get("timeout"):
            ip = ev["ip"]
            if _is_private_ip(ip):
                ev["local"] = True
                if home_lat is not None and home_lon is not None:
                    ev["lat"], ev["lon"] = home_lat, home_lon
                    ev["city"] = "Local network"
        yield ev


def geolocate_hops(ips, timeout=6, max_workers=8):
    """Geolocate several IPs at once. Returns {ip: geo_or_None}.

    Tries ip-api.com's batch endpoint first (a single POST for up to 100
    addresses, far faster and much less likely to hit the per-minute rate
    limit than one request per hop). Falls back to parallel single lookups
    if the batch call isn't available.
    """
    out = {}
    todo = []
    for ip in dict.fromkeys(ips):
        if not ip or _is_private_ip(ip):
            continue
        if ip in _GEO_CACHE:
            out[ip] = _GEO_CACHE[ip]
        else:
            todo.append(ip)
    if not todo:
        return out

    # 1) Batch endpoint: one request for everything.
    try:
        payload = json.dumps([
            {"query": ip, "fields": "status,lat,lon,city,country,query"}
            for ip in todo[:100]
        ]).encode("utf-8")
        req = urllib.request.Request(
            "http://ip-api.com/batch", data=payload,
            headers={"User-Agent": "NETWER/1.0",
                     "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            results = json.loads(r.read().decode("utf-8", errors="replace"))
        got = False
        for item in results or []:
            ip = item.get("query")
            if not ip:
                continue
            if item.get("status") == "success" and item.get("lat") is not None:
                geo = {"lat": item["lat"], "lon": item["lon"],
                       "city": item.get("city") or "",
                       "country": item.get("country") or ""}
                _GEO_CACHE[ip] = geo
                out[ip] = geo
                got = True
            else:
                out[ip] = None
        if got:
            # Fill any the batch marked as failed with the offline estimate.
            for ip in todo:
                if out.get(ip) is None:
                    off = _offline_geolocate(ip)
                    if off:
                        _GEO_CACHE[ip] = off
                        out[ip] = off
            return out
    except Exception:
        pass

    # 2) Fallback: parallel single lookups (each already falls back offline).
    from concurrent.futures import ThreadPoolExecutor
    try:
        with ThreadPoolExecutor(max_workers=min(max_workers, len(todo))) as ex:
            for ip, geo in zip(todo, ex.map(
                    lambda i: geolocate_ip(i, timeout=4), todo)):
                out[ip] = geo
    except Exception:
        for ip in todo:
            out.setdefault(ip, geolocate_ip(ip))
    return out


def geolocate_me(timeout=3):
    """Best-effort geolocation of the user's own public IP (for the map's
    starting point). Returns {lat, lon, city, country} or None."""
    try:
        url = ("http://ip-api.com/json/"
               "?fields=status,lat,lon,city,country,regionName,query")
        req = urllib.request.Request(url, headers={"User-Agent": "NETWER"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8", errors="replace"))
        if data.get("status") == "success":
            return {"lat": data.get("lat"), "lon": data.get("lon"),
                    "city": data.get("city") or "", "country": data.get("country") or ""}
    except Exception:
        pass
    return None


# DNS tools

def dns_lookup(domain):
    try:
        results = socket.getaddrinfo(domain, None)
        ipv4 = list({r[4][0] for r in results if r[0] == socket.AF_INET})
        ipv6 = list({r[4][0] for r in results if r[0] == socket.AF_INET6})
        try:
            canonical = socket.gethostbyname_ex(domain)[0]
        except Exception:
            canonical = domain
        return {"ipv4": ipv4, "ipv6": ipv6, "canonical": canonical, "total": len(ipv4) + len(ipv6)}
    except Exception as e:
        return {"error": str(e)}


def reverse_dns(ip):
    try:
        hostname, aliases, _ = socket.gethostbyaddr(ip)
        return {"ip": ip, "hostname": hostname, "aliases": list(aliases)}
    except Exception as e:
        return {"error": str(e)}


# Network adapters

def list_adapters_linux():
    """List network adapters on Linux via psutil (name, status, speed, MTU,
    MAC). Mirrors the shape of the Windows PowerShell path so the Network
    Information page can render either the same way."""
    stats = psutil.net_if_stats()
    adapter_list = []

    for name, stat in stats.items():
        adapter_dict = dict()
        adapter_dict["name"] = name
        adapter_dict["description"] = f"No description for {name} adapter"
        adapter_dict["status"] = "Up" if stat.isup else "Down"
        adapter_dict["link_speed"] = stat.speed
        adapter_dict["mtu"] = stat.mtu
        adapter_list.append(adapter_dict)

    for interface, addresses in psutil.net_if_addrs().items():
        for address in addresses:
            if address.family == psutil.AF_LINK:
                for adapter in adapter_list:
                    if adapter["name"] == interface:
                        adapter["mac"] = address.address
    return adapter_list


def handle_adapter_details_linux(adapter_name):
    """Full IP configuration for ONE adapter on Linux. Uses psutil for
    addresses and nmcli for gateway/DNS/DHCP method, and /sys/class/net to
    tell physical from virtual interfaces."""
    try:
        def run_nmcli(field, adapter_name):
            args = ["nmcli", "-g", field, "device", "show", adapter_name]
            output_from_command = subprocess.run(
                args, capture_output=True, text=True).stdout.strip()
            return output_from_command

        def get_dhcp(adapter_name):
            # First get the connection type, then retrieve the dhcp method.
            connection_type = run_nmcli("GENERAL.CONNECTION", adapter_name)
            args = ["nmcli", "-g", "ipv4.method", "connection", "show",
                    connection_type]
            dhcp_output = subprocess.run(
                args, capture_output=True, text=True).stdout.strip()
            return dhcp_output

        def get_virtual_type(adapter_name):
            adapter_path = Path(f"/sys/class/net/{adapter_name}/device")
            if adapter_path.is_dir():
                # Physical, so return nothing (UI treats empty as physical).
                return ""
            else:
                return "Virtual"

        def get_prefix(subnet_mask):
            prefix = ipaddress.IPv4Network(
                f"0.0.0.0/{subnet_mask}"
            ).prefixlen
            return prefix

        adapter_list = list_adapters_linux()
        stats = psutil.net_if_addrs()
        for name, stat in stats.items():
            for address in stat:
                for adapter in adapter_list:
                    if adapter["name"] == name:
                        if address.family == socket.AF_INET:
                            adapter["ipv4"] = str(address.address)
                            adapter["subnet_mask"] = str(address.netmask)
                        if address.family == socket.AF_INET6:
                            adapter["ipv6"] = str(address.address)
        for adapter in adapter_list:
            adapter["gateway"] = run_nmcli("IP4.GATEWAY", adapter["name"])
            adapter["prefix"] = get_prefix(adapter.get("subnet_mask", "0.0.0.0"))
            adapter["dns"] = run_nmcli("IP4.DNS", adapter["name"])
            adapter["dhcp"] = get_dhcp(adapter["name"])
            adapter["virtual"] = get_virtual_type(adapter["name"])
        for adapter in adapter_list:
            if adapter["name"] == adapter_name:
                return adapter
    except Exception as e:
        return {"error": str(e)}


def list_adapters():
    try:
        # If it's linux, handle it accordingly, otherwise handle it for windows
        if used_os == "linux":
            return list_adapters_linux()
        ps_cmd = "Get-NetAdapter | Select-Object Name,Status,InterfaceDescription,MacAddress | ConvertTo-Json -Depth 2"
        raw = run_powershell(ps_cmd, timeout=20)
        if not raw:
            return {"error": "No adapters found (Unsupported OS found)"}
        data = json.loads(raw)
        if isinstance(data, dict):
            data = [data]
        return [
            {"name": a.get("Name", ""), "status": a.get("Status", ""),
             "description": a.get("InterfaceDescription", ""), "mac": a.get("MacAddress", "")}
            for a in data
        ]
    except Exception as e:
        return {"error": str(e)}


def _windows_adapter_details_native(adapter_name):
    """Fast native adapter details via `ipconfig /all` (+ `netsh wlan` for the
    Wi-Fi link rate). Used to fill in Description / DHCP / Link Speed when the
    Get-Net* PowerShell path is slow or times out, which is exactly what left
    those fields blank in the PDF report on Wi-Fi."""
    out = {}
    try:
        raw = subprocess.run(["ipconfig", "/all"], capture_output=True,
                             text=True, timeout=6, **_no_window()).stdout or ""
    except Exception:
        return out
    if not raw:
        return out

    blocks = re.split(r'\n(?=[^\s].*:\s*\n)', raw)
    want = (adapter_name or "").strip().lower()
    for block in blocks:
        header = block.strip().splitlines()[0] if block.strip() else ""
        alias = re.sub(r'^.*adapter\s+', '', header, flags=re.I).rstrip(":").strip()
        if want and alias.lower() != want:
            continue

        def field(*labels):
            for lab in labels:
                m = re.search(r'^\s*' + lab + r'[ .]*:\s*(.+)$', block,
                              re.MULTILINE)
                if m:
                    return m.group(1).strip()
            return ""

        desc = field(r'Description', r'Opis')
        if desc:
            out["description"] = desc
        dhcp = field(r'DHCP Enabled', r'DHCP omogućen', r'DHCP omogucen')
        if dhcp:
            out["dhcp"] = ("Enabled" if dhcp.strip().lower().startswith(("yes", "da"))
                           else "Static/Manual")
        mac = field(r'Physical Address', r'Fizička adresa')
        if mac:
            out["mac"] = mac.replace("-", ":").upper()

        # Addressing: these were still blank on the Network Information page
        # whenever the PowerShell path timed out, so read them here too.
        ipv4 = re.sub(r'\(.*?\)', '', field(r'IPv4 Address', r'IPv4 adresa',
                                            r'IP Address')).strip()
        if re.fullmatch(r'\d{1,3}(\.\d{1,3}){3}', ipv4 or ""):
            out["ipv4"] = ipv4
        mask = field(r'Subnet Mask', r'Maska podmreže')
        if mask:
            out["subnet_mask"] = mask
            out["prefix"] = _mask_to_prefix(mask)
        gw = field(r'Default Gateway', r'Zadani pristupnik')
        gm = re.search(r'\d{1,3}(\.\d{1,3}){3}', gw or "")
        if gm:
            out["gateway"] = gm.group(0)
        # DNS servers can span several indented continuation lines.
        dm = re.search(r'^\s*DNS Servers[ .]*:\s*(.+(?:\n\s{6,}\S+)*)',
                       block, re.MULTILINE)
        if dm:
            servers = re.findall(r'\d{1,3}(?:\.\d{1,3}){3}', dm.group(1))
            if servers:
                out["dns"] = ", ".join(servers)
        # "Media State . . . : Media disconnected" means the adapter is down.
        media = field(r'Media State', r'Stanje medija')
        if media:
            out["status"] = ("Disconnected" if "disconnect" in media.lower()
                             else "Up")
        elif out.get("ipv4"):
            out["status"] = "Up"
        break

    # MTU isn't in ipconfig, but netsh knows it.
    try:
        mt = subprocess.run(
            ["netsh", "interface", "ipv4", "show", "subinterfaces"],
            capture_output=True, text=True, timeout=6, **_no_window()).stdout or ""
        for line in mt.splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[0].isdigit():
                if " ".join(parts[4:]).strip().lower() == (adapter_name or "").lower():
                    out["mtu"] = parts[0]
                    break
    except Exception:
        pass

    # Link speed: ipconfig doesn't report it. For Wi-Fi, netsh does.
    try:
        wl = subprocess.run(["netsh", "wlan", "show", "interfaces"],
                            capture_output=True, text=True, timeout=6,
                            **_no_window()).stdout or ""
        m = re.search(r'^\s*Receive rate \(Mbps\)[ .]*:\s*(.+)$', wl,
                      re.MULTILINE)
        if m:
            out["link_speed"] = f"{m.group(1).strip()} Mbps"
    except Exception:
        pass
    return out


def get_adapter_details(adapter_name):
    """Full IP configuration for ONE named adapter, drives the Network
    Information page. Returns a dict of fields (ip, mask, gateway, dns,
    mac, speed, status, dhcp, ...) or {"error": ...}. Windows-only."""
    if not adapter_name:
        return {"error": "No adapter name given"}
    try:
        # Escape single quotes in the name for PowerShell safety.
        safe = adapter_name.replace("'", "''")
        ps_cmd = r"""
$name = '""" + safe + r"""'
$ad = Get-NetAdapter -Name $name -ErrorAction SilentlyContinue
if (-not $ad) { Write-Output '{}'; exit }
$cfg = Get-NetIPConfiguration -InterfaceAlias $name -ErrorAction SilentlyContinue
$ipv4 = Get-NetIPAddress -InterfaceAlias $name -AddressFamily IPv4 -ErrorAction SilentlyContinue | Select-Object -First 1
$ipv6 = Get-NetIPAddress -InterfaceAlias $name -AddressFamily IPv6 -ErrorAction SilentlyContinue | Select-Object -First 1
$dnsList = @()
if ($cfg -and $cfg.DNSServer) {
    foreach ($d in $cfg.DNSServer) {
        if ($d.ServerAddresses) { $dnsList += $d.ServerAddresses }
    }
}
$dnsList = $dnsList | Where-Object { $_ -match '^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$' }
$gw = if ($cfg -and $cfg.IPv4DefaultGateway) { $cfg.IPv4DefaultGateway.NextHop } else { '' }
$prefix = if ($ipv4) { [int]$ipv4.PrefixLength } else { 0 }
$dhcp = if ($ipv4) { $ipv4.PrefixOrigin } else { '' }
$linkSpeed = if ($ad.LinkSpeed) { $ad.LinkSpeed } else { '' }
[pscustomobject]@{
    name        = $ad.Name
    description = $ad.InterfaceDescription
    status      = $ad.Status
    mac         = $ad.MacAddress
    link_speed  = $linkSpeed
    ipv4        = if ($ipv4) { $ipv4.IPAddress } else { '' }
    ipv6        = if ($ipv6) { $ipv6.IPAddress } else { '' }
    prefix      = $prefix
    gateway     = $gw
    dns         = ($dnsList -join ', ')
    dhcp        = $dhcp
    mtu         = $ad.MtuSize
    virtual     = $ad.Virtual
} | ConvertTo-Json
"""  # noqa: W605 (regex backslashes are for PowerShell)
        raw = run_powershell(ps_cmd, timeout=10)
        if used_os == "linux":
            return handle_adapter_details_linux(adapter_name)
        if not raw or raw.strip() == "{}":
            return {"error": f"Adapter '{adapter_name}' not found"}
        data = json.loads(raw)

        # Derive subnet mask from prefix length
        prefix = data.get("prefix", 0)
        mask = _prefix_to_mask(prefix) if prefix else ""

        result = {
            "name": data.get("name", adapter_name),
            "description": data.get("description", ""),
            "status": data.get("status", ""),
            "mac": data.get("mac", ""),
            "link_speed": data.get("link_speed", ""),
            "ipv4": data.get("ipv4", ""),
            "ipv6": data.get("ipv6", ""),
            "subnet_mask": mask,
            "prefix": prefix,
            "gateway": data.get("gateway", ""),
            "dns": data.get("dns", ""),
            "dhcp": "Enabled" if str(data.get("dhcp", "")).lower() == "dhcp" else "Static/Manual",
            "mtu": data.get("mtu", ""),
            "virtual": data.get("virtual", False),
        }
        # Backfill anything PowerShell left blank from the fast native source.
        native = _windows_adapter_details_native(adapter_name)
        for key in ("description", "dhcp", "link_speed", "mac", "ipv4",
                    "subnet_mask", "gateway", "dns", "status", "mtu",
                    "prefix"):
            if not result.get(key) and native.get(key):
                result[key] = native[key]
        return result
    except Exception:
        # PowerShell failed or timed out (common on Wi-Fi), so return whatever
        # the native path can tell us instead of an error with empty fields.
        native = _windows_adapter_details_native(adapter_name)
        if native:
            native.setdefault("name", adapter_name)
            return native
        return {"error": "Could not read adapter details"}


def _prefix_to_mask(prefix):
    """Convert CIDR prefix length (e.g. 24) to dotted mask (255.255.255.0)."""
    try:
        prefix = int(prefix)
        mask = (0xffffffff >> (32 - prefix)) << (32 - prefix) if prefix else 0
        return ".".join(str((mask >> (8 * i)) & 0xff) for i in (3, 2, 1, 0))
    except (ValueError, TypeError):
        return ""


# Network monitor (live download/upload, for both the standalone screen
# and the dashboard's "Live Network Monitor" + "Interface Traffic" charts)

def find_psutil_interface(ps_name):
    if not PSUTIL_AVAILABLE:
        return None
    io = psutil.net_io_counters(pernic=True)
    if not io:
        return None
    if ps_name in io:
        return ps_name
    ps_lower = ps_name.lower()
    for k in io:
        if k.lower() == ps_lower:
            return k
    for k in io:
        if ps_lower in k.lower() or k.lower() in ps_lower:
            return k
    skip = ("loopback", "isatap", "teredo", "virtual", "vethernet", "bluetooth", "npcap")
    candidates = {k: v for k, v in io.items() if not any(s in k.lower() for s in skip)}
    pool = candidates if candidates else io
    return max(pool, key=lambda k: pool[k].bytes_recv + pool[k].bytes_sent)


def _is_virtual_iface(name):
    """Heuristic: is this psutil interface name a virtual/non-physical one?"""
    low = name.lower()
    keywords = ("vmware", "virtualbox", "vethernet", "hyper-v", "loopback",
                "vmnet", "vpn", "tap", "tun", "pseudo", "bluetooth",
                "isatap", "teredo", "wan miniport")
    return any(k in low for k in keywords)


def _pick_traffic_ifaces(adapter_name=""):
    """Return the list of psutil interface names to monitor.

    - If adapter_name is given, resolve it to a single psutil iface.
    - Otherwise, return ALL real (physical, up) interfaces. We sum their
      traffic, so it doesn't matter which one the OS routes through, the
      one actually moving bytes dominates. This avoids the whole 'picked
      the VMware adapter' problem entirely.
    """
    if not PSUTIL_AVAILABLE:
        return []
    io = psutil.net_io_counters(pernic=True)
    stats = psutil.net_if_stats()

    if adapter_name:
        key = find_psutil_interface(adapter_name)
        return [key] if key else []

    picked = []
    for name in io:
        st = stats.get(name)
        if st is None or not st.isup:
            continue
        if _is_virtual_iface(name):
            continue
        picked.append(name)
    # Fallback: if we filtered everything out, use all up interfaces
    if not picked:
        picked = [n for n in io if stats.get(n) and stats[n].isup]
    return picked


def _sum_counters(iface_names):
    """Sum bytes_recv/bytes_sent across the given psutil interfaces."""
    io = psutil.net_io_counters(pernic=True)
    recv = sent = 0
    for n in iface_names:
        c = io.get(n)
        if c:
            recv += c.bytes_recv
            sent += c.bytes_sent
    return recv, sent


def monitor_stream(adapter_name="", max_samples=600):
    """Generator: yields one dict per second with current dl/ul Mbps and
    running totals. Drives both the standalone Network Monitor screen and
    the dashboard's live traffic chart.

    Auto mode sums ALL real (non-virtual) adapters, so traffic shows up
    regardless of which adapter Windows routes through, no fragile
    'guess the right adapter' logic, and VMware/VirtualBox adapters are
    excluded automatically.
    """
    if not PSUTIL_AVAILABLE:
        yield {"error": "psutil is required for Network Monitor. pip install psutil"}
        return

    ifaces = _pick_traffic_ifaces(adapter_name)
    if not ifaces:
        yield {"error": "No active network interface found"}
        return

    # Friendly label for what we're monitoring
    if adapter_name:
        label = adapter_name
    elif len(ifaces) == 1:
        label = ifaces[0]
    else:
        label = f"All physical adapters ({len(ifaces)})"

    prev_recv, prev_sent = _sum_counters(ifaces)
    prev_time = time.time()
    total_dl = total_ul = 0.0

    yield {"dl": 0.0, "ul": 0.0, "total_dl": 0.0, "total_ul": 0.0,
           "adapter": label, "iface": ",".join(ifaces)}

    for _ in range(max_samples):
        time.sleep(1)
        cur_recv, cur_sent = _sum_counters(ifaces)
        now = time.time()
        elapsed = max(now - prev_time, 0.001)
        prev_time = now

        dl_bytes = max(0, cur_recv - prev_recv)
        ul_bytes = max(0, cur_sent - prev_sent)
        prev_recv, prev_sent = cur_recv, cur_sent

        dl_mbps = round(dl_bytes * 8 / elapsed / 1_048_576, 2)
        ul_mbps = round(ul_bytes * 8 / elapsed / 1_048_576, 2)
        total_dl += dl_bytes / 1_048_576
        total_ul += ul_bytes / 1_048_576

        yield {"dl": dl_mbps, "ul": ul_mbps, "total_dl": round(total_dl, 2),
               "total_ul": round(total_ul, 2), "adapter": label,
               "iface": ",".join(ifaces)}


def get_bandwidth_today():
    """Total bytes sent/received since boot, backs the dashboard's
    'Bandwidth Usage (Today)' card. Note: this is since-boot, not a true
    midnight-to-now figure, since the OS doesn't track that natively
    without a persistence layer. Documented here so the PyQt side knows
    the caveat and can label it accordingly."""
    if not PSUTIL_AVAILABLE:
        return {"error": "psutil is required. pip install psutil"}
    try:
        io = psutil.net_io_counters()
        return {
            "download_gb": round(io.bytes_recv / (1024 ** 3), 2),
            "upload_gb": round(io.bytes_sent / (1024 ** 3), 2),
        }
    except Exception as e:
        return {"error": str(e)}


# Speed test (Ookla CLI wrapper)

def find_speedtest_exe():
    search_paths = [
        os.path.expandvars(r"%USERPROFILE%\Desktop\speedtest.exe"),
        os.path.expandvars(r"%USERPROFILE%\Downloads\speedtest.exe"),
        r"C:\speedtest\speedtest.exe",
    ]
    for p in search_paths:
        if os.path.isfile(p):
            return p
    try:
        r = subprocess.run(["where", "speedtest.exe"], capture_output=True, text=True)
        if r.returncode == 0:
            return r.stdout.strip().splitlines()[0]
    except Exception:
        pass
    return None


def speedtest_stream():
    exe = find_speedtest_exe()
    if not exe:
        yield {"error": "speedtest.exe not found"}
        return

    try:
        proc = subprocess.Popen(
            [exe, "--format=jsonl", "--accept-license", "--accept-gdpr"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True
        )
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            etype = event.get("type", "")
            if etype == "testStart":
                yield {"type": "start", "isp": event.get("isp", ""),
                       "server": event.get("server", {}).get("name", "")}
            elif etype == "ping":
                yield {"type": "ping", "ms": round(event["ping"]["latency"], 1)}
            elif etype == "download":
                yield {"type": "download", "mbps": round(event["download"]["bandwidth"] * 8 / 1_048_576, 2)}
            elif etype == "upload":
                yield {"type": "upload", "mbps": round(event["upload"]["bandwidth"] * 8 / 1_048_576, 2)}
            elif etype == "result":
                yield {"type": "result",
                       "ping": round(event["ping"]["latency"], 1),
                       "dl": round(event["download"]["bandwidth"] * 8 / 1_048_576, 2),
                       "ul": round(event["upload"]["bandwidth"] * 8 / 1_048_576, 2)}
    except Exception as e:
        yield {"error": str(e)}


# Save report

def save_report(path="", name="netwer_report"):
    path = path.strip() or os.path.join(os.path.expanduser("~"), "Desktop")
    path = os.path.expandvars(os.path.expanduser(path))
    name = name.strip() or "netwer_report"

    if not os.path.isdir(path):
        return {"error": f"Path does not exist: {path}"}

    invalid_chars = set(r'/:*?"<>|')
    bad = [c for c in name if c in invalid_chars]
    if bad:
        return {"error": f"Invalid characters in filename: {bad}"}

    eth = get_ethernet_info()
    if "error" in eth:
        return {"error": f"Could not read network config: {eth['error']}"}

    lines = [
        "==============================",
        "     NETWER NETWORK REPORT    ",
        "==============================",
        "",
        f"  Computer : {socket.gethostname()}",
        f"  Date     : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "  ----- NETWORK INFO -----",
        f"  Adapter      : {eth['adapter']}",
        f"  IPv4 Address : {eth['ip']}",
        f"  Public IP    : {eth['public_ip']}",
        f"  MAC Address  : {eth['mac']}",
        f"  Subnet Mask  : {eth['subnet_mask']}",
        f"  Gateway      : {eth['gateway']}",
        f"  DNS Server   : {eth['dns']}",
        "",
        "  ----- IP ANALYSIS -----",
        f"  Class : {eth['ip_class']}",
        f"  Type  : {eth['ip_type']}",
        "",
        "==============================",
    ]

    filepath = os.path.join(path, f"{name}.txt")
    try:
        with open(filepath, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
        return {"success": True, "path": filepath}
    except PermissionError:
        return {"error": f"Permission denied: {filepath}"}
    except Exception as e:
        return {"error": str(e)}
