"""
NETWER — NetworkMap widget.

LAN topology: Internet (top), Router (middle), devices (row below).
- Internet: label sits to the RIGHT of the globe icon
- Router: name + IP stacked to the RIGHT of the router icon (name above IP)
- Devices: icon with name + IP stacked below, clearly separated
- Connection lines are green when online, and routed so they never cross
  any icon or text.
"""

from PyQt6.QtCore import Qt, QRectF, QPointF
from PyQt6.QtGui import QPainter, QColor, QPen, QFont
from PyQt6.QtWidgets import QWidget

from app.theme import Theme
from app.resources import Icons


def guess_device_icon(dev: dict) -> str:
    text = f"{dev.get('hostname','')} {dev.get('vendor','')}".lower()

    def has(*words):
        return any(w in text for w in words)

    if has("router", "mikrotik", "gateway", "ubiquiti", "tp-link", "netgear",
           "asus", "fritz", "openwrt", "d-link", "zyxel", "cisco", "unifi"):
        return "dev_router"
    if has("tv", "television", "bravia", "roku", "chromecast", "firetv",
           "shield", "appletv", "vizio", "samsung tv", "lg tv"):
        return "dev_tv"
    if has("watch", "band"):
        return "dev_watch"
    if has("ipad", "tablet", "tab-"):
        return "dev_tablet"
    if has("phone", "iphone", "android", "galaxy", "pixel", "xiaomi",
           "redmi", "oneplus", "huawei", "oppo", "vivo", "mobile"):
        return "dev_phone"
    if has("laptop", "notebook", "macbook", "thinkpad", "ideapad"):
        return "dev_laptop"
    if has("nas", "synology", "qnap", "storage", "server", "truenas",
           "western digital", "seagate"):
        return "dev_nas"
    if has("printer", "print", "canon", "epson", "brother", "laserjet",
           "officejet"):
        return "dev_printer"
    if has("playstation", "ps4", "ps5", "xbox", "nintendo", "switch"):
        return "dev_console"
    if has("camera", "cam", "hikvision", "dahua", "axis", "cctv", "ring"):
        return "dev_camera"
    if has("echo", "alexa", "sonos", "speaker", "homepod"):
        return "dev_speaker"
    if has("esp", "espressif", "tuya", "sonoff", "shelly", "bulb", "lifx",
           "nest", "hue", "smart", "iot", "wemo"):
        return "dev_iot"
    if has("desktop", "pc-", "-pc", "windows", "asrock", "msi", "gigabyte"):
        return "dev_pc"
    return "dev_generic"


def device_display_name(dev: dict) -> str:
    """Best available name: hostname, else vendor, else IP."""
    hostname = (dev.get("hostname") or "").strip()
    if hostname and hostname.lower() not in ("unknown", "?", ""):
        return hostname
    vendor = (dev.get("vendor") or "").strip()
    if vendor and vendor.lower() != "unknown":
        return vendor
    return dev.get("ip", "?")


class NetworkMap(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(190)
        self.setStyleSheet("background: transparent;")
        self._gateway = "—"
        self._router_vendor = ""
        self._devices = []
        self._online = True

    def set_topology(self, gateway, devices, router_vendor="", online=True):
        self._gateway = gateway or "—"
        self._router_vendor = router_vendor
        self._online = online
        self._devices = [d for d in devices if d.get("ip") != gateway][:5]
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        cx = w / 2
        icon_r = 17
        gap = 12          # guaranteed clearance between a line end and an icon
        label_h = 32      # space under a device icon for name + IP

        # Lay out from the bottom up so spacing is guaranteed regardless of
        # the widget's height. Devices sit above their labels; the bus sits
        # a fixed clearance above the device icons; the router above that.
        y_devices = h - label_h - icon_r - 4
        bus_y = y_devices - icon_r - gap - 14      # bus is clearly above icons
        y_router = bus_y - 26 - icon_r             # router above the bus
        y_internet = icon_r + 8   # pinned to the top of the map area

        link_color = QColor(Theme.SUCCESS) if self._online else QColor(Theme.TEXT_FAINT)
        pen = QPen(link_color, 2.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)

        # ── Internet -> Router (vertical, ends at icon edges) ──
        p.drawLine(QPointF(cx, y_internet + icon_r + gap),
                   QPointF(cx, y_router - icon_r - gap))

        # ── Router -> bus -> devices ──
        n = len(self._devices)
        if n > 0:
            p.drawLine(QPointF(cx, y_router + icon_r + gap), QPointF(cx, bus_y))
            xs = self._device_xs(w, n)
            if n > 1:
                p.drawLine(QPointF(xs[0], bus_y), QPointF(xs[-1], bus_y))
            for x in xs:
                p.drawLine(QPointF(x, bus_y),
                           QPointF(x, y_devices - icon_r - gap))

        # ── Internet node: icon + "Internet" label to the RIGHT ──
        icol = QColor(Theme.SUCCESS) if self._online else QColor(Theme.TEXT_MUTED)
        self._icon(p, cx, y_internet, "internet", icol, icon_r)
        self._text_left(p, cx + icon_r + 8, y_internet, "Internet",
                        icol.name(), bold=True, size=9)

        # ── Router node: icon + name (above) + IP (below) to the RIGHT ──
        self._icon(p, cx, y_router, "dev_router", QColor(Theme.ACCENT), icon_r)
        router_name = self._router_vendor or "Router"
        rx = cx + icon_r + 8
        self._text_left(p, rx, y_router - 7, router_name, Theme.TEXT_BODY,
                        bold=True, size=9)
        if self._gateway and self._gateway != "—":
            self._text_left(p, rx, y_router + 6, self._gateway,
                            Theme.TEXT_MUTED, mono=True, size=8)

        # ── Device nodes: icon with name + IP stacked BELOW, separated ──
        if n > 0:
            xs = self._device_xs(w, n)
            for x, dev in zip(xs, self._devices):
                self._icon(p, x, y_devices, guess_device_icon(dev),
                           QColor(Theme.TEXT_SECONDARY), icon_r)
                name = device_display_name(dev)
                self._text_center(p, x, y_devices + icon_r + 5, str(name)[:14],
                                  Theme.TEXT_BODY, bold=True, size=8)
                self._text_center(p, x, y_devices + icon_r + 18,
                                  dev.get("ip", ""), Theme.TEXT_MUTED,
                                  mono=True, size=8)
        p.end()

    def _device_xs(self, w, n):
        if n == 1:
            return [w / 2]
        margin = 56
        span = w - 2 * margin
        return [margin + span * i / (n - 1) for i in range(n)]

    def _icon(self, p, cx, cy, name, color, r):
        pm = Icons.pixmap(name, r * 2, color.name())
        p.drawPixmap(int(cx - r), int(cy - r), pm)

    def _text_center(self, p, cx, y_top, text, color, bold=False, mono=False, size=8):
        p.setPen(QColor(color))
        fam = Theme.FONT_MONO if mono else Theme.FONT_FAMILY
        f = QFont(fam, size); f.setBold(bold)
        p.setFont(f)
        p.drawText(QRectF(cx - 70, y_top, 140, 13),
                   Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, text)

    def _text_left(self, p, x, cy, text, color, bold=False, mono=False, size=8):
        """Draw text left-aligned, vertically centered on cy."""
        p.setPen(QColor(color))
        fam = Theme.FONT_MONO if mono else Theme.FONT_FAMILY
        f = QFont(fam, size); f.setBold(bold)
        p.setFont(f)
        p.drawText(QRectF(x, cy - 8, 150, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
