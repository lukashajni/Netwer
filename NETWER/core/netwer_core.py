"""
NETWER CORE — pure Python backend logic, no web framework dependency.

This module contains every diagnostic/monitoring function as plain
functions and generators. Designed to be imported directly by any
frontend (PyQt, CLI, Flask, etc.) — nothing here depends on Flask,
request objects, or HTTP at all.

Conventions used throughout:
- Functions that return one result return a dict.
- Functions that produce a stream of updates (ping sweep, monitor,
  speed test) are Python generators that `yield` dicts — the caller
  decides how to consume them (Qt signal emission, SSE, print, etc.)
- All functions handle their own errors and return {"error": "..."}
  rather than raising, so callers don't need try/except everywhere.
"""

import os
import re
import json
import time
import socket
import platform
import ipaddress
import subprocess
from datetime import datetime

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False


# ══════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════

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
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True, text=True, timeout=timeout
    )
    return result.stdout.strip()


# ══════════════════════════════════════════
# MAC VENDOR LOOKUP (OUI) — offline, no API dependency
# ══════════════════════════════════════════

# Minimal built-in OUI table covering the vendors you'll actually see on a
# home/office network. Keys are the first 6 hex chars of the MAC (no
# separators, uppercase). This is intentionally small — add entries as
# needed rather than shipping a multi-MB IEEE database.
OUI_TABLE = {
    "001A11": "Google", "3C5AB4": "Google", "F4F5D8": "Google",
    "A45C2C": "ASUSTek", "AC9E17": "ASUSTek", "D8501A": "ASUSTek",
    "B827EB": "Raspberry Pi", "DCA632": "Raspberry Pi", "E45F01": "Raspberry Pi",
    "001E58": "Synology", "0011D8": "Synology", "001132": "Synology",
    "B0A4E8": "MikroTik", "4C5E0C": "MikroTik", "6C3B6B": "MikroTik", "DC2C6E": "MikroTik",
    "00163C": "TP-Link", "1C61B4": "TP-Link", "50C7BF": "TP-Link", "F4F26D": "TP-Link",
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

    # 1) Local table
    vendor = OUI_TABLE.get(prefix)
    if vendor:
        return vendor

    # 2) Cache from earlier online lookups
    if prefix in _ONLINE_VENDOR_CACHE:
        return _ONLINE_VENDOR_CACHE[prefix]

    # 3) Online lookup (opt-in, worker only)
    if allow_online:
        try:
            from core.oui_extended import online_vendor_lookup
            name = online_vendor_lookup(mac_address)
            if name:
                _ONLINE_VENDOR_CACHE[prefix] = name
                return name
        except Exception:
            pass
        # Cache the miss so we don't retry every scan
        _ONLINE_VENDOR_CACHE[prefix] = "Unknown"

    return "Unknown"


# ══════════════════════════════════════════
# NETWORK CONFIG (Ethernet Info source of truth)
# ══════════════════════════════════════════

def get_network_config():
    """Returns the active adapter's IP config as a dict, or {"error": ...}."""
    try:
        if platform.system() == "Windows":
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
    """Full Ethernet Info screen data — same shape as before, unchanged."""
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


# ══════════════════════════════════════════
# WIFI INFO
# ══════════════════════════════════════════

def get_wifi_info():
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


# ══════════════════════════════════════════
# SYSTEM INFO (static snapshot — name/CPU model/OS/uptime)
# ══════════════════════════════════════════

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
    hardware detail — core counts, CPU frequency, architecture, OS build,
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


# ══════════════════════════════════════════
# SYSTEM RESOURCES — live CPU / RAM / Disk for dashboard gauges
# (NEW — this is the "System Resources" card from the dashboard mockup)
# ══════════════════════════════════════════

def get_system_resources():
    """A live snapshot of CPU%, RAM%, and Disk% usage — call this on a
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
    the loop (e.g. by closing the dashboard tab) — this doesn't run forever
    on its own past max_samples as a safety net."""
    for _ in range(max_samples):
        yield get_system_resources()
        time.sleep(interval_s)


# ══════════════════════════════════════════
# PING — quick / stability / custom
# ══════════════════════════════════════════

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

    count=0 means CONTINUOUS — run until the caller stops iterating (the
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


# ══════════════════════════════════════════
# PORT SCANNER
# ══════════════════════════════════════════

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


def _classify_port(ip, port, timeout):
    """Probe a single TCP port and classify the result the way a real
    scanner does:
        open     — connection succeeded (service is listening)
        closed   — host actively refused (RST) → port reachable, nothing there
        filtered — no response within timeout (firewall dropping packets)
    Returns a dict with port, service, protocol, state.
    """
    service, proto = port_service(port)
    state = "filtered"
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        result = s.connect_ex((ip, int(port)))
        s.close()
        if result == 0:
            state = "open"
        elif result in (111, 10061):        # ECONNREFUSED (Linux / Windows)
            state = "closed"
        else:
            state = "filtered"              # timeout / unreachable → filtered
    except socket.timeout:
        state = "filtered"
    except Exception:
        state = "filtered"
    return {"port": int(port), "service": service, "protocol": proto,
            "state": state}


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

    ip         — target host (IP or resolvable hostname)
    ports      — profile name, spec string, or explicit list of ints.
                 Defaults to the 'common' profile.
    timeout_ms — per-port connect timeout.

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

    # Resolve hostname → IP up front.
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


# ══════════════════════════════════════════
# PING SWEEP / TOP DEVICES / NETWORK MAP
# These three share the same underlying scan — they're just different
# presentations of "what's alive on my LAN right now".
# ══════════════════════════════════════════

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
    # Own machine: ARP won't have it — use the adapter MAC.
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
    """Read the full ARP table → {ip: mac}. Devices that block ping (common
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
    or '192.168.88'. Only /24 (or an implied /24) is supported — returns
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

    subnet — optional CIDR or prefix to scan (e.g. "192.168.88.0/24" or
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

    # Resolve our own IP/MAC once — ARP won't list us, so we label our own
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
        mac = _get_mac_for_ip(ip, own_ip=own_ip, own_mac=own_mac)
        vendor = lookup_vendor(mac, allow_online=True) if mac else "Unknown"
        return {
            "online": True,
            "ip": ip,
            "hostname": hostname,
            "mac": mac or "Unknown",
            "vendor": vendor,
            "is_gateway": (ip == gateway),
            "is_self": (own_ip and ip == own_ip),
            "rtt_ms": ms,
        }

    found = 0
    scanned = 0
    seen_ips = set()
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
                yield host

    # Second pass: the ping sweep populates the OS ARP table as a side
    # effect. Devices that block ping (typical Windows firewall default)
    # never answered above, but they're now in the ARP table — pick them up
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


def get_top_devices(limit=10):
    """Non-streaming convenience wrapper around ping_sweep_stream — runs
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


# ══════════════════════════════════════════
# TRACEROUTE
# ══════════════════════════════════════════

def traceroute_stream(target, max_hops=30):
    try:
        resolved = socket.gethostbyname(target)
        yield {"resolved": resolved, "target": target}
    except Exception:
        yield {"error": f"Could not resolve: {target}"}
        return

    for ttl in range(1, max_hops + 1):
        times, hop_ip = [], None
        try:
            if platform.system() == "Windows":
                cmd = ["tracert", "-h", str(ttl), "-w", "1000", "-d", resolved]
            else:
                cmd = ["traceroute", "-m", str(ttl), "-w", "1", "-q", "1", resolved]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=6)
            for line in result.stdout.splitlines():
                m = re.search(r'(\d+)\s*ms', line)
                ip_m = re.search(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})', line)
                if m:
                    times.append(int(m.group(1)))
                if ip_m:
                    hop_ip = ip_m.group(1)
        except Exception:
            pass

        if not times or not hop_ip:
            yield {"ttl": ttl, "timeout": True}
        else:
            try:
                hostname = socket.gethostbyaddr(hop_ip)[0]
            except Exception:
                hostname = hop_ip
            avg = round(sum(times) / len(times))
            yield {"ttl": ttl, "ip": hop_ip, "hostname": hostname, "times": times, "avg": avg}
            if hop_ip == resolved:
                yield {"done": True, "reached": True}
                return

    yield {"done": True, "reached": False}


# ══════════════════════════════════════════
# DNS TOOLS
# ══════════════════════════════════════════

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


# ══════════════════════════════════════════
# NETWORK ADAPTERS
# ══════════════════════════════════════════

def list_adapters():
    try:
        ps_cmd = "Get-NetAdapter | Select-Object Name,Status,InterfaceDescription,MacAddress | ConvertTo-Json -Depth 2"
        raw = run_powershell(ps_cmd, timeout=8)
        if not raw:
            return {"error": "No adapters found (Windows-only feature)"}
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


def get_adapter_details(adapter_name):
    """Full IP configuration for ONE named adapter — drives the Network
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
        if not raw or raw.strip() == "{}":
            return {"error": f"Adapter '{adapter_name}' not found"}
        data = json.loads(raw)

        # Derive subnet mask from prefix length
        prefix = data.get("prefix", 0)
        mask = _prefix_to_mask(prefix) if prefix else ""

        return {
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
    except Exception as e:
        return {"error": str(e)}


def _prefix_to_mask(prefix):
    """Convert CIDR prefix length (e.g. 24) to dotted mask (255.255.255.0)."""
    try:
        prefix = int(prefix)
        mask = (0xffffffff >> (32 - prefix)) << (32 - prefix) if prefix else 0
        return ".".join(str((mask >> (8 * i)) & 0xff) for i in (3, 2, 1, 0))
    except (ValueError, TypeError):
        return ""


# ══════════════════════════════════════════
# NETWORK MONITOR (live download/upload, for both the standalone screen
# and the dashboard's "Live Network Monitor" + "Interface Traffic" charts)
# ══════════════════════════════════════════

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
      traffic, so it doesn't matter which one the OS routes through — the
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
    regardless of which adapter Windows routes through — no fragile
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
    """Total bytes sent/received since boot — backs the dashboard's
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


# ══════════════════════════════════════════
# SPEED TEST (Ookla CLI wrapper)
# ══════════════════════════════════════════

def find_speedtest_exe():
    search_paths = [
        os.path.expandvars(r"%USERPROFILE%\Desktop\Netwer\ookla-speedtest-1.2.0-win64\speedtest.exe"),
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


# ══════════════════════════════════════════
# SAVE REPORT
# ══════════════════════════════════════════

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
