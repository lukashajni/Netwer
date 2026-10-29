"""AI assistant for Network Health"""
import json
import os
import urllib.error
import urllib.request


# The instructions live in core/ai_prompts.py, which is git ignored.
try:
    from core.ai_prompts import ASSISTANT_PROMPT as SYSTEM_PROMPT
except ImportError:
    from core.ai_prompts_example import ASSISTANT_PROMPT as SYSTEM_PROMPT


def get_model() -> str:
    from app.store import store
    return store.get_setting("assistant_model", DEFAULT_MODEL) or DEFAULT_MODEL


def _round(v, n=1):
    return None if v is None else round(float(v), n)


def traffic_summary(bandwidth_rows, conn_rows, adapter="") -> dict:
    out = {"adapter": adapter, "window": "last 5 minutes"}
    if bandwidth_rows:
        n = sum(r[5] for r in bandwidth_rows)
        out["download_mbps"] = {
            "avg": _round(sum(r[1] * r[5] for r in bandwidth_rows) / n, 2),
            "peak": _round(max(r[3] for r in bandwidth_rows), 2)}
        out["upload_mbps"] = {
            "avg": _round(sum(r[2] * r[5] for r in bandwidth_rows) / n, 2),
            "peak": _round(max(r[4] for r in bandwidth_rows), 2)}
    if conn_rows:
        losses = [c[2] for c in conn_rows]
        pings = [c[1] for c in conn_rows if c[1] is not None]
        out["packet_loss_pct"] = {"avg": _round(sum(losses) / len(losses)),
                                  "worst": _round(max(losses))}
        if pings:
            out["latency_ms"] = {"avg": _round(sum(pings) / len(pings)),
                                 "max": _round(max(pings))}
    return out


def build_context(report=None, devices=None, port_scan=None, traffic=None) -> dict:
    ctx = {"diagnosis": None, "devices": [], "port_scan": None, "traffic": traffic or None}

    if report:
        m = dict(report.get("measurements") or {})
        m.pop("ssid", None)
        ctx["diagnosis"] = {
            "headline": report.get("headline"),
            "summary": report.get("summary"),
            "severity": report.get("severity"),
            "findings": [{k: f.get(k) for k in ("severity", "title", "detail", "action")}
                         for f in report.get("findings", [])],
            "measurements": m,
        }

    for d in (devices or [])[:MAX_DEVICES]:
        ctx["devices"].append({k: d.get(k) for k in
                               ("ip", "name", "vendor", "kind", "is_gateway") if d.get(k)})

    if port_scan and (port_scan.get("results") or port_scan.get("target")):
        ctx["port_scan"] = {
            "target": port_scan.get("target"),
            "device_type": port_scan.get("device_type"),
            "open_ports": [{"port": r.get("port"), "service": r.get("service"),
                            "banner": (r.get("banner") or "")[:60]}
                           for r in port_scan.get("results", [])],
        }
    return ctx


def build_messages(history: list, question: str, context: dict) -> list:
    turns = [m for m in history if m.get("role") in ("user", "assistant") and m.get("content")]
    turns = turns[-MAX_HISTORY:]
    while turns and turns[0]["role"] != "user":
        turns.pop(0)
    snapshot = json.dumps(context, ensure_ascii=False, default=str)
    final = f"<snapshot>\n{snapshot}\n</snapshot>\n\n{question}"
    return turns + [{"role": "user", "content": final}]


def _http_error(err: urllib.error.HTTPError) -> str:
    detail = ""
    try:
        detail = json.loads(err.read().decode("utf-8", "replace")).get("error", {}).get("message", "")
    except Exception:
        pass
    if err.code == 401:
        return "The API key was rejected. Check it with the \u201cAPI key\u201d button."
    if err.code == 403:
        return "This API key isn't allowed to use that model. " + detail
    if err.code == 429:
        return "Rate limit reached. Wait a minute and try again."
    if err.code in (500, 502, 503, 529):
        return "The AI service is busy right now. Try again shortly."
    return detail or f"The AI service returned an error ({err.code})."


def stream_answer(messages, model=DEFAULT_MODEL, max_tokens=900, cancel_event=None):
    body = json.dumps({"model": model, "max_tokens": max_tokens, "system": SYSTEM_PROMPT,
                       "messages": messages, "stream": True}).encode("utf-8")
    req = urllib.request.Request(API_URL, data=body, method="POST", headers={
        "content-type": "application/json",
        "anthropic-version": API_VERSION, "accept": "text/event-stream"})
    try:
        resp = urllib.request.urlopen(req, timeout=30)
    except urllib.error.HTTPError as err:
        yield {"error": _http_error(err)}
        return
    except (urllib.error.URLError, TimeoutError, OSError):
        yield {"error": "Can't reach the AI service. Check your internet connection."}
        return

    try:
        with resp:
            for raw in resp:
                if cancel_event is not None and cancel_event.is_set():
                    return
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                try:
                    data = json.loads(line[5:].strip())
                except ValueError:
                    continue
                kind = data.get("type")
                if kind == "content_block_delta":
                    delta = data.get("delta") or {}
                    if delta.get("type") == "text_delta" and delta.get("text"):
                        yield {"text": delta["text"]}
                elif kind == "error":
                    yield {"error": (data.get("error") or {}).get("message", "The AI service reported an error.")}
                    return
                elif kind == "message_stop":
                    break
    except (TimeoutError, OSError):
        yield {"error": "The connection to the AI service was interrupted."}
        return
    yield {"done": True}