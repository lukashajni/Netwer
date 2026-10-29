"""Wireshark-style display filters for the Packet Capture page.

Supports protocol names (tcp, dns, tls ...), fields compared with
== != > < >= <= contains (or eq ne gt lt ge le), and/or/not (&& || !) and
parentheses, e.g.  tls && ip.addr == 140.82.121.4  or  !(arp || mdns).
"""

import re


class FilterError(ValueError):
    pass


PROTOCOLS = {"eth", "vlan", "llc", "stp", "ip", "ipv6", "arp", "tcp", "udp", "icmp", "icmpv6", "igmp", "dns",
             "mdns", "llmnr", "nbns", "dhcp", "ntp", "tls", "quic", "http", "ssdp", "ftp", "telnet", "pop3",
             "imap", "ssh", "smb", "rdp"}


def _tcp(p, value):
    return value if p.dis.l4 == "tcp" else None


def _udp(p, value):
    return value if p.dis.l4 == "udp" else None


def _flag(bit):
    return lambda p: _tcp(p, int(bool((p.dis.tcp_flags or 0) & bit)))


def _ports(p):
    return [p.dis.sport, p.dis.dport]


FIELDS = {
    "frame.number": lambda p: p.no,
    "frame.len": lambda p: p.dis.length,
    "frame.time_relative": lambda p: p.rel,
    "eth.src": lambda p: p.dis.smac,
    "eth.dst": lambda p: p.dis.dmac,
    "eth.addr": lambda p: [p.dis.smac, p.dis.dmac],
    "ip.src": lambda p: p.dis.ip_src,
    "ip.dst": lambda p: p.dis.ip_dst,
    "ip.addr": lambda p: [p.dis.ip_src, p.dis.ip_dst] if p.dis.ip_src else None,
    "ip.ttl": lambda p: p.dis.ip_ttl,
    "tcp.port": lambda p: _tcp(p, _ports(p)),
    "tcp.srcport": lambda p: _tcp(p, p.dis.sport),
    "tcp.dstport": lambda p: _tcp(p, p.dis.dport),
    "tcp.len": lambda p: _tcp(p, p.dis.payload_len),
    "tcp.window_size": lambda p: _tcp(p, p.dis.tcp_win),
    "tcp.stream": lambda p: _tcp(p, p.stream),
    "tcp.flags.fin": _flag(1),
    "tcp.flags.syn": _flag(2),
    "tcp.flags.reset": _flag(4),
    "tcp.flags.push": _flag(8),
    "tcp.flags.ack": _flag(16),
    "tcp.analysis.flags": lambda p: 1 if p.tags else None,
    "tcp.analysis.retransmission": lambda p: 1 if "retrans" in p.tags else None,
    "tcp.analysis.duplicate_ack": lambda p: 1 if "dupack" in p.tags else None,
    "tcp.analysis.zero_window": lambda p: 1 if "zerowin" in p.tags else None,
    "udp.port": lambda p: _udp(p, _ports(p)),
    "udp.srcport": lambda p: _udp(p, p.dis.sport),
    "udp.dstport": lambda p: _udp(p, p.dis.dport),
    "udp.stream": lambda p: _udp(p, p.stream),
    "port": lambda p: _ports(p) if p.dis.sport is not None else None,
}
# Everything the dissector stores in Dissection.fields is filterable too.
DISSECTOR_FIELDS = {"dns.qry.name", "dns.a", "dns.id", "dns.flags.response", "dns.flags.rcode",
                    "tls.handshake.extensions_server_name", "tls.handshake.type", "tls.alert", "http.host",
                    "http.request", "http.response", "http.response.code", "http.request.method",
                    "http.request.uri", "icmp.type", "icmp.seq", "icmpv6.type", "arp.opcode",
                    "arp.src.proto_ipv4", "arp.dst.proto_ipv4", "arp.src.hw_mac", "dhcp.option.hostname"}
ALL_NAMES = sorted(PROTOCOLS | set(FIELDS) | DISSECTOR_FIELDS)

_OPS = {"==": "eq", "eq": "eq", "!=": "ne", "ne": "ne", ">": "gt", "gt": "gt", "<": "lt", "lt": "lt",
        ">=": "ge", "ge": "ge", "<=": "le", "le": "le", "contains": "contains", "matches": "matches"}
_TOKEN = re.compile(r'\s*(\(|\)|&&|\|\||==|!=|>=|<=|>|<|!|"(?:[^"\\]|\\.)*"|[A-Za-z0-9_.:\-/]+)\s*')


def _getter(name):
    if name in FIELDS:
        return FIELDS[name]
    if name in DISSECTOR_FIELDS:
        return lambda p: p.dis.fields.get(name)
    return None


def _tokenize(text):
    out, pos = [], 0
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m or m.end() == pos:
            if text[pos:].strip():
                raise FilterError(f'Unexpected "{text[pos:].strip()[0]}" at column {pos + 1}')
            break
        out.append(m.group(1))
        pos = m.end()
    return out


def _number(v):
    try:
        return int(v, 0)
    except ValueError:
        try:
            return float(v)
        except ValueError:
            return None


def compile_filter(text: str):
    """Return a predicate packet -> bool. Raises FilterError with a readable message."""
    text = (text or "").strip()
    if not text:
        return lambda p: True
    toks = _tokenize(text)
    pos = [0]

    def peek():
        return toks[pos[0]] if pos[0] < len(toks) else None

    def take():
        t = peek()
        pos[0] += 1
        return t

    def or_expr():
        left = and_expr()
        while peek() in ("||", "or"):
            take()
            a, b = left, and_expr()
            left = lambda p, a=a, b=b: a(p) or b(p)
        return left

    def and_expr():
        left = unary()
        while peek() in ("&&", "and"):
            take()
            a, b = left, unary()
            left = lambda p, a=a, b=b: a(p) and b(p)
        return left

    def unary():
        t = peek()
        if t in ("!", "not"):
            take()
            f = unary()
            return lambda p: not f(p)
        if t == "(":
            take()
            f = or_expr()
            if take() != ")":
                raise FilterError("Missing closing parenthesis")
            return f
        return comparison()

    def comparison():
        name = take()
        if name is None:
            raise FilterError("The filter is incomplete")
        key = name.lower()
        is_proto, get = key in PROTOCOLS, _getter(key)
        if not is_proto and get is None:
            raise FilterError(f'"{name}" is neither a field nor a protocol name')
        op = _OPS.get((peek() or "").lower())
        if op is None:
            if is_proto:
                return lambda p: key in p.dis.protos
            return lambda p: get(p) is not None
        if get is None:
            raise FilterError(f'"{name}" is a protocol. Compare one of its fields instead')
        take()
        raw = take()
        if raw is None:
            raise FilterError(f'"{name}" needs a value to compare with')
        if raw.startswith('"'):
            raw = raw[1:-1].replace('\\"', '"')
        num = _number(raw)
        low = raw.lower()
        if op in ("gt", "lt", "ge", "le") and num is None:
            raise FilterError(f'"{raw}" is not a number')
        rx = None
        if op == "matches":
            try:
                rx = re.compile(raw, re.IGNORECASE)
            except re.error as exc:
                raise FilterError(f"Bad regular expression: {exc}") from None

        def values(p):
            v = get(p)
            if v is None:
                return []
            return [x for x in (v if isinstance(v, (list, tuple)) else [v]) if x is not None]

        def eq(x):
            if num is not None and isinstance(x, (int, float)):
                return x == num
            return str(x).lower() == low

        if op == "ne":
            return lambda p: bool(values(p)) and not any(eq(x) for x in values(p))
        test = {
            "eq": eq,
            "contains": lambda x: low in str(x).lower(),
            "matches": lambda x: bool(rx.search(str(x))),
            "gt": lambda x: isinstance(x, (int, float)) and x > num,
            "lt": lambda x: isinstance(x, (int, float)) and x < num,
            "ge": lambda x: isinstance(x, (int, float)) and x >= num,
            "le": lambda x: isinstance(x, (int, float)) and x <= num,
        }[op]
        return lambda p: any(test(x) for x in values(p))

    pred = or_expr()
    if pos[0] < len(toks):
        raise FilterError(f'Unexpected "{toks[pos[0]]}"')
    return pred
