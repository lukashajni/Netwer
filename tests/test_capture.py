"""Tests for the Packet Capture core: dissector, display filters, TCP analysis, pcap files."""
import json
import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.capture import CaptureService  # noqa: E402
from core.display_filter import FilterError, compile_filter  # noqa: E402
from core.packet_dissect import dissect  # noqa: E402

PC_MAC, GW_MAC = bytes.fromhex("a8a1593c7e12"), bytes.fromhex("488f5a210bc4")
PC, GW = "192.168.88.253", "192.168.88.1"


def _ip(a):
    return bytes(int(x) for x in a.split("."))


def ipv4(src, dst, proto, payload, ttl=64):
    hdr = struct.pack("!BBHHHBBH4s4s", 0x45, 0, 20 + len(payload), 1, 0x4000, ttl, proto, 0, _ip(src), _ip(dst))
    return hdr + payload


def eth(payload, src=PC_MAC, dst=GW_MAC, etype=0x0800):
    return dst + src + struct.pack("!H", etype) + payload


def tcp(sport, dport, seq, ack, flags, payload=b"", win=1026):
    return struct.pack("!HHIIBBHHH", sport, dport, seq, ack, 0x50, flags, win, 0, 0) + payload


def udp(sport, dport, payload):
    return struct.pack("!HHHH", sport, dport, 8 + len(payload), 0) + payload


def dns_query(tid, name):
    q = b"".join(bytes([len(p)]) + p.encode() for p in name.split(".")) + b"\x00"
    return struct.pack("!HHHHHH", tid, 0x0100, 1, 0, 0, 0) + q + struct.pack("!HH", 1, 1)


def dns_answer(tid, name, ip):
    q = b"".join(bytes([len(p)]) + p.encode() for p in name.split(".")) + b"\x00"
    ans = b"\xc0\x0c" + struct.pack("!HHIH", 1, 1, 300, 4) + _ip(ip)
    return struct.pack("!HHHHHH", tid, 0x8180, 1, 1, 0, 0) + q + struct.pack("!HH", 1, 1) + ans


def client_hello(sni):
    name = sni.encode()
    ext = struct.pack("!HHHBH", 0, len(name) + 5, len(name) + 3, 0, len(name)) + name
    ext += bytes.fromhex("002b0005040304030300100005000302683200")
    body = b"\x03\x03" + bytes(32) + b"\x00" + b"\x00\x02\x13\x01" + b"\x01\x00" + struct.pack("!H", len(ext)) + ext
    hs = b"\x01" + struct.pack("!I", len(body))[1:] + body
    return b"\x16\x03\x01" + struct.pack("!H", len(hs)) + hs


def frame_tcp(src, dst, sport, dport, seq, ack, flags, payload=b""):
    up = src == PC
    return eth(ipv4(src, dst, 6, tcp(sport, dport, seq, ack, flags, payload)),
               src=PC_MAC if up else GW_MAC, dst=GW_MAC if up else PC_MAC)


class TestDissector(unittest.TestCase):
    def test_dns_query_and_answer(self):
        q = dissect(eth(ipv4(PC, GW, 17, udp(50000, 53, dns_query(0x1A2B, "github.com")))))
        self.assertEqual(q.proto, "DNS")
        self.assertEqual(q.fields["dns.qry.name"], "github.com")
        self.assertIn("Standard query 0x1a2b A github.com", q.info)
        a = dissect(eth(ipv4(GW, PC, 17, udp(53, 50000, dns_answer(0x1A2B, "github.com", "140.82.121.4"))),
                        src=GW_MAC, dst=PC_MAC))
        self.assertEqual(a.fields["dns.a"], ["140.82.121.4"])
        self.assertEqual(a.fields["dns.flags.response"], 1)

    def test_tls_client_hello_sni_and_byte_range(self):
        data = frame_tcp(PC, "140.82.121.4", 51234, 443, 1000, 2000, 0x18, client_hello("github.com"))
        d = dissect(data, tree=True)
        self.assertEqual(d.proto, "TLSv1.3")
        self.assertEqual(d.fields["tls.handshake.extensions_server_name"], "github.com")
        self.assertEqual(d.info, "Client Hello (SNI=github.com)")

        def find(nodes):
            for n in nodes:
                if n.title == "Server Name: github.com":
                    return n
                hit = find(n.children)
                if hit:
                    return hit
        node = find(d.tree)
        self.assertIsNotNone(node)
        self.assertEqual(data[node.off:node.off + node.length], b"github.com")

    def test_tcp_fields_offsets(self):
        data = frame_tcp(PC, "140.82.121.4", 51234, 443, 7, 9, 0x02)
        d = dissect(data, tree=True)
        self.assertEqual((d.sport, d.dport, d.tcp_flags), (51234, 443, 2))
        self.assertIn("[SYN]", d.info)
        tcp_node = d.tree[-1]
        sport = tcp_node.children[0]
        self.assertEqual(struct.unpack("!H", data[sport.off:sport.off + 2])[0], 51234)

    def test_arp_and_http(self):
        arp = struct.pack("!HHBBH", 1, 0x0800, 6, 4, 1) + GW_MAC + _ip(GW) + bytes(6) + _ip(PC)
        d = dissect(eth(arp, src=GW_MAC, dst=b"\xff" * 6, etype=0x0806))
        self.assertEqual(d.info, f"Who has {PC}? Tell {GW}")
        req = b"GET / HTTP/1.1\r\nHost: neverssl.com\r\n\r\n"
        h = dissect(frame_tcp(PC, "34.223.124.45", 51000, 80, 1, 1, 0x18, req))
        self.assertEqual(h.proto, "HTTP")
        self.assertEqual(h.fields["http.host"], "neverssl.com")

    def test_garbage_never_raises(self):
        for blob in (b"", b"\x00" * 13, os.urandom(200), eth(b"\x45" + b"\x00" * 5)):
            dissect(blob, tree=True)


class _P:
    def __init__(self, data, no=1, tags=()):
        self.dis, self.no, self.rel, self.tags, self.stream = dissect(data), no, 0.0, set(tags), 0


class TestDisplayFilter(unittest.TestCase):
    def setUp(self):
        self.dns = _P(eth(ipv4(PC, GW, 17, udp(50000, 53, dns_query(1, "www.google.com")))))
        self.tls = _P(frame_tcp(PC, "140.82.121.4", 51234, 443, 1, 1, 0x18, client_hello("github.com")))
        self.bad = _P(frame_tcp("151.101.1.140", PC, 443, 51300, 5, 5, 0x10, b"x" * 100), tags={"retrans"})

    def match(self, expr):
        f = compile_filter(expr)
        return [name for name, p in (("dns", self.dns), ("tls", self.tls), ("bad", self.bad)) if f(p)]

    def test_protocols_and_logic(self):
        self.assertEqual(self.match("dns"), ["dns"])
        self.assertEqual(self.match("tcp && !tls"), ["bad"])
        self.assertEqual(self.match("tls or dns"), ["dns", "tls"])
        self.assertEqual(self.match(""), ["dns", "tls", "bad"])

    def test_fields(self):
        self.assertEqual(self.match("ip.addr == 140.82.121.4"), ["tls"])
        self.assertEqual(self.match('dns.qry.name contains "google"'), ["dns"])
        self.assertEqual(self.match("tls.handshake.extensions_server_name == github.com"), ["tls"])
        self.assertEqual(self.match("tcp.port == 443 && frame.len > 100"), ["tls", "bad"])
        self.assertEqual(self.match("tcp.analysis.flags"), ["bad"])
        self.assertEqual(self.match("ip.src != 192.168.88.253"), ["bad"])

    def test_errors_are_readable(self):
        for expr, part in (("tcp &&", "incomplete"), ("foo.bar", "neither"), ("(dns", "parenthesis"),
                           ("frame.len > big", "not a number"), ("tcp == 1", "is a protocol")):
            with self.assertRaises(FilterError) as cm:
                compile_filter(expr)
            self.assertIn(part, str(cm.exception))


class TestCaptureService(unittest.TestCase):
    def build(self):
        s = CaptureService()
        s.iface_ip = PC
        srv = "151.101.1.140"
        s.add_frame(eth(ipv4(PC, GW, 17, udp(50000, 53, dns_query(7, "www.reddit.com")))), 1.000)
        s.add_frame(eth(ipv4(GW, PC, 17, udp(53, 50000, dns_answer(7, "www.reddit.com", srv))),
                        src=GW_MAC, dst=PC_MAC), 1.015)
        s.add_frame(frame_tcp(PC, srv, 51300, 443, 100, 0, 0x02), 1.02)
        s.add_frame(frame_tcp(srv, PC, 443, 51300, 500, 101, 0x12), 1.04)
        s.add_frame(frame_tcp(PC, srv, 51300, 443, 101, 501, 0x10), 1.05)
        s.add_frame(frame_tcp(srv, PC, 443, 51300, 501, 101, 0x10, b"a" * 1000), 1.06)
        s.add_frame(frame_tcp(srv, PC, 443, 51300, 1501, 101, 0x10, b"b" * 1000), 1.07)
        s.add_frame(frame_tcp(PC, srv, 51300, 443, 101, 1501, 0x10), 1.08)
        s.add_frame(frame_tcp(PC, srv, 51300, 443, 101, 1501, 0x10), 1.09)       # duplicate ack
        s.add_frame(frame_tcp(srv, PC, 443, 51300, 1501, 101, 0x10, b"b" * 1000), 1.30)  # resend
        s.add_frame(frame_tcp(PC, "34.223.124.45", 51400, 80, 1, 1, 0x18,
                              b"GET / HTTP/1.1\r\nHost: neverssl.com\r\n\r\n"), 1.4)
        return s

    def test_analysis(self):
        s = self.build()
        tags = {p.no: p.tags for p in s.packets if p.tags}
        self.assertEqual(tags, {9: {"dupack"}, 10: {"retrans"}})
        self.assertEqual(s.names["151.101.1.140"], "www.reddit.com")
        self.assertAlmostEqual(s.dns_times[0]["ms"], 15, delta=0.5)
        self.assertIn(("HTTP", "neverssl.com"), s.plaintext)
        kinds = [i["text"] for i in s.insights()]
        self.assertTrue(any("retransmission" in k for k in kinds))
        self.assertTrue(any("Unencrypted HTTP" in k for k in kinds))

    def test_summary_is_json_and_names_hosts(self):
        s = self.build()
        sm = s.summary(selected=10)
        json.dumps(sm)
        self.assertEqual(sm["tcp_problems"]["by_host"][0]["host"], "www.reddit.com")
        self.assertEqual(sm["selected_packet"]["tcp_analysis"], ["retrans"])
        self.assertIn("Transmission Control Protocol", sm["selected_packet"]["layers"])

    def test_pcap_round_trip(self):
        s = self.build()
        path = os.path.join(tempfile.mkdtemp(), "t.pcap")
        s.save_pcap(path)
        frames = [p.data for p in s.packets]
        t = CaptureService()
        self.assertEqual(t.load_file(path), len(frames))
        self.assertEqual([p.data for p in t.packets], frames)
        self.assertEqual(t.iface_ip, PC)
        self.assertAlmostEqual(t.packets[1].rel, 0.015, places=5)


class TestAssistantTools(unittest.TestCase):
    def test_get_packet_and_filter_action(self):
        from core import ai_tools, capture
        svc = capture.get_capture_service()
        svc.reset()
        svc.add_frame(frame_tcp(PC, "140.82.121.4", 51234, 443, 1, 1, 0x18, client_hello("github.com")), 5.0)
        tools = ai_tools.AppTools({"capture": svc.summary()})
        detail = json.loads(tools.call("get_packet", {"number": 1}))
        self.assertIn("github.com", detail["layers"])
        self.assertIn("error", json.loads(tools.call("get_packet", {"number": 99})))
        self.assertTrue(json.loads(tools.call("suggest_action", {"label": "Show TLS", "target": "filter:tls"}))["ok"])
        self.assertIn("error", json.loads(tools.call("suggest_action", {"label": "x", "target": "filter:tls &&"})))
        self.assertEqual(json.loads(tools.call("get_capture", {}))["packets"], 1)
        svc.reset()


if __name__ == "__main__":
    unittest.main()
