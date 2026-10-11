
from threading import RLock

_lock = RLock()
_offline_mode = True


def set_offline_mode(enabled):
    global _offline_mode
    with _lock:
        _offline_mode = bool(enabled)


def is_offline_mode():
    with _lock:
        return _offline_mode
