import json
import urllib.error
import urllib.request

PROVIDERS = {"anthropic": "Anthropic (Claude)", "gemini": "Google Gemini", "openai": "OpenAI-compatible"}
DEFAULTS = {"anthropic": {"url": "https://api.anthropic.com", "model": "claude-sonnet-5-5"},
            "gemini": {"url": "https://generativelanguage.googleapis.com/v1beta/openai", "model": "gemini-2.5-flash"},
            "openai": {"url": "https://api.openai.com/v1", "model": "gpt-4o-mini"}}
# connection lives in core/ai_secrets.py, which is git ignored
try:
    from core.ai_secrets import AI_CONFIG
except ImportError:
    AI_CONFIG = {"provider": "openai", "url": "", "model": "", "key": ""}
MAX_ROUNDS = 6
MAX_HISTORY = 12


def load_config() -> dict:
    # Load provider and defaults
    from app.store import store
    return dict(AI_CONFIG)
    provider = store.get_setting("ai_provider", "anthropic")
    if provider not in PROVIDERS:
        provider = "anthropic"
    d = DEFAULTS[provider]

    # Try keyring first for the API key, fallback to store
    key = ""
    try:
        import keyring
        key = keyring.get_password("netwer", "ai_api_key") or ""
    except Exception:
        pass
    if not key:
        key = store.get_setting("ai_key", "")

    return {
        "provider": provider,
        "url": store.get_setting("ai_url", "") or d["url"],
        "model": store.get_setting("ai_model", "") or d["model"],
        "key": key
    }


def get_key() -> str:
    cfg = load_config()
    return cfg["key"]


_listeners = []


def add_listener(callback) -> None:
    # panels listen so the status dot updates
    _listeners.append(callback)


def _notify() -> None:
    for callback in list(_listeners):
        try:
            callback()
        except RuntimeError:
            # widget is gone
            try:
                _listeners.remove(callback)
            except ValueError:
                pass
        except Exception:
            pass


def save_config(provider, url, model, key) -> None:
    # Save settings persistently
    from app.store import store
    store.set_setting("ai_provider", provider)
    store.set_setting("ai_url", url.strip())
    store.set_setting("ai_model", model.strip())

    # Securely store key if possible, fallback to store
    key_str = key.strip()
    try:
        import keyring
        if key_str:
            keyring.set_password("netwer", "ai_api_key", key_str)
        else:
            keyring.delete_password("netwer", "ai_api_key")
    except Exception:
        pass
    store.set_setting("ai_key", key_str)
    _notify()


def purge_saved() -> None:
    # Wipe saved config and keys
    from app.store import store
    for name in ("ai_provider", "ai_url", "ai_model", "ai_key"):
        if store.get_setting(name, ""):
            store.set_setting(name, "")
    try:
        import keyring
        keyring.delete_password("netwer", "ai_api_key")
    except Exception:
        pass
    _notify()


def is_configured() -> bool:
    cfg = load_config()
    # Local servers like Ollama don't strictly need a real API key
    return bool(cfg["model"] and (cfg["key"] or cfg["provider"] == "openai" and "localhost" in cfg["url"]))


# --- HTTP helpers ---

def _error_text(err: urllib.error.HTTPError) -> str:
    detail = ""
    try:
        body = json.loads(err.read().decode("utf-8", "replace"))
        if isinstance(body, list) and body:
            body = body[0]
        e = body.get("error", body) if isinstance(body, dict) else body
        detail = (e.get("message") or e.get("detail") or "") if isinstance(e, dict) else str(e)
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
    return f"The AI service returned an error ({err.code}). {detail[:300]}".strip()


def _open(url, headers, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST", headers=headers)
    return urllib.request.urlopen(req, timeout=60)


def _sse(resp, cancel):
    # Stream and parse SSE data lines
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


# --- Provider rounds ---

def _anthropic_round(cfg, system, msgs, tools, cancel):
    body = {"model": cfg["model"], "max_tokens": 1500, "system": system, "messages": msgs, "stream": True}
    if tools:
        body["tools"] = [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]} for t in
                         tools]
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
    if cfg.get("temperature") is not None:
        body["temperature"] = cfg["temperature"]
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
                    if tc.get("extra_content"):
                        c["extra"] = tc["extra_content"]
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
        parsed.append((c["id"] or f"call_{i}", c["name"], args, c["args"] or "{}", c.get("extra")))
    assistant = {"role": "assistant", "content": text or None}
    if parsed:
        assistant["tool_calls"] = []
        for i, n, _a, raw, extra in parsed:
            call = {"id": i, "type": "function", "function": {"name": n, "arguments": raw}}
            if extra:
                call["extra_content"] = extra
            assistant["tool_calls"].append(call)
    yield "end", {"assistant": assistant, "calls": [(i, n, a) for i, n, a, _r, _e in parsed]}


def _tool_messages(provider, results):
    if provider == "anthropic":
        return [{"role": "user", "content": [{"type": "tool_result", "tool_use_id": i, "content": out}
                                             for i, _n, out in results]}]
    msgs = [{"role": "tool", "tool_call_id": i, "content": out} for i, _n, out in results]
    if provider == "gemini":
        for m, (_i, name, _o) in zip(msgs, results):
            m["name"] = name
    return msgs


FRIENDLY = {"get_network_status": "network status", "get_diagnosis": "the diagnosis", "get_devices": "devices",
            "get_port_scan": "the port scan", "get_traffic": "traffic history", "get_wifi": "Wi-Fi details",
            "get_system": "system usage", "get_recent_activity": "recent activity", "get_app_guide": "the app guide",
            "suggest_action": "an action"}


def chat(history, question, system, tools, app_tools, cfg, cancel_event=None):
    # Main chat loop with tool calling & streaming support
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
                results.append((call_id, name, app_tools.call(name, args)))
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


_NOT_CHAT = ("embedding", "aqa", "imagen", "tts", "image", "live", "audio", "realtime", "transcribe",
             "robotics", "computer-use", "search", "moderation", "whisper", "dall", "instruct", "veo")


def list_models(cfg):
    # Fetch model list from the provider API
    try:
        if cfg["provider"] == "anthropic":
            req = urllib.request.Request(cfg["url"].rstrip("/") + "/v1/models?limit=100",
                                         headers={"x-api-key": cfg["key"], "anthropic-version": "2023-06-01"})
        else:
            headers = {"authorization": "Bearer " + cfg["key"]} if cfg["key"] else {}
            req = urllib.request.Request(cfg["url"].rstrip("/") + "/models", headers=headers)
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as err:
        return [], _error_text(err)
    except (urllib.error.URLError, TimeoutError, OSError):
        return [], "Can't reach the AI service. Check your internet connection and the address."
    except ValueError:
        return [], "The address did not return a model list."
    items = body.get("data", body.get("models", [])) if isinstance(body, dict) else body
    names = []
    for it in items or []:
        mid = (it.get("id") or it.get("name") or "") if isinstance(it, dict) else str(it)
        mid = mid.split("/", 1)[1] if mid.startswith("models/") else mid
        if mid:
            names.append(mid)
    if cfg["provider"] == "gemini":
        names = [n for n in names if n.startswith("gemini") and not any(x in n for x in _NOT_CHAT)]
    elif cfg["provider"] == "openai" and "api.openai.com" in cfg["url"]:
        names = [n for n in names if n.startswith(("gpt", "o1", "o3", "o4", "chatgpt"))
                 and not any(x in n for x in _NOT_CHAT)]
    if cfg["provider"] != "anthropic":
        names = sorted(set(names), reverse=True)
    return names, ("" if names else "No models were returned for this key.")


def test_connection(cfg) -> str:
    # Quick connectivity check
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