"""Network configuration, diagnostics and traffic operations."""

import ipaddress
import json
import os
import platform
import queue
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from . import privacy, windows_network
from .system import PSUTIL_AVAILABLE, _no_window, psutil, run_powershell

used_os = sys.platform


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
    try:
        if platform.system() == "Windows":
            cmd = ["ping", "-n", "1", "-w", str(timeout_ms), host]
        else:
            cmd = ["ping", "-c", "1", "-W", str(max(timeout_ms // 1000, 1)), host]
        result = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=timeout_ms / 1000 + 2, **_no_window())
        if result.returncode == 0:
            match = re.search(r'[Tt]ime[=<](\d+)', result.stdout)
            return int(match.group(1)) if match else 1
        return None
    except Exception:
        return None


def _mask_to_prefix(mask):
    try:
        return sum(bin(int(o)).count("1") for o in mask.split("."))
    except Exception:
        return 24


def _windows_ipconfig_config():
    """Return Windows adapter configuration from native APIs."""
    return windows_network.active_network_config()


def list_adapters_linux():
    stats = psutil.net_if_stats()
    adapters = [{"name": name, "description": f"No description for {name} adapter",
                 "status": "Up" if stat.isup else "Down", "link_speed": stat.speed,
                 "mtu": stat.mtu} for name, stat in stats.items()]
    for name, addresses in psutil.net_if_addrs().items():
        for address in addresses:
            if address.family == psutil.AF_LINK:
                for adapter in adapters:
                    if adapter["name"] == name:
                        adapter["mac"] = address.address
    return adapters


def handle_adapter_details_linux(adapter_name):
    if adapter_name == "error":
        return {"error": "Couldn't find an adapter"}
    try:
        def run_nmcli(field, name):
            return subprocess.run(["nmcli", "-g", field, "device", "show", name],
                                  capture_output=True, text=True).stdout.strip()
        adapters = list_adapters_linux()
        addresses = psutil.net_if_addrs()
        for adapter in adapters:
            for address in addresses.get(adapter["name"], []):
                if address.family == socket.AF_INET:
                    adapter["ipv4"], adapter["subnet_mask"] = address.address, address.netmask
                elif address.family == socket.AF_INET6:
                    adapter["ipv6"] = address.address
            name = adapter["name"]
            adapter["gateway"] = run_nmcli("IP4.GATEWAY", name)
            adapter["prefix"] = ipaddress.IPv4Network(
                f"0.0.0.0/{adapter.get('subnet_mask', '0.0.0.0')}"
            ).prefixlen
            adapter["dns"] = run_nmcli("IP4.DNS", name)
            connection = run_nmcli("GENERAL.CONNECTION", name)
            adapter["dhcp"] = subprocess.run(
                ["nmcli", "-g", "ipv4.method", "connection", "show", connection],
                capture_output=True, text=True).stdout.strip()
            adapter["virtual"] = "" if os.path.isdir(f"/sys/class/net/{name}/device") else "Virtual"
        return next((a for a in adapters if a["name"] == adapter_name), None)
    except Exception as exc:
        return {"error": str(exc)}


def list_adapters():
    try:
        if platform.system() == "Windows":
            return windows_network.list_adapters()
        if used_os == "linux":
            return list_adapters_linux()
        raw = run_powershell("Get-NetAdapter | Select-Object Name,Status,InterfaceDescription,MacAddress | ConvertTo-Json -Depth 2", timeout=20)
        if not raw:
            return {"error": "No adapters found (Unsupported OS found)"}
        data = json.loads(raw)
        if isinstance(data, dict):
            data = [data]
        return [{"name": a.get("Name", ""), "status": a.get("Status", ""),
                 "description": a.get("InterfaceDescription", ""), "mac": a.get("MacAddress", "")} for a in data]
    except Exception as exc:
        return {"error": str(exc)}


def get_main_adapter_linux():
    try:
        result = subprocess.run(["ip", "route", "get", "1.1.1.1"], capture_output=True,
                                text=True, check=True)
        parts = result.stdout.split()
        return parts[parts.index("dev") + 1]
    except Exception:
        return "error"


def convert_adapter_details_into_network_config(details):
    return {"ip": details["ipv4"], "prefix": details["prefix"],
            "gateway": details["gateway"], "dns": details["dns"],
            "mac": details["mac"], "adapter": details["name"]}


def get_network_config():
    try:
        if platform.system() == "Windows":
            return windows_network.active_network_config()
        if platform.system() == "Linux":
            return convert_adapter_details_into_network_config(handle_adapter_details_linux(get_main_adapter_linux()))
        if PSUTIL_AVAILABLE:
            for name, addrs in psutil.net_if_addrs().items():
                stats = psutil.net_if_stats().get(name)
                if not stats or not stats.isup:
                    continue
                ip = mac = None
                prefix = None
                for address in addrs:
                    if address.family == socket.AF_INET and not address.address.startswith("127."):
                        ip = address.address
                        try:
                            prefix = ipaddress.IPv4Network(
                                f"0.0.0.0/{address.netmask}").prefixlen
                        except (TypeError, ValueError):
                            prefix = None
                    if address.family == psutil.AF_LINK:
                        mac = address.address
                if ip and prefix is not None:
                    return {"ip": ip, "prefix": prefix, "gateway": "N/A", "dns": "N/A",
                            "mac": mac or "N/A", "adapter": name}
        return {"error": "No active network connection found"}
    except Exception as exc:
        return {"error": str(exc)}


def get_public_ip():
    global _PUBLIC_IP_CACHE, _PUBLIC_IP_CACHE_AT
    if privacy.is_offline_mode():
        return "Unavailable"
    if _PUBLIC_IP_CACHE and time.monotonic() - _PUBLIC_IP_CACHE_AT < 60:
        return _PUBLIC_IP_CACHE
    try:
        request = urllib.request.Request("https://ipapi.co/ip/", headers={"User-Agent": "NETWER"})
        with urllib.request.urlopen(request, timeout=3) as response:
            value = response.read().decode("utf-8", errors="replace").strip()
        ipaddress.ip_address(value)
        _PUBLIC_IP_CACHE, _PUBLIC_IP_CACHE_AT = value, time.monotonic()
        return value
    except Exception:
        return "Unavailable"


def get_ethernet_info():
    cfg = get_network_config()
    if "error" in cfg:
        return cfg
    ip = cfg["ip"]
    return {"adapter": cfg["adapter"], "ip": ip, "public_ip": get_public_ip(),
            "ip_class": get_ip_class(ip), "mac": cfg["mac"],
            "subnet_mask": prefix_to_mask(cfg["prefix"]), "gateway": cfg["gateway"],
            "dns": cfg["dns"], "ip_type": "PRIVATE" if is_private(ip) else "PUBLIC"}


def ping_quick():
    results = []
    for target in ({"label": "Google DNS", "ip": "8.8.8.8"},
                   {"label": "Cloudflare", "ip": "1.1.1.1"},
                   {"label": "Quad9", "ip": "9.9.9.9"}):
        times, lost = [], 0
        for _ in range(4):
            ms = ping_host(target["ip"], 1000)
            if ms is not None:
                times.append(ms)
            else:
                lost += 1
        results.append({"label": target["label"], "ip": target["ip"],
                        **({"avg": round(sum(times) / len(times)), "min": min(times),
                            "max": max(times), "loss": round(lost / 4 * 100)} if times else {"unreachable": True})})
    return results


def ping_stability_stream(target="8.8.8.8", count=20):
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
        jitter = sum(abs(times[j] - times[j - 1]) for j in range(1, len(times))) / max(len(times) - 1, 1)
        yield {"done": True, "avg": round(sum(times) / len(times), 1), "min": min(times),
               "max": max(times), "loss": round(lost / count * 100), "jitter": round(jitter, 1)}
    else:
        yield {"done": True, "error": "All packets lost"}


def ping_custom_stream(target="8.8.8.8", count=4, interval_ms=500):
    try:
        socket.getaddrinfo(target, None)
    except socket.gaierror:
        yield {"error": f"Could not resolve host: {target}"}
        return

    times, lost, sent, i = [], 0, 0, 0
    continuous = count == 0
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
        deltas = [abs(times[j] - times[j - 1]) for j in range(1, len(times))]
        yield {"i": i, "ms": ms, "status": status,
               "avg": round(sum(times) / len(times), 1) if times else None,
               "min": min(times) if times else None, "max": max(times) if times else None,
               "jitter": round(sum(deltas) / len(deltas), 1) if deltas else 0.0,
               "loss": round(lost / sent * 100, 1), "sent": sent}
        if continuous or i < count:
            time.sleep(interval_ms / 1000)
    if times:
        deltas = [abs(times[j] - times[j - 1]) for j in range(1, len(times))]
        yield {"done": True, "avg": round(sum(times) / len(times), 1), "min": min(times),
               "max": max(times), "jitter": round(sum(deltas) / len(deltas), 1) if deltas else 0.0,
               "loss": round(lost / sent * 100, 1), "sent": sent}
    else:
        yield {"done": True, "error": "All packets lost", "sent": sent}


_HOP_RE = re.compile(r'^\s*(\d{1,2})\s+(.*)$')
_IP_RE = re.compile(r'(\d{1,3}(?:\.\d{1,3}){3})')
_MS_RE = re.compile(r'(\d+(?:[.,]\d+)?)\s*ms', re.I)
_FROM_RE = re.compile(r'(?:reply from|from)\s+(\d{1,3}(?:\.\d{1,3}){3})', re.I)
_TIME_RE = re.compile(r'time[=<]\s*(\d+(?:[.,]\d+)?)', re.I)
_GEO_CACHE = {}
_GEO_LAST_ERROR = None
_OFFLINE_GEO = None
_PUBLIC_IP_CACHE = None
_PUBLIC_IP_CACHE_AT = 0


def _parse_hop_line(line):
    match = _HOP_RE.match(line.rstrip())
    if not match:
        return None
    ttl, rest = int(match.group(1)), match.group(2)
    ip_match = _IP_RE.search(rest)
    if not ip_match:
        return {"ttl": ttl, "timeout": True}
    times = [float(x.replace(",", ".")) for x in _MS_RE.findall(rest)]
    ip = ip_match.group(1)
    host_match = re.search(r'([A-Za-z0-9][A-Za-z0-9.\-]*[A-Za-z0-9])\s*[\[(]\s*' + re.escape(ip), rest)
    hostname = host_match.group(1) if host_match and host_match.group(1) != ip else ip
    return {"ttl": ttl, "ip": ip, "hostname": hostname, "times": times,
            "avg": round(sum(times) / len(times)) if times else None}


def _system_trace(resolved, max_hops):
    cmd = (["tracert", "-h", str(max_hops), "-w", "1000", resolved]
           if platform.system() == "Windows" else
           ["traceroute", "-m", str(max_hops), "-w", "2", "-q", "1", resolved])
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                text=True, errors="replace", **_no_window())
    except Exception:
        return
    seen = 0
    try:
        for line in proc.stdout:
            if "trace complete" in line.lower() or "trace aborted" in line.lower():
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
        for method in ("terminate", "kill"):
            try:
                getattr(proc, method)()
                break
            except Exception:
                pass


def _ping_trace(resolved, max_hops):
    windows = platform.system() == "Windows"
    for ttl in range(1, max_hops + 1):
        cmd = (["ping", "-n", "1", "-i", str(ttl), "-w", "1500", resolved]
               if windows else ["ping", "-c", "1", "-t", str(ttl), "-W", "2", resolved])
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                                    timeout=8, **_no_window())
            output = (result.stdout or "") + (result.stderr or "")
        except Exception:
            yield {"ttl": ttl, "timeout": True}
            continue
        match = _FROM_RE.search(output)
        if not match:
            yield {"ttl": ttl, "timeout": True}
            continue
        ip = match.group(1)
        timing = _TIME_RE.search(output)
        avg = round(float(timing.group(1).replace(",", "."))) if timing else None
        yield {"ttl": ttl, "ip": ip, "hostname": ip,
               "times": [avg] if avg is not None else [], "avg": avg}
        if ip == resolved:
            break


def traceroute_stream(target, max_hops=30, auto=False):
    try:
        resolved = socket.gethostbyname(target)
    except Exception:
        yield {"error": f"Could not resolve: {target}"}
        return
    yield {"resolved": resolved, "target": target}
    produced = reached = consecutive_timeouts = 0
    timeout_limit = 5
    def walk(source):
        nonlocal produced, reached, consecutive_timeouts
        for hop in source:
            produced += 1
            consecutive_timeouts = consecutive_timeouts + 1 if hop.get("timeout") else 0
            yield hop
            if hop.get("ip") == resolved:
                reached = True
                return
            if auto and consecutive_timeouts >= timeout_limit:
                return
    yield from walk(_system_trace(resolved, max_hops))
    if produced == 0:
        yield from walk(_ping_trace(resolved, max_hops))
    yield {"done": True, "reached": reached}


def _load_offline_geo():
    global _OFFLINE_GEO
    if _OFFLINE_GEO is None:
        try:
            path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "assets", "geoip_offline.json")
            with open(path, "r", encoding="utf-8") as source:
                _OFFLINE_GEO = json.load(source)
        except Exception:
            _OFFLINE_GEO = {"known": {}, "octet": {}, "names": {}}
    return _OFFLINE_GEO


def _offline_geolocate(ip):
    data = _load_offline_geo()
    if ip in data.get("known", {}):
        lat, lon, country, city = data["known"][ip]
        return {"lat": lat, "lon": lon, "city": city, "country": country}
    try:
        first = int(ip.split(".")[0])
    except Exception:
        return None
    rule = data.get("octet", {}).get(str(first))
    if rule:
        lat, lon, country = rule
    elif first < 64:
        lat, lon, country = 39, -98, "United States"
    elif first < 128:
        lat, lon, country = 48, 10, "Europe"
    elif first < 192:
        lat, lon, country = 35, 105, "Asia"
    else:
        lat, lon, country = 39, -98, "United States"
    return {"lat": lat, "lon": lon, "city": country, "country": country, "approx": True}


def geo_last_error():
    return _GEO_LAST_ERROR


def _is_private_ip(ip):
    try:
        return ipaddress.ip_address(ip).is_private
    except Exception:
        return False


def geolocate_ip(ip, timeout=4):
    if not ip or _is_private_ip(ip):
        return None
    if ip in _GEO_CACHE:
        return _GEO_CACHE[ip]
    if not privacy.is_offline_mode():
        try:
            request = urllib.request.Request(f"https://ipapi.co/{ip}/json/", headers={"User-Agent": "NETWER"})
            with urllib.request.urlopen(request, timeout=min(max(float(timeout), 0.1), 6)) as response:
                data = json.loads(response.read().decode("utf-8", errors="replace"))
            if data.get("latitude") is not None and not data.get("error"):
                result = {"lat": data.get("latitude"), "lon": data.get("longitude"),
                          "city": data.get("city") or data.get("region") or "",
                          "country": data.get("country_name") or ""}
                _GEO_CACHE[ip] = result
                return result
        except Exception:
            pass
    result = _offline_geolocate(ip)
    if result:
        _GEO_CACHE[ip] = result
    return result


def traceroute_geo_stream(target, max_hops=30, home_lat=None, home_lon=None):
    for event in traceroute_stream(target, max_hops=max_hops):
        if "ip" in event and not event.get("timeout") and _is_private_ip(event["ip"]):
            event["local"] = True
            if home_lat is not None and home_lon is not None:
                event["lat"], event["lon"], event["city"] = home_lat, home_lon, "Local network"
        yield event


def geolocate_hops(ips, timeout=6, max_workers=8):
    output, todo = {}, []
    for ip in dict.fromkeys(ips):
        if not ip or _is_private_ip(ip):
            continue
        if ip in _GEO_CACHE:
            output[ip] = _GEO_CACHE[ip]
        else:
            todo.append(ip)
    if not todo:
        return output
    with ThreadPoolExecutor(max_workers=min(max(int(max_workers), 1), 8, len(todo))) as pool:
        for ip, geo in zip(todo, pool.map(lambda value: geolocate_ip(value, timeout=min(timeout, 6)), todo)):
            output[ip] = geo
    return output


def geolocate_me(timeout=3):
    if privacy.is_offline_mode():
        return _offline_geolocate(_PUBLIC_IP_CACHE) if _PUBLIC_IP_CACHE else None
    try:
        request = urllib.request.Request("https://ipapi.co/json/", headers={"User-Agent": "NETWER"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8", errors="replace"))
        if data.get("latitude") is not None and not data.get("error"):
            return {"lat": data.get("latitude"), "lon": data.get("longitude"),
                    "city": data.get("city") or data.get("region") or "",
                    "country": data.get("country_name") or ""}
    except Exception:
        pass
    return _offline_geolocate(_PUBLIC_IP_CACHE) if _PUBLIC_IP_CACHE else None


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
    except Exception as exc:
        return {"error": str(exc)}


def reverse_dns(ip):
    try:
        hostname, aliases, _ = socket.gethostbyaddr(ip)
        return {"ip": ip, "hostname": hostname, "aliases": list(aliases)}
    except Exception as exc:
        return {"error": str(exc)}


def _prefix_to_mask(prefix):
    try:
        prefix = int(prefix)
        mask = (0xffffffff >> (32 - prefix)) << (32 - prefix) if prefix else 0
        return ".".join(str((mask >> (8 * i)) & 0xff) for i in (3, 2, 1, 0))
    except (ValueError, TypeError):
        return ""


def get_adapter_details(adapter_name):
    if not adapter_name:
        return {"error": "No adapter name given"}
    try:
        if platform.system() == "Windows":
            data = windows_network.adapter_details(adapter_name)
            if "error" in data:
                return data
            prefix = data.get("prefix", 0)
            return {"name": data.get("name", adapter_name), "description": data.get("description", ""),
                    "status": data.get("status", ""), "mac": data.get("mac", ""), "link_speed": "",
                    "ipv4": data.get("ipv4", ""), "ipv6": data.get("ipv6", ""),
                    "subnet_mask": _prefix_to_mask(prefix) if prefix else "", "prefix": prefix,
                    "gateway": data.get("gateway", ""), "dns": data.get("dns", ""),
                    "dhcp": data.get("dhcp", "Unknown"), "mtu": data.get("mtu", ""),
                    "virtual": data.get("virtual", False)}
        safe = adapter_name.replace("'", "''")
        command = r"""
$name = '""" + safe + r"""'
$ad=Get-NetAdapter -Name $name -ErrorAction SilentlyContinue
if(-not $ad){Write-Output '{}';exit}
$cfg=Get-NetIPConfiguration -InterfaceAlias $name -ErrorAction SilentlyContinue
$ipv4=Get-NetIPAddress -InterfaceAlias $name -AddressFamily IPv4 -ErrorAction SilentlyContinue | Select-Object -First 1
$ipv6=Get-NetIPAddress -InterfaceAlias $name -AddressFamily IPv6 -ErrorAction SilentlyContinue | Select-Object -First 1
$dnsList=@();if($cfg -and $cfg.DNSServer){foreach($d in $cfg.DNSServer){if($d.ServerAddresses){$dnsList += $d.ServerAddresses}}}
$dnsList=$dnsList | Where-Object {$_ -match '^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$'}
$gw=if($cfg -and $cfg.IPv4DefaultGateway){$cfg.IPv4DefaultGateway.NextHop}else{''}
$prefix=if($ipv4){[int]$ipv4.PrefixLength}else{0};$dhcp=if($ipv4){$ipv4.PrefixOrigin}else{''}
[pscustomobject]@{name=$ad.Name;description=$ad.InterfaceDescription;status=$ad.Status;mac=$ad.MacAddress;link_speed=$ad.LinkSpeed;ipv4=if($ipv4){$ipv4.IPAddress}else{''};ipv6=if($ipv6){$ipv6.IPAddress}else{''};prefix=$prefix;gateway=$gw;dns=($dnsList -join ', ');dhcp=$dhcp;mtu=$ad.MtuSize;virtual=$ad.Virtual} | ConvertTo-Json
"""
        raw = run_powershell(command, timeout=10)
        if used_os == "linux":
            return handle_adapter_details_linux(adapter_name)
        if not raw or raw.strip() == "{}":
            return {"error": f"Adapter '{adapter_name}' not found"}
        data = json.loads(raw)
        prefix = data.get("prefix", 0)
        result = {"name": data.get("name", adapter_name), "description": data.get("description", ""),
                  "status": data.get("status", ""), "mac": data.get("mac", ""),
                  "link_speed": data.get("link_speed", ""), "ipv4": data.get("ipv4", ""),
                  "ipv6": data.get("ipv6", ""), "subnet_mask": _prefix_to_mask(prefix) if prefix else "",
                  "prefix": prefix, "gateway": data.get("gateway", ""), "dns": data.get("dns", ""),
                  "dhcp": "Enabled" if str(data.get("dhcp", "")).lower() == "dhcp" else "Static/Manual",
                  "mtu": data.get("mtu", ""), "virtual": data.get("virtual", False)}
        return result
    except Exception:
        return {"error": "Could not read adapter details"}


def _windows_adapter_details_native(adapter_name):
    """Return Windows adapter details from native APIs."""
    return windows_network.adapter_details(adapter_name)


def find_psutil_interface(ps_name):
    if not PSUTIL_AVAILABLE:
        return None
    io = psutil.net_io_counters(pernic=True)
    if not io:
        return None
    if ps_name in io:
        return ps_name
    lower = ps_name.lower()
    for name in io:
        if name.lower() == lower:
            return name
    for name in io:
        if lower in name.lower() or name.lower() in lower:
            return name
    skip = ("loopback", "isatap", "teredo", "virtual", "vethernet", "bluetooth", "npcap")
    candidates = {k: v for k, v in io.items() if not any(s in k.lower() for s in skip)}
    pool = candidates or io
    return max(pool, key=lambda k: pool[k].bytes_recv + pool[k].bytes_sent)


def _is_virtual_iface(name):
    words = ("vmware", "virtualbox", "vethernet", "hyper-v", "loopback", "vmnet", "vpn", "tap", "tun", "pseudo", "bluetooth", "isatap", "teredo", "wan miniport")
    return any(word in name.lower() for word in words)


def _pick_traffic_ifaces(adapter_name=""):
    if not PSUTIL_AVAILABLE:
        return []
    io, stats = psutil.net_io_counters(pernic=True), psutil.net_if_stats()
    if adapter_name:
        key = find_psutil_interface(adapter_name)
        return [key] if key else []
    picked = [name for name in io if stats.get(name) and stats[name].isup and not _is_virtual_iface(name)]
    return picked or [name for name in io if stats.get(name) and stats[name].isup]


def _sum_counters(iface_names):
    io = psutil.net_io_counters(pernic=True)
    recv = sent = 0
    for name in iface_names:
        counter = io.get(name)
        if counter:
            recv += counter.bytes_recv
            sent += counter.bytes_sent
    return recv, sent


def monitor_stream(adapter_name="", max_samples=600):
    if not PSUTIL_AVAILABLE:
        yield {"error": "psutil is required for Network Monitor. pip install psutil"}
        return
    ifaces = _pick_traffic_ifaces(adapter_name)
    if not ifaces:
        yield {"error": "No active network interface found"}
        return
    label = adapter_name or (ifaces[0] if len(ifaces) == 1 else f"All physical adapters ({len(ifaces)})")
    prev_recv, prev_sent = _sum_counters(ifaces)
    prev_time, total_dl, total_ul = time.time(), 0.0, 0.0
    yield {"dl": 0.0, "ul": 0.0, "total_dl": 0.0, "total_ul": 0.0,
           "adapter": label, "iface": ",".join(ifaces)}
    for _ in range(max_samples):
        time.sleep(1)
        cur_recv, cur_sent = _sum_counters(ifaces)
        now = time.time()
        elapsed = max(now - prev_time, 0.001)
        prev_time = now
        dl, ul = max(0, cur_recv - prev_recv), max(0, cur_sent - prev_sent)
        prev_recv, prev_sent = cur_recv, cur_sent
        dl_mbps, ul_mbps = round(dl * 8 / elapsed / 1_048_576, 2), round(ul * 8 / elapsed / 1_048_576, 2)
        total_dl += dl / 1_048_576
        total_ul += ul / 1_048_576
        yield {"dl": dl_mbps, "ul": ul_mbps, "total_dl": round(total_dl, 2),
               "total_ul": round(total_ul, 2), "adapter": label, "iface": ",".join(ifaces)}


def get_bandwidth_today():
    if not PSUTIL_AVAILABLE:
        return {"error": "psutil is required. pip install psutil"}
    try:
        io = psutil.net_io_counters()
        return {"download_gb": round(io.bytes_recv / (1024 ** 3), 2),
                "upload_gb": round(io.bytes_sent / (1024 ** 3), 2)}
    except Exception as exc:
        return {"error": str(exc)}


def find_speedtest_exe():
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    paths = [os.path.join(project_root, "ookla-speedtest-1.2.0-win64", "speedtest.exe"),
             os.path.expandvars(r"%USERPROFILE%\Desktop\speedtest.exe"),
             os.path.expandvars(r"%USERPROFILE%\Downloads\speedtest.exe"), r"C:\speedtest\speedtest.exe"]
    for path in paths:
        if os.path.isfile(path):
            return path
    try:
        result = subprocess.run(["where", "speedtest.exe"], capture_output=True, text=True,
                                **_no_window())
        if result.returncode == 0:
            return result.stdout.strip().splitlines()[0]
    except Exception:
        pass
    return None


def speedtest_stream(cancel_event=None):
    exe = find_speedtest_exe()
    if not exe:
        yield {"error": "speedtest.exe not found"}
        return
    proc = None
    reader = None

    def stop_process():
        if proc is None or proc.poll() is not None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

    try:
        proc = subprocess.Popen([exe, "--format=jsonl", "--accept-license", "--accept-gdpr"],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                **_no_window())
        lines = queue.Queue()

        def read_output():
            try:
                for output_line in proc.stdout:
                    lines.put(output_line)
            finally:
                lines.put(None)

        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()
        while True:
            if cancel_event is not None and cancel_event.is_set():
                stop_process()
                return
            try:
                line = lines.get(timeout=0.1)
            except queue.Empty:
                continue
            if line is None:
                break
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = event.get("type", "")
            if kind == "testStart":
                yield {"type": "start", "isp": event.get("isp", ""), "server": event.get("server", {}).get("name", "")}
            elif kind == "ping":
                yield {"type": "ping", "ms": round(event["ping"]["latency"], 1)}
            elif kind in ("download", "upload"):
                yield {"type": kind, "mbps": round(event[kind]["bandwidth"] * 8 / 1_048_576, 2)}
            elif kind == "result":
                yield {"type": "result", "ping": round(event["ping"]["latency"], 1),
                        "dl": round(event["download"]["bandwidth"] * 8 / 1_048_576, 2),
                        "ul": round(event["upload"]["bandwidth"] * 8 / 1_048_576, 2)}
    except Exception as exc:
        yield {"error": str(exc)}
    finally:
        stop_process()
        if reader is not None:
            reader.join(timeout=0.5)


def save_report(path="", name="netwer_report"):
    path = path.strip() or os.path.join(os.path.expanduser("~"), "Desktop")
    path = os.path.expandvars(os.path.expanduser(path))
    name = name.strip() or "netwer_report"
    if not os.path.isdir(path):
        return {"error": f"Path does not exist: {path}"}
    bad = [char for char in name if char in set(r'/:*?"<>|')]
    if bad:
        return {"error": f"Invalid characters in filename: {bad}"}
    eth = get_ethernet_info()
    if "error" in eth:
        return {"error": f"Could not read network config: {eth['error']}"}
    lines = ["==============================", "     NETWER NETWORK REPORT    ", "==============================", "",
             f"  Computer : {socket.gethostname()}", f"  Date     : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
             "", "  ----- NETWORK INFO -----", f"  Adapter      : {eth['adapter']}",
             f"  IPv4 Address : {eth['ip']}", f"  Public IP    : {eth['public_ip']}",
             f"  MAC Address  : {eth['mac']}", f"  Subnet Mask  : {eth['subnet_mask']}",
             f"  Gateway      : {eth['gateway']}", f"  DNS Server   : {eth['dns']}", "",
             "  ----- IP ANALYSIS -----", f"  Class : {eth['ip_class']}", f"  Type  : {eth['ip_type']}", "",
             "=============================="]
    filepath = os.path.join(path, f"{name}.txt")
    try:
        with open(filepath, "w", encoding="utf-8") as report:
            report.write("\n".join(lines))
        return {"success": True, "path": filepath}
    except PermissionError:
        return {"error": f"Permission denied: {filepath}"}
    except Exception as exc:
        return {"error": str(exc)}
