"""
NETWER notification center.

A tiny in-memory pub/sub for app notifications (host down, scan complete,
new device, etc.). Widgets push notifications; the TopBar bell and the
Notifications panel subscribe to render them and the unread count.

Separate from the activity feed (which is a dashboard widget): this is the
global, cross-page notification stream shown in the slide-in panel.
"""

from datetime import datetime


class _Notification:
    __slots__ = ("title", "detail", "kind", "ts", "read")

    def __init__(self, title, detail="", kind="info"):
        self.title = title
        self.detail = detail
        self.kind = kind          # success | warning | error | info
        self.ts = datetime.now()
        self.read = False


class NotificationCenter:
    def __init__(self):
        self._items = []          # newest first
        self._listeners = []
        self._max = 50

    def subscribe(self, callback):
        """callback() is called whenever notifications change."""
        self._listeners.append(callback)

    def _emit(self):
        for cb in list(self._listeners):
            try:
                cb()
            except Exception:
                pass

    def push(self, title, detail="", kind="info"):
        self._items.insert(0, _Notification(title, detail, kind))
        del self._items[self._max:]
        self._emit()

    # Settings-aware helpers.
    # These respect the on/off toggles in Settings, so a disabled category
    # produces no notification. Pages should call these instead of push()
    # for the three toggleable categories.
    def notify_host_down(self, host, up):
        from app.store import store
        if not store.get_setting("notify_host_down", True):
            return
        if up:
            self.push(f"Host recovered", f"{host} is reachable again",
                      kind="success")
        else:
            self.push(f"Host unreachable", f"{host} stopped responding",
                      kind="error")

    def notify_scan_done(self, title, detail=""):
        from app.store import store
        if not store.get_setting("notify_scan_done", True):
            return
        self.push(title, detail, kind="success")

    def notify_new_device(self, name, ip):
        from app.store import store
        if not store.get_setting("notify_new_device", True):
            return
        self.push("New device on network", f"{name} ({ip})", kind="info")

    def items(self):
        return list(self._items)

    def unread_count(self):
        return sum(1 for n in self._items if not n.read)

    def mark_all_read(self):
        for n in self._items:
            n.read = True
        self._emit()

    def clear(self):
        self._items = []
        self._emit()


# Module-level singleton.
notifications = NotificationCenter()
