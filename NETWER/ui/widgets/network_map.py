"""
NETWER — NetworkMap widget.

Draws the LAN topology: Internet at top, Router in the middle, discovered
devices in a row below, connected with lines. Device icons are chosen per
type (PC, laptop, phone, TV, NAS, printer, console, IoT) from hostname and
vendor hints. Lines stop cleanly ABOVE each icon so they never cross labels.
"""

from PyQt6.QtCore import Qt, QRectF, QPointF
from PyQt6.QtGui import QPainter, QColor, QPen, QFont
from PyQt6.QtWidgets import QWidget

from app.theme import Theme
from app.resources import Icons


def guess_device_icon(dev: dict) -> str:
    """Pick an icon name based on hostname/vendor hints."""
    text = f"{dev.get('hostname','')} {dev.get('vendor','')}".lower()

    def has(*words):
        return any(w in text for w in words)

    if has("router", "mikrotik", "gateway", "ubiquiti", "tp-link",
           "netgear", "asus", "fritz", "openwrt"):
        return "dev_router"
    if has("tv", "television", "samsung tv", "lg tv", "bravia", "roku",
           "chromecast", "firetv", "shield", "appletv"):
        return "dev_tv"
    if has("phone", "iphone", "android", "galaxy", "pixel", "xiaomi",
           "redmi", "oneplus", "huawei", "mobile"):
        return "dev_phone"
    if has("laptop", "notebook", "macbook", "thinkpad", "ideapad"):
        return "dev_laptop"
    if has("nas", "synology", "qnap", "storage", "server", "truenas"):
        return "dev_nas"
    if has("printer", "print", "canon", "epson", "brother", "hp laserjet"):
        return "dev_printer"
    if has("playstation", "ps4", "ps5", "xbox", "nintendo", "switch"):
        return "dev_console"
    if has("esp", "espressif", "tuya", "sonoff", "shelly", "bulb", "lifx",
           "nest", "hue", "smart", "iot"):
        return "dev_iot"
    if has("desktop", "pc-", "-pc", "windows"):
        return "dev_pc"
    return "dev_generic"


class NetworkMap(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(250)
        self.setStyleSheet("background: transparent;")
        self._gateway = "—"
        self._router_vendor = ""
        self._devices = []

    def set_topology(self, gateway: str, devices: list, router_vendor: str = ""):
        self._gateway = gateway or "—"
        self._router_vendor = router_vendor
        self._devices = [d for d in devices if d.get("ip") != gateway][:5]
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        cx = w / 2
        icon_r = 15          # icon half-size
        node_gap = 6         # gap between line end and icon

        # Vertical positions — leave room for the label UNDER each icon
        y_internet = 24
        y_router = h * 0.44
        y_devices = h - 48

        line_pen = QPen(QColor(Theme.SUCCESS), 1.5)
        line_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(line_pen)

        # Internet -> Router (stop above/below icons, not through them)
        p.drawLine(QPointF(cx, y_internet + icon_r + node_gap),
                   QPointF(cx, y_router - icon_r - node_gap))

        n = len(self._devices)
        if n > 0:
            # Router drops to a horizontal bus, bus spans devices, each drops down
            bus_y = y_router + (y_devices - y_router) * 0.52
            p.drawLine(QPointF(cx, y_router + icon_r + node_gap),
                       QPointF(cx, bus_y))
            xs = self._device_xs(w, n)
            if n > 1:
                p.drawLine(QPointF(xs[0], bus_y), QPointF(xs[-1], bus_y))
            for x in xs:
                p.drawLine(QPointF(x, bus_y),
                           QPointF(x, y_devices - icon_r - node_gap))

        # Nodes (icons + labels)
        self._draw_node(p, cx, y_internet, "internet", "Internet", "",
                        Theme.ACCENT, icon_r)
        router_label = self._router_vendor or "Router"
        self._draw_node(p, cx, y_router, "dev_router", router_label,
                        self._gateway, Theme.ACCENT, icon_r)

        if n > 0:
            xs = self._device_xs(w, n)
            for x, dev in zip(xs, self._devices):
                name = dev.get("hostname") or dev.get("ip", "?")
                self._draw_node(p, x, y_devices, guess_device_icon(dev),
                                str(name)[:14], dev.get("ip", ""),
                                Theme.TEXT_SECONDARY, icon_r)
        p.end()

    def _device_xs(self, w, n):
        if n == 1:
            return [w / 2]
        margin = 52
        span = w - 2 * margin
        return [margin + span * i / (n - 1) for i in range(n)]

    def _draw_node(self, p, cx, cy, icon_name, label, sublabel, icon_color, icon_r):
        # Icon centered at (cx, cy)
        size = icon_r * 2
        pm = Icons.pixmap(icon_name, size, icon_color)
        p.drawPixmap(int(cx - icon_r), int(cy - icon_r), pm)

        # Name label below the icon
        p.setPen(QColor(Theme.TEXT_BODY))
        f = QFont(Theme.FONT_FAMILY, 8)
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(cx - 65, cy + icon_r + 4, 130, 13),
                   Qt.AlignmentFlag.AlignCenter, label)

        # IP sublabel
        if sublabel:
            p.setPen(QColor(Theme.TEXT_MUTED))
            f2 = QFont(Theme.FONT_MONO, 7)
            p.setFont(f2)
            p.drawText(QRectF(cx - 65, cy + icon_r + 17, 130, 12),
                       Qt.AlignmentFlag.AlignCenter, sublabel)
