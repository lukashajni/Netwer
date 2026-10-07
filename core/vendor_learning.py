from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path


def _store_path() -> Path:
    base = os.environ.get("APPDATA") or os.environ.get("XDG_DATA_HOME")
    if base:
        d = Path(base) / "NETWER"
    else:
        d = Path.home() / ".netwer"
    try:
        d.mkdir(parents=True, exist_ok=True)
        return d / "learned_vendors.json"
    except Exception:
        return Path(__file__).with_name("learned_vendors.json")


_LOCK = threading.Lock()
_LEARNED: dict[str, str] = {}
_LOADED = False


def _norm(mac_or_prefix: str) -> str:
    cleaned = re.sub(r"[^0-9A-Fa-f]", "", mac_or_prefix or "").upper()
    return cleaned[:6]


def load() -> None:
    global _LOADED
    if _LOADED:
        return
    with _LOCK:
        if _LOADED:
            return
        try:
            p = _store_path()
            if p.exists():
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    _LEARNED.update({str(k).upper(): str(v)
                                     for k, v in data.items()})
        except Exception:
            pass
        _LOADED = True


def _save() -> None:
    try:
        _store_path().write_text(
            json.dumps(_LEARNED, indent=2, ensure_ascii=False),
            encoding="utf-8")
    except Exception:
        pass


def lookup(mac_or_prefix: str) -> str | None:
    load()
    return _LEARNED.get(_norm(mac_or_prefix))


def remember(mac_or_prefix: str, vendor: str) -> None:
    if not vendor or vendor.strip().lower() in (
            "unknown", "private (randomized)", ""):
        return
    prefix = _norm(mac_or_prefix)
    if len(prefix) < 6:
        return
    load()
    with _LOCK:
        if prefix in _LEARNED:
            return                       # keep the earlier/taught value
        _LEARNED[prefix] = vendor.strip()
        _save()


def teach(mac_or_prefix: str, vendor: str) -> bool:
    prefix = _norm(mac_or_prefix)
    if len(prefix) < 6:
        return False
    load()
    with _LOCK:
        if vendor and vendor.strip():
            _LEARNED[prefix] = vendor.strip()
        else:
            _LEARNED.pop(prefix, None)
        _save()
    return True


def all_learned() -> dict[str, str]:
    load()
    return dict(_LEARNED)
