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


def lookup_vendor(mac_address):
    """Best-effort vendor name from a MAC address using the local OUI table.
    Returns 'Unknown' if not found — does not call out to the network."""
    if not mac_address:
        return "Unknown"
    cleaned = re.sub(r'[^0-9A-Fa-f]', '', mac_address).upper()
    if len(cleaned) < 6:
        return "Unknown"
    prefix = cleaned[:6]
    return OUI_TABLE.get(prefix, "Unknown")


# ══════════════════════════════════════════
# NETWORK CONFIG (Ethernet Info source of truth)
# ══════════════════════════════════════════

def get_network_config():
    """Returns the active adapter's IP config as a dict, or {"error": ...}."""
    try:
        if platform.system() == "Windows":
            ps_cmd = """
$c = Get-NetIPConfiguration | Where-Object { $_.IPv4Address -ne $null -and $_.NetAdapter.Status -eq 'Up' } | Select-Object -First 1
if (-not $c) { Write-Output '{}'; exit }
$ip      = $c.IPv4Address.IPAddress
$prefix  = [int]$c.IPv4Address.PrefixLength
$gw      = if ($c.IPv4DefaultGateway) { $c.IPv4DefaultGateway.NextHop } else { 'N/A' }
$dns     = if ($c.DNSServer.ServerAddresses) { $c.DNSServer.ServerAddresses[0] } else { 'N/A' }
$mac     = $c.NetAdapter.MacAddress
$adapter = $c.InterfaceAlias
[pscustomobject]@{ ip=$ip; prefix=$prefix; gateway=$gw; dns=$dns; mac=$mac; adapter=$adapter } | ConvertTo-Json
"""
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
        channel = extract(r'^\s*(?:Channel|Kanal)\s*:\s*(\d+)')

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

        return {
            "ssid": ssid, "bssid": bssid, "signal": signal,
            "radio": radio, "band": band, "auth": auth, "channel": channel,
        }
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
    times, lost = [], 0
    for i in range(1, count + 1):
        ms = ping_host(target, 2000)
        if ms is not None:
            times.append(ms)
            yield {"i": i, "ms": ms, "status": "ok"}
        else:
            lost += 1
            yield {"i": i, "status": "timeout"}
        if i < count:
            time.sleep(interval_ms / 1000)

    if times:
        yield {"done": True, "avg": round(sum(times) / len(times), 1),
               "min": min(times), "max": max(times),
               "loss": round((lost / count) * 100)}
    else:
        yield {"done": True, "error": "All packets lost"}


# ══════════════════════════════════════════
# PORT SCANNER
# ══════════════════════════════════════════

PORT_NAMES = {
    21: "FTP", 22: "SSH", 23: "Telnet", 25: "SMTP", 53: "DNS",
    80: "HTTP", 110: "POP3", 135: "RPC", 139: "NetBIOS", 143: "IMAP",
    443: "HTTPS", 445: "SMB", 3389: "RDP",
}


def port_scan_quick_stream(ip):
    ports = list(PORT_NAMES.keys())
    for port in ports:
        open_ = scan_port(ip, port, timeout=0.5)
        yield {"port": port, "name": PORT_NAMES.get(port, ""), "open": open_}
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


def _get_mac_for_ip(ip):
    """Best-effort MAC lookup via the ARP table (Windows: arp -a)."""
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


def ping_sweep_stream(timeout_ms=150):
    """Generator: scans the local /24 range. Yields progress + per-host
    results, then a final summary. This is the same scan used to power
    Ping Sweep, Top Devices, and Network Map — those three just format
    the same `host` dicts differently on the frontend."""
    try:
        network, gateway, cfg = _resolve_local_network_prefix()
    except RuntimeError as e:
        yield {"error": str(e)}
        return

    yield {"network": network}

    found = 0
    for i in range(1, 255):
        ip = f"{network}.{i}"
        ms = ping_host(ip, timeout_ms)

        if i % 16 == 0:
            yield {"scanned": i}

        if ms is not None:
            try:
                hostname = socket.gethostbyaddr(ip)[0]
            except Exception:
                hostname = "Unknown"

            mac = _get_mac_for_ip(ip)
            vendor = lookup_vendor(mac) if mac else "Unknown"
            is_gateway = (ip == gateway)

            found += 1
            yield {
                "online": True,
                "ip": ip,
                "hostname": hostname,
                "mac": mac or "Unknown",
                "vendor": vendor,
                "is_gateway": is_gateway,
                "rtt_ms": ms,
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


def monitor_stream(adapter_name="", max_samples=600):
    """Generator: yields one dict per second with current dl/ul Mbps and
    running totals. Drives both the standalone Network Monitor screen and
    the dashboard's live traffic chart — same data, frontend just renders
    it differently (single big chart vs. compact sparkline)."""
    if not PSUTIL_AVAILABLE:
        yield {"error": "psutil is required for Network Monitor. pip install psutil"}
        return

    name = adapter_name
    if not name:
        raw = run_powershell(
            "(Get-NetAdapter | Where-Object {$_.Status -eq 'Up'} | Select-Object -First 1).Name",
            timeout=6
        )
        name = raw

    if not name:
        yield {"error": "No active adapter found"}
        return

    key = find_psutil_interface(name)
    if not key:
        yield {"error": "No network interfaces found via psutil"}
        return

    snap = psutil.net_io_counters(pernic=True).get(key)
    if not snap:
        yield {"error": f"Interface {key} not found"}
        return

    yield {"dl": 0.0, "ul": 0.0, "total_dl": 0.0, "total_ul": 0.0, "adapter": name, "iface": key}

    total_dl = total_ul = 0.0
    prev_recv, prev_sent = snap.bytes_recv, snap.bytes_sent
    prev_time = time.time()

    for _ in range(max_samples):
        time.sleep(1)
        cur = psutil.net_io_counters(pernic=True).get(key)
        if not cur:
            yield {"error": "Adapter disappeared"}
            return

        now = time.time()
        elapsed = max(now - prev_time, 0.001)
        prev_time = now

        dl_bytes = max(0, cur.bytes_recv - prev_recv)
        ul_bytes = max(0, cur.bytes_sent - prev_sent)
        prev_recv, prev_sent = cur.bytes_recv, cur.bytes_sent

        dl_mbps = round(dl_bytes * 8 / elapsed / 1_048_576, 2)
        ul_mbps = round(ul_bytes * 8 / elapsed / 1_048_576, 2)
        total_dl += dl_bytes / 1_048_576
        total_ul += ul_bytes / 1_048_576

        yield {"dl": dl_mbps, "ul": ul_mbps, "total_dl": round(total_dl, 2),
               "total_ul": round(total_ul, 2), "adapter": name, "iface": key}


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
