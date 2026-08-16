"""Device fingerprinting for devices that hide behind a randomized MAC.

Since iOS 14 / Android 10, phones use a *private Wi-Fi address* — a randomized
MAC — so the OUI table has nothing to look up and the device shows as a bare IP.
That's most of the "unidentified" nodes on a home network, and most of those are
Apple devices.

Two techniques that don't depend on the MAC at all:

1. **mDNS (Bonjour) reverse lookup.** Apple devices run Bonjour and answer a
   reverse PTR query on 224.0.0.251:5353 with their real name — "Lukas-iPhone",
   "Ana-iPad", "MacBook-Pro". This is the reliable one: it gives us the actual
   device name, not a guess.

2. **Port signatures.** If mDNS is quiet, a few TCP ports are strong hints:
   62078 is iOS `lockdownd` (iPhone/iPad sync) and is effectively an iOS
   fingerprint; 7000 + 5000 mean AirPlay; 548 (AFP) and 88 point at a Mac.

Everything here is best-effort and fast-failing: short timeouts, run in
parallel, and a miss simply leaves the device as it was.
"""
from __future__ import annotations

import re
import socket
import struct

# TCP ports that identify Apple gear.
_IOS_LOCKDOWN = 62078      # iPhone / iPad (lockdownd)
_AIRPLAY = 7000            # Apple TV / HomePod / Mac
_AIRPLAY_ALT = 5000
_DAAP = 3689               # iTunes / Apple TV
_AFP = 548                 # macOS file sharing

_APPLE_PORT_HINTS = (_IOS_LOCKDOWN, _AIRPLAY, _DAAP, _AFP, _AIRPLAY_ALT)

#: Hostname fragment → (vendor, device kind)
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


# ── mDNS reverse lookup ────────────────────────────────────────
def _build_reverse_query(ip: str) -> bytes:
    """A DNS PTR query for <reversed-ip>.in-addr.arpa, with mDNS's QU bit set
    so the device answers us directly instead of multicasting."""
    labels = ip.split(".")[::-1] + ["in-addr", "arpa"]
    qname = b"".join(bytes([len(l)]) + l.encode("ascii") for l in labels) + b"\x00"
    header = struct.pack(">HHHHHH", 0, 0, 1, 0, 0, 0)   # id 0, 1 question
    # QTYPE=PTR(12), QCLASS=IN(1) with the top "unicast response" bit set.
    return header + qname + struct.pack(">HH", 12, 0x8001)


def _read_name(data: bytes, offset: int) -> tuple[str, int]:
    """Read a DNS name, following compression pointers. Returns (name, next)."""
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
    """Pull the first PTR target out of a DNS response."""
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
    """Ask the device for its Bonjour name. Returns e.g. 'Lukas-iPhone' or None.

    Sent to the mDNS multicast group; Apple/Android/printers that run Bonjour
    or Avahi will answer. Anything else just stays silent and we time out."""
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
    """'Lukas-iPhone.local.' → 'Lukas-iPhone'."""
    n = (name or "").strip().rstrip(".")
    for suffix in (".local", ".lan", ".home", ".home.arpa"):
        if n.lower().endswith(suffix):
            n = n[: -len(suffix)]
            break
    return n.strip()


# ── Port signatures ────────────────────────────────────────────
def _port_open(ip: str, port: int, timeout: float = 0.35) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            return s.connect_ex((ip, port)) == 0
    except Exception:
        return False


def apple_port_signature(ip: str, timeout: float = 0.35) -> tuple[str, str] | None:
    """Probe a few Apple-specific ports. Returns (vendor, kind) or None.

    Port 62078 is iOS `lockdownd` — present on iPhones and iPads and almost
    nothing else, so it's the strongest single signal we have."""
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
    """Map a hostname to (vendor, kind) using well-known naming patterns."""
    h = (hostname or "").lower()
    if not h:
        return None
    h = re.sub(r"[\s_]+", "-", h)
    for fragment, result in _NAME_SIGNATURES:
        if fragment in h:
            return result
    return None


# ── Public entry point ─────────────────────────────────────────
def identify(ip: str, hostname: str = "", vendor: str = "",
             use_ports: bool = True) -> dict:
    """Best-effort identification of a device the MAC couldn't name.

    Returns a dict that may contain 'hostname', 'vendor' and 'kind'. Keys are
    only present when we actually learned something, so callers can update a
    device dict without clobbering good data with blanks."""
    out: dict = {}

    # 1) Ask Bonjour for the real name — by far the best answer.
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
