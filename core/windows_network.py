"""Native Windows network information using IP Helper and WLAN APIs."""

import ctypes
import ipaddress
import platform
import socket
import time
from ctypes import wintypes

ERROR_BUFFER_OVERFLOW = 111
GAA_FLAG_INCLUDE_PREFIX = 0x10
GAA_FLAG_INCLUDE_GATEWAYS = 0x80
IP_ADAPTER_DHCP_ENABLED = 0x4
AF_UNSPEC = 0
AF_INET = socket.AF_INET
AF_INET6 = socket.AF_INET6


class _SockaddrIn(ctypes.Structure):
    _fields_ = [("family", ctypes.c_ushort), ("port", ctypes.c_ushort),
                ("address", ctypes.c_ubyte * 4), ("zero", ctypes.c_ubyte * 8)]


class _SockaddrIn6(ctypes.Structure):
    _fields_ = [("family", ctypes.c_ushort), ("port", ctypes.c_ushort),
                ("flowinfo", ctypes.c_uint32), ("address", ctypes.c_ubyte * 16),
                ("scope_id", ctypes.c_uint32)]


class _SocketAddress(ctypes.Structure):
    _fields_ = [("sockaddr", ctypes.c_void_p), ("length", ctypes.c_int)]


class _Unicast(ctypes.Structure):
    pass


_Unicast._fields_ = [
    ("length", wintypes.ULONG), ("flags", wintypes.DWORD), ("next", ctypes.POINTER(_Unicast)),
    ("address", _SocketAddress), ("prefix_origin", ctypes.c_int), ("suffix_origin", ctypes.c_int),
    ("dad_state", ctypes.c_int), ("valid_lifetime", wintypes.ULONG),
    ("preferred_lifetime", wintypes.ULONG), ("lease_lifetime", wintypes.ULONG),
    ("on_link_prefix_length", ctypes.c_ubyte),
]


class _AddressNode(ctypes.Structure):
    pass


_AddressNode._fields_ = [("length", wintypes.ULONG), ("flags", wintypes.DWORD),
                         ("next", ctypes.POINTER(_AddressNode)), ("address", _SocketAddress)]


class _Adapter(ctypes.Structure):
    pass


_Adapter._fields_ = [
    ("length", wintypes.ULONG), ("if_index", wintypes.DWORD), ("next", ctypes.POINTER(_Adapter)),
    ("adapter_name", ctypes.c_char_p), ("first_unicast", ctypes.POINTER(_Unicast)),
    ("first_anycast", ctypes.POINTER(_AddressNode)), ("first_multicast", ctypes.POINTER(_AddressNode)),
    ("first_dns", ctypes.POINTER(_AddressNode)), ("dns_suffix", wintypes.LPWSTR),
    ("description", wintypes.LPWSTR), ("friendly_name", wintypes.LPWSTR),
    ("physical_address", ctypes.c_ubyte * 8), ("physical_address_length", wintypes.DWORD),
    ("flags", wintypes.DWORD), ("mtu", wintypes.DWORD), ("if_type", wintypes.DWORD),
    ("oper_status", ctypes.c_int), ("ipv6_index", wintypes.DWORD), ("zone_indices", wintypes.DWORD * 16),
    ("first_prefix", ctypes.POINTER(_AddressNode)), ("transmit_link_speed", ctypes.c_ulonglong),
    ("receive_link_speed", ctypes.c_ulonglong), ("first_wins", ctypes.POINTER(_AddressNode)),
    ("first_gateway", ctypes.POINTER(_AddressNode)), ("ipv4_metric", wintypes.ULONG),
    ("ipv6_metric", wintypes.ULONG), ("luid", ctypes.c_ulonglong), ("dhcpv4_server", _SocketAddress),
    ("compartment_id", wintypes.ULONG), ("network_guid", ctypes.c_ubyte * 16),
    ("connection_type", ctypes.c_int), ("tunnel_type", ctypes.c_int),
]


def _windows():
    return platform.system() == "Windows"


def _api():
    if not _windows():
        raise OSError("Windows network APIs are unavailable on this platform")
    return ctypes.WinDLL("iphlpapi.dll", use_last_error=True)


def _address(sockaddr):
    ptr = sockaddr.sockaddr
    if not ptr or sockaddr.length < 2:
        return None
    family = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_ushort))[0]
    if family == AF_INET and sockaddr.length >= ctypes.sizeof(_SockaddrIn):
        raw = ctypes.cast(ptr, ctypes.POINTER(_SockaddrIn)).contents
        return socket.inet_ntop(AF_INET, bytes(raw.address))
    if family == AF_INET6 and sockaddr.length >= ctypes.sizeof(_SockaddrIn6):
        raw = ctypes.cast(ptr, ctypes.POINTER(_SockaddrIn6)).contents
        text = socket.inet_ntop(AF_INET6, bytes(raw.address))
        return f"{text}%{raw.scope_id}" if raw.scope_id else text
    return None


def _addresses(head):
    result = []
    while head:
        value = _address(head.contents.address)
        if value:
            result.append(value)
        head = head.contents.next
    return result


_ULA_NETWORK = ipaddress.ip_network("fc00::/7")


def _preferred_ipv6(addresses):
    """Pick the most useful IPv6 address: global, then unique-local, then
    link-local. The first one the API lists is often just fe80::, which made
    a perfectly good IPv6 setup look like "no IPv6"."""
    candidates = []
    for entry in addresses:
        raw = entry["address"]
        if ":" not in raw:
            continue
        try:
            ip = ipaddress.IPv6Address(raw.split("%")[0])
        except ValueError:
            continue
        if ip.is_loopback or ip.is_unspecified or ip.is_multicast:
            continue
        rank = 2 if ip.is_link_local else (1 if ip in _ULA_NETWORK else 0)
        candidates.append((rank, entry))
    return min(candidates, key=lambda c: c[0])[1] if candidates else None


def _preferred_ipv4(addresses):
    ipv4 = [a for a in addresses if ":" not in a["address"]]
    return next((a for a in ipv4 if not ipaddress.IPv4Address(a["address"]).is_link_local),
                ipv4[0] if ipv4 else None)


_LINK_SPEED_UNKNOWN = 0xFFFFFFFFFFFFFFFF


def _format_link_speed(*speeds_bps):
    """Format IP Helper link speeds (bits/s) as e.g. '1 Gbps' or '866.7 Mbps'."""
    values = [int(v) for v in speeds_bps if v and int(v) != _LINK_SPEED_UNKNOWN]
    if not values:
        return ""
    mbps = max(values) / 1_000_000
    if mbps >= 1000:
        return f"{round(mbps / 1000, 2):g} Gbps"
    return f"{round(mbps, 1):g} Mbps"


def _adapters():
    api = _api()
    fn = api.GetAdaptersAddresses
    fn.argtypes = [wintypes.ULONG, wintypes.ULONG, ctypes.c_void_p,
                   ctypes.POINTER(_Adapter), ctypes.POINTER(wintypes.ULONG)]
    fn.restype = wintypes.ULONG
    size = wintypes.ULONG(15000)
    while True:
        buf = ctypes.create_string_buffer(size.value)
        code = fn(AF_UNSPEC, GAA_FLAG_INCLUDE_PREFIX | GAA_FLAG_INCLUDE_GATEWAYS,
                  None, ctypes.cast(buf, ctypes.POINTER(_Adapter)), ctypes.byref(size))
        if code == ERROR_BUFFER_OVERFLOW:
            continue
        if code:
            raise OSError(code, "GetAdaptersAddresses failed")
        items, ptr = [], ctypes.cast(buf, ctypes.POINTER(_Adapter))
        while ptr:
            item = ptr.contents
            name = item.friendly_name or (item.adapter_name.decode("ascii", "replace") if item.adapter_name else "")
            mac = ":".join(f"{b:02X}" for b in item.physical_address[:min(item.physical_address_length, 8)])
            unicast, cur = [], item.first_unicast
            while cur:
                u = cur.contents
                value = _address(u.address)
                if value:
                    unicast.append({"address": value, "prefix": int(u.on_link_prefix_length)})
                cur = u.next
            items.append({"name": name, "description": item.description or "",
                          "status": "Up" if item.oper_status == 1 else "Down", "mac": mac,
                          "mtu": int(item.mtu), "if_index": int(item.if_index), "addresses": unicast,
                          "link_speed": _format_link_speed(item.transmit_link_speed,
                                                           item.receive_link_speed),
                          "gateways": _addresses(item.first_gateway), "dns": _addresses(item.first_dns),
                          "dhcp_enabled": bool(item.flags & IP_ADAPTER_DHCP_ENABLED),
                          "ipv4_metric": int(item.ipv4_metric), "if_type": int(item.if_type)})
            ptr = item.next
        return items


def _not_windows():
    return {"error": "Windows network APIs are unavailable on this platform"}


def list_adapters():
    """Return adapter summaries; errors use the consumer-friendly error key."""
    try:
        return [{k: v for k, v in adapter.items()
                 if k not in ("addresses", "gateways", "dns", "dhcp_enabled")}
                for adapter in _adapters()]
    except Exception as exc:
        return _not_windows() if not _windows() else {"error": str(exc)}


def adapter_details(name):
    """Return one adapter with address and link configuration fields."""
    if not name:
        return {"error": "No adapter name given"}
    try:
        for adapter in _adapters():
            if adapter["name"].casefold() == name.casefold():
                addresses = adapter.pop("addresses")
                ipv4 = _preferred_ipv4(addresses) or {}
                ipv6 = _preferred_ipv6(addresses) or {}
                adapter.update({"ipv4": ipv4.get("address", ""), "ipv6": ipv6.get("address", ""),
                                "prefix": ipv4.get("prefix", 0),
                                 "subnet_mask": str(ipaddress.IPv4Network(f"0.0.0.0/{ipv4['prefix']}").netmask) if ipv4 else "",
                                 "gateway": ", ".join(adapter.pop("gateways")), "dns": ", ".join(adapter.pop("dns")),
                                 "dhcp": "Enabled" if adapter.pop("dhcp_enabled") else "Static/Manual",
                                 "virtual": False})
                return adapter
        return {"error": f"Adapter '{name}' not found"}
    except Exception as exc:
        return _not_windows() if not _windows() else {"error": str(exc)}


def active_network_config():
    """Return the IPv4 address on the active default-route adapter."""
    try:
        adapters = _adapters()
        routes = _default_ipv4_routes()
        choices = []
        for route in routes:
            adapter = next((a for a in adapters if a["if_index"] == route[0]), None)
            if adapter and adapter["status"] == "Up":
                choices.append((route[1] + adapter["ipv4_metric"], adapter, route[2]))
        if not choices:
            return {"error": "No active network connection found"}
        _, adapter, gateway = min(choices, key=lambda item: item[0])
        entry = _preferred_ipv4(adapter["addresses"])
        if not entry:
            return {"error": "No active IPv4 address found"}
        return {"ip": entry["address"], "prefix": entry["prefix"],
                "gateway": gateway or "N/A",
                "dns": ", ".join(adapter["dns"]) or "N/A", "mac": adapter["mac"] or "N/A",
                "adapter": adapter["name"],
                "ipv6": (_preferred_ipv6(adapter["addresses"]) or {}).get("address", "")}
    except Exception as exc:
        return _not_windows() if not _windows() else {"error": str(exc)}


class _SockaddrInet(ctypes.Union):
    _fields_ = [("ipv4", _SockaddrIn), ("ipv6", _SockaddrIn6), ("raw", ctypes.c_ubyte * 28)]


class _IpAddressPrefix(ctypes.Structure):
    _fields_ = [("prefix", _SockaddrInet), ("length", ctypes.c_ubyte)]


class _ForwardRow(ctypes.Structure):
    _fields_ = [("luid", ctypes.c_ulonglong), ("if_index", ctypes.c_uint32),
                ("destination", _IpAddressPrefix), ("next_hop", _SockaddrInet),
                ("site_prefix_length", ctypes.c_ubyte), ("valid_lifetime", ctypes.c_uint32),
                ("preferred_lifetime", ctypes.c_uint32), ("metric", ctypes.c_uint32),
                ("protocol", ctypes.c_int), ("loopback", ctypes.c_ubyte),
                ("autoconfigure", ctypes.c_ubyte), ("publish", ctypes.c_ubyte),
                ("immortal", ctypes.c_ubyte), ("age", ctypes.c_uint32),
                 ("origin", ctypes.c_int)]


class _IcmpEchoReply(ctypes.Structure):
    _fields_ = [("address", wintypes.ULONG), ("status", wintypes.ULONG),
                ("round_trip_time", wintypes.ULONG), ("data_size", wintypes.USHORT),
                ("reserved", wintypes.USHORT), ("data", ctypes.c_void_p),
                ("options", ctypes.c_void_p)]


def _inet_value(value):
    fam = value.raw[0:2]
    family = int.from_bytes(bytes(fam), byteorder="little")
    if family == AF_INET:
        return socket.inet_ntop(AF_INET, bytes(value.ipv4.address))
    return None


def _default_ipv4_routes():
    return [(route["interface_index"], route["metric"], route["next_hop"])
            for route in ipv4_route_table()
            if route["destination"] == "0.0.0.0/0"]


def ipv4_route_table():
    """Return IPv4 routes with their actual prefixes and interface indices."""
    api = _api()
    fn, free = api.GetIpForwardTable2, api.FreeMibTable
    fn.argtypes = [ctypes.c_ushort, ctypes.POINTER(ctypes.c_void_p)]
    fn.restype = wintypes.ULONG
    free.argtypes = [ctypes.c_void_p]
    free.restype = None
    ptr = ctypes.c_void_p()
    try:
        code = fn(AF_INET, ctypes.byref(ptr))
        if code:
            raise OSError(code, "GetIpForwardTable2 failed")
        if not ptr:
            return []
        count = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_uint32))[0]
        offset = (ctypes.sizeof(wintypes.ULONG) + ctypes.alignment(_ForwardRow) - 1) & ~(ctypes.alignment(_ForwardRow) - 1)
        out = []
        for i in range(count):
            row = _ForwardRow.from_address(ptr.value + offset + i * ctypes.sizeof(_ForwardRow))
            destination = _inet_value(row.destination.prefix)
            if destination is None:
                continue
            prefix = int(row.destination.length)
            out.append({"destination": f"{destination}/{prefix}",
                        "interface_index": int(row.if_index),
                        "next_hop": _inet_value(row.next_hop) or "",
                        "metric": int(row.metric)})
        return out
    finally:
        if ptr:
            free(ptr)


def icmp_probe(ip, timeout_ms=200):
    """Send one native ICMP echo without spawning a ping subprocess."""
    if not _windows():
        return None
    api = _api()
    create = api.IcmpCreateFile
    create.argtypes = []
    create.restype = wintypes.HANDLE
    send = api.IcmpSendEcho
    send.argtypes = [wintypes.HANDLE, wintypes.ULONG, ctypes.c_void_p,
                     wintypes.USHORT, ctypes.c_void_p, ctypes.c_void_p,
                     wintypes.DWORD, wintypes.DWORD]
    send.restype = wintypes.DWORD
    close = api.IcmpCloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL

    handle = create()
    handle_value = getattr(handle, "value", handle)
    if not handle_value or handle_value == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    request = ctypes.create_string_buffer(b"N", 1)
    # Windows may append the returned payload and option structure after the
    # fixed reply header; leave room for both on 32- and 64-bit runtimes.
    reply_buffer = ctypes.create_string_buffer(
        max(128, ctypes.sizeof(_IcmpEchoReply) + len(request) + 16))
    try:
        address = int.from_bytes(socket.inet_aton(ip), "little")
        count = send(handle, address, request, 1, None, reply_buffer,
                     ctypes.sizeof(reply_buffer), max(1, int(timeout_ms)))
        if not count:
            return None
        reply = ctypes.cast(reply_buffer, ctypes.POINTER(_IcmpEchoReply)).contents
        if reply.status != 0:
            return None
        return float(reply.round_trip_time)
    finally:
        close(handle)


class _Dot11Ssid(ctypes.Structure):
    _fields_ = [("length", wintypes.ULONG), ("value", ctypes.c_ubyte * 32)]


class _WlanAssociation(ctypes.Structure):
    _fields_ = [("ssid", _Dot11Ssid), ("bss_type", ctypes.c_int), ("bssid", ctypes.c_ubyte * 6),
                ("phy_type", ctypes.c_int), ("phy_index", wintypes.ULONG),
                ("signal", wintypes.ULONG), ("rx_rate", wintypes.ULONG), ("tx_rate", wintypes.ULONG)]


class _WlanSecurity(ctypes.Structure):
    _fields_ = [("security_enabled", wintypes.BOOL), ("one_x_enabled", wintypes.BOOL),
                ("auth", ctypes.c_int), ("cipher", ctypes.c_int)]


class _WlanConnectionAttributes(ctypes.Structure):
    _fields_ = [("state", ctypes.c_int), ("mode", ctypes.c_int),
                ("profile", wintypes.WCHAR * 256), ("association", _WlanAssociation),
                ("security", _WlanSecurity)]


class _Guid(ctypes.Structure):
    _fields_ = [("data", ctypes.c_ubyte * 16)]


class _WlanInterface(ctypes.Structure):
    _fields_ = [("guid", _Guid), ("description", wintypes.WCHAR * 256), ("state", ctypes.c_int)]


class _WlanList(ctypes.Structure):
    _fields_ = [("count", wintypes.DWORD), ("index", wintypes.DWORD), ("items", _WlanInterface * 1)]


class _WlanAvailableNetwork(ctypes.Structure):
    _fields_ = [("profile", wintypes.WCHAR * 256), ("ssid", _Dot11Ssid),
                ("bss_type", ctypes.c_int), ("number_of_bssids", wintypes.ULONG),
                ("connectable", wintypes.BOOL), ("reason", wintypes.ULONG),
                ("number_of_phy_types", wintypes.ULONG), ("phy_types", ctypes.c_int * 8),
                ("more_phy_types", wintypes.BOOL), ("signal", wintypes.ULONG),
                ("security_enabled", wintypes.BOOL), ("auth", ctypes.c_int),
                ("cipher", ctypes.c_int), ("flags", wintypes.ULONG), ("reserved", wintypes.ULONG)]


class _WlanNetworkList(ctypes.Structure):
    _fields_ = [("count", wintypes.DWORD), ("index", wintypes.DWORD),
                ("items", _WlanAvailableNetwork * 1)]


_AUTH = {1: "Open", 2: "Shared/WEP", 3: "WPA-Enterprise", 4: "WPA-Personal",
         5: "WPA-None", 6: "WPA2-Enterprise", 7: "WPA2-Personal",
         8: "WPA3-Enterprise-192", 9: "WPA3-Personal", 10: "OWE",
         11: "WPA3-Enterprise"}
_CIPHER = {0: "None", 1: "WEP-40", 2: "TKIP", 4: "CCMP", 5: "WEP-104",
            6: "BIP", 8: "GCMP", 9: "GCMP-256", 10: "CCMP-256",
            11: "BIP-GMAC-128", 12: "BIP-GMAC-256", 13: "BIP-CMAC-256"}


def _wlan_interfaces():
    if not _windows():
        raise OSError("Windows WLAN API is unavailable on this platform")
    wlan = ctypes.WinDLL("wlanapi.dll", use_last_error=True)
    wlan.WlanOpenHandle.argtypes = [wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.HANDLE)]
    wlan.WlanOpenHandle.restype = wintypes.DWORD
    wlan.WlanEnumInterfaces.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    wlan.WlanEnumInterfaces.restype = wintypes.DWORD
    wlan.WlanFreeMemory.argtypes = [ctypes.c_void_p]
    wlan.WlanFreeMemory.restype = None
    wlan.WlanCloseHandle.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    wlan.WlanCloseHandle.restype = wintypes.DWORD
    handle, negotiated = wintypes.HANDLE(), wintypes.DWORD()
    code = wlan.WlanOpenHandle(2, None, ctypes.byref(negotiated), ctypes.byref(handle))
    if code:
        raise OSError(code, "WlanOpenHandle failed")
    ptr = ctypes.c_void_p()
    try:
        code = wlan.WlanEnumInterfaces(handle, None, ctypes.byref(ptr))
        if code:
            raise OSError(code, "WlanEnumInterfaces failed")
        header = ctypes.cast(ptr, ctypes.POINTER(_WlanList)).contents
        base = ctypes.addressof(header) + _WlanList.items.offset
        return [(_WlanInterface.from_address(base + i * ctypes.sizeof(_WlanInterface)), wlan, handle)
                for i in range(header.count)], wlan, handle, ptr
    except Exception:
        if ptr:
            wlan.WlanFreeMemory(ptr)
        wlan.WlanCloseHandle(handle, None)
        raise


def _query_connection(wlan, handle, guid):
    fn = wlan.WlanQueryInterface
    fn.argtypes = [wintypes.HANDLE, ctypes.POINTER(_Guid), ctypes.c_int, ctypes.c_void_p,
                   ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_int)]
    fn.restype = wintypes.DWORD
    size, opcode, data = wintypes.DWORD(), ctypes.c_int(), ctypes.c_void_p()
    code = fn(handle, ctypes.byref(guid), 7, None, ctypes.byref(size), ctypes.byref(data), ctypes.byref(opcode))
    if code:
        raise OSError(code, "WlanQueryInterface failed")
    try:
        if not data or size.value < ctypes.sizeof(_WlanConnectionAttributes):
            raise OSError("WlanQueryInterface returned an invalid connection structure")
        raw = ctypes.string_at(data, ctypes.sizeof(_WlanConnectionAttributes))
        return _WlanConnectionAttributes.from_buffer_copy(raw)
    finally:
        if data:
            wlan.WlanFreeMemory(data)


def current_wifi():
    """Return current WLAN connection details, or an error dictionary."""
    try:
        interfaces, wlan, handle, list_ptr = _wlan_interfaces()
        try:
            for interface, _, _ in interfaces:
                try:
                    info = _query_connection(wlan, handle, interface.guid)
                except OSError:
                    continue
                if info.state != 1:
                    continue
                assoc, sec = info.association, info.security
                ssid = bytes(assoc.ssid.value[:min(assoc.ssid.length, 32)]).decode("utf-8", "replace")
                bssid = ":".join(f"{b:02X}" for b in assoc.bssid)
                return {"ssid": ssid or "Unknown", "bssid": bssid, "signal": f"{assoc.signal}%",
                        "radio": "Unknown", "band": "Unknown", "auth": _AUTH.get(sec.auth, "Unknown"),
                        "channel": "Unknown", "cipher": _CIPHER.get(sec.cipher, "Unknown"),
                        "link_speed": f"{max(assoc.rx_rate, assoc.tx_rate) / 1000:g} Mbps",
                        "rx_rate": f"{assoc.rx_rate / 1000:g} Mbps", "tx_rate": f"{assoc.tx_rate / 1000:g} Mbps"}
            return {"error": "No active Wi-Fi connection"}
        finally:
            if list_ptr:
                wlan.WlanFreeMemory(list_ptr)
            wlan.WlanCloseHandle(handle, None)
    except Exception as exc:
        return _not_windows() if not _windows() else {"error": str(exc)}


def scan_wifi_networks():
    """Request a WLAN scan and return the available SSIDs and signal levels."""
    try:
        interfaces, wlan, handle, list_ptr = _wlan_interfaces()
        networks = {}
        failures = []
        scan = wlan.WlanScan
        scan.argtypes = [wintypes.HANDLE, ctypes.POINTER(_Guid), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        scan.restype = wintypes.DWORD
        get_list = wlan.WlanGetAvailableNetworkList
        get_list.argtypes = [wintypes.HANDLE, ctypes.POINTER(_Guid), wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        get_list.restype = wintypes.DWORD
        try:
            for interface, _, _ in interfaces:
                try:
                    code = scan(handle, ctypes.byref(interface.guid), None, None, None)
                    if code:
                        raise OSError(code, "WlanScan failed")
                    time.sleep(4.0)
                    ptr = ctypes.c_void_p()
                    code = get_list(handle, ctypes.byref(interface.guid), 1, None, ctypes.byref(ptr))
                    if code:
                        raise OSError(code, "WlanGetAvailableNetworkList failed")
                except OSError as exc:
                    failures.append(f"{interface.description}: {exc}")
                    continue
                try:
                    if not ptr:
                        continue
                    header = ctypes.cast(ptr, ctypes.POINTER(_WlanNetworkList)).contents
                    base = ctypes.addressof(header) + _WlanNetworkList.items.offset
                    for i in range(header.count):
                        item = _WlanAvailableNetwork.from_address(base + i * ctypes.sizeof(_WlanAvailableNetwork))
                        length = min(item.ssid.length, 32)
                        ssid = bytes(item.ssid.value[:length]).decode("utf-8", "replace") or "(hidden network)"
                        found = {"ssid": ssid, "auth": _AUTH.get(item.auth, "Unknown"),
                                 "encryption": _CIPHER.get(item.cipher, "Unknown"), "signal": int(item.signal),
                                 "signal_dbm": round(item.signal / 2 - 100), "channel": "", "band": "", "radio": "Unknown"}
                        if ssid not in networks or item.signal > networks[ssid]["signal"]:
                            networks[ssid] = found
                finally:
                    if ptr:
                        wlan.WlanFreeMemory(ptr)
        finally:
            if list_ptr:
                wlan.WlanFreeMemory(list_ptr)
            wlan.WlanCloseHandle(handle, None)
        found = sorted(networks.values(), key=lambda item: item["signal"], reverse=True)
        if not found and failures:
            return {"error": "; ".join(failures)}
        result = {"networks": found, "count": len(found)}
        if failures:
            result["errors"] = failures
        return result
    except Exception as exc:
        return _not_windows() if not _windows() else {"error": str(exc)}


class _MibNeighborRow(ctypes.Structure):
    _fields_ = [("address", _SockaddrInet), ("if_index", wintypes.DWORD),
                ("luid", ctypes.c_ulonglong), ("physical_address", ctypes.c_ubyte * 32),
                ("physical_length", ctypes.c_uint32), ("state", ctypes.c_int),
                ("flags", ctypes.c_ubyte * 2), ("reachability_time", wintypes.ULONG)]


def neighbor_table():
    """Return IPv4 and IPv6 neighbor entries from GetIpNetTable2."""
    if not _windows():
        return _not_windows()
    api = _api()
    fn, free = api.GetIpNetTable2, api.FreeMibTable
    fn.argtypes = [ctypes.c_ushort, ctypes.POINTER(ctypes.c_void_p)]
    fn.restype = wintypes.ULONG
    free.argtypes = [ctypes.c_void_p]
    free.restype = None
    ptr = ctypes.c_void_p()
    try:
        code = fn(AF_UNSPEC, ctypes.byref(ptr))
        if code:
            raise OSError(code, "GetIpNetTable2 failed")
        if not ptr:
            return []
        count = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_uint32))[0]
        offset = (ctypes.sizeof(wintypes.ULONG) + ctypes.alignment(_MibNeighborRow) - 1) & ~(ctypes.alignment(_MibNeighborRow) - 1)
        rows = []
        for i in range(count):
            row = _MibNeighborRow.from_address(ptr.value + offset + i * ctypes.sizeof(_MibNeighborRow))
            family = int.from_bytes(bytes(row.address.raw[:2]), "little")
            if family == AF_INET:
                ip = socket.inet_ntop(AF_INET, bytes(row.address.ipv4.address))
            elif family == AF_INET6:
                raw = row.address.ipv6
                ip = socket.inet_ntop(AF_INET6, bytes(raw.address))
                if raw.scope_id:
                    ip += f"%{raw.scope_id}"
            else:
                continue
            length = min(int(row.physical_length), 32)
            mac = ":".join(f"{b:02X}" for b in row.physical_address[:length])
            rows.append({"ip": ip, "mac": mac, "interface_index": int(row.if_index), "state": int(row.state)})
        return rows
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if ptr:
            free(ptr)
