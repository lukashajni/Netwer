import json
import urllib.error
import urllib.request

PROVIDERS = {"anthropic": "Anthropic (Claude)", "gemini": "Google Gemini", "openai": "OpenAI-compatible"}
DEFAULTS = {"anthropic": {"url": "https://api.anthropic.com", "model": "claude-sonnet-5-5"},
            "gemini": {"url": "https://generativelanguage.googleapis.com/v1beta/openai", "model": "gemini-2.5-flash"},
            "openai": {"url": "https://api.openai.com/v1", "model": "gpt-4o-mini"}}
MAX_ROUNDS = 6
MAX_HISTORY = 12


def load_config() -> dict:
    from app.store import store
    provider = store.get_setting("ai_provider", "anthropic")
    if provider not in PROVIDERS:
        provider = "anthropic"
    d = DEFAULTS[provider]
    return {"provider": provider,
            "url": store.get_setting("ai_url", "") or d["url"],
            "model": store.get_setting("ai_model", "") or d["model"],
            "key": get_key()}


def get_key() -> str:
    from app.store import store
    try:
        import keyring
        saved = keyring.get_password("netwer", "ai_api_key")
        if saved:
            return saved
    except Exception:
        pass
    return (store.get_setting("ai_key", "") or "").strip()


def save_config(provider, url, model, key) -> None:
    from app.store import store
    store.set_setting("ai_provider", provider)
    store.set_setting("ai_url", url.strip())
    store.set_setting("ai_model", model.strip())
    try:
        import keyring
        keyring.set_password("netwer", "ai_api_key", key.strip())
        store.set_setting("ai_key", "")
    except Exception:
        store.set_setting("ai_key", key.strip())


def is_configured() -> bool:
    cfg = load_config()
    # local servers such as Ollama accept any key, so only the URL and model are required there
    return bool(cfg["model"] and (cfg["key"] or cfg["provider"] == "openai" and "localhost" in cfg["url"]))


# -- HTTP --
def _error_text(err: urllib.error.HTTPError) -> str:
    detail = ""
    try:
        body = json.loads(err.read().decode("utf-8", "replace"))
        e = body.get("error", body)
        detail = e.get("message", "") if isinstance(e, dict) else str(e)
    except Exception:
        pass
    if err.code == 401:
        return "The API key was rejected. Check it in the AI settings."
    if err.code == 403:
        return "The key isn't allowed to use this model. " + detail
    if err.code == 405:
        return ("This address doesn't accept AI requests. It is probably a website, not the API address. "
                "Press \u201cReset address and model\u201d in the AI settings.")
    if err.code == 404:
        return "Model or address not found. Check the model name and URL in the AI settings. " + detail
    if err.code == 429:
        return "Rate limit or quota reached. " + (detail or "Try again in a minute.")
    return detail or f"The AI service returned an error ({err.code})."


def _open(url, headers, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST", headers=headers)
    return urllib.request.urlopen(req, timeout=60)


def _sse(resp, cancel):
    # yields the JSON payload of each "data:" line
    for raw in resp:
        if cancel is not None and cancel.is_set():
            return
        line = raw.decode("utf-8", "replace").strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            return
        try:
            yield json.loads(payload)
        except ValueError:
            continue


# -- one round per provider: yields ("text", s) then ("end", info) --
def _anthropic_round(cfg, system, msgs, tools, cancel):
    body = {"model": cfg["model"], "max_tokens": 1500, "system": system, "messages": msgs, "stream": True}
    if tools:
        body["tools"] = [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]} for t in tools]
    headers = {"content-type": "application/json", "x-api-key": cfg["key"], "anthropic-version": "2023-06-01"}
    resp = _open(cfg["url"].rstrip("/") + "/v1/messages", headers, body)
    blocks, raw_json = {}, {}
    with resp:
        for ev in _sse(resp, cancel):
            kind = ev.get("type")
            if kind == "content_block_start":
                b = ev.get("content_block", {})
                blocks[ev["index"]] = ({"type": "text", "text": ""} if b.get("type") == "text"
                                       else {"type": "tool_use", "id": b.get("id"), "name": b.get("name"), "input": {}})
                raw_json[ev["index"]] = ""
            elif kind == "content_block_delta":
                d, i = ev.get("delta", {}), ev["index"]
                if d.get("type") == "text_delta" and i in blocks:
                    blocks[i]["text"] += d.get("text", "")
                    yield "text", d.get("text", "")
                elif d.get("type") == "input_json_delta":
                    raw_json[i] = raw_json.get(i, "") + d.get("partial_json", "")
            elif kind == "error":
                raise RuntimeError((ev.get("error") or {}).get("message", "The AI service reported an error."))
    content, calls = [], []
    for i in sorted(blocks):
        b = blocks[i]
        if b["type"] == "text":
            if b["text"]:
                content.append(b)
        else:
            try:
                b["input"] = json.loads(raw_json.get(i) or "{}")
            except ValueError:
                b["input"] = {}
            content.append(b)
            calls.append((b["id"], b["name"], b["input"]))
    yield "end", {"assistant": {"role": "assistant", "content": content}, "calls": calls}


def _openai_round(cfg, system, msgs, tools, cancel):
    body = {"model": cfg["model"], "stream": True, "messages": [{"role": "system", "content": system}] + msgs}
    if tools:
        body["tools"] = [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                            "parameters": t["parameters"]}} for t in tools]
    headers = {"content-type": "application/json"}
    if cfg["key"]:
        headers["authorization"] = "Bearer " + cfg["key"]
    resp = _open(cfg["url"].rstrip("/") + "/chat/completions", headers, body)
    text, calls = "", {}
    with resp:
        for ev in _sse(resp, cancel):
            if ev.get("error"):
                raise RuntimeError(str(ev["error"].get("message", ev["error"])))
            for choice in ev.get("choices", []):
                delta = choice.get("delta", {})
                if delta.get("content"):
                    text += delta["content"]
                    yield "text", delta["content"]
                for tc in delta.get("tool_calls") or []:
                    idx = tc.get("index")
                    if idx is None:
                        idx = len(calls) if tc.get("id") or not calls else len(calls) - 1
                    c = calls.setdefault(idx, {"id": "", "name": "", "args": ""})
                    c["id"] = tc.get("id") or c["id"]
                    fn = tc.get("function", {})
                    c["name"] = fn.get("name") or c["name"]
                    c["args"] += fn.get("arguments") or ""
    parsed = []
    for i in sorted(calls):
        c = calls[i]
        try:
            args = json.loads(c["args"] or "{}")
        except ValueError:
            args = {}
        parsed.append((c["id"] or f"call_{i}", c["name"], args, c["args"] or "{}"))
    assistant = {"role": "assistant", "content": text or None}
    if parsed:
        assistant["tool_calls"] = [{"id": i, "type": "function", "function": {"name": n, "arguments": raw}}
                                   for i, n, _a, raw in parsed]
    yield "end", {"assistant": assistant, "calls": [(i, n, a) for i, n, a, _r in parsed]}


def _tool_messages(provider, results):
    if provider == "anthropic":
        return [{"role": "user", "content": [{"type": "tool_result", "tool_use_id": i, "content": out}
                                             for i, out in results]}]
    return [{"role": "tool", "tool_call_id": i, "content": out} for i, out in results]


FRIENDLY = {"get_network_status": "network status", "get_diagnosis": "the diagnosis", "get_devices": "devices",
            "get_port_scan": "the port scan", "get_traffic": "traffic history", "get_wifi": "Wi-Fi details",
            "get_system": "system usage", "get_recent_activity": "recent activity", "get_app_guide": "the app guide",
            "suggest_action": "an action"}


def chat(history, question, system, tools, app_tools, cfg, cancel_event=None):
    """Yield {"text"}, {"tool"}, {"action"}, then {"done"}; failures come as {"error"}."""
    msgs = [m for m in history[-MAX_HISTORY:] if m.get("content")] + [{"role": "user", "content": question}]
    while msgs and msgs[0]["role"] != "user":
        msgs.pop(0)
    rnd = _anthropic_round if cfg["provider"] == "anthropic" else _openai_round
    got_text = False
    try:
        for _ in range(MAX_ROUNDS):
            info = None
            for kind, value in rnd(cfg, system, msgs, tools, cancel_event):
                if kind == "text":
                    got_text = True
                    yield {"text": value}
                else:
                    info = value
            if cancel_event is not None and cancel_event.is_set():
                return
            if not info or not info["calls"]:
                if not got_text:
                    yield {"error": "The AI returned an empty answer. Check the model name in the AI settings."}
                else:
                    yield {"done": True}
                return
            msgs.append(info["assistant"])
            results = []
            for call_id, name, args in info["calls"]:
                yield {"tool": FRIENDLY.get(name, name)}
                before = len(app_tools.actions)
                results.append((call_id, app_tools.call(name, args)))
                for act in app_tools.actions[before:]:
                    yield {"action": act}
            msgs.extend(_tool_messages(cfg["provider"], results))
        yield {"text": "\n\n(I stopped after several lookups. Ask again if you need more.)"}
        yield {"done": True}
    except urllib.error.HTTPError as err:
        yield {"error": _error_text(err)}
    except (urllib.error.URLError, TimeoutError, OSError):
        yield {"error": "Can't reach the AI service. Check your internet connection and the URL in the AI settings."}
    except RuntimeError as exc:
        yield {"error": str(exc)}


def test_connection(cfg) -> str:
    """Return "" on success or an error message."""
    for ev in chat([], "Reply with the single word: ok", "You are a connection test.", [], _NoTools(), cfg):
        if "error" in ev:
            return ev["error"]
        if ev.get("done"):
            return ""
    return "No answer received."


class _NoTools:
    actions = []

    def call(self, name, args):
        return "{}"
