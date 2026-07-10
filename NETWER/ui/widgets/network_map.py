"""
NETWER — NetworkMap widget.

Draws the LAN topology like the reference mockup:

        [ Internet ]
             |
        [ Router ]
        192.168.x.1
     ┌────┬────┬────┐
   [dev][dev][dev][dev]

Internet at top, router in the middle, discovered devices in a row below,
all connected with lines. Node icons come from qtawesome and are chosen
per-device (PC, phone, NAS, printer, router) by a simple heuristic.
"""

from PyQt6.QtCore import Qt, QRectF, QPointF
from PyQt6.QtGui import QPainter, QColor, QPen, QFont
from PyQt6.QtWidgets import QWidget

from app.theme import Theme
from app.resources import Icons


def _guess_icon(dev: dict) -> str:
    """Pick an icon name for a device based on hostname/vendor hints."""
    text = f"{dev.get('hostname','')} {dev.get('vendor','')}".lower()
    if any(k in text for k in ("router", "mikrotik", "gateway", "ubiquiti", "tp-link", "netgear")):
        return "network"
    if any(k in text for k in ("phone", "iphone", "android", "samsung", "xiaomi", "pixel")):
        return "ping"  # phone-ish; qtawesome mobile fallback handled below
    if any(k in text for k in ("nas", "synology", "qnap", "server", "storage")):
        return "resources"
    if any(k in text for k in ("printer", "hp", "canon", "epson", "brother")):
        return "report"
    return "system"  # generic PC/device


class NetworkMap(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(230)
        self.setStyleSheet("background: transparent;")
        self._gateway = "—"
        self._router_vendor = ""
        self._devices = []  # list of dicts: hostname, ip, vendor

    def set_topology(self, gateway: str, devices: list, router_vendor: str = ""):
        self._gateway = gateway or "—"
        self._router_vendor = router_vendor
        # Cap at 5 devices so the row fits; router is shown separately.
        self._devices = [d for d in devices
                         if d.get("ip") != gateway][:5]
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        cx = w / 2

        y_internet = 26
        y_router = h * 0.42
        y_devices = h - 46

        line_pen = QPen(QColor(Theme.SUCCESS), 1.6)
        p.setPen(line_pen)

        # Internet -> Router vertical line
        p.drawLine(QPointF(cx, y_internet + 14), QPointF(cx, y_router - 14))

        # Router -> devices: vertical drop then horizontal bus then drops
        n = len(self._devices)
        if n > 0:
            bus_y = (y_router + y_devices) / 2
            p.drawLine(QPointF(cx, y_router + 16), QPointF(cx, bus_y))
            xs = self._device_xs(w, n)
            # horizontal bus
            p.drawLine(QPointF(xs[0], bus_y), QPointF(xs[-1], bus_y))
            # drops to each device
            for x in xs:
                p.drawLine(QPointF(x, bus_y), QPointF(x, y_devices - 16))

        # Nodes
        self._draw_node(p, cx, y_internet, "internet", "Internet", "", Theme.ACCENT)
        router_label = self._router_vendor or "Router"
        self._draw_node(p, cx, y_router, "network", router_label, self._gateway, Theme.ACCENT)

        if n > 0:
            xs = self._device_xs(w, n)
            for x, dev in zip(xs, self._devices):
                name = dev.get("hostname") or dev.get("ip", "?")
                self._draw_node(p, x, y_devices, _guess_icon(dev),
                                str(name)[:12], dev.get("ip", ""), Theme.TEXT_SECONDARY)
        p.end()

    def _device_xs(self, w, n):
        if n == 1:
            return [w / 2]
        margin = 46
        span = w - 2 * margin
        return [margin + span * i / (n - 1) for i in range(n)]

    def _draw_node(self, p, cx, cy, icon_name, label, sublabel, icon_color):
        # Icon
        size = 26
        pm = Icons.pixmap(icon_name, size, icon_color)
        p.drawPixmap(int(cx - size / 2), int(cy - size / 2), pm)

        # Label below
        p.setPen(QColor(Theme.TEXT_BODY))
        f = QFont(Theme.FONT_FAMILY, 8)
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(cx - 60, cy + size / 2 + 2, 120, 14),
                   Qt.AlignmentFlag.AlignCenter, label)

        if sublabel:
            p.setPen(QColor(Theme.TEXT_MUTED))
            f2 = QFont(Theme.FONT_MONO, 7)
            p.setFont(f2)
            p.drawText(QRectF(cx - 60, cy + size / 2 + 16, 120, 12),
                       Qt.AlignmentFlag.AlignCenter, sublabel)
