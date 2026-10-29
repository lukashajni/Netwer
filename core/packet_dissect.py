"""Packet dissector for the Packet Capture page.

Turns raw Ethernet frames into a summary row (source, destination, protocol,
info) plus the fields the display filter and the assistant read. With
tree=True it also builds the layer tree shown in the details panel; every node
carries the byte range it came from so the bytes panel can highlight it.
"""

import struct

ETH_TYPES = {0x0800: "IPv4", 0x0806: "ARP", 0x86DD: "IPv6", 0x8100: "802.1Q VLAN", 0x88CC: "LLDP", 0x888E: "EAPOL"}
IP_PROTOS = {1: "ICMP", 2: "IGMP", 6: "TCP", 17: "UDP", 58: "ICMPv6"}
TCP_FLAGS = [("FIN", 1), ("SYN", 2), ("RST", 4), ("PSH", 8), ("ACK", 16), ("URG", 32), ("ECE", 64), ("CWR", 128)]
WELL_KNOWN = {20: "FTP-DATA", 21: "FTP", 22: "SSH", 23: "Telnet", 25: "SMTP", 53: "DNS", 67: "DHCP", 68: "DHCP",
              80: "HTTP", 110: "POP3", 123: "NTP", 137: "NBNS", 143: "IMAP", 161: "SNMP", 443: "HTTPS", 445: "SMB",
              1900: "SSDP", 3389: "RDP", 5353: "MDNS", 5355: "LLMNR", 8080: "HTTP"}
PLAINTEXT_PORTS = {21: "FTP", 23: "Telnet", 80: "HTTP", 110: "POP3", 143: "IMAP", 8080: "HTTP"}
DNS_TYPES = {1: "A", 2: "NS", 5: "CNAME", 6: "SOA", 12: "PTR", 15: "MX", 16: "TXT", 28: "AAAA", 33: "SRV",
             47: "NSEC", 65: "HTTPS", 255: "ANY"}
ICMP_TYPES = {0: "Echo (ping) reply", 3: "Destination unreachable", 5: "Redirect", 8: "Echo (ping) request",
              11: "Time-to-live exceeded"}
ICMP6_TYPES = {128: "Echo (ping) request", 129: "Echo (ping) reply", 133: "Router Solicitation",
               134: "Router Advertisement", 135: "Neighbor Solicitation", 136: "Neighbor Advertisement",
               143: "Multicast Listener Report Message v2"}
TLS_CONTENT = {20: "Change Cipher Spec", 21: "Alert", 22: "Handshake", 23: "Application Data"}
TLS_HS = {1: "Client Hello", 2: "Server Hello", 4: "New Session Ticket", 11: "Certificate", 16: "Client Key Exchange"}
TLS_VERSIONS = {0x0301: "TLS 1.0", 0x0302: "TLS 1.1", 0x0303: "TLS 1.2", 0x0304: "TLS 1.3"}


def mac_str(b: bytes) -> str:
    return ":".join(f"{x:02x}" for x in b)


def ip4_str(b: bytes) -> str:
    return ".".join(str(x) for x in b)


def ip6_str(b: bytes) -> str:
    groups = [f"{(b[i] << 8) | b[i + 1]:x}" for i in range(0, 16, 2)]
    # compress the longest run of zero groups
    best, run, start = (0, -1), 0, -1
    for i, g in enumerate(groups + ["x"]):
        if g == "0":
            if run == 0:
                start = i
            run += 1
        else:
            if run > best[0] and run > 1:
                best = (run, start)
            run = 0
    if best[0]:
        n, s = best
        left, right = ":".join(groups[:s]), ":".join(groups[s + n:])
        return f"{left}::{right}"
    return ":".join(groups)


def flag_names(flags: int) -> list:
    return [n for n, bit in TCP_FLAGS if flags & bit]


class Node:
    __slots__ = ("title", "off", "length", "children")

    def __init__(self, title, off=None, length=0, children=None):
        self.title, self.off, self.length = title, off, length
        self.children = children or []

    def add(self, title, off=None, length=0):
        n = Node(title, off, length)
        self.children.append(n)
        return n

    def text(self, depth=0) -> str:
        lines = ["  " * depth + self.title]
        for c in self.children:
            lines.append(c.text(depth + 1))
        return "\n".join(lines)


class _NoNode:
    """Stand-in used when no tree is needed, so the parsing code stays the same."""

    def add(self, *a, **k):
        return self

    children = ()


_NO = _NoNode()


class Dissection:
    """Result of dissecting one frame."""

    def __init__(self, data: bytes):
        self.data = data
        self.length = len(data)
        self.protos = ["eth"]
        self.proto = "Ethernet"
        self.info = ""
        self.src = self.dst = ""
        self.smac = self.dmac = ""
        self.ip_src = self.ip_dst = None
        self.ip_ttl = None
        self.l4 = None
        self.sport = self.dport = None
        self.tcp_seq = self.tcp_ack = self.tcp_flags = self.tcp_win = None
        self.payload_len = 0
        self.fields = {}          # extra filter fields: dns.qry.name, tls sni, http host, ...
        self.tree = []


class _Dissector:
    def __init__(self, data: bytes, tree: bool):
        self.d = Dissection(data)
        self.data = data
        self.tree = tree

    def node(self, title, off=None, length=0):
        if not self.tree:
            return _NO
        n = Node(title, off, length)
        self.d.tree.append(n)
        return n

    # -- link layer --
    def run(self) -> Dissection:
        b, d = self.data, self.d
        if len(b) < 14:
            d.info = "Truncated frame"
            return d
        d.dmac, d.smac = mac_str(b[0:6]), mac_str(b[6:12])
        d.src, d.dst = d.smac, d.dmac
        etype = struct.unpack("!H", b[12:14])[0]
        if etype <= 1500:
            return self.llc(etype)
        eth = self.node(f"Ethernet II, Src: {d.smac}, Dst: {d.dmac}", 0, 14)
        eth.add(f"Destination: {d.dmac}", 0, 6)
        eth.add(f"Source: {d.smac}", 6, 6)
        off = 12
        if etype == 0x8100 and len(b) >= 18:
            vid = struct.unpack("!H", b[14:16])[0] & 0x0FFF
            eth.add(f"802.1Q Virtual LAN, ID: {vid}", 12, 4)
            d.protos.append("vlan")
            off, etype = 16, struct.unpack("!H", b[16:18])[0]
        eth.add(f"Type: {ETH_TYPES.get(etype, 'Unknown')} (0x{etype:04x})", off, 2)
        start = off + 2
        if etype == 0x0800:
            self.ipv4(start)
        elif etype == 0x86DD:
            self.ipv6(start)
        elif etype == 0x0806:
            self.arp(start)
        else:
            d.proto = ETH_TYPES.get(etype, f"0x{etype:04x}")
            d.protos.append(d.proto.lower())
            d.info = f"Ethertype 0x{etype:04x}"
        return d

    def llc(self, length):
        b, d = self.data, self.d
        n = self.node(f"IEEE 802.3 Ethernet, Src: {d.smac}, Dst: {d.dmac}", 0, 14)
        n.add(f"Length: {length}", 12, 2)
        d.protos.append("llc")
        if len(b) >= 17 and b[14] == 0x42 and b[15] == 0x42:
            d.proto = "STP"
            d.protos.append("stp")
            d.info = "Spanning Tree bridge protocol data unit"
            self.node("Spanning Tree Protocol", 17, max(0, min(len(b), 14 + length) - 17))
        else:
            d.proto = "LLC"
            d.info = f"DSAP 0x{b[14]:02x} SSAP 0x{b[15]:02x}" if len(b) >= 16 else "LLC"
        return d

    # -- network layer --
    def ipv4(self, o):
        b, d = self.data, self.d
        if len(b) < o + 20:
            d.info = "Truncated IPv4"
            return
        ihl = (b[o] & 0x0F) * 4
        total, ident = struct.unpack("!HH", b[o + 2:o + 6])
        frag = struct.unpack("!H", b[o + 6:o + 8])[0]
        ttl, proto = b[o + 8], b[o + 9]
        csum = struct.unpack("!H", b[o + 10:o + 12])[0]
        src, dst = ip4_str(b[o + 12:o + 16]), ip4_str(b[o + 16:o + 20])
        d.ip_src, d.ip_dst, d.ip_ttl = src, dst, ttl
        d.src, d.dst = src, dst
        d.protos.append("ip")
        n = self.node(f"Internet Protocol Version 4, Src: {src}, Dst: {dst}", o, ihl)
        n.add("Version: 4", o, 1)
        n.add(f"Header Length: {ihl} bytes ({ihl // 4})", o, 1)
        n.add(f"Differentiated Services Field: 0x{b[o + 1]:02x}", o + 1, 1)
        n.add(f"Total Length: {total}", o + 2, 2)
        n.add(f"Identification: 0x{ident:04x} ({ident})", o + 4, 2)
        df = " Don't fragment" if frag & 0x4000 else ""
        n.add(f"Flags: 0x{frag >> 13:x}{df}, Fragment Offset: {frag & 0x1FFF}", o + 6, 2)
        n.add(f"Time to Live: {ttl}", o + 8, 1)
        n.add(f"Protocol: {IP_PROTOS.get(proto, 'Unknown')} ({proto})", o + 9, 1)
        n.add(f"Header Checksum: 0x{csum:04x}", o + 10, 2)
        n.add(f"Source Address: {src}", o + 12, 4)
        n.add(f"Destination Address: {dst}", o + 16, 4)
        end = min(len(b), o + total) if total >= ihl else len(b)
        if frag & 0x1FFF:
            d.proto, d.info = "IPv4", f"Fragmented IP protocol (proto={proto}, off={(frag & 0x1FFF) * 8})"
            return
        self.transport(proto, o + ihl, end)

    def ipv6(self, o):
        b, d = self.data, self.d
        if len(b) < o + 40:
            d.info = "Truncated IPv6"
            return
        plen, nxt, hop = struct.unpack("!HBB", b[o + 4:o + 8])
        src, dst = ip6_str(b[o + 8:o + 24]), ip6_str(b[o + 24:o + 40])
        d.ip_src, d.ip_dst, d.ip_ttl = src, dst, hop
        d.src, d.dst = src, dst
        d.protos.append("ipv6")
        n = self.node(f"Internet Protocol Version 6, Src: {src}, Dst: {dst}", o, 40)
        n.add(f"Payload Length: {plen}", o + 4, 2)
        n.add(f"Next Header: {IP_PROTOS.get(nxt, nxt)} ({nxt})", o + 6, 1)
        n.add(f"Hop Limit: {hop}", o + 7, 1)
        n.add(f"Source Address: {src}", o + 8, 16)
        n.add(f"Destination Address: {dst}", o + 24, 16)
        off = o + 40
        # skip hop-by-hop / routing / destination option headers
        while nxt in (0, 43, 60) and len(b) >= off + 8:
            nxt, ln = b[off], (b[off + 1] + 1) * 8
            off += ln
        self.transport(nxt, off, min(len(b), o + 40 + plen))

    def arp(self, o):
        b, d = self.data, self.d
        if len(b) < o + 28:
            d.proto, d.info = "ARP", "Truncated ARP"
            return
        op = struct.unpack("!H", b[o + 6:o + 8])[0]
        sha, spa = mac_str(b[o + 8:o + 14]), ip4_str(b[o + 14:o + 18])
        tha, tpa = mac_str(b[o + 18:o + 24]), ip4_str(b[o + 24:o + 28])
        d.proto, d.l4 = "ARP", "arp"
        d.protos.append("arp")
        d.fields.update({"arp.opcode": op, "arp.src.proto_ipv4": spa, "arp.dst.proto_ipv4": tpa,
                         "arp.src.hw_mac": sha})
        if op == 1:
            d.info = f"Who has {tpa}? Tell {spa}" if spa != tpa else f"ARP Announcement for {spa}"
        else:
            d.info = f"{spa} is at {sha}"
        n = self.node(f"Address Resolution Protocol ({'request' if op == 1 else 'reply'})", o, 28)
        n.add("Hardware type: Ethernet (1)", o, 2)
        n.add("Protocol type: IPv4 (0x0800)", o + 2, 2)
        n.add(f"Opcode: {'request' if op == 1 else 'reply'} ({op})", o + 6, 2)
        n.add(f"Sender MAC address: {sha}", o + 8, 6)
        n.add(f"Sender IP address: {spa}", o + 14, 4)
        n.add(f"Target MAC address: {tha}", o + 18, 6)
        n.add(f"Target IP address: {tpa}", o + 24, 4)

    # -- transport layer --
    def transport(self, proto, o, end):
        d = self.d
        if proto == 6:
            self.tcp(o, end)
        elif proto == 17:
            self.udp(o, end)
        elif proto == 1:
            self.icmp(o, end)
        elif proto == 58:
            self.icmp6(o, end)
        else:
            name = IP_PROTOS.get(proto, f"IP proto {proto}")
            d.proto, d.info = name, name
            d.protos.append(name.lower())

    def tcp(self, o, end):
        b, d = self.data, self.d
        if end < o + 20:
            d.proto, d.info = "TCP", "Truncated TCP"
            return
        sp, dp, seq, ack = struct.unpack("!HHII", b[o:o + 12])
        hl = (b[o + 12] >> 4) * 4
        flags = b[o + 13] | ((b[o + 12] & 1) << 8)
        win, csum = struct.unpack("!HH", b[o + 14:o + 18])
        plen = max(0, end - o - hl)
        d.l4, d.sport, d.dport = "tcp", sp, dp
        d.tcp_seq, d.tcp_ack, d.tcp_flags, d.tcp_win, d.payload_len = seq, ack, flags, win, plen
        d.protos.append("tcp")
        d.proto = "TCP"
        fl = ", ".join(flag_names(flags))
        info = f"{sp} → {dp} [{fl}] Seq={seq}"
        if flags & 16:
            info += f" Ack={ack}"
        d.info = info + f" Win={win} Len={plen}"
        n = self.node(f"Transmission Control Protocol, Src Port: {sp}, Dst Port: {dp}, Len: {plen}", o, hl)
        n.add(f"Source Port: {sp}", o, 2)
        n.add(f"Destination Port: {dp}", o + 2, 2)
        n.add(f"[TCP Segment Len: {plen}]")
        n.add(f"Sequence Number (raw): {seq}", o + 4, 4)
        n.add(f"Acknowledgment Number (raw): {ack}", o + 8, 4)
        n.add(f"Header Length: {hl} bytes ({hl // 4})", o + 12, 1)
        f = n.add(f"Flags: 0x{flags:03x} ({fl})", o + 12, 2)
        for name, bit in reversed(TCP_FLAGS):
            f.add(f"{name}: {'Set' if flags & bit else 'Not set'}", o + 13, 1)
        n.add(f"Window: {win}", o + 14, 2)
        n.add(f"Checksum: 0x{csum:04x} [unverified]", o + 16, 2)
        if hl > 20:
            n.add(f"Options: ({hl - 20} bytes)", o + 20, hl - 20)
        p = o + hl
        if plen:
            self.app_tcp(p, end, sp, dp)

    def udp(self, o, end):
        b, d = self.data, self.d
        if end < o + 8:
            d.proto, d.info = "UDP", "Truncated UDP"
            return
        sp, dp, ln, csum = struct.unpack("!HHHH", b[o:o + 8])
        d.l4, d.sport, d.dport = "udp", sp, dp
        d.payload_len = max(0, min(end, o + ln) - o - 8)
        d.protos.append("udp")
        d.proto, d.info = "UDP", f"{sp} → {dp} Len={d.payload_len}"
        n = self.node(f"User Datagram Protocol, Src Port: {sp}, Dst Port: {dp}", o, 8)
        n.add(f"Source Port: {sp}", o, 2)
        n.add(f"Destination Port: {dp}", o + 2, 2)
        n.add(f"Length: {ln}", o + 4, 2)
        n.add(f"Checksum: 0x{csum:04x} [unverified]", o + 6, 2)
        p, pend = o + 8, min(end, o + ln) if ln >= 8 else end
        ports = (sp, dp)
        if 53 in ports or 5353 in ports or 5355 in ports:
            self.dns(p, pend, "MDNS" if 5353 in ports else "LLMNR" if 5355 in ports else "DNS")
        elif 67 in ports or 68 in ports:
            self.dhcp(p, pend)
        elif 1900 in ports:
            self.text_proto(p, pend, "SSDP", "Simple Service Discovery Protocol")
        elif 443 in ports and pend > p:
            self.quic(p, pend)
        elif 123 in ports:
            d.proto, d.info = "NTP", "NTP " + ("client" if dp == 123 else "server")
            d.protos.append("ntp")
            self.node("Network Time Protocol", p, pend - p)
        elif 137 in ports:
            d.proto, d.info = "NBNS", "NetBIOS name service"
            d.protos.append("nbns")
            self.node("NetBIOS Name Service", p, pend - p)

    def icmp(self, o, end):
        b, d = self.data, self.d
        if end < o + 4:
            return
        t, code = b[o], b[o + 1]
        d.l4, d.proto = "icmp", "ICMP"
        d.protos.append("icmp")
        d.fields["icmp.type"] = t
        name = ICMP_TYPES.get(t, f"Type {t}")
        n = self.node("Internet Control Message Protocol", o, end - o)
        n.add(f"Type: {t} ({name})", o, 1)
        n.add(f"Code: {code}", o + 1, 1)
        n.add(f"Checksum: 0x{struct.unpack('!H', b[o + 2:o + 4])[0]:04x}", o + 2, 2)
        if t in (0, 8) and end >= o + 8:
            ident, seq = struct.unpack("!HH", b[o + 4:o + 8])
            d.fields["icmp.seq"] = seq
            d.fields["icmp.ident"] = ident
            n.add(f"Identifier (BE): {ident} (0x{ident:04x})", o + 4, 2)
            n.add(f"Sequence Number (BE): {seq} (0x{seq:04x})", o + 6, 2)
            if end > o + 8:
                n.add(f"Data ({end - o - 8} bytes)", o + 8, end - o - 8)
            d.info = f"{name}  id=0x{ident:04x}, seq={seq}, ttl={d.ip_ttl}"
        else:
            d.info = name + (f" (code {code})" if code else "")

    def icmp6(self, o, end):
        b, d = self.data, self.d
        if end < o + 4:
            return
        t = b[o]
        d.l4, d.proto = "icmpv6", "ICMPv6"
        d.protos.append("icmpv6")
        d.fields["icmpv6.type"] = t
        d.info = ICMP6_TYPES.get(t, f"Type {t}")
        n = self.node("Internet Control Message Protocol v6", o, end - o)
        n.add(f"Type: {d.info} ({t})", o, 1)
        n.add(f"Code: {b[o + 1]}", o + 1, 1)

    # -- application layer --
    def app_tcp(self, p, end, sp, dp):
        b, d = self.data, self.d
        first = b[p]
        if first in (20, 21, 22, 23) and end >= p + 5 and b[p + 1] == 3:
            self.tls(p, end)
        elif b[p:p + 4] in (b"GET ", b"POST", b"HEAD", b"PUT ", b"HTTP", b"DELE", b"OPTI", b"PATC"):
            self.http(p, end)
        elif 53 in (sp, dp) and end >= p + 2:
            self.dns(p + 2, end, "DNS")
        elif sp in PLAINTEXT_PORTS or dp in PLAINTEXT_PORTS:
            port = sp if sp in PLAINTEXT_PORTS else dp
            name = PLAINTEXT_PORTS[port]
            line = b[p:end].split(b"\r\n", 1)[0][:80].decode("latin-1", "replace")
            d.proto = name
            d.protos.append(name.lower())
            d.info = line if line.isprintable() and line else d.info
            self.node(name, p, end - p)
        else:
            name = WELL_KNOWN.get(dp) or WELL_KNOWN.get(sp)
            if name in ("SSH", "SMB", "RDP"):
                d.proto = name
                d.protos.append(name.lower())
                self.node(f"{name} payload", p, end - p)

    def tls(self, p, end):
        b, d = self.data, self.d
        d.protos.append("tls")
        records, infos, ver_name = [], [], "TLS"
        off = p
        top = self.node("Transport Layer Security", p, end - p)
        while off + 5 <= end:
            ctype, ver, ln = b[off], struct.unpack("!H", b[off + 1:off + 3])[0], struct.unpack("!H", b[off + 3:off + 5])[0]
            if ctype not in TLS_CONTENT or (ver >> 8) != 3:
                break
            rlen = min(ln, end - off - 5)
            name = TLS_CONTENT[ctype]
            label = name
            rec = top.add(f"TLS Record Layer: {name}", off, 5 + rlen)
            rec.add(f"Content Type: {name} ({ctype})", off, 1)
            rec.add(f"Version: {TLS_VERSIONS.get(ver, hex(ver))} (0x{ver:04x})", off + 1, 2)
            rec.add(f"Length: {ln}", off + 3, 2)
            if ctype == 22 and rlen >= 4:
                hs = b[off + 5]
                label = TLS_HS.get(hs, f"Handshake type {hs}")
                h = rec.add(f"Handshake Protocol: {label}", off + 5, rlen)
                if hs == 1:
                    sni = self.client_hello(off + 5, off + 5 + rlen, h)
                    if sni:
                        d.fields["tls.handshake.extensions_server_name"] = sni
                        label = f"Client Hello (SNI={sni})"
                    d.fields["tls.handshake.type"] = 1
                    ver_name = "TLSv1.3" if self._offers_tls13 else "TLSv1.2"
                elif hs == 2:
                    d.fields["tls.handshake.type"] = 2
                    ver_name = "TLSv1.3" if b"\x00\x2b\x00\x02\x03\x04" in b[off + 5:off + 5 + rlen] else "TLSv1.2"
            elif ctype == 23:
                rec.add(f"Encrypted Application Data ({rlen} bytes)", off + 5, rlen)
            elif ctype == 21:
                d.fields["tls.alert"] = 1
            infos.append(label)
            records.append(ctype)
            off += 5 + ln
        if not infos:
            d.info = f"{d.sport} → {d.dport} Continuation Data, Len={end - p}"
            d.proto = "TLS"
            return
        # Record headers of TLS 1.2 and 1.3 look the same; only the hellos tell them
        # apart. The capture service relabels the rest of the flow once it has seen one.
        d.proto = ver_name
        dedup = []
        for x in infos:
            if not dedup or dedup[-1] != x:
                dedup.append(x)
        d.info = ", ".join(dedup)

    _offers_tls13 = False

    def client_hello(self, o, end, h) -> str:
        b = self.data
        try:
            p = o + 4
            ver = struct.unpack("!H", b[p:p + 2])[0]
            h.add(f"Version: {TLS_VERSIONS.get(ver, hex(ver))} (0x{ver:04x})", p, 2)
            h.add("Random", p + 2, 32)
            p += 34
            sid = b[p]
            h.add(f"Session ID Length: {sid}", p, 1)
            p += 1 + sid
            cs = struct.unpack("!H", b[p:p + 2])[0]
            h.add(f"Cipher Suites ({cs // 2} suites)", p, 2 + cs)
            p += 2 + cs
            cm = b[p]
            p += 1 + cm
            ext_len = struct.unpack("!H", b[p:p + 2])[0]
            h.add(f"Extensions Length: {ext_len}", p, 2)
            p += 2
            stop = min(end, p + ext_len)
            sni = ""
            while p + 4 <= stop:
                et, el = struct.unpack("!HH", b[p:p + 4])
                if et == 0 and el >= 5:
                    nl = struct.unpack("!H", b[p + 7:p + 9])[0]
                    sni = b[p + 9:p + 9 + nl].decode("ascii", "replace")
                    e = h.add(f"Extension: server_name (len={el}) name={sni}", p, 4 + el)
                    e.add(f"Server Name: {sni}", p + 9, nl)
                elif et == 0x2B:
                    vers = b[p + 5:p + 4 + el]
                    self._offers_tls13 = any(vers[i:i + 2] == b"\x03\x04" for i in range(0, len(vers), 2))
                    h.add(f"Extension: supported_versions (len={el})", p, 4 + el)
                elif et == 0x10:
                    alpn, q, protos = b[p + 6:p + 4 + el], 0, []
                    while q < len(alpn):
                        ln = alpn[q]
                        protos.append(alpn[q + 1:q + 1 + ln].decode("ascii", "replace"))
                        q += 1 + ln
                    h.add(f"Extension: application_layer_protocol_negotiation ({', '.join(protos)})", p, 4 + el)
                else:
                    h.add(f"Extension: type {et} (len={el})", p, 4 + el)
                p += 4 + el
            return sni
        except (IndexError, struct.error):
            return ""

    def http(self, p, end):
        b, d = self.data, self.d
        text = b[p:end]
        head, _, _body = text.partition(b"\r\n\r\n")
        lines = head.split(b"\r\n")
        first = lines[0].decode("latin-1", "replace")
        d.proto = "HTTP"
        d.protos.append("http")
        d.info = first
        if first.startswith("HTTP/"):
            d.fields["http.response"] = 1
            parts = first.split(" ")
            if len(parts) > 1 and parts[1].isdigit():
                d.fields["http.response.code"] = int(parts[1])
        else:
            d.fields["http.request"] = 1
            d.fields["http.request.method"] = first.split(" ")[0]
            if len(first.split(" ")) > 1:
                d.fields["http.request.uri"] = first.split(" ")[1]
        n = self.node("Hypertext Transfer Protocol", p, end - p)
        off = p
        for ln in lines:
            s = ln.decode("latin-1", "replace")
            if s.lower().startswith("host:"):
                d.fields["http.host"] = s[5:].strip()
            n.add(s + "\\r\\n", off, len(ln) + 2)
            off += len(ln) + 2

    def text_proto(self, p, end, name, title):
        b, d = self.data, self.d
        lines = b[p:end].split(b"\r\n")
        d.proto, d.info = name, lines[0].decode("latin-1", "replace")
        d.protos.append(name.lower())
        n = self.node(title, p, end - p)
        off = p
        for ln in lines:
            if ln:
                n.add(ln.decode("latin-1", "replace") + "\\r\\n", off, len(ln) + 2)
            off += len(ln) + 2

    def quic(self, p, end):
        b, d = self.data, self.d
        first = b[p]
        if not first & 0x40:
            return
        d.proto = "QUIC"
        d.protos.append("quic")
        n = self.node("QUIC IETF", p, end - p)
        if first & 0x80 and end >= p + 6:
            ver = struct.unpack("!I", b[p + 1:p + 5])[0]
            ptype = ["Initial", "0-RTT", "Handshake", "Retry"][(first >> 4) & 3]
            dl = b[p + 5]
            dcid = b[p + 6:p + 6 + dl].hex()
            n.add("Header Form: Long Header (1)", p, 1)
            n.add(f"Packet Type: {ptype}", p, 1)
            n.add(f"Version: 0x{ver:08x}", p + 1, 4)
            n.add(f"Destination Connection ID: {dcid}", p + 6, dl)
            d.info = f"{ptype}, DCID={dcid}"
        else:
            n.add("Header Form: Short Header (0)", p, 1)
            n.add("Protected Payload", p + 1, end - p - 1)
            d.info = "Protected Payload"

    def dhcp(self, p, end):
        b, d = self.data, self.d
        d.proto = "DHCP"
        d.protos.append("dhcp")
        n = self.node("Dynamic Host Configuration Protocol", p, end - p)
        kinds = {1: "Discover", 2: "Offer", 3: "Request", 4: "Decline", 5: "ACK", 6: "NAK", 7: "Release", 8: "Inform"}
        d.info = "DHCP"
        q = p + 240
        while q + 2 <= end and b[q] != 255:
            if b[q] == 0:
                q += 1
                continue
            code, ln = b[q], b[q + 1]
            if code == 53 and ln >= 1:
                kind = kinds.get(b[q + 2], str(b[q + 2]))
                d.info = f"DHCP {kind}"
                n.add(f"Option: (53) DHCP Message Type ({kind})", q, 2 + ln)
            elif code == 12:
                host = b[q + 2:q + 2 + ln].decode("latin-1", "replace")
                d.fields["dhcp.option.hostname"] = host
                n.add(f"Option: (12) Host Name: {host}", q, 2 + ln)
            q += 2 + ln

    def dns(self, p, end, kind):
        b, d = self.data, self.d
        if end < p + 12:
            return
        d.proto = kind
        d.protos.append(kind.lower())
        if kind != "DNS":
            d.protos.append("dns")
        tid, flags, qd, an, ns, ar = struct.unpack("!HHHHHH", b[p:p + 12])
        resp = bool(flags & 0x8000)
        rcode = flags & 0xF
        d.fields.update({"dns.id": tid, "dns.flags.response": int(resp), "dns.flags.rcode": rcode})
        n = self.node(f"{'Multicast ' if kind == 'MDNS' else ''}Domain Name System ({'response' if resp else 'query'})",
                      p, end - p)
        n.add(f"Transaction ID: 0x{tid:04x}", p, 2)
        n.add(f"Flags: 0x{flags:04x} {'Standard query response' if resp else 'Standard query'}"
              + (f", error {rcode}" if rcode else ", No error" if resp else ""), p + 2, 2)
        n.add(f"Questions: {qd}", p + 4, 2)
        n.add(f"Answer RRs: {an}", p + 6, 2)
        q = p + 12
        names, answers, parts = [], [], []
        try:
            qn = n.add("Queries", q, 0)
            for _ in range(min(qd, 10)):
                name, nq = self._dns_name(p, q, end)
                qtype = struct.unpack("!H", b[nq:nq + 2])[0]
                tname = DNS_TYPES.get(qtype, str(qtype))
                qn.add(f"{name}: type {tname}", q, nq + 4 - q)
                names.append(name)
                parts.append(f"{tname} {name}")
                q = nq + 4
            an_node = n.add("Answers", q, 0) if an else _NO
            for _ in range(min(an, 20)):
                name, nq = self._dns_name(p, q, end)
                rtype, _cls, ttl, rdlen = struct.unpack("!HHIH", b[nq:nq + 10])
                rd = nq + 10
                tname = DNS_TYPES.get(rtype, str(rtype))
                if rtype == 1 and rdlen == 4:
                    val = ip4_str(b[rd:rd + 4])
                    answers.append(val)
                elif rtype == 28 and rdlen == 16:
                    val = ip6_str(b[rd:rd + 16])
                    answers.append(val)
                elif rtype in (5, 12, 2):
                    val, _ = self._dns_name(p, rd, end)
                else:
                    val = f"{rdlen} bytes"
                an_node.add(f"{name}: type {tname}, {val} (TTL {ttl})", q, rd + rdlen - q)
                parts.append(f"{tname} {val}")
                q = rd + rdlen
        except (IndexError, struct.error, ValueError):
            pass
        if names:
            d.fields["dns.qry.name"] = names[0]
        if answers:
            d.fields["dns.a"] = answers
        label = "Standard query response" if resp else "Standard query"
        d.info = f"{label} 0x{tid:04x} " + " ".join(parts[:4]) + (" ..." if len(parts) > 4 else "")

    def _dns_name(self, base, q, end, depth=0):
        b, labels, jumped, nxt = self.data, [], False, q
        while True:
            if q >= end or depth > 10:
                raise ValueError("bad name")
            ln = b[q]
            if ln == 0:
                q += 1
                break
            if ln & 0xC0 == 0xC0:
                ptr = ((ln & 0x3F) << 8) | b[q + 1]
                if not jumped:
                    nxt = q + 2
                jumped, q, depth = True, base + ptr, depth + 1
                continue
            labels.append(b[q + 1:q + 1 + ln].decode("latin-1", "replace"))
            q += 1 + ln
        return ".".join(labels) or "<Root>", (nxt if jumped else q)


def dissect(data: bytes, tree: bool = False) -> Dissection:
    """Dissect an Ethernet frame. Never raises; unknown data stays undecoded."""
    dis = _Dissector(bytes(data), tree)
    try:
        return dis.run()
    except Exception as exc:          # a malformed frame must not stop the capture
        d = dis.d
        d.info = (d.info + " " if d.info else "") + f"[Malformed: {type(exc).__name__}]"
        return d
