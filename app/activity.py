"""
NETWER activity log.

A small in-memory log of things the user has done (ran a ping sweep, saved
a report, completed a speed test...). The Dashboard's Recent Activity card
reads from it; any page can append to it.

It's a module-level singleton with a bounded deque, so any page can record
an event without passing a reference down through the whole app. Entries
are timestamped so the UI can show "2m ago".

Usage:
    from app.activity import activity
    activity.add("Ping sweep completed", "192.168.1.1 - 254", kind="success")
"""

import time
from collections import deque

from PyQt6.QtCore import QObject, pyqtSignal


class ActivityLog(QObject):
    #: Emitted when a new entry is added so open views can refresh.
    changed = pyqtSignal()

    MAX_ENTRIES = 50

    def __init__(self):
        super().__init__()
        self._entries = deque(maxlen=self.MAX_ENTRIES)

    def add(self, title: str, detail: str = "", kind: str = "success") -> None:
        """Record an action.

        title: what happened ("Ping sweep completed")
        detail: supporting text ("192.168.1.1 - 254")
        kind: "success" | "warning" | "error" | "info", picks the icon
        """
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
    """Relative time for display: 'just now', '2m ago', '3h ago'."""
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


#: Application-wide singleton.
activity = ActivityLog()
