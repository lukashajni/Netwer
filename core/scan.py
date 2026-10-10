"""Port scanning and LAN device discovery."""
import concurrent.futures
import ipaddress
import platform
import re
import socket

from . import network, oui_extended, vendor_learning, windows_network

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
PORT_PROFILES = {
    "common": [21, 22, 23, 25, 53, 80, 110, 135, 139, 143, 443, 445, 993,
               995, 3306, 3389, 5900, 8080, 8443],
    "top100": sorted(PORT_SERVICES),
    "web": [80, 443, 8000, 8008, 8080, 8443, 8888, 9000, 9090, 3000, 5000],
    "database": [1433, 1521, 3306, 5432, 6379, 9200, 11211, 27017],
    "remote": [22, 23, 3389, 5900, 5985, 5986],
}
PORT_NAMES = {port: value[0] for port, value in PORT_SERVICES.items()}
OUI_TABLE = {
    "001A11": "Google", "3C5AB4": "Google", "F4F5D8": "Google",
    "A45C2C": "ASUSTek", "AC9E17": "ASUSTek", "D8501A": "ASUSTek",
    "B827EB": "Raspberry Pi", "DCA632": "Raspberry Pi",
    "E45F01": "Raspberry Pi", "001E58": "Synology", "0011D8": "Synology",
    "001132": "Synology", "B0A4E8": "MikroTik", "4C5E0C": "MikroTik",
    "6C3B6B": "MikroTik", "DC2C6E": "MikroTik", "00163C": "TP-Link",
    "1C61B4": "TP-Link", "50C7BF": "TP-Link", "F4F26D": "TP-Link",
    "6C4CBC": "TP-Link", "6C4CBB": "TP-Link", "AC84C6": "TP-Link",
    "5091E3": "TP-Link", "9C5322": "TP-Link", "EC086B": "TP-Link",
    "60A4B7": "TP-Link", "C46E1F": "TP-Link", "A42BB0": "TP-Link",
    "003192": "TP-Link", "B0BE76": "TP-Link", "10FEED": "TP-Link",
    "54AF97": "TP-Link", "98DAC4": "TP-Link", "E848B8": "TP-Link",
    "001D7E": "Cisco", "0050F2": "Microsoft", "7C1E52": "Microsoft",
    "A85C2C": "Apple", "F0DBE2": "Apple", "BC9264": "Apple",
    "001CB3": "Apple", "3C0754": "Apple", "88665A": "Apple",
    "00E04C": "Realtek", "525400": "QEMU/Virtual", "000C29": "VMware",
    "001C14": "VMware", "005056": "VMware", "080027": "VirtualBox",
    "F8F005": "Netgear", "A0040F": "Netgear", "B0B984": "Netgear",
    "8C8590": "Espressif (IoT)", "240AC4": "Espressif (IoT)",
    "00408C": "HP Inc.", "3C4A92": "HP Inc.", "D4C9EF": "HP Inc.",
    "001143": "Canon",
}
OUI_TABLE.update(oui_extended.EXTENDED_OUI)
OUI_TABLE.update(oui_extended.BULK_OUI)
_ONLINE_VENDOR_CACHE = {}


def scan_port(ip, port, timeout=0.5):
    try:
        with socket.create_connection((ip, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def port_service(port):
    return PORT_SERVICES.get(int(port), ("Unknown", "TCP"))


def _clean_banner(text):
    return " ".join("".join(c for c in (text or "") if 32 <= ord(c) <= 126).split())


def _grab_banner(sock, port, timeout):
    try:
        sock.settimeout(min(timeout, 1.5))
        if port in (80, 443, 8000, 8008, 8080, 8443, 8888, 9090):
            sock.sendall(b"HEAD / HTTP/1.0\r\n\r\n")
        data = sock.recv(256).decode("utf-8", errors="replace")
        for line in data.splitlines():
            if line.strip():
                return _clean_banner(line)[:60]
    except OSError:
        pass
    return ""


def _classify_port(ip, port, timeout, grab_banner=True):
    service, protocol = port_service(port)
    state, banner = "filtered", ""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((ip, int(port)))
        if result == 0:
            state = "open"
            if grab_banner:
                banner = _grab_banner(sock, int(port), timeout)
        elif result in (111, 10061):
            state = "closed"
        sock.close()
    except OSError:
        pass
    return {"port": int(port), "service": service, "protocol": protocol,
            "state": state, "banner": banner}


def _parse_port_spec(spec):
    spec = (spec or "").strip().lower()
    if not spec:
        return PORT_PROFILES["common"]
    if spec in PORT_PROFILES:
        return PORT_PROFILES[spec]
    ports = set()
    try:
        for part in spec.replace(" ", "").split(","):
            if "-" in part:
                start, end = map(int, part.split("-", 1))
                ports.update(range(max(1, min(start, end)), min(65535, max(start, end)) + 1))
            elif part and 1 <= int(part) <= 65535:
                ports.add(int(part))
    except ValueError:
        return []
    return sorted(ports)


def port_scan_stream(ip, ports=None, timeout_ms=600, max_workers=100):
    try:
        resolved = socket.gethostbyname(ip)
    except OSError:
        yield {"error": f"Could not resolve host: {ip}"}
        return
    port_list = _parse_port_spec(ports) if isinstance(ports, str) or ports is None else sorted(set(ports))
    if not port_list:
        yield {"error": "No valid ports to scan."}
        return
    yield {"target": ip, "resolved": resolved, "total": len(port_list)}
    counts = {"open": 0, "closed": 0, "filtered": 0}
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(max_workers, len(port_list))) as pool:
        futures = [pool.submit(_classify_port, resolved, p, max(.1, timeout_ms / 1000)) for p in port_list]
        for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
            result = future.result()
            counts[result["state"]] += 1
            result["scanned"] = index
            yield result
    yield {"done": True, **counts, "total": len(port_list)}


def port_scan_quick_stream(ip):
    for result in port_scan_stream(ip, "common"):
        if "port" in result:
            yield {"port": result["port"], "name": result["service"], "open": result["state"] == "open"}
        elif result.get("done"):
            yield {"done": True}


def port_scan_custom(ip, port):
    return {"port": port, "open": scan_port(ip, port, timeout=1)}


def lookup_vendor(mac_address, allow_online=False):
    try:
        cleaned = re.sub(r"[^0-9A-Fa-f]", "", mac_address or "").upper()
        if len(cleaned) < 6:
            return "Unknown"
        prefix = cleaned[:6]
        taught = vendor_learning.lookup(prefix)
        if taught:
            return taught
        if int(cleaned[1], 16) & 2:
            return "Private (randomized)"
        if prefix in OUI_TABLE:
            return OUI_TABLE[prefix]
        if prefix in _ONLINE_VENDOR_CACHE:
            return _ONLINE_VENDOR_CACHE[prefix]
        if allow_online:
            name = oui_extended.online_vendor_lookup(mac_address, allow_network=allow_online)
            _ONLINE_VENDOR_CACHE[prefix] = name or "Unknown"
            if name:
                vendor_learning.remember(prefix, name)
                return name
        return "Unknown"
    except Exception as e:
        return "Unknown"


def teach_vendor(mac_address, vendor):
    return vendor_learning.teach(mac_address, vendor)


def wake_on_lan(mac, broadcast="255.255.255.255", port=9):
    clean = re.sub(r"[^0-9A-Fa-f]", "", mac or "")
    if len(clean) != 12:
        return {"error": f"Invalid MAC address: {mac}"}
    try:
        packet = b"\xff" * 6 + bytes.fromhex(clean) * 16
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.sendto(packet, (broadcast, int(port)))
        return {"ok": True, "mac": ":".join(clean[i:i + 2].upper() for i in range(0, 12, 2))}
    except OSError as exc:
        return {"error": str(exc)}


_VENDOR_TYPE_HINTS = {
    "router": ["mikrotik", "tp-link", "netgear", "asus", "d-link", "ubiquiti", "cisco", "zyxel", "huawei", "linksys", "fritz"],
    "printer": ["hp", "canon", "epson", "brother", "lexmark", "xerox"],
    "nas": ["synology", "qnap", "western digital", "wd ", "drobo"],
    "tv": ["samsung", "lg electronics", "sony", "vizio", "roku", "hisense", "tcl"],
    "phone": ["apple", "xiaomi", "oneplus", "oppo", "vivo", "realme", "google", "motorola", "nokia"],
    "camera": ["hikvision", "dahua", "axis", "reolink", "wyze", "amcrest"],
    "console": ["nintendo", "sony interactive", "microsoft"],
}
_PORT_TYPE_HINTS = {9100: "printer", 631: "printer", 515: "printer", 32400: "media", 554: "camera", 8554: "camera", 5000: "nas", 5001: "nas", 445: "computer", 139: "computer", 3389: "computer", 62078: "phone", 8009: "tv"}


def detect_device_type(open_ports=None, vendor="", is_gateway=False, hostname=""):
    if is_gateway:
        return "router"
    ports = set(map(int, open_ports or []))
    for port, kind in _PORT_TYPE_HINTS.items():
        if port in ports:
            return kind
    vendor = (vendor or "").lower()
    for kind, hints in _VENDOR_TYPE_HINTS.items():
        if any(hint in vendor for hint in hints):
            return kind
    hostname = (hostname or "").lower()
    for hint, kind in (("printer", "printer"), ("cam", "camera"), ("nas", "nas"), ("tv", "tv"), ("phone", "phone"), ("desktop", "computer"), ("pc", "computer"), ("laptop", "computer"), ("router", "router")):
        if hint in hostname:
            return kind
    return "computer" if ports & {80, 443, 8080} else "generic"


def _resolve_local_network_prefix():
    cfg = network.get_network_config()
    if "error" in cfg:
        raise RuntimeError(cfg["error"])
    try:
        if cfg.get("prefix") is None:
            raise ValueError("missing interface prefix")
        subnet = ipaddress.ip_network(
            f"{cfg['ip']}/{int(cfg['prefix'])}", strict=False)
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("Could not determine the local IPv4 subnet") from exc
    gateway = cfg.get("gateway") or str(next(subnet.hosts()))
    return subnet, gateway, cfg


def _get_own_ip_and_mac():
    info = network.get_network_config()
    if isinstance(info, dict) and "error" not in info:
        return info.get("ip"), (info.get("mac") or "").replace("-", ":").upper()
    return None, None


def _read_arp_table():
    table = {}
    if platform.system() == "Windows":
        rows = windows_network.neighbor_table()
        if isinstance(rows, list):
            for row in rows:
                ip, mac = row.get("ip"), row.get("mac", "")
                if ip and mac and mac != "FF:FF:FF:FF:FF:FF" and not ip.endswith(".255"):
                    table[ip] = mac.replace("-", ":").upper()
        return table
    try:
        with open("/proc/net/arp", encoding="ascii") as arp_file:
            for line in arp_file:
                fields = line.split()
                if len(fields) < 4 or fields[0] == "IP":
                    continue
                ip, mac = fields[0], fields[3].replace("-", ":").upper()
                if mac != "FF:FF:FF:FF:FF:FF" and not ip.endswith(".255"):
                    table[ip] = mac
    except OSError:
        pass
    return table


def _get_mac_for_ip(ip, own_ip=None, own_mac=None):
    return own_mac if own_ip == ip and own_mac else _read_arp_table().get(ip)


def _parse_subnet_prefix(subnet):
    try:
        return ".".join(str(ipaddress.ip_network(subnet, strict=False).network_address).split(".")[:3])
    except (ValueError, TypeError):
        parts = (subnet or "").split("/")[0].strip(".").split(".")
        if len(parts) < 3:
            return None
        try:
            values = [int(part) for part in parts[:3]]
            return ".".join(map(str, values)) if all(0 <= n <= 255 for n in values) else None
        except ValueError:
            return None


def _parse_subnet_network(subnet):
    value = (subnet or "").strip()
    if "/" not in value:
        return None
    try:
        parsed = ipaddress.ip_network(value, strict=False)
        return parsed if parsed.version == 4 else None
    except (TypeError, ValueError):
        return None


def _fingerprint_unknown_devices(hosts, max_workers=16):
    from . import device_fingerprint
    def identify(host):
        return host, device_fingerprint.identify(host.get("ip", ""), host.get("hostname", ""), host.get("vendor", ""))
    targets = [h for h in hosts if not h.get("is_self") and not h.get("is_gateway") and h.get("vendor") in (None, "", "Unknown", "Private (randomized)") and h.get("hostname", "Unknown") == "Unknown"]
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(max_workers, len(targets) or 1)) as pool:
        for host, found in pool.map(identify, targets):
            host.update({key: found[key] for key in ("hostname", "vendor", "kind") if found.get(key)})


def ping_sweep_stream(timeout_ms=150, subnet=None, cancel_event=None):
    """Compatibility wrapper around the shared subnet-aware discovery service."""
    from .discovery import configured_subnets, get_discovery_service, manual_subnet

    service = get_discovery_service()
    if not subnet:
        yield from service.scan_stream(timeout_ms=timeout_ms,
                                       cancel_event=cancel_event)
        return
    network_range = _parse_subnet_network(subnet)
    if network_range is None:
        yield {"error": f"Invalid subnet: {subnet}"}
        return
    segment = next((entry for entry in configured_subnets()
                    if entry["cidr"] == str(network_range)), None)
    if segment is None:
        try:
            segment = manual_subnet(str(network_range))
        except ValueError as exc:
            yield {"error": str(exc)}
            return
    yield from service.scan_stream([segment], timeout_ms=timeout_ms,
                                   cancel_event=cancel_event)


def _needs_fingerprint(host):
    return not host.get("is_self") and not host.get("is_gateway") and host.get("vendor") in (None, "", "Unknown", "Private (randomized)") and host.get("hostname", "Unknown") == "Unknown"


def get_top_devices(limit=10):
    from .discovery import get_discovery_service

    service = get_discovery_service()
    snapshot = service.snapshot()
    if snapshot["status"] == "idle":
        for event in service.scan_stream():
            if event.get("error"):
                return {"error": event["error"]}
        snapshot = service.snapshot()
    devices = snapshot["devices"]
    devices.sort(key=lambda d: (not d["is_gateway"], [int(x) for x in d["ip"].split(".")]))
    return {"devices": devices[:limit], "total_found": len(devices)}


def get_network_map():
    from .discovery import configured_subnets

    segments = configured_subnets()
    result = get_top_devices(512)
    if "error" in result:
        return result
    devices = result["devices"]
    gateway = next((s.get("gateway") for s in segments if s.get("gateway")), "")
    router = next((d for d in devices if d["is_gateway"]),
                  {"ip": gateway, "hostname": "Router", "vendor": "Unknown"})
    ranges = [s["cidr"] for s in segments if s.get("enabled", True)]
    return {
        "router": router,
        "devices": [d for d in devices if not d["is_gateway"]],
        "network_range": ", ".join(ranges),
        "segments": segments,
    }
