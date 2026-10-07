import time
from collections import deque

from PyQt6.QtCore import QObject, pyqtSignal


class ActivityLog(QObject):
    changed = pyqtSignal()

    MAX_ENTRIES = 50

    def __init__(self):
        super().__init__()
        self._entries = deque(maxlen=self.MAX_ENTRIES)

    def add(self, title: str, detail: str = "", kind: str = "success") -> None:
        self._entries.appendleft({
            "title": title,
            "detail": detail,
            "kind": kind,
            "time": time.time(),
        })
        self.changed.emit()

    def entries(self, limit: int = None):
        items = list(self._entries)
        return items[:limit] if limit else items

    def clear(self) -> None:
        self._entries.clear()
        self.changed.emit()


def time_ago(timestamp: float) -> str:
    delta = max(0, int(time.time() - timestamp))
    if delta < 10:
        return "just now"
    if delta < 60:
        return f"{delta}s ago"
    if delta < 3600:
        return f"{delta // 60}m ago"
    if delta < 86400:
        return f"{delta // 3600}h ago"
    return f"{delta // 86400}d ago"


activity = ActivityLog()
