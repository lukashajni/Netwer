"""Live packet capture for the Packet Capture page."""
import ipaddress
import struct
import threading
import time
from collections import Counter, deque

from core.packet_dissect import PLAINTEXT_PORTS, dissect

MAX_PACKETS = 200_000
PCAP_MAGIC = 0xA1B2C3D4
LINKTYPE_ETHERNET = 1


class CapturedPacket:
    __slots__ = ("no", "ts", "rel", "data", "dis", "tags", "stream")

    def __init__(self, no, ts, rel, data, dis):
        self.no, self.ts, self.rel, self.data, self.dis = no, ts, rel, data, dis
        self.tags = set()
        self.stream = None

    def tree(self):
        return dissect(self.data, tree=True).tree


def _is_local(ip):
    try:
        a = ipaddress.ip_address(ip)
        return a.is_private or a.is_link_local or a.is_loopback
    except ValueError:
        return False


def _is_unicast(ip):
    try:
        a = ipaddress.ip_address(ip)
        return not (a.is_multicast or ip.endswith(".255") or a.is_unspecified)
    except ValueError:
        return False


def capture_backend():
    try:
        from scapy.all import conf
    except Exception:
        return False, "Live capture needs scapy. Install it with:  pip install scapy"
    import sys
    if sys.platform == "win32":
        if not conf.use_pcap:
            return False, "Live capture needs Npcap. Install it from npcap.com, then restart Netwer."
    return True, ""


def list_interfaces():
    try:
        from scapy.all import get_working_ifaces
        out = []
        for i in get_working_ifaces():
            ip = getattr(i, "ip", "") or ""
            out.append({"name": i.name, "description": getattr(i, "description", "") or "", "ip": ip})
        out.sort(key=lambda x: (not x["ip"] or x["ip"].startswith("127."), x["name"].lower()))
        return out
    except Exception:
        return []


class CaptureService:
    def __init__(self):
        self._lock = threading.Lock()
        self._sniffer = None
        self.iface = ""
        self.iface_ip = ""
        self.error = ""
        self.view_filter = ""
        self.displayed = 0
        self.selected_no = None
        self.reset()

    def reset(self):
        with getattr(self, "_lock", threading.Lock()):
            self.packets = []
            self.start_ts = None
            self.total_bytes = 0
            self.truncated = False
            self._flows = {}
            self._streams = {}
            self._tls_ver = {}
            self.conv = {}
            self.names = {}
            self.proto_mix = Counter()
            self.per_sec = Counter()
            self.per_sec_up = Counter()
            self.per_sec_down = Counter()
            self.retrans = self.dupacks = self.zerowin = 0
            self.plaintext = {}
            self._dns_pending = {}
            self.dns_times = deque(maxlen=500)
            self._icmp_pending = {}
            self.ping_rtts = deque(maxlen=200)
            self.lan_macs = {}
            self.sni = Counter()

    @property
    def running(self):
        return self._sniffer is not None

    def count(self):
        return len(self.packets)

    def since(self, index):
        with self._lock:
            return self.packets[index:]

    def packet(self, no):
        if 1 <= (no or 0) <= len(self.packets):
            return self.packets[no - 1]
        return None

    def start(self, iface, bpf=""):
        ok, msg = capture_backend()
        if not ok:
            raise RuntimeError(msg)
        self.stop()
        self.reset()
        self.iface, self.error = iface, ""
        self.iface_ip = next((i["ip"] for i in list_interfaces() if i["name"] == iface), "")
        from scapy.all import AsyncSniffer
        self._sniffer = AsyncSniffer(iface=iface, prn=self._on_scapy, store=False, filter=bpf or None)
        self._sniffer.start()

    def stop(self):
        s, self._sniffer = self._sniffer, None
        if s is not None:
            try:
                s.stop(join=True)
            except Exception:
                pass

    def poll_error(self):
        s = self._sniffer
        if s is None:
            return ""
        exc = getattr(s, "exception", None)
        thread = getattr(s, "thread", None)
        if exc is not None or (thread is not None and not thread.is_alive()):
            self._sniffer = None
            self.error = str(exc or "The capture stopped unexpectedly.")
            return self.error
        return ""

    def _on_scapy(self, pkt):
        try:
            from scapy.layers.inet import IP
            from scapy.layers.inet6 import IPv6
            from scapy.layers.l2 import Ether
            if isinstance(pkt, Ether):
                data = bytes(pkt)
            elif IP in pkt or IPv6 in pkt:
                # loopback has no ethernet header, fake one
                layer = pkt[IP] if IP in pkt else pkt[IPv6]
                etype = 0x0800 if IP in pkt else 0x86DD
                data = b"\x00" * 12 + struct.pack("!H", etype) + bytes(layer)
            else:
                return
            self.add_frame(data, float(pkt.time))
        except Exception:
            pass

    def add_frame(self, data, ts=None):
        ts = time.time() if ts is None else ts
        if len(self.packets) >= MAX_PACKETS:
            self.truncated = True
            return None
        dis = dissect(data)
        with self._lock:
            if self.start_ts is None:
                self.start_ts = ts
            p = CapturedPacket(len(self.packets) + 1, ts, ts - self.start_ts, data, dis)
            self._analyze(p)
            self.packets.append(p)
        if self.truncated and self._sniffer is not None:
            threading.Thread(target=self.stop, daemon=True).start()
        return p

    def _analyze(self, p):
        d = p.dis
        self.total_bytes += d.length
        sec = int(p.rel)
        self.per_sec[sec] += 1
        self.proto_mix[_mix_bucket(d)] += 1

        local = self.iface_ip or ""
        if d.ip_src and d.ip_dst:
            if d.ip_src == local or (not local and _is_local(d.ip_src) and not _is_local(d.ip_dst)):
                remote, up = d.ip_dst, True
            elif d.ip_dst == local or (not local and _is_local(d.ip_dst) and not _is_local(d.ip_src)):
                remote, up = d.ip_src, False
            else:
                remote, up = None, False
            (self.per_sec_up if up else self.per_sec_down)[sec] += d.length
            if remote and _is_unicast(remote):
                c = self.conv.get(remote)
                if c is None:
                    c = self.conv[remote] = {"bytes": 0, "packets": 0, "up": 0, "down": 0, "tcp": 0, "retrans": 0,
                                             "protos": Counter()}
                c["bytes"] += d.length
                c["packets"] += 1
                c["up" if up else "down"] += d.length
                c["protos"][d.proto] += 1
                if d.l4 == "tcp":
                    c["tcp"] += 1
            if _is_local(d.ip_src) and d.ip_src != local and _is_unicast(d.ip_src) and d.smac:
                self.lan_macs.setdefault(d.smac, {"ip": d.ip_src, "first": p.no})
        if d.l4 == "arp" and d.fields.get("arp.src.proto_ipv4") not in ("0.0.0.0", local):
            self.lan_macs.setdefault(d.smac, {"ip": d.fields.get("arp.src.proto_ipv4"), "first": p.no})

        if d.l4 in ("tcp", "udp"):
            a, b = (d.ip_src, d.sport), (d.ip_dst, d.dport)
            key = (d.l4,) + (a + b if a <= b else b + a)
            p.stream = self._streams.setdefault(key, len(self._streams))
        if d.l4 == "tcp":
            self._tcp_analysis(p)
            if d.proto in ("TLSv1.2", "TLSv1.3") and d.fields.get("tls.handshake.type") == 2:
                self._tls_ver[p.stream] = d.proto
            elif d.proto in ("TLS", "TLSv1.2") and p.stream in self._tls_ver:
                d.proto = self._tls_ver[p.stream]

        port = d.dport if d.dport in PLAINTEXT_PORTS else d.sport if d.sport in PLAINTEXT_PORTS else None
        if port and d.payload_len and d.proto in ("HTTP", "FTP", "Telnet", "POP3", "IMAP"):
            host = d.fields.get("http.host") or (d.ip_dst if d.dport == port else d.ip_src)
            e = self.plaintext.setdefault((d.proto, host), {"packets": 0, "first": p.no})
            e["packets"] += 1

        sni = d.fields.get("tls.handshake.extensions_server_name")
        if sni:
            self.sni[sni] += 1
            self.names.setdefault(d.ip_dst, sni)
        if "dns" in d.protos and "mdns" not in d.protos and d.sport is not None:
            if not d.fields.get("dns.flags.response"):
                self._dns_pending[(d.fields.get("dns.id"), d.sport)] = (p.rel, d.fields.get("dns.qry.name"))
            else:
                q = self._dns_pending.pop((d.fields.get("dns.id"), d.dport), None)
                if q:
                    self.dns_times.append({"name": q[1], "ms": (p.rel - q[0]) * 1000, "no": p.no})
                for ip in d.fields.get("dns.a") or []:
                    if d.fields.get("dns.qry.name"):
                        self.names[ip] = d.fields["dns.qry.name"]
        if d.l4 == "icmp" and "icmp.seq" in d.fields:
            k = (d.fields.get("icmp.ident"), d.fields["icmp.seq"])
            if d.fields.get("icmp.type") == 8:
                self._icmp_pending[k] = (p.rel, d.ip_dst)
            elif d.fields.get("icmp.type") == 0 and k in self._icmp_pending:
                t0, host = self._icmp_pending.pop(k)
                self.ping_rtts.append({"host": host, "ms": (p.rel - t0) * 1000})

    def _tcp_analysis(self, p):
        d = p.dis
        fwd = (d.ip_src, d.sport, d.ip_dst, d.dport)
        rev = (d.ip_dst, d.dport, d.ip_src, d.sport)
        f = self._flows.setdefault(fwd, {"end": None, "ack": None, "win": None})
        r = self._flows.get(rev)
        flags, seq, plen = d.tcp_flags, d.tcp_seq, d.payload_len
        if flags & 2:
            f["end"] = (seq + 1) & 0xFFFFFFFF
        elif plen or flags & 1:
            end = (seq + plen + (flags & 1)) & 0xFFFFFFFF
            keepalive = plen <= 1 and f["end"] is not None and seq == (f["end"] - 1) & 0xFFFFFFFF
            # ends before what we already sent -> resend
            behind = f["end"] is not None and ((f["end"] - end) & 0xFFFFFFFF) < 0x80000000
            if plen and behind and not keepalive:
                p.tags.add("retrans")
                self.retrans += 1
                remote = d.ip_src if d.ip_dst == self.iface_ip else d.ip_dst
                if remote in self.conv:
                    self.conv[remote]["retrans"] += 1
            else:
                f["end"] = end
        if flags & 16 and not plen and not flags & 7:
            outstanding = r is not None and r["end"] is not None and r["end"] != d.tcp_ack
            if f["ack"] == d.tcp_ack and f["win"] == d.tcp_win and outstanding:
                p.tags.add("dupack")
                self.dupacks += 1
        if d.tcp_win == 0 and not flags & 6:
            p.tags.add("zerowin")
            self.zerowin += 1
        if flags & 16:
            f["ack"], f["win"] = d.tcp_ack, d.tcp_win

    def save_pcap(self, path, packets=None):
        packets = self.packets if packets is None else packets
        with open(path, "wb") as fh:
            fh.write(struct.pack("<IHHiIII", PCAP_MAGIC, 2, 4, 0, 0, 65535, LINKTYPE_ETHERNET))
            for p in packets:
                sec = int(p.ts)
                usec = int(round((p.ts - sec) * 1_000_000))
                fh.write(struct.pack("<IIII", sec, min(usec, 999_999), len(p.data), len(p.data)))
                fh.write(p.data)
        return len(packets)

    def load_file(self, path):
        self.stop()
        self.reset()
        self.iface, self.iface_ip, self.error = path, "", ""
        frames = list(_read_pcap(path))
        if frames and len(frames[0][1]) >= 34:
            # our ip = the private address that talks the most
            c = Counter()
            for _, data in frames[:2000]:
                dd = dissect(data)
                for ip in (dd.ip_src, dd.ip_dst):
                    if ip and ":" not in ip and _is_local(ip) and _is_unicast(ip):
                        c[ip] += 1
            self.iface_ip = c.most_common(1)[0][0] if c else ""
        for ts, data in frames:
            self.add_frame(data, ts)
        return len(frames)

    def host(self, ip):
        return self.names.get(ip) or ip

    def insights(self):
        out = []
        if self.retrans:
            worst = max(self.conv.items(), key=lambda kv: kv[1]["retrans"], default=(None, None))
            host = self.host(worst[0]) if worst[0] else ""
            out.append({"severity": "warning", "text": f"{self.retrans} TCP retransmission{'s' if self.retrans != 1 else ''}",
                        "detail": host, "filter": "tcp.analysis.flags",
                        "question": "Why are there TCP retransmissions in my capture, and is it a problem?"})
        for (proto, host), e in list(self.plaintext.items())[:2]:
            out.append({"severity": "danger", "text": f"Unencrypted {proto}", "detail": host,
                        "filter": proto.lower(), "frame": e["first"],
                        "question": f"Explain packet #{e['first']}. It is unencrypted {proto} to {host}."})
        if self.lan_macs:
            n = len(self.lan_macs)
            out.append({"severity": "info", "text": f"{n} LAN device{'s' if n != 1 else ''} seen",
                        "detail": ", ".join(v["ip"] for v in list(self.lan_macs.values())[:3] if v["ip"]),
                        "filter": "arp || mdns || ssdp || llmnr || nbns",
                        "question": "Which other devices on my network show up in the capture, and what are they doing?"})
        if self.dns_times:
            avg = sum(x["ms"] for x in self.dns_times) / len(self.dns_times)
            out.append({"severity": "success" if avg < 80 else "warning", "text": f"DNS answers in {avg:.0f} ms avg",
                        "detail": "", "filter": "dns && !mdns", "question": "How fast is my DNS according to the capture?"})
        if self.zerowin:
            out.append({"severity": "warning", "text": f"{self.zerowin} zero-window", "detail": "receiver full",
                        "filter": "tcp.analysis.zero_window", "question": "What do the TCP zero window packets mean?"})
        return out

    def summary(self, selected=None):
        n = len(self.packets)
        dur = self.packets[-1].rel if n else 0
        mix_total = sum(self.proto_mix.values()) or 1
        top = sorted(self.conv.items(), key=lambda kv: -kv[1]["bytes"])[:10]
        tcp_hosts = [(ip, c) for ip, c in self.conv.items() if c["retrans"]]
        tcp_hosts.sort(key=lambda kv: -kv[1]["retrans"])
        out = {
            "state": "capturing" if self.running else ("stopped" if n else "empty"),
            "source": self.iface, "this_computer_ip": self.iface_ip,
            "packets": n, "bytes": self.total_bytes, "duration_s": round(dur, 1),
            "truncated_at_limit": self.truncated,
            "protocol_mix_pct": {k: round(v / mix_total * 100, 1) for k, v in self.proto_mix.most_common(10)},
            "top_remote_hosts": [{"host": self.host(ip), "ip": ip, "bytes": c["bytes"], "packets": c["packets"],
                                  "received": c["down"], "sent": c["up"],
                                  "share_pct": round(c["bytes"] / (self.total_bytes or 1) * 100, 1),
                                  "main_protocol": c["protos"].most_common(1)[0][0] if c["protos"] else ""}
                                 for ip, c in top],
            "tcp_problems": {"retransmissions": self.retrans, "duplicate_acks": self.dupacks, "zero_window": self.zerowin,
                             "by_host": [{"host": self.host(ip), "ip": ip, "retransmissions": c["retrans"],
                                          "pct_of_host_tcp": round(c["retrans"] / max(1, c["tcp"]) * 100, 1)}
                                         for ip, c in tcp_hosts[:5]]},
            "unencrypted": [{"protocol": pr, "host": h, "packets": e["packets"], "first_frame": e["first"]}
                            for (pr, h), e in list(self.plaintext.items())[:10]],
            "dns": {"answered_lookups": len(self.dns_times),
                    "avg_ms": round(sum(x["ms"] for x in self.dns_times) / len(self.dns_times), 1) if self.dns_times else None,
                    "slowest": sorted(({"name": x["name"], "ms": round(x["ms"], 1)} for x in self.dns_times),
                                      key=lambda x: -x["ms"])[:5]},
            "ping": {"replies": len(self.ping_rtts),
                     "avg_ms": round(sum(x["ms"] for x in self.ping_rtts) / len(self.ping_rtts), 1) if self.ping_rtts else None},
            "lan_devices_seen": [{"mac": m, "ip": v["ip"], "first_frame": v["first"]} for m, v in list(self.lan_macs.items())[:20]],
            "tls_server_names": [s for s, _ in self.sni.most_common(20)],
            "display_filter": self.view_filter, "displayed_packets": self.displayed,
        }
        sel = self.packet(selected or self.selected_no)
        if sel is not None:
            out["selected_packet"] = packet_detail(sel)
        return out


def packet_detail(p):
    d = p.dis
    tree = "\n".join(n.text() for n in p.tree())
    return {"number": p.no, "time_s": round(p.rel, 6), "source": d.src, "destination": d.dst, "protocol": d.proto,
            "length": d.length, "info": d.info, "tcp_analysis": sorted(p.tags),
            "layers": tree[:5000] + ("\n...(truncated)" if len(tree) > 5000 else ""),
            "first_bytes_hex": p.data[:96].hex(" ")}


def _mix_bucket(d):
    name = d.proto
    if name.startswith("TLS"):
        return "TLS"
    if name in ("MDNS", "SSDP", "LLMNR", "NBNS"):
        return "Discovery"
    return name


def _read_pcap(path):
    with open(path, "rb") as fh:
        head = fh.read(24)
        magic = struct.unpack("<I", head[:4])[0] if len(head) >= 4 else 0
        endian = {0xA1B2C3D4: "<", 0xD4C3B2A1: ">", 0xA1B23C4D: "<", 0x4D3CB2A1: ">"}.get(magic)
        if endian is None:
            yield from _read_with_scapy(path)
            return
        nano = magic in (0xA1B23C4D, 0x4D3CB2A1)
        link = struct.unpack(endian + "I", head[20:24])[0]
        if link != LINKTYPE_ETHERNET:
            raise ValueError("Only Ethernet captures can be opened.")
        while True:
            rec = fh.read(16)
            if len(rec) < 16:
                return
            sec, frac, incl, _orig = struct.unpack(endian + "IIII", rec)
            data = fh.read(incl)
            yield sec + frac / (1e9 if nano else 1e6), data


def _read_with_scapy(path):
    try:
        from scapy.all import PcapReader
        from scapy.layers.l2 import Ether
    except Exception:
        raise ValueError("This file is not a classic .pcap. Opening .pcapng needs scapy (pip install scapy).") from None
    with PcapReader(path) as reader:
        for pkt in reader:
            if isinstance(pkt, Ether):
                yield float(pkt.time), bytes(pkt)


_service = None


def get_capture_service():
    global _service
    if _service is None:
        _service = CaptureService()
    return _service
