"""Measure network health and produce a plain-language diagnosis."""
from __future__ import annotations

import secrets
import socket
import statistics
import struct
import time

# Severity levels, worst first.
CRITICAL = "critical"
WARNING = "warning"
GOOD = "good"
INFO = "info"

_SEVERITY_ORDER = {CRITICAL: 0, WARNING: 1, INFO: 2, GOOD: 3}

# Public resolvers used to sanity-check the local DNS.
_PUBLIC_DNS = [("Cloudflare", "1.1.1.1"), ("Google", "8.8.8.8")]
_TEST_DOMAINS = ["google.com", "cloudflare.com", "github.com"]


# Measuring
def _ping_series(core, host, count=5, timeout_ms=1000):
    """Ping a host a few times. Returns (rtts, loss_percent)."""
    rtts = []
    for _ in range(count):
        ms = core.ping_host(host, timeout_ms)
        if ms is not None:
            rtts.append(ms)
    loss = round(100.0 * (count - len(rtts)) / count, 1)
    return rtts, loss


def _summarise(rtts):
    """avg / min / max / jitter for a list of round-trip times."""
    if not rtts:
        return {"avg": None, "min": None, "max": None, "jitter": None}
    jitter = 0.0
    if len(rtts) > 1:
        deltas = [abs(b - a) for a, b in zip(rtts, rtts[1:])]
        jitter = round(statistics.fmean(deltas), 1)
    return {
        "avg": round(statistics.fmean(rtts), 1),
        "min": round(min(rtts), 1),
        "max": round(max(rtts), 1),
        "jitter": jitter,
    }


def _time_dns(domain, server=None, timeout=1.0, record_type=1):
    """Resolve a domain and time it. Returns ms, or None on failure.

    With `server` set we ask that resolver directly, so we can compare the
    router/ISP resolver against public ones. The OS resolver call has no local
    timeout control; its duration depends on the system resolver configuration."""
    start = time.perf_counter()
    try:
        if server is None:
            family = socket.AF_INET if record_type == 1 else socket.AF_INET6
            socket.getaddrinfo(domain, None, family, socket.SOCK_DGRAM)
        else:
            _query_dns(domain, server, timeout, record_type)
        return round((time.perf_counter() - start) * 1000, 1)
    except Exception:
        return None


def _query_dns(domain, server, timeout=1.0, record_type=1):
    """Send one validated A or AAAA DNS query."""
    if record_type not in (1, 28):
        raise ValueError("unsupported DNS record type")
    labels = domain.rstrip(".").split(".")
    if not labels or any(not label or len(label.encode("idna")) > 63
                         for label in labels):
        raise ValueError("invalid DNS name")
    qname = b"".join(bytes([len(label.encode("idna"))]) + label.encode("idna")
                     for label in labels) + b"\x00"
    txid = secrets.randbits(16)
    packet = (struct.pack(">HHHHHH", txid, 0x0100, 1, 0, 0, 0)
              + qname + struct.pack(">HH", record_type, 1))
    try:
        socket.inet_pton(socket.AF_INET, server)
        family = socket.AF_INET
    except OSError:
        socket.inet_pton(socket.AF_INET6, server)
        family = socket.AF_INET6
    with socket.socket(family, socket.SOCK_DGRAM) as s:
        s.settimeout(timeout)
        endpoint = (server, 53) if family == socket.AF_INET else (server, 53, 0, 0)
        s.connect(endpoint)
        s.send(packet)
        data = s.recv(1024)
    if len(data) < 12 or struct.unpack(">H", data[:2])[0] != txid:
        raise ValueError("short DNS reply")
    flags = struct.unpack(">H", data[2:4])[0]
    questions, answers = struct.unpack(">HH", data[4:8])
    if not flags & 0x8000 or flags & 0x0200 or flags & 0x000F:
        raise ValueError("invalid DNS response")
    if questions != 1:
        raise ValueError("unexpected DNS question")
    offset = 12
    question_name, offset = _read_dns_name(data, offset)
    if question_name.lower() != domain.rstrip(".").encode("idna").lower():
        raise ValueError("DNS question does not match")
    if len(data) < offset + 4 or struct.unpack(">HH", data[offset:offset + 4]) != (record_type, 1):
        raise ValueError("DNS question type does not match")
    offset += 4
    if not answers:
        raise ValueError("no DNS answer")
    aliases = {domain.rstrip(".").encode("idna").lower()}
    records = []
    for _ in range(answers):
        owner, offset = _read_dns_name(data, offset)
        if len(data) < offset + 10:
            raise ValueError("incomplete DNS answer")
        answer_type, answer_class, _, length = struct.unpack(">HHIH", data[offset:offset + 10])
        offset += 10
        if len(data) < offset + length:
            raise ValueError("incomplete DNS answer")
        if answer_class == 1 and answer_type == 5:
            target, end = _read_dns_name(data, offset)
            if end > offset + length:
                raise ValueError("invalid CNAME record")
            records.append((owner.lower(), answer_type, target.lower(), length))
        else:
            records.append((owner.lower(), answer_type, None, length))
        offset += length
    changed = True
    while changed:
        changed = False
        for owner, answer_type, target, _ in records:
            if answer_type == 5 and owner in aliases and target not in aliases:
                aliases.add(target)
                changed = True
    expected_length = 4 if record_type == 1 else 16
    if any(owner in aliases and answer_type == record_type and length == expected_length
           for owner, answer_type, _, length in records):
        return True
    raise ValueError("no matching DNS answer")


def _read_dns_name(data, offset):
    """Decode a DNS name, safely following compression pointers."""
    labels = []
    cursor = offset
    resume = None
    visited = set()
    while True:
        if cursor >= len(data):
            raise ValueError("incomplete DNS name")
        size = data[cursor]
        if size & 0xC0 == 0xC0:
            if cursor + 1 >= len(data):
                raise ValueError("incomplete DNS pointer")
            pointer = ((size & 0x3F) << 8) | data[cursor + 1]
            if pointer >= len(data) or pointer in visited:
                raise ValueError("invalid DNS pointer")
            visited.add(pointer)
            if resume is None:
                resume = cursor + 2
            cursor = pointer
            continue
        if size & 0xC0:
            raise ValueError("invalid DNS label")
        cursor += 1
        if size == 0:
            return b".".join(labels), resume if resume is not None else cursor
        if size > 63 or cursor + size > len(data):
            raise ValueError("invalid DNS label length")
        labels.append(data[cursor:cursor + size])
        cursor += size


def run_diagnostics_stream(core, deep=False):
    """Run the checks, yielding {'step', 'label', 'progress'} updates and
    finally {'done': True, 'measurements': {...}, 'report': {...}}."""
    m = {}
    steps = 6
    done = 0

    def progress(label):
        nonlocal done
        done += 1
        return {"step": done, "steps": steps, "label": label,
                "progress": int(100 * done / steps)}

    yield {"step": 0, "steps": steps, "label": "Checking your adapter…",
           "progress": 0}
    try:
        cfg = core.get_network_config()
    except Exception:
        cfg = {}
    if not isinstance(cfg, dict) or cfg.get("error"):
        cfg = {}
    m["ip"] = cfg.get("ip", "")
    m["gateway"] = cfg.get("gateway", "")
    m["adapter"] = cfg.get("adapter", "")
    m["has_ip"] = bool(m["ip"]) and m["ip"] not in ("N/A", "")
    m["has_gateway"] = bool(m["gateway"]) and m["gateway"] not in ("N/A", "")
    m["self_assigned"] = str(m["ip"]).startswith("169.254.")
    yield progress("Checking your adapter…")

    wifi = {}
    try:
        wifi = core.get_wifi_info() or {}
    except Exception:
        wifi = {}
    if isinstance(wifi, dict) and not wifi.get("error") and wifi.get("ssid"):
        m["wifi"] = True
        m["ssid"] = wifi.get("ssid", "")
        try:
            m["signal"] = int(str(wifi.get("signal", 0)).rstrip("%") or 0)
        except Exception:
            m["signal"] = 0
        m["band"] = wifi.get("band", "")
        m["channel"] = wifi.get("channel", "")
    else:
        m["wifi"] = False
    yield progress("Measuring Wi-Fi quality…")

    if m["has_gateway"]:
        rtts, loss = _ping_series(core, m["gateway"], count=5, timeout_ms=1000)
        m["router"] = _summarise(rtts)
        m["router"]["loss"] = loss
        m["router_reachable"] = bool(rtts)
    else:
        m["router"] = _summarise([])
        m["router"]["loss"] = 100.0
        m["router_reachable"] = False
    yield progress("Talking to your router…")

    inet_rtts = []
    inet_loss = 100.0
    for _, host in _PUBLIC_DNS:
        rtts, loss = _ping_series(core, host, count=5, timeout_ms=1500)
        if rtts:
            inet_rtts = rtts
            inet_loss = loss
            break
    m["internet"] = _summarise(inet_rtts)
    m["internet"]["loss"] = inet_loss
    m["internet_reachable"] = bool(inet_rtts)
    yield progress("Reaching the internet…")

    local_v4 = [t for t in (_time_dns(d, record_type=1) for d in _TEST_DOMAINS)
                if t is not None]
    local_v6 = [t for t in (_time_dns(d, record_type=28) for d in _TEST_DOMAINS)
                if t is not None]
    m["dns_working"] = bool(local_v4)
    m["dns_ms"] = round(statistics.fmean(local_v4), 1) if local_v4 else None
    m["dns_failures"] = len(_TEST_DOMAINS) - len(local_v4)
    m["dns_ipv4_ms"] = round(statistics.fmean(local_v4), 1) if local_v4 else None
    m["dns_ipv4_failures"] = len(_TEST_DOMAINS) - len(local_v4)
    m["dns_ipv6_ms"] = round(statistics.fmean(local_v6), 1) if local_v6 else None
    m["dns_ipv6_failures"] = len(_TEST_DOMAINS) - len(local_v6)
    yield progress("Testing name resolution…")

    best_public = None
    if m["internet_reachable"]:
        results = {}
        for name, server in _PUBLIC_DNS:
            times = [t for t in (_time_dns(d, server) for d in _TEST_DOMAINS[:2])
                     if t is not None]
            if times:
                results[name] = round(statistics.fmean(times), 1)
        if results:
            best_name = min(results, key=results.get)
            best_public = {"name": best_name, "ms": results[best_name]}
    m["best_public_dns"] = best_public
    yield progress("Comparing DNS providers…")

    yield {"done": True, "measurements": m, "report": analyse(m)}


# Reasoning (pure logic, no I/O)
def _finding(severity, title, detail, action=""):
    return {"severity": severity, "title": title, "detail": detail,
            "action": action}


def analyse(m: dict) -> dict:
    """Turn raw measurements into a verdict and ranked findings."""
    findings = []

    # Link layer
    if not m.get("has_ip"):
        findings.append(_finding(
            CRITICAL, "No IP address",
            "Your computer hasn't been given an address on the network, so it "
            "can't talk to anything yet.",
            "Check that Wi-Fi is on (or the cable is plugged in), then "
            "reconnect to the network."))
        return _verdict(findings, m)

    if m.get("self_assigned"):
        findings.append(_finding(
            CRITICAL, "Router didn't hand out an address",
            "Your device gave itself a fallback address (169.254.x.x), which "
            "means it never got one from the router.",
            "Restart the router, then reconnect. If it keeps happening, check "
            "that DHCP is enabled on the router."))
        return _verdict(findings, m)

    if not m.get("has_gateway"):
        findings.append(_finding(
            CRITICAL, "No gateway configured",
            "There's no router set as the way out to the internet.",
            "Reconnect to the network, or set the gateway manually if you use "
            "a static configuration."))
        return _verdict(findings, m)

    # Router
    router = m.get("router") or {}
    if not m.get("router_reachable"):
        findings.append(_finding(
            CRITICAL, "Your router isn't responding",
            f"We can't reach {m.get('gateway')} at all. The problem is between "
            "this device and your router — nothing beyond it will work.",
            "Restart the router. If you're on Wi-Fi, move closer or try a "
            "cable to rule the wireless link out."))
        return _verdict(findings, m)

    router_loss = router.get("loss") or 0
    router_avg = router.get("avg") or 0
    if router_loss >= 20:
        findings.append(_finding(
            CRITICAL, "Losing packets to your own router",
            f"{router_loss}% of packets to the router never came back. That's "
            "a local link problem, not your internet provider.",
            "On Wi-Fi: move closer or change channel. On cable: try another "
            "cable or port."))
    elif router_loss > 0:
        findings.append(_finding(
            WARNING, "Some packet loss on the local link",
            f"{router_loss}% of packets to the router were lost — enough to "
            "cause stutters in calls and games.",
            "Worth checking your Wi-Fi signal or cable."))
    elif router_avg > 25:
        findings.append(_finding(
            WARNING, "Slow response from the router",
            f"The router takes {router_avg} ms to answer, which is high for a "
            "device in your own home.",
            "Usually a weak Wi-Fi link or a busy router."))

    # Wi-Fi quality
    if m.get("wifi"):
        signal = m.get("signal", 0)
        if signal and signal < 40:
            findings.append(_finding(
                CRITICAL if signal < 25 else WARNING,
                "Weak Wi-Fi signal",
                f"Signal strength is {signal}%. At this level speeds drop and "
                "the connection drops out under load.",
                "Move closer to the router, or consider a mesh/repeater for "
                "this room."))
        elif signal and signal < 60:
            findings.append(_finding(
                INFO, "Wi-Fi signal is just okay",
                f"Signal strength is {signal}% — usable, but not great.",
                "Moving the router higher or more central usually helps."))

    # Internet
    internet = m.get("internet") or {}
    if not m.get("internet_reachable"):
        if m.get("router_reachable"):
            findings.append(_finding(
                CRITICAL, "Your network is fine — the internet isn't",
                "Your router answers normally, but nothing beyond it does. "
                "That points at your provider or the modem, not your devices.",
                "Restart the modem/router. If it persists, contact your ISP — "
                "the fault is on their side of the line."))
        return _verdict(findings, m)

    inet_loss = internet.get("loss") or 0
    inet_avg = internet.get("avg") or 0
    inet_jitter = internet.get("jitter") or 0

    if inet_loss >= 20:
        findings.append(_finding(
            CRITICAL, "Heavy packet loss to the internet",
            f"{inet_loss}% of packets are being dropped beyond your router. "
            "Calls, games and video will break up.",
            "Your local network looks fine, so this is likely your provider — "
            "report it to them."))
    elif inet_loss > 0:
        findings.append(_finding(
            WARNING, "Some packet loss to the internet",
            f"{inet_loss}% of packets didn't make it back.",
            "Keep an eye on it — occasional loss can be normal, sustained "
            "loss is worth reporting."))

    if inet_avg >= 150:
        findings.append(_finding(
            WARNING, "High latency",
            f"Round trip to the internet averages {inet_avg} ms, which feels "
            "sluggish and hurts video calls and gaming.",
            "Check nothing is saturating the line (big downloads, backups)."))
    elif inet_avg >= 80:
        findings.append(_finding(
            INFO, "Latency is a bit high",
            f"Average round trip is {inet_avg} ms.",
            ""))

    if inet_jitter >= 30:
        findings.append(_finding(
            WARNING, "Unstable latency (jitter)",
            f"Response times swing by about {inet_jitter} ms between pings. "
            "That instability is what makes calls robotic.",
            "Often caused by a congested Wi-Fi channel or an overloaded line."))

    # DNS: keep legacy fields tied to A records; report AAAA independently.
    ipv4_failures = m.get("dns_ipv4_failures", m.get("dns_failures", 0))
    if "dns_ipv4_failures" not in m and not m.get("dns_working", True):
        ipv4_failures = len(_TEST_DOMAINS)
    ipv6_failures = m.get("dns_ipv6_failures")
    ipv4_working = ipv4_failures < len(_TEST_DOMAINS)
    ipv6_working = (ipv6_failures is None or ipv6_failures < len(_TEST_DOMAINS))
    if not ipv4_working:
        if ipv6_failures is not None and ipv6_working:
            findings.append(_finding(
                WARNING, "IPv4 DNS lookups are failing",
                "A-record lookups failed for every test domain, but IPv6 DNS is responding.",
                "Check the resolver's IPv4 configuration."))
        else:
            findings.append(_finding(
                CRITICAL, "Names aren't resolving",
                "A-record lookups failed for every test domain, and IPv6 DNS is also unavailable.",
                "Switch your DNS to 1.1.1.1 or 8.8.8.8 in your adapter settings."))
    elif ipv6_failures is not None and not ipv6_working:
        findings.append(_finding(
            WARNING, "IPv6 DNS lookups are failing",
            "AAAA-record lookups failed for every test domain; IPv4 DNS is still responding.",
            "Check the resolver's IPv6 configuration."))
    if ipv4_working:
        dns_ms = m.get("dns_ms") or 0
        best = m.get("best_public_dns")
        if ipv4_failures:
            findings.append(_finding(
                WARNING, "Some lookups failed",
                f"{m['dns_failures']} of {len(_TEST_DOMAINS)} test domains "
                "didn't resolve first time.",
                "An unreliable resolver — a public DNS is usually steadier."))
        if dns_ms >= 120:
            action = "Consider switching your DNS."
            if best and best["ms"] < dns_ms * 0.6:
                action = (f"{best['name']} answered in {best['ms']} ms here — "
                          f"switching would make sites start loading sooner.")
            findings.append(_finding(
                WARNING, "Slow DNS",
                f"Name lookups take {dns_ms} ms on average, so every new site "
                "hesitates before it starts loading.",
                action))
        elif best and dns_ms and best["ms"] < dns_ms * 0.5 and dns_ms > 40:
            findings.append(_finding(
                INFO, "A faster DNS is available",
                f"Your current resolver takes {dns_ms} ms; {best['name']} "
                f"managed {best['ms']} ms.",
                f"Switching to {best['name']} would shave a little off every "
                "page load."))

    return _verdict(findings, m)


def _verdict(findings, m):
    """Wrap findings in an overall headline."""
    if not findings:
        findings = [_finding(
            GOOD, "Everything looks healthy",
            "Your adapter, router, internet connection and DNS all responded "
            "normally, with no packet loss worth mentioning.",
            "")]

    findings.sort(key=lambda f: _SEVERITY_ORDER.get(f["severity"], 9))
    worst = findings[0]["severity"]

    if worst == CRITICAL:
        headline = findings[0]["title"]
        summary = findings[0]["detail"]
    elif worst == WARNING:
        headline = "Working, but with problems"
        summary = findings[0]["detail"]
    elif worst == INFO:
        headline = "Working well"
        summary = "Everything essential is fine; a couple of small things could be better."
    else:
        headline = "Your network is healthy"
        summary = findings[0]["detail"]

    return {
        "severity": worst,
        "headline": headline,
        "summary": summary,
        "findings": findings,
        "measurements": m,
    }
