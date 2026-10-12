"""Netwer AI: the built-in, on-device assistant for Network Health."""
import re
import unicodedata

from core.diagnostics import CRITICAL, GOOD, INFO, WARNING

_SEV_RANK = {CRITICAL: 0, WARNING: 1, INFO: 2, GOOD: 3}


# answer blocks
def text(s):
    return {"type": "text", "text": s}


def steps(items):
    return {"type": "steps", "items": list(items)}


def bullets(items):
    return {"type": "bullets", "items": list(items)}


def finding(sev, title, detail="", action=""):
    return {"type": "finding", "severity": sev, "title": title, "detail": detail, "action": action}


def actions(*pairs):
    return {"type": "actions", "items": [{"label": l, "target": t} for l, t in pairs]}


def _answer(intent, blocks, suggestions=()):
    return {"intent": intent, "blocks": blocks, "suggestions": list(suggestions)[:3]}


# context
def _round(v, n=1):
    return None if v is None else round(float(v), n)


def traffic_summary(bandwidth_rows, conn_rows, adapter="") -> dict:
    out = {"adapter": adapter}
    if bandwidth_rows:
        n = sum(r[5] for r in bandwidth_rows)
        out["download_mbps"] = {"avg": _round(sum(r[1] * r[5] for r in bandwidth_rows) / n, 2),
                                "peak": _round(max(r[3] for r in bandwidth_rows), 2)}
        out["upload_mbps"] = {"avg": _round(sum(r[2] * r[5] for r in bandwidth_rows) / n, 2),
                              "peak": _round(max(r[4] for r in bandwidth_rows), 2)}
    if conn_rows:
        losses = [c[2] for c in conn_rows]
        pings = [c[1] for c in conn_rows if c[1] is not None]
        out["packet_loss_pct"] = {"avg": _round(sum(losses) / len(losses)), "worst": _round(max(losses))}
        if pings:
            out["latency_ms"] = {"avg": _round(sum(pings) / len(pings)), "max": _round(max(pings))}
    return out


def build_context(report=None, devices=None, port_scan=None, traffic=None) -> dict:
    ctx = {"diagnosis": None, "devices": list(devices or []), "port_scan": None,
           "traffic": traffic or {}}
    if report:
        ctx["diagnosis"] = {
            "headline": report.get("headline", ""), "summary": report.get("summary", ""),
            "severity": report.get("severity", INFO),
            "findings": sorted(report.get("findings", []),
                               key=lambda f: _SEV_RANK.get(f.get("severity"), 2)),
            "measurements": report.get("measurements") or {}}
    if port_scan and (port_scan.get("results") or port_scan.get("target")):
        ctx["port_scan"] = {"target": port_scan.get("target", ""),
                            "target_name": port_scan.get("target_name", ""),
                            "results": port_scan.get("results", [])}
    return ctx


# language
def _norm(s: str) -> str:
    s = s.replace("\u0111", "d").replace("\u0110", "d")
    s = "".join(c for c in unicodedata.normalize("NFD", s) if not unicodedata.combining(c))
    s = s.lower().replace("wi-fi", "wifi").replace("wi fi", "wifi")
    return re.sub(r"[^a-z0-9 ]+", " ", s).strip()


INTENTS = {
    "explain_results": ["explain", "result", "summar", "overview", "whats wrong", "what s wrong",
                        "status", "how is my network", "objasni", "rezultat", "sazet", "stanje",
                        "sto nije u redu", "sto ne valja", "kako je moja mreza", "analiz"],
    "fix_first": ["fix", "first", "priorit", "important", "repair", "solve", "what should i do",
                  "popravi", "rijesi", "prvo", "najvazn", "sto da radim", "sto napraviti"],
    "slow": ["slow", "lag", "buffer", "freez", "stutter", "sporo", "spor ", "zaostaj", "koci",
             "seka", "zablokir", "ne radi dobro", "problem s internet"],
    "security": ["secur", "safe", "hack", "vulnerab", "risk", "open port", "exposed", "sigurn",
                 "opasn", "ranjiv", "otvoren", "zasticen", "napad", "zastit"],
    "wifi": ["wifi", "wireless", "signal", "channel", "bezic", "kanal"],
    "dns": ["dns", "domain", "ipv6", "ipv4", "name resolution", "domen"],
    "devices": ["device", "who is on", "connected", "unknown", "intruder", "stranger", "uredaj",
                "tko je", "spojen", "nepoznat", "uljez", "na mrezi"],
    "loss_latency": ["packet", "loss", "latenc", "ping", "jitter", "gubit", "kasnjen", "odziv"],
    "traffic": ["bandwidth", "download", "upload", "traffic", "speed", "usage", "promet", "brzin",
                "preuzim", "bandwith"],
    "router": ["router", "ruter", "gateway", "mikrotik", "modem"],
    "glossary": ["what is", "what does", "what are", "meaning", "define", "sto je", "sto znaci",
                 "sto su", "pojam"],
    "help": ["help", "what can you do", "pomoc", "pomozi", "sto mozes", "kako radis", "mogucnost"],
    "greet": ["=hi", "=hello", "=hey", "=bok", "=cao", "pozdrav", "dobar dan", "dobro jutro"],
    "thanks": ["thank", "=thx", "=ty", "hvala"],
}

PRIORITY = ["glossary", "security", "slow", "wifi", "dns", "devices", "loss_latency", "traffic",
            "router", "fix_first", "explain_results", "help", "greet", "thanks"]
FOLLOW_UP = ["how", "why", "more", "detail", "kako", "zasto", "jos", "detalj", "and then", "a onda"]


def _score(q: str, tokens: list, kws: list) -> int:
    padded = f" {q} "
    total = 0
    for kw in kws:
        if kw.startswith("="):
            total += 2 if kw[1:] in tokens else 0
        elif " " in kw.strip():
            total += 3 if f" {kw.strip()} " in padded or kw in padded else 0
        elif kw.endswith(" "):
            total += 2 if f" {kw}" in padded else 0
        else:
            total += 2 if any(t.startswith(kw) for t in tokens) else 0
    return total


GLOSSARY = {
    "packet loss": ("Packet loss", "Data travels in small pieces called packets. Packet loss means some never "
                    "arrive. Even 1-2% makes calls stutter and pages hang; 0% is what you want."),
    "latency": ("Latency (ping)", "How long a tiny message takes to reach a device and come back, in milliseconds. "
                "Under 30 ms to the internet is great, over 100 ms feels laggy in games and calls."),
    "ping": ("Ping", "A tiny test message sent to a device to see if it answers and how fast. It's the "
             "quickest way to check that something is reachable."),
    "jitter": ("Jitter", "How much latency changes from one message to the next. High jitter makes voice and "
               "video choppy even when the average ping looks fine."),
    "dns": ("DNS", "The internet's phone book: it turns names like google.com into addresses. If DNS is slow, "
            "pages seem to hang before they even start loading."),
    "ipv6": ("IPv6", "The newer kind of internet address. Many networks work fine on IPv4 only, so a missing "
             "IPv6 address is usually not a problem."),
    "gateway": ("Gateway / router", "The device your computer sends everything through to reach the internet. "
                "At home that's your router."),
    "router": ("Router", "The box that connects your devices to each other and to the internet."),
    "port": ("Port", "Think of an IP address as a building and ports as its numbered doors. Each service "
             "(web, SSH, file sharing) listens on its own door. Open doors you don't need are a risk."),
    "telnet": ("Telnet (port 23)", "An old way to log into a device remotely that sends everything, including "
               "your password, as plain text. Use SSH instead."),
    "ssh": ("SSH (port 22)", "A secure, encrypted way to log into a device remotely. Open SSH is normal and fine "
            "if the password is strong."),
    "ftp": ("FTP (port 21)", "An old file-transfer protocol that sends passwords unencrypted. SFTP is the safe "
            "replacement."),
    "smb": ("SMB (port 445)", "Windows file and printer sharing. Fine inside your home, dangerous if reachable "
            "from the internet."),
    "winbox": ("Winbox (port 8291)", "MikroTik's management tool for configuring the router. It should only be "
               "reachable from your local network."),
    "dhcp": ("DHCP", "The router's job of handing each device an address when it joins the network."),
    "mac": ("MAC address", "A hardware ID burned into a network card. It identifies the device on your local "
            "network and its first half reveals the manufacturer."),
    "upnp": ("UPnP", "Lets devices ask the router to open ports automatically. Convenient, but malware can "
             "abuse it, so turn it off if you don't need it."),
    "bandwidth": ("Bandwidth", "How much data per second your connection can carry, in Mbps. More bandwidth "
                  "doesn't fix high latency or packet loss."),
}
GLOSSARY_ALIASES = {"paket": "packet loss", "gubitak": "packet loss", "kasnjenje": "latency",
                    "ruter": "router", "usmjernik": "router", "vrata": "port", "propusnost": "bandwidth",
                    "mac adres": "mac", "pristupnik": "gateway", "ip6": "ipv6"}


# helpers
_TOOLS = [("dns", ("Open DNS Tools", "dns_tools")), ("ipv6", ("Open DNS Tools", "dns_tools")),
          ("wi fi", ("Wi-Fi details", "wifi")), ("wifi", ("Wi-Fi details", "wifi")),
          ("signal", ("Wi-Fi details", "wifi")), ("port", ("Open Port Scanner", "port_scanner")),
          ("telnet", ("Open Port Scanner", "port_scanner")), ("speed", ("Run speed test", "speedtest")),
          ("router", ("Ping the router", "ping")), ("gateway", ("Ping the router", "ping")),
          ("loss", ("Open Ping", "ping")), ("internet", ("Open Ping", "ping"))]


def _tools_for(blob: str, limit=2):
    blob = _norm(blob)
    out = []
    for key, pair in _TOOLS:
        if key in blob and pair not in out:
            out.append(pair)
    return out[:limit]


def _split_action(action: str):
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", action or "") if p.strip()]
    return parts or []


def _diag(ctx):
    return ctx.get("diagnosis")


def _m(ctx):
    d = _diag(ctx)
    return (d or {}).get("measurements") or {}


def _need_diagnosis(intent="need_diagnosis"):
    return _answer(intent, [
        text("I don't have fresh measurements yet. Run a diagnosis and I'll explain what it finds "
             "in plain language."),
        actions(("Diagnose my network", "health_run"))])


def _gateway_ip(ctx):
    for d in ctx.get("devices", []):
        if d.get("is_gateway"):
            return d.get("ip", "")
    return _m(ctx).get("gateway", "")


def _device_name(ctx, ip):
    for d in ctx.get("devices", []):
        if d.get("ip") == ip and d.get("name"):
            return d["name"]
    return ip


PORT_RISKS = {
    21: ("FTP", WARNING, "FTP sends passwords and files unencrypted, so anyone on the network can read them.",
         "Turn FTP off, or use SFTP instead."),
    23: ("Telnet", CRITICAL, "Telnet sends everything, including your admin password, as plain text.",
         "Turn Telnet off and log in with SSH instead."),
    69: ("TFTP", WARNING, "TFTP has no login at all.", "Disable it unless you use it for firmware transfers."),
    135: ("Windows RPC", WARNING, "Used by Windows internals and a common attack target.",
          "Block it in the firewall unless you need it."),
    139: ("Windows file sharing", WARNING, "Old Windows sharing port, often probed by malware.",
          "Disable file sharing on devices that don't need it."),
    445: ("Windows file sharing (SMB)", WARNING, "File sharing is fine at home but must never be reachable "
          "from the internet.", "Make sure it's blocked on the router's internet side."),
    161: ("SNMP", WARNING, "SNMP can leak details about the device with default settings.",
          "Disable it or change the default community string."),
    1900: ("UPnP", INFO, "UPnP lets devices open ports on the router by themselves.",
           "Turn it off if you don't need it."),
    3306: ("MySQL database", WARNING, "Databases shouldn't be reachable from other devices.",
           "Bind it to localhost or firewall it."),
    3389: ("Remote Desktop", CRITICAL, "Remote Desktop is a frequent ransomware entry point.",
           "Turn it off, or put it behind a VPN."),
    5900: ("VNC remote control", CRITICAL, "VNC is often weakly protected.", "Turn it off or tunnel it via SSH/VPN."),
    8291: ("MikroTik Winbox", WARNING, "Winbox is the router's management port; it should only be reachable "
           "from your local network.", "Restrict it to the LAN (IP > Services > Winbox > Available From)."),
    8728: ("MikroTik API", WARNING, "The router's management API.", "Disable it or restrict it to the LAN."),
    80: ("HTTP web page", INFO, "An unencrypted web page, often the router login. Fine at home with a "
         "strong admin password.", "Use HTTPS if the device offers it."),
}
SAFE_PORTS = {22: "SSH", 443: "HTTPS", 53: "DNS", 8729: "API-SSL"}


def _glossary_term(q: str):
    for key in sorted(GLOSSARY, key=len, reverse=True):
        if re.search(rf"\b{re.escape(key)}\b", q):
            return key
    for alias, key in GLOSSARY_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}", q):
            return key
    return None


# the engine
class NetwerAI:
    def __init__(self):
        self._last = None

    def reset(self):
        self._last = None

    def welcome_suggestions(self):
        return ["Explain these results", "What should I fix first?", "Why is my internet slow?",
                "Is my network secure?", "Who is on my network?"]

    def answer(self, question: str, ctx: dict) -> dict:
        q = _norm(question)
        tokens = q.split()
        if not tokens:
            return _answer("empty", [text("Ask me something about your network.")], self.welcome_suggestions())

        intent, best = None, 0
        if _score(q, tokens, INTENTS["glossary"]) and _glossary_term(q):
            intent, best = "glossary", 99
        for name in PRIORITY:
            s = _score(q, tokens, INTENTS[name])
            if s > best:
                intent, best = name, s

        if best == 0 and self._last and any(f in q for f in FOLLOW_UP):
            intent = "security_steps" if self._last == "security" else "fix_first"
        if intent is None:
            return _answer("unknown", [
                text("I'm not sure I understood that. I can explain your diagnosis, find what to fix, "
                     "check security, devices, Wi-Fi, DNS and traffic, or explain terms like "
                     "\"packet loss\".")], self.welcome_suggestions())

        handler = getattr(self, "_" + intent)
        result = handler(q, ctx)
        if intent not in ("greet", "thanks", "help", "glossary", "security_steps"):
            self._last = intent
        return result

    def explain_finding(self, f: dict, ctx: dict) -> dict:
        self._last = "fix_first"
        blocks = [finding(f.get("severity", INFO), f.get("title", ""), f.get("detail", ""))]
        todo = _split_action(f.get("action", ""))
        if todo:
            blocks.append(text("Here's what to do:"))
            blocks.append(steps(todo))
        tools = _tools_for(f"{f.get('title', '')} {f.get('detail', '')} {f.get('action', '')}")
        if tools:
            blocks.append(actions(*tools))
        return _answer("finding", blocks, ["What should I fix first?", "Explain these results"])

    # intents
    def _greet(self, q, ctx):
        return _answer("greet", [text("Hi! I'm Netwer AI. I read your latest diagnosis, devices and traffic "
                                      "and explain them in plain language. What would you like to know?")],
                       self.welcome_suggestions())

    def _thanks(self, q, ctx):
        return _answer("thanks", [text("Happy to help! Ask me anything else about your network.")],
                       ["Explain these results", "Is my network secure?"])

    def _help(self, q, ctx):
        return _answer("help", [
            text("I work entirely on your PC, from NETWER's own measurements. I can:"),
            bullets(["Explain your diagnosis and rank what to fix first",
                     "Work out why the internet feels slow",
                     "Check your port scan for security risks",
                     "List who is on your network and flag unknown devices",
                     "Explain Wi-Fi, DNS, ping, packet loss and other terms"]),
            text("You can ask in English or Croatian; my answers are in English for now.")],
            self.welcome_suggestions())

    def _explain_results(self, q, ctx):
        d = _diag(ctx)
        if not d:
            return _need_diagnosis()
        blocks = [text(f"**{d['headline']}** {d['summary']}")]
        issues = [f for f in d["findings"] if f["severity"] in (CRITICAL, WARNING)]
        notes = [f for f in d["findings"] if f["severity"] == INFO]
        for f in (issues + notes)[:4]:
            blocks.append(finding(f["severity"], f["title"], f["detail"]))
        if not issues:
            blocks.append(text("Nothing needs fixing right now."))
        tr = ctx.get("traffic") or {}
        if tr.get("download_mbps"):
            dl, ul = tr["download_mbps"], tr.get("upload_mbps", {})
            blocks.append(text(f"Recent traffic: download averaging {dl['avg']} Mbps (peak {dl['peak']}), "
                               f"upload averaging {ul.get('avg', 0)} Mbps."))
        sug = ["What should I fix first?"] if issues else ["Is my network secure?"]
        return _answer("explain_results", blocks, sug + ["Why is my internet slow?"])

    def _fix_first(self, q, ctx):
        d = _diag(ctx)
        if not d:
            return _need_diagnosis()
        issues = [f for f in d["findings"] if f["severity"] in (CRITICAL, WARNING)]
        if not issues:
            blocks = [text("Nothing urgent. Your connection looks healthy.")]
            best = _m(ctx).get("best_public_dns")
            if best:
                blocks.append(text(f"One optional tweak: {best['name']} DNS answered fastest "
                                   f"({best['ms']} ms) if you want snappier page loads."))
            return _answer("fix_first", blocks, ["Is my network secure?", "Who is on my network?"])
        top = issues[0]
        blocks = [text("Start with this one:"), finding(top["severity"], top["title"], top["detail"])]
        todo = _split_action(top.get("action", ""))
        if todo:
            blocks.append(steps(todo))
        tools = _tools_for(f"{top['title']} {top['detail']} {top.get('action', '')}")
        if tools:
            blocks.append(actions(*tools))
        if len(issues) > 1:
            blocks.append(text(f"After that there {'is' if len(issues) == 2 else 'are'} "
                               f"{len(issues) - 1} more: {', '.join(i['title'] for i in issues[1:3])}."))
        return _answer("fix_first", blocks, ["Explain these results", "Is my network secure?"])

    def _slow(self, q, ctx):
        d = _diag(ctx)
        if not d:
            return _need_diagnosis()
        m, tr = _m(ctx), ctx.get("traffic") or {}
        router, inet = m.get("router") or {}, m.get("internet") or {}
        causes = []
        if router.get("loss") or (router.get("avg") or 0) > 25:
            causes.append((0, "The problem is between your computer and your router",
                           f"Router ping {router.get('avg')} ms with {router.get('loss')}% loss.",
                           ["If you use Wi-Fi, move closer to the router or switch to a cable to test.",
                            "Restart the router and wait two minutes.",
                            "Check that nothing else is saturating the link (backups, streaming)."]))
        elif m.get("router_reachable") and (inet.get("loss") or 0) >= 1:
            causes.append((1, "Your router is fine, but the connection beyond it loses data",
                           f"Internet packet loss is {inet.get('loss')}%.",
                           ["Restart the router and modem.", "Test again with a cable to rule out Wi-Fi.",
                            "If it keeps happening, contact your provider and quote the packet loss."]))
        if (inet.get("avg") or 0) > 80:
            causes.append((2, "The route to the internet is slow",
                           f"Internet ping averages {inet.get('avg')} ms.",
                           ["Run the speed test to see your real speed.",
                            "Try at a different time of day; evening congestion is common.",
                            "Contact your provider if it stays high."]))
        if (inet.get("jitter") or 0) > 30:
            causes.append((3, "Your connection is unstable (high jitter)",
                           f"Jitter is {inet.get('jitter')} ms, which makes calls and games choppy.",
                           ["Use a cable instead of Wi-Fi if possible.",
                            "Pause large downloads and uploads while you need it stable."]))
        if m.get("dns_failures") or (m.get("dns_ms") or 0) > 100:
            best = m.get("best_public_dns")
            fix = ["Switch your DNS server to a faster one in the adapter settings."]
            if best:
                fix.insert(0, f"{best['name']} DNS answered fastest at {best['ms']} ms; use it.")
            causes.append((4, "Name lookups are slow, so pages hang before loading",
                           f"DNS takes {m.get('dns_ms')} ms.", fix))
        if m.get("wifi") and (m.get("signal") or 100) < 50:
            causes.append((5, "Your Wi-Fi signal is weak",
                           f"Signal strength is {m.get('signal')}%.",
                           ["Move closer to the router or remove obstacles between you.",
                            "Try the 5 GHz band if your router has it, or change the Wi-Fi channel."]))
        ul = (tr.get("upload_mbps") or {}).get("avg") or 0
        if ul > 3:
            causes.append((6, "Something on your PC is uploading a lot",
                           f"Upload is averaging {ul} Mbps, which can slow everything else.",
                           ["Pause cloud backups and sync tools (OneDrive, Google Drive).",
                            "Check the Dashboard graph to see when it happens."]))
        causes.sort(key=lambda c: c[0])
        if not causes:
            return _answer("slow", [
                text("Your measurements look healthy: low latency, no packet loss and fast DNS. So the "
                     "slowness is probably the website or service itself, or something temporary."),
                text("A speed test will show whether your line delivers what you pay for."),
                actions(("Run speed test", "speedtest"))], ["Is my network secure?", "Explain these results"])
        top = causes[0]
        blocks = [text(f"**{top[1]}.**"), bullets([c[2] for c in causes[:3]]),
                  text("What to try:"), steps(top[3])]
        tools = _tools_for(top[1] + " " + top[2])
        if tools:
            blocks.append(actions(*tools))
        return _answer("slow", blocks, ["What should I fix first?", "Explain these results"])

    def _security(self, q, ctx, steps_only=False):
        ps = ctx.get("port_scan")
        if not ps:
            gw = _gateway_ip(ctx)
            blocks = [text("I haven't seen a port scan yet. Scanning your router shows which services "
                           "it exposes, which is the most useful security check at home.")]
            blocks.append(actions(*([("Scan my router", f"scan:{gw}")] if gw else []),
                                  ("Open Port Scanner", "port_scanner")))
            return _answer("security", blocks, ["Who is on my network?", "Explain these results"])
        name = ps.get("target_name") or _device_name(ctx, ps["target"])
        label = f"{name} ({ps['target']})" if name and name != ps["target"] else ps["target"]
        open_ports = [r["port"] for r in ps["results"]]
        risky = sorted(((p, PORT_RISKS[p]) for p in open_ports if p in PORT_RISKS),
                       key=lambda x: (_SEV_RANK[x[1][1]], x[0]))
        serious = [r for r in risky if r[1][1] in (CRITICAL, WARNING)]
        if not open_ports:
            return _answer("security", [text(f"The last scan found no open ports on {label}. That's the "
                                             "safest result.")], ["Who is on my network?"])
        blocks = [text(f"Last scan of **{label}**: {len(open_ports)} open port"
                       f"{'s' if len(open_ports) != 1 else ''}, {len(serious)} worth closing.")]
        todo = []
        if not steps_only:
            for p, (nm, sev, why, fix) in risky[:4]:
                blocks.append(finding(sev, f"{nm} (port {p}) is open", why))
        for p, (nm, sev, why, fix) in risky:
            if sev in (CRITICAL, WARNING):
                todo.append(f"{nm}: {fix}")
        fine = [f"{SAFE_PORTS[p]} ({p})" for p in open_ports if p in SAFE_PORTS]
        if fine and not steps_only:
            blocks.append(text("These are encrypted or harmless: " + ", ".join(fine) + "."))
        if todo:
            blocks.append(text("How to close them:"))
            hint = "mikrotik" in _norm(f"{name} {' '.join(str(r.get('banner', '')) for r in ps['results'])}")
            first = ("Open your router's admin page" + (" (WinBox or WebFig on MikroTik)" if hint else "")
                     + " and note the current settings first.")
            blocks.append(steps([first] + todo[:4] + ["Run the port scan again to confirm they're closed."]))
        else:
            blocks.append(text("Nothing alarming here. Keep the router firmware up to date and use a strong "
                               "admin password."))
        blocks.append(actions(("Scan again", f"scan:{ps['target']}")))
        return _answer("security", blocks, ["What should I fix first?", "Who is on my network?"])

    def _security_steps(self, q, ctx):
        return self._security(q, ctx, steps_only=True)

    def _wifi(self, q, ctx):
        d = _diag(ctx)
        if not d:
            return _need_diagnosis()
        m = _m(ctx)
        if not m.get("wifi"):
            return _answer("wifi", [text(f"You're not on Wi-Fi right now ({m.get('adapter') or 'wired adapter'}), "
                                         "so Wi-Fi isn't affecting your connection."),
                                    actions(("Wi-Fi details", "wifi"))], ["Why is my internet slow?"])
        sig = m.get("signal") or 0
        rating = ("excellent" if sig >= 80 else "good" if sig >= 60 else "fair" if sig >= 40 else "weak")
        blocks = [text(f"Your Wi-Fi signal is **{rating}** ({sig}%)"
                       + (f" on {m['band']}" if m.get("band") else "")
                       + (f", channel {m['channel']}" if m.get("channel") else "") + ".")]
        if sig < 60:
            blocks += [text("To improve it:"),
                       steps(["Move closer to the router or remove walls and metal objects between you.",
                              "Use the 5 GHz band for speed at short range, 2.4 GHz for range.",
                              "Try a less crowded channel in the router settings."])]
        blocks.append(actions(("Wi-Fi details", "wifi")))
        return _answer("wifi", blocks, ["Why is my internet slow?", "Explain these results"])

    def _dns(self, q, ctx):
        d = _diag(ctx)
        if not d:
            return _need_diagnosis()
        m = _m(ctx)
        lines = []
        if m.get("dns_working"):
            lines.append(f"DNS lookups succeed and average {m.get('dns_ipv4_ms')} ms.")
        else:
            lines.append("DNS lookups are failing, so names like google.com can't be resolved.")
        scope = m.get("ipv6_scope")
        lines.append({"global": "IPv6 is active.",
                      "ula": "IPv6 works on your local network only.",
                      "link-local": "IPv6 is link-local only (no internet over IPv6)."}.get(
                          scope, "You have no IPv6 address, which is normal on many networks."))
        blocks = [bullets(lines)]
        best = m.get("best_public_dns")
        if best and (m.get("dns_ipv4_ms") or 0) > best["ms"] * 1.5:
            blocks.append(text(f"{best['name']} DNS answered in {best['ms']} ms, noticeably faster than yours. "
                               "Switching your DNS server can make pages feel snappier."))
        blocks.append(actions(("Open DNS Tools", "dns_tools")))
        return _answer("dns", blocks, ["Why is my internet slow?", "What is DNS?"])

    def _devices(self, q, ctx):
        devs = ctx.get("devices") or []
        if not devs:
            return _answer("devices", [text("I haven't discovered any devices yet. Run a network scan from "
                                            "the Dashboard or Ping Sweep."),
                                       actions(("Open Ping Sweep", "ping_sweep"))], ["Explain these results"])
        unnamed = [d for d in devs if (d.get("name") or "").lower() in ("", "device", "unknown device",
                                                                       "device (private)")]
        items = [f"{d.get('name') or 'Unnamed'} ({d.get('ip', '')})" + (" (router)" if d.get("is_gateway") else "")
                 for d in devs[:8]]
        blocks = [text(f"There {'is' if len(devs) == 1 else 'are'} **{len(devs)} device"
                       f"{'s' if len(devs) != 1 else ''}** on your network:"), bullets(items)]
        if len(devs) > 8:
            blocks.append(text(f"...and {len(devs) - 8} more."))
        if unnamed:
            blocks.append(text(f"{len(unnamed)} of them {'has' if len(unnamed) == 1 else 'have'} no recognisable name. If you don't know what "
                               "they are, check them in Connected Devices, or change your Wi-Fi password "
                               "if something looks off."))
        else:
            blocks.append(text("Every device has a recognisable name, which is a good sign."))
        blocks.append(actions(("Rescan network", "ping_sweep")))
        return _answer("devices", blocks, ["Is my network secure?", "What should I fix first?"])

    def _loss_latency(self, q, ctx):
        d, tr = _diag(ctx), ctx.get("traffic") or {}
        m = _m(ctx)
        router, inet = m.get("router") or {}, m.get("internet") or {}
        if not d and not tr.get("latency_ms"):
            return _need_diagnosis()
        lines = []
        if router:
            lines.append(f"Router: {router.get('avg')} ms, {router.get('loss')}% loss")
        if inet:
            lines.append(f"Internet: {inet.get('avg')} ms, {inet.get('loss')}% loss, jitter {inet.get('jitter')} ms")
        if tr.get("packet_loss_pct"):
            pl = tr["packet_loss_pct"]
            lines.append(f"Last few minutes: loss averaging {pl['avg']}% (worst {pl['worst']}%)")
        loss = max([inet.get("loss") or 0, (tr.get("packet_loss_pct") or {}).get("avg") or 0])
        lat = inet.get("avg") or (tr.get("latency_ms") or {}).get("avg") or 0
        verdict = ("No packet loss and low latency: this is as good as it gets." if loss < 1 and lat < 30
                   else "Some packet loss or higher latency detected.")
        blocks = [text(verdict), bullets(lines), actions(("Open Ping", "ping"))]
        return _answer("loss_latency", blocks, ["Why is my internet slow?", "Explain these results"])