from __future__ import annotations

import re
import selectors
import socket
import struct
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

# TCP ports that identify Apple gear.
_IOS_LOCKDOWN = 62078      # iPhone / iPad (lockdownd)
_AIRPLAY = 7000            # Apple TV / HomePod / Mac
_AIRPLAY_ALT = 5000
_DAAP = 3689               # iTunes / Apple TV
_AFP = 548                 # macOS file sharing

_APPLE_PORT_HINTS = (_IOS_LOCKDOWN, _AIRPLAY, _DAAP, _AFP, _AIRPLAY_ALT)

#: Hostname fragment -> (vendor, device kind)
_NAME_SIGNATURES = (
    ("iphone", ("Apple", "dev_phone")),
    ("ipad", ("Apple", "dev_tablet")),
    ("ipod", ("Apple", "dev_phone")),
    ("macbook", ("Apple", "dev_laptop")),
    ("imac", ("Apple", "dev_pc")),
    ("mac-mini", ("Apple", "dev_pc")),
    ("macmini", ("Apple", "dev_pc")),
    ("mac-pro", ("Apple", "dev_pc")),
    ("apple-tv", ("Apple", "dev_tv")),
    ("appletv", ("Apple", "dev_tv")),
    ("homepod", ("Apple", "dev_iot")),
    ("airpods", ("Apple", "dev_iot")),
    ("watch", ("Apple", "dev_watch")),
    ("galaxy", ("Samsung", "dev_phone")),
    ("pixel", ("Google", "dev_phone")),
    ("xiaomi", ("Xiaomi", "dev_phone")),
    ("redmi", ("Xiaomi", "dev_phone")),
    ("oneplus", ("OnePlus", "dev_phone")),
    ("huawei", ("Huawei", "dev_phone")),
    ("kindle", ("Amazon", "dev_tablet")),
    ("echo", ("Amazon", "dev_iot")),
    ("chromecast", ("Google", "dev_tv")),
    ("roku", ("Roku", "dev_tv")),
    ("playstation", ("Sony", "dev_console")),
    ("ps5", ("Sony", "dev_console")),
    ("xbox", ("Microsoft", "dev_console")),
    ("switch", ("Nintendo", "dev_console")),
)


# mDNS reverse lookup
def _build_reverse_query(ip: str) -> bytes:
    labels = ip.split(".")[::-1] + ["in-addr", "arpa"]
    qname = b"".join(
        bytes([len(label)]) + label.encode("ascii") for label in labels
    ) + b"\x00"
    header = struct.pack(">HHHHHH", 0, 0, 1, 0, 0, 0)   # id 0, 1 question
    # QTYPE=PTR(12), QCLASS=IN(1) with the top "unicast response" bit set.
    return header + qname + struct.pack(">HH", 12, 0x8001)


def _read_name(data: bytes, offset: int) -> tuple[str, int]:
    parts: list[str] = []
    jumped = False
    end = offset
    hops = 0
    while True:
        if offset >= len(data) or hops > 20:
            break
        length = data[offset]
        if length == 0:
            offset += 1
            if not jumped:
                end = offset
            break
        if length & 0xC0 == 0xC0:                      # compression pointer
            if offset + 1 >= len(data):
                break
            pointer = ((length & 0x3F) << 8) | data[offset + 1]
            if not jumped:
                end = offset + 2
            offset = pointer
            jumped = True
            hops += 1
            continue
        offset += 1
        parts.append(data[offset:offset + length].decode("utf-8", "ignore"))
        offset += length
        if not jumped:
            end = offset
    return ".".join(parts), end


def _parse_ptr_answer(data: bytes) -> str | None:
    try:
        if len(data) < 12:
            return None
        _, _, qd, an, _, _ = struct.unpack(">HHHHHH", data[:12])
        if an < 1:
            return None
        offset = 12
        for _ in range(qd):                            # skip the questions
            _, offset = _read_name(data, offset)
            offset += 4
        for _ in range(an):
            _, offset = _read_name(data, offset)
            if offset + 10 > len(data):
                return None
            rtype, _, _, rdlen = struct.unpack(">HHIH", data[offset:offset + 10])
            offset += 10
            if rtype == 12:                            # PTR
                name, _ = _read_name(data, offset)
                return name
            offset += rdlen
    except Exception:
        return None
    return None


def mdns_hostname(ip: str, timeout: float = 0.7) -> str | None:
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        query = _build_reverse_query(ip)
        # Unicast to the host as well as the multicast group: some devices
        # answer a direct query on 5353 even when multicast is filtered.
        for dest in (("224.0.0.251", 5353), (ip, 5353)):
            try:
                sock.sendto(query, dest)
            except Exception:
                continue
        deadline_tries = 3
        for _ in range(deadline_tries):
            try:
                data, _addr = sock.recvfrom(2048)
            except socket.timeout:
                break
            name = _parse_ptr_answer(data)
            if name:
                return clean_mdns_name(name)
    except Exception:
        return None
    finally:
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass
    return None


def clean_mdns_name(name: str) -> str:
    n = (name or "").strip().rstrip(".")
    for suffix in (".local", ".lan", ".home", ".home.arpa"):
        if n.lower().endswith(suffix):
            n = n[: -len(suffix)]
            break
    return n.strip()


# Port signatures
def _port_open(ip: str, port: int, timeout: float = 0.35) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            return s.connect_ex((ip, port)) == 0
    except Exception:
        return False


def apple_port_signature(ip: str, timeout: float = 0.35) -> tuple[str, str] | None:
    if _port_open(ip, _IOS_LOCKDOWN, timeout):
        return ("Apple", "dev_phone")          # iPhone or iPad
    if _port_open(ip, _AIRPLAY, timeout):
        return ("Apple", "dev_tv")             # Apple TV / HomePod / Mac
    if _port_open(ip, _AFP, timeout):
        return ("Apple", "dev_pc")             # macOS file sharing
    if _port_open(ip, _DAAP, timeout):
        return ("Apple", "dev_tv")
    return None


def name_signature(hostname: str) -> tuple[str, str] | None:
    h = (hostname or "").lower()
    if not h:
        return None
    h = re.sub(r"[\s_]+", "-", h)
    for fragment, result in _NAME_SIGNATURES:
        if fragment in h:
            return result
    return None


# Public entry point
def identify(ip: str, hostname: str = "", vendor: str = "",
             use_ports: bool = True) -> dict:
    out: dict = {}

    # 1) Ask Bonjour for the real name, by far the best answer.
    name = mdns_hostname(ip)
    if name:
        out["hostname"] = name
        sig = name_signature(name)
        if sig:
            out["vendor"], out["kind"] = sig
            return out

    # 2) A hostname we already had might still be recognisable.
    sig = name_signature(hostname)
    if sig and "vendor" not in out:
        out["vendor"], out["kind"] = sig
        return out

    # 3) Fall back to port fingerprinting.
    if use_ports:
        sig = apple_port_signature(ip)
        if sig:
            out["vendor"], out["kind"] = sig
    return out

# Device naming and type detection
KIND_LABELS = {
    "dev_router": "Router", "dev_tv": "TV", "dev_phone": "Phone",
    "dev_tablet": "Tablet", "dev_laptop": "Laptop", "dev_pc": "Computer",
    "dev_nas": "NAS", "dev_server": "Server", "dev_printer": "Printer",
    "dev_console": "Game console", "dev_camera": "Camera",
    "dev_speaker": "Speaker", "dev_iot": "Smart device",
    "dev_watch": "Watch", "dev_media": "Media device",
}

# Names that tell the user nothing, so we fall through to something better.
_GENERIC_NAMES = {
    "", "unknown", "?", "localhost", "router", "gateway", "_gateway", "lan",
    "modem", "dhcp", "host", "device", "android", "wlan0",
}
_IP_LIKE = re.compile(r"^\d{1,3}([.\-]\d{1,3}){3}$")


def usable_name(name, ip: str = "") -> str:
    """Return a cleaned hostname, or "" when it is not a real name."""
    n = clean_mdns_name(name or "")
    if not n or n == ip or n.lower() in _GENERIC_NAMES:
        return ""
    if _IP_LIKE.match(n) or n.lower().endswith(".arpa"):
        return ""
    return n


def _run_with_timeout(fn, timeout: float, *args):
    """Run a blocking call (gethostbyaddr has no timeout) on a daemon thread."""
    box: list = []

    def target():
        try:
            box.append(fn(*args))
        except Exception:
            box.append(None)

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(timeout)
    return box[0] if box else None


def _gethostbyaddr(ip: str):
    return socket.gethostbyaddr(ip)[0]


def reverse_dns(ip: str, timeout: float = 1.5) -> str:
    return usable_name(_run_with_timeout(_gethostbyaddr, timeout, ip), ip)


# NetBIOS node status (UDP 137): Windows PCs and most Samba/NAS boxes answer.
def _nbstat_query() -> bytes:
    raw = b"*" + b"\x00" * 15
    encoded = b"".join(bytes([0x41 + (c >> 4), 0x41 + (c & 0x0F)]) for c in raw)
    header = struct.pack(">HHHHHH", 0x4E57, 0, 1, 0, 0, 0)
    return header + b"\x20" + encoded + b"\x00" + struct.pack(">HH", 0x0021, 0x0001)


def _parse_nbstat(data: bytes):
    try:
        if len(data) < 12:
            return None
        qdcount = struct.unpack(">H", data[4:6])[0]
        offset = 12
        for _ in range(qdcount):                       # skip echoed questions
            offset += 34 + 4
        if offset >= len(data):
            return None
        if data[offset] == 0x20:                       # full encoded name
            offset += 34
        elif data[offset] & 0xC0 == 0xC0:              # compression pointer
            offset += 2
        else:
            return None
        offset += 10                                   # type, class, ttl, rdlen
        if offset >= len(data):
            return None
        count = data[offset]
        offset += 1
        for _ in range(count):
            if offset + 18 > len(data):
                break
            raw = data[offset:offset + 15]
            suffix = data[offset + 15]
            flags = struct.unpack(">H", data[offset + 16:offset + 18])[0]
            offset += 18
            if suffix == 0x00 and not flags & 0x8000:  # unique workstation name
                name = raw.decode("ascii", "ignore").strip()
                if name:
                    return name
    except Exception:
        return None
    return None


def netbios_name(ip: str, timeout: float = 1.0) -> str:
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        sock.sendto(_nbstat_query(), (ip, 137))
        data, _addr = sock.recvfrom(1024)
        return usable_name(_parse_nbstat(data), ip)
    except Exception:
        return ""
    finally:
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass


def _lookup_name(ip: str, timeout: float = 1.8):
    """Ask mDNS, NetBIOS and reverse DNS in parallel; best answer wins."""
    results: dict = {}
    sources = (("mdns", mdns_hostname), ("netbios", netbios_name),
               ("dns", reverse_dns))

    def run(key, fn):
        try:
            results[key] = fn(ip)
        except Exception:
            results[key] = None

    threads = [threading.Thread(target=run, args=(k, f), daemon=True)
               for k, f in sources]
    for t in threads:
        t.start()
    deadline = time.monotonic() + timeout
    for t in threads:
        t.join(max(0.0, deadline - time.monotonic()))
    for key, _fn in sources:
        name = usable_name(results.get(key), ip)
        if name:
            return name, key
    return "", ""


# UPnP / SSDP: TVs, media boxes and many IoT devices describe themselves.
_SSDP_SEARCH = (b"M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\n"
                b"MAN: \"ssdp:discover\"\r\nMX: 1\r\nST: ssdp:all\r\n\r\n")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _parse_upnp_description(xml_bytes: bytes) -> dict:
    # The XML comes from a device on the LAN; refuse entity tricks outright.
    if b"<!DOCTYPE" in xml_bytes.upper() or b"<!ENTITY" in xml_bytes.upper():
        return {}
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return {}
    wanted = {"friendlyName": "friendly_name", "manufacturer": "manufacturer",
              "modelName": "model", "deviceType": "device_type"}
    out: dict = {}
    for elem in root.iter():
        tag = elem.tag.rsplit("}", 1)[-1]
        key = wanted.get(tag)
        if key and key not in out and (elem.text or "").strip():
            out[key] = elem.text.strip()
    return out


def upnp_info(ip: str, timeout: float = 1.2) -> dict:
    """Unicast an SSDP search to one host and read its device description."""
    sock = None
    location = ""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        sock.sendto(_SSDP_SEARCH, (ip, 1900))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not location:
            sock.settimeout(max(0.05, deadline - time.monotonic()))
            data, addr = sock.recvfrom(2048)
            if addr[0] != ip:
                continue
            for line in data.decode("utf-8", "ignore").splitlines():
                if line.lower().startswith("location:"):
                    location = line.split(":", 1)[1].strip()
                    break
    except Exception:
        pass
    finally:
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass
    if not location:
        return {}
    try:
        parts = urllib.parse.urlsplit(location)
        if parts.scheme != "http" or parts.hostname != ip:
            return {}                                  # only talk to that host
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), _NoRedirect)
        with opener.open(location, timeout=timeout) as resp:
            return _parse_upnp_description(resp.read(65536))
    except Exception:
        return {}


# Port probing (only used when nothing cheaper identified the device).
PROBE_PORTS = (22, 80, 139, 443, 445, 515, 554, 631, 1925, 3000, 3001, 3389,
               5000, 8001, 8002, 8008, 8009, 9100, 55000, 62078)
_IN_PROGRESS = {11, 115, 10035}


def open_ports(ip: str, ports=PROBE_PORTS, timeout: float = 0.4) -> set:
    """Return which of `ports` accept a TCP connection (all raced at once)."""
    deadline = time.monotonic() + timeout
    sel = selectors.DefaultSelector()
    socks: list = []
    found: set = set()
    try:
        for port in ports:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setblocking(False)
            err = s.connect_ex((ip, port))
            if err == 0:
                found.add(port)
                s.close()
                continue
            if err not in _IN_PROGRESS:
                s.close()
                continue
            socks.append(s)
            sel.register(s, selectors.EVENT_WRITE, port)
        while socks:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            for key, _ in sel.select(timeout=remaining):
                s, port = key.fileobj, key.data
                err = s.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                sel.unregister(s)
                socks.remove(s)
                s.close()
                if err == 0:
                    found.add(port)
    except Exception:
        pass
    finally:
        for s in socks:
            try:
                sel.unregister(s)
            except Exception:
                pass
            s.close()
        sel.close()
    return found


# Classification
def _b(word: str) -> str:
    """Regex for `word` as a whole token inside a hostname."""
    return rf"(?:^|[^a-z0-9]){word}(?:[^a-z]|$)"


_HOST_PATTERNS = (
    (r"iphone|ipod", "dev_phone"),
    (r"ipad", "dev_tablet"),
    (r"macbook", "dev_laptop"),
    (r"imac|mac-?mini|mac-?pro|mac-?studio", "dev_pc"),
    (r"apple-?tv|appletv", "dev_tv"),
    (r"homepod", "dev_speaker"),
    (r"android-|galaxy|pixel|redmi|xiaomi|oneplus|huawei|oppo|realme|"
     r"poco|" + _b(r"sm-[a-z]\d+"), "dev_phone"),
    (r"webos|bravia|roku|chromecast|fire-?tv|fire-?stick|vizio|tizen|"
     r"smart-?tv|android-?tv|hisense|" + _b("tv") + "|" + _b("tv-[a-z0-9]+"),
     "dev_tv"),
    (r"playstation|nintendo|xbox|" + _b(r"ps[345]"), "dev_console"),
    (r"printer|laserjet|officejet|deskjet|epson|brother|" + _b(r"npi[0-9a-f]+"),
     "dev_printer"),
    (r"ipcam|hikvision|dahua|reolink|" + _b("cam") + "|" + _b("camera")
     + "|" + _b("nvr") + "|" + _b("dvr"), "dev_camera"),
    (r"sonos|alexa|echo-|echodot|" + _b("speaker"), "dev_speaker"),
    (r"synology|diskstation|qnap|truenas|freenas|unraid|" + _b("nas"),
     "dev_nas"),
    (r"server|proxmox|esxi|raspberrypi|homeassistant|pihole|docker|"
     + _b("srv[0-9]*") + "|" + _b("pi"), "dev_server"),
    (r"laptop|notebook|thinkpad|ideapad|latitude|elitebook|probook|"
     r"zenbook|vivobook", "dev_laptop"),
    (r"desktop|workstation|gaming|optiplex|" + _b("pc"), "dev_pc"),
    (r"tasmota|shelly|sonoff|tuya|wled|lifx|" + _b(r"esp[-_0-9a-f]*"),
     "dev_iot"),
    (r"mikrotik|openwrt|fritz|unifi|" + _b("ap") + "|" + _b("router"),
     "dev_router"),
)
_HOST_REGEX = tuple((re.compile(p), kind) for p, kind in _HOST_PATTERNS)


def _kind_from_hostname(hostname: str):
    h = (hostname or "").lower()
    if not h:
        return None
    for regex, kind in _HOST_REGEX:
        if regex.search(h):
            return kind
    return None


def _kind_from_upnp(upnp: dict):
    text = " ".join(str(upnp.get(k, "")) for k in
                    ("friendly_name", "manufacturer", "model", "device_type")).lower()
    if not text.strip():
        return None
    if "internetgatewaydevice" in text or "wanconnectiondevice" in text:
        return "dev_router"
    if re.search(r"webos|bravia|smart ?tv|roku|chromecast|dtv|"
                 r"(?:^|[^a-z])tv(?:[^a-z]|$)", text):
        return "dev_tv"
    if "printer" in text:
        return "dev_printer"
    if re.search(r"camera|ipcam", text):
        return "dev_camera"
    if re.search(r"synology|qnap|diskstation", text):
        return "dev_nas"
    if re.search(r"sonos|speaker|echo", text):
        return "dev_speaker"
    return None


def _kind_from_ports(ports: set, vendor: str):
    v = (vendor or "").lower()
    if 62078 in ports:
        return "dev_phone"                              # iOS lockdownd
    if ports & {8001, 8002, 55000, 3001, 1925}:
        return "dev_tv"                                 # Samsung / LG / Philips
    if 3000 in ports and "lg" in v:
        return "dev_tv"
    if {8008, 8009} <= ports:
        return "dev_tv"                                 # Chromecast / Android TV
    if ports & {9100, 631, 515}:
        return "dev_printer"
    if 554 in ports and not ports & {139, 445, 3389}:
        return "dev_camera"                             # RTSP
    return None


# Vendor substring
_VENDOR_KINDS = (
    (("mikrotik", "routerboard", "ubiquiti", "tp-link", "tplink", "netgear",
      "d-link", "zyxel", "cisco", "linksys", "tenda", "mercusys", "avm",
      "arris", "sagemcom", "technicolor", "ruckus", "aruba"), "dev_router"),
    (("lg electronics", "lg innotek", "tcl", "hisense", "vizio", "roku",
      "skyworth", "sharp", "toshiba", "philips", "panasonic"), "dev_tv"),
    (("synology", "qnap", "asustor", "western digital", "seagate"), "dev_nas"),
    (("supermicro", "raspberry", "vmware", "virtualbox", "qemu", "xen",
      "parallels", "hyper-v", "proxmox"), "dev_server"),
    (("canon", "epson", "brother", "xerox", "lexmark", "ricoh", "kyocera",
      "konica"), "dev_printer"),
    (("sony interactive", "nintendo"), "dev_console"),
    (("hikvision", "dahua", "axis comm", "reolink", "amcrest", "foscam"),
     "dev_camera"),
    (("sonos",), "dev_speaker"),
    (("espressif", "tuya", "shelly", "sonoff", "lifx", "signify",
      "nest labs", "wemo"), "dev_iot"),
    (("xiaomi", "huawei device", "oneplus", "oppo", "vivo", "realme",
      "motorola", "hmd", "honor", "nothing technology"), "dev_phone"),
    (("intel", "realtek", "asustek", "asrock", "gigabyte", "micro-star",
      "msi", "dell", "hewlett", "hp inc", "lenovo", "acer", "microsoft",
      "foxconn", "hon hai", "liteon", "azurewave", "killer", "wistron",
      "compal", "quanta", "pegatron", "biostar", "elitegroup"), "dev_pc"),
    (("samsung", "apple"), "dev_phone"),               # weakest guess, last
)


def _kind_from_vendor(vendor: str):
    v = (vendor or "").lower()
    if not v:
        return None
    for needles, kind in _VENDOR_KINDS:
        if any(n in v for n in needles):
            return kind
    return None


def _is_randomized(vendor: str) -> bool:
    v = (vendor or "").lower()
    return "random" in v or v == "private" or v.startswith("private (")


def _self_kind() -> str:
    try:
        import psutil
        if psutil.sensors_battery() is not None:
            return "dev_laptop"
    except Exception:
        pass
    return "dev_pc"


def classify_kind(dev: dict, ports=None, upnp=None) -> str:
    """Best guess at what a device is; returns a Icons name like "dev_tv"."""
    ports = set(ports or ())
    if dev.get("is_gateway"):
        return "dev_router"
    if dev.get("is_self"):
        return _self_kind()
    ip = dev.get("ip", "")
    hostname = usable_name(dev.get("hostname") or "", ip)
    vendor = dev.get("vendor") or ""
    for kind in (_kind_from_hostname(hostname),
                 _kind_from_upnp(upnp or {}),
                 _kind_from_ports(ports, vendor),
                 _kind_from_vendor(vendor)):
        if kind:
            return kind
    if _is_randomized(vendor):
        return "dev_phone"                              # privacy MACs: phones
    if ports & {445, 139, 3389}:
        return "dev_pc"
    if 22 in ports:
        return "dev_server"
    return "dev_generic"


# Router naming
# A home router rarely answers mDNS/NetBIOS and the system resolver cannot
# name it, so ask the router itself.
def _gateway_dns_name(ip: str, timeout: float = 1.0) -> str:
    """Ask the router's own DNS service (UDP 53) for the PTR of its address."""
    sock = None
    try:
        labels = ip.split(".")[::-1] + ["in-addr", "arpa"]
        qname = b"".join(bytes([len(x)]) + x.encode("ascii") for x in labels) + b"\x00"
        query = struct.pack(">HHHHHH", 0x4E52, 0x0100, 1, 0, 0, 0) + qname \
            + struct.pack(">HH", 12, 1)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        sock.sendto(query, (ip, 53))
        data, _addr = sock.recvfrom(1024)
        return usable_name(_parse_ptr_answer(data), ip)
    except Exception:
        return ""
    finally:
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass


def _mndp_identity(ip: str, timeout: float = 1.0) -> str:
    """MikroTik Neighbor Discovery (UDP 5678): returns the router's identity."""
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        sock.sendto(b"\x00\x00\x00\x00", (ip, 5678))
        data, _addr = sock.recvfrom(2048)
        offset = 4                                     # skip the header
        while offset + 4 <= len(data):
            tlv_type, tlv_len = struct.unpack(">HH", data[offset:offset + 4])
            offset += 4
            if tlv_type == 5:                          # identity
                return usable_name(
                    data[offset:offset + tlv_len].decode("utf-8", "ignore"), ip)
            offset += tlv_len
    except Exception:
        return ""
    finally:
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass
    return ""


def gateway_name(ip: str, vendor: str = "") -> tuple[str, str]:
    """Best name for the default gateway: (name, source)."""
    for source, fn in (("router-dns", _gateway_dns_name), ("mndp", _mndp_identity)):
        name = fn(ip)
        if name:
            return name, source
    v = (vendor or "").strip()
    if v and v.lower() != "unknown" and not _is_randomized(v):
        return f"{v} Router", "inferred"
    return "Router", "inferred"


def enrich_device(dev: dict) -> dict:
    """Look up a real name and the device type for one discovered host.

    Returns only the keys worth updating: hostname, kind, name_source, model
    and (when the MAC lookup found nothing) vendor.
    """
    ip = dev.get("ip", "")
    out: dict = {}
    name, source = "", ""
    if dev.get("is_self"):
        try:
            name, source = usable_name(socket.gethostname(), ip), "this-pc"
        except Exception:
            name = ""
    if not name:
        name, source = _lookup_name(ip)
    if not name and dev.get("is_gateway"):
        name, source = gateway_name(ip, dev.get("vendor", ""))

    upnp: dict = {}
    ports: set = set()
    skip_probes = (dev.get("is_self") or dev.get("is_gateway")
                   or _kind_from_hostname(name))
    if not skip_probes:
        upnp = upnp_info(ip)
        ports = open_ports(ip)
        if not name and upnp.get("friendly_name"):
            name, source = usable_name(upnp["friendly_name"], ip), "upnp"

    probe = dict(dev, hostname=name or "")
    out["kind"] = classify_kind(probe, ports, upnp)
    if name:
        out["hostname"] = name
        out["name_source"] = source
    if upnp.get("model"):
        out["model"] = upnp["model"]
    vendor = (dev.get("vendor") or "").strip()
    if upnp.get("manufacturer") and vendor.lower() in ("", "unknown"):
        out["vendor"] = upnp["manufacturer"]
    return out
