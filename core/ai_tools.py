import json

from core.ai_knowledge import APP_GUIDE

PAGES = ["dashboard", "network", "wifi", "system", "health", "ping", "ping_sweep", "port_scanner",
         "dns_tools", "speedtest", "report"]


def _tool(name, description, properties=None, required=None):
    return {"name": name, "description": description,
            "parameters": {"type": "object", "properties": properties or {}, "required": required or []}}


TOOLS = [
    _tool("get_network_status", "Current adapter in use, IP, gateway, DNS, whether the internet works and latency. Start here for general questions."),
    _tool("get_diagnosis", "Result of the last Network Health diagnosis: headline, findings with fixes and raw measurements (router/internet latency, loss, jitter, DNS)."),
    _tool("get_devices", "Devices found on the local network with name, IP, vendor and kind."),
    _tool("get_port_scan", "Open ports from the last port scan, including which device was scanned."),
    _tool("get_traffic", "Receive/send speed and packet loss/latency history recorded while Netwer ran.",
          {"minutes": {"type": "integer", "description": "How far back, 1 to 60. Default 10."}}),
    _tool("get_wifi", "Current Wi-Fi connection: SSID, signal, band, channel, radio type, link speed."),
    _tool("get_system", "CPU, memory and disk usage of this computer."),
    _tool("get_recent_activity", "Recent Netwer notifications such as new devices or hosts going down."),
    _tool("get_app_guide", "Describe a Netwer page or feature and how to use it.",
          {"topic": {"type": "string", "description": "Page or feature name, e.g. Port Scanner. Leave empty for all."}}),
    _tool("suggest_action", "Show the user a button. target is a page key (" + ", ".join(PAGES) +
          "), 'diagnose' to run the diagnosis, or 'scan:<ip>' to port-scan a device.",
          {"label": {"type": "string"}, "target": {"type": "string"}}, ["label", "target"]),
]


def _digest(rows, step):
    # average receive/send per step seconds
    out = []
    for i in range(0, len(rows), step):
        chunk = rows[i:i + step]
        out.append({"dl": round(sum(r[1] for r in chunk) / len(chunk), 2),
                    "ul": round(sum(r[2] for r in chunk) / len(chunk), 2)})
    return out


def traffic_snapshot(bw_hour, conn_rows, adapter):
    # bw_hour: traffic_history rows for the last hour, oldest first
    snap = {"adapter": adapter, "unit": "Mbps"}
    if bw_hour:
        last10 = bw_hour[-600:]
        snap["last_10_min_per_minute"] = _digest(last10, 60)
        snap["last_60_min_per_5_min"] = _digest(bw_hour, 300)
        n = sum(r[5] for r in bw_hour)
        snap["hour_avg"] = {"receive": round(sum(r[1] * r[5] for r in bw_hour) / n, 2),
                            "send": round(sum(r[2] * r[5] for r in bw_hour) / n, 2)}
        snap["hour_peak"] = {"receive": round(max(r[3] for r in bw_hour), 2),
                             "send": round(max(r[4] for r in bw_hour), 2)}
        snap["now"] = {"receive": bw_hour[-1][1], "send": bw_hour[-1][2]}
    if conn_rows:
        loss = [c[2] for c in conn_rows]
        ping = [c[1] for c in conn_rows if c[1] is not None]
        snap["packet_loss_pct"] = {"avg": round(sum(loss) / len(loss), 1), "worst": max(loss)}
        if ping:
            snap["latency_ms"] = {"avg": round(sum(ping) / len(ping), 1), "max": round(max(ping), 1)}
    return snap


class AppTools:
    """Answers tool calls from a snapshot taken on the GUI thread."""

    def __init__(self, snap: dict):
        self.snap = snap
        self.actions = []

    def call(self, name, args) -> str:
        args = args if isinstance(args, dict) else {}
        fn = getattr(self, "_t_" + name, None)
        if fn is None:
            return json.dumps({"error": f"unknown tool {name}"})
        try:
            out = fn(args)
        except Exception as exc:
            out = {"error": str(exc)}
        text = json.dumps(out, ensure_ascii=False, default=str)
        return text if len(text) < 9000 else text[:9000] + "...(truncated)"

    def _t_get_network_status(self, a):
        s = self.snap
        m = ((s.get("diagnosis") or {}).get("measurements")) or {}
        return {"network": s.get("network"), "selected_adapter_setting": s.get("selected_adapter") or "auto",
                "internet_reachable": m.get("internet_reachable"), "router_reachable": m.get("router_reachable"),
                "router": m.get("router"), "internet": m.get("internet"),
                "diagnosis_available": bool(s.get("diagnosis"))}

    def _t_get_diagnosis(self, a):
        d = self.snap.get("diagnosis")
        if not d:
            return {"available": False, "hint": "The user has not run Network Health yet. Offer suggest_action target 'diagnose'."}
        return d

    def _t_get_devices(self, a):
        d = self.snap.get("devices")
        return {"count": len(d or []), "devices": d} if d else {"available": False, "hint": "No devices discovered yet; Dashboard Rescan or Ping Sweep finds them."}

    def _t_get_port_scan(self, a):
        p = self.snap.get("port_scan")
        return p or {"available": False, "hint": "No port scan yet. Offer suggest_action 'scan:<router ip>'."}

    def _t_get_traffic(self, a):
        t = self.snap.get("traffic") or {}
        return t if t.get("now") else {"available": False, "hint": "No traffic samples yet; Netwer records while it runs."}

    def _t_get_wifi(self, a):
        return self.snap.get("wifi") or {"available": False, "hint": "Not on Wi-Fi or no data."}

    def _t_get_system(self, a):
        return self.snap.get("system") or {"available": False}

    def _t_get_recent_activity(self, a):
        return {"items": self.snap.get("activity") or []}

    def _t_get_app_guide(self, a):
        topic = (a.get("topic") or "").lower().strip()
        rows = [{"title": t, "description": d} for t, d in APP_GUIDE if not topic or topic in t.lower() or topic in d.lower()]
        return {"topics": rows or [{"title": t, "description": d} for t, d in APP_GUIDE]}

    def _t_suggest_action(self, a):
        label, target = str(a.get("label", ""))[:40], str(a.get("target", ""))
        if target == "diagnose":
            target = "health_run"
        ok = target in PAGES or target == "health_run" or (target.startswith("scan:") and len(target) > 5)
        if not ok or not label:
            return {"error": "invalid target"}
        self.actions.append({"label": label, "target": target})
        return {"ok": True}
