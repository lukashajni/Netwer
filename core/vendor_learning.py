"""Self-building vendor database.

NETWER ships with a built-in OUI table, but it can't know every device on
Earth. This module lets the app *learn*: every time it successfully resolves a
vendor online, it remembers it; and the user can correct a wrong/blank guess,
which is also remembered. Over time the local database fills in, so the app
gets better the more it's used — even offline.

Everything is stored in a small JSON file next to the app's other settings, so
learned vendors survive restarts. Keys are 6-hex-digit OUI prefixes (the first
half of a MAC), values are vendor names.
"""
from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path


def _store_path() -> Path:
    """Where the learned DB lives. Uses the same per-user app dir as settings,
    falling back to the module folder if that can't be determined."""
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
    """Normalise a MAC or prefix to a 6-hex-digit uppercase OUI."""
    cleaned = re.sub(r"[^0-9A-Fa-f]", "", mac_or_prefix or "").upper()
    return cleaned[:6]


def load() -> None:
    """Load the learned DB from disk once (idempotent)."""
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
    """Return a learned vendor for this MAC/prefix, or None."""
    load()
    return _LEARNED.get(_norm(mac_or_prefix))


def remember(mac_or_prefix: str, vendor: str) -> None:
    """Record a vendor learned from a successful online lookup. Won't
    overwrite an existing (possibly user-corrected) entry, and ignores blanks
    and placeholders."""
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
    """User correction — always wins and is persisted. Returns True if stored.
    Passing an empty vendor forgets a previously taught entry."""
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
