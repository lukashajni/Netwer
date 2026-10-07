from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path


def _store_path() -> Path:
    base = os.environ.get("APPDATA") or os.environ.get("XDG_DATA_HOME")
    d = Path(base) / "NETWER" if base else Path.home() / ".netwer"
    try:
        d.mkdir(parents=True, exist_ok=True)
        return d / "device_names.json"
    except Exception:
        return Path(__file__).with_name("device_names.json")


_LOCK = threading.Lock()
_NAMES: dict[str, str] = {}
_LOADED = False


def _key(device: dict) -> str | None:
    mac = re.sub(r"[^0-9A-Fa-f]", "", (device.get("mac") or "")).upper()
    if len(mac) == 12:
        return "MAC:" + mac
    ip = (device.get("ip") or "").strip()
    return "IP:" + ip if ip else None


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
                    _NAMES.update({str(k): str(v) for k, v in data.items()})
        except Exception:
            pass
        _LOADED = True


def _save() -> None:
    try:
        _store_path().write_text(
            json.dumps(_NAMES, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def get(device: dict) -> str | None:
    load()
    k = _key(device)
    return _NAMES.get(k) if k else None


def set_name(device: dict, name: str) -> bool:
    k = _key(device)
    if not k:
        return False
    load()
    with _LOCK:
        if name and name.strip():
            _NAMES[k] = name.strip()
        else:
            _NAMES.pop(k, None)
        _save()
    return True


def all_names() -> dict[str, str]:
    load()
    return dict(_NAMES)
