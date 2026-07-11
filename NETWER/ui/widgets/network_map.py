"""
NETWER — NetworkMap widget.

LAN topology like the reference: Internet at top (green when the connection
is up), Router in the middle with its IP shown BESIDE the icon, and
discovered devices in a row below. Lines connect the tiers and never cross
label text. Device icons are chosen per type from hostname/vendor hints.
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
    if has("camera", "cam", "hikvision", "dahua", "axis", "cctv", "ring",
           "nest cam"):
        return "dev_camera"
    if has("echo", "alexa", "sonos", "speaker", "homepod"):
        return "dev_speaker"
    if has("esp", "espressif", "tuya", "sonoff", "shelly", "bulb", "lifx",
           "nest", "hue", "smart", "iot", "wemo"):
        return "dev_iot"
    if has("desktop", "pc-", "-pc", "windows", "asrock", "msi", "gigabyte"):
        return "dev_pc"
    return "dev_generic"


class NetworkMap(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(190)
        self.setStyleSheet("background: transparent;")
        self._gateway = "—"
        self._router_vendor = ""
        self._devices = []
        self._online = True   # is the internet connection up?

    def set_topology(self, gateway: str, devices: list, router_vendor: str = "",
                     online: bool = True):
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
        icon_r = 16
        node_gap = 8
        label_space = 34

        y_internet = 30
        y_router = h * 0.44
        y_devices = h - label_space - icon_r - 4

        # Line color: green when online, muted when offline
        link_color = QColor(Theme.SUCCESS) if self._online else QColor(Theme.TEXT_FAINT)
        line_pen = QPen(link_color, 1.6)
        line_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(line_pen)

        # Internet -> Router
        p.drawLine(QPointF(cx, y_internet + icon_r + node_gap),
                   QPointF(cx, y_router - icon_r - node_gap))

        n = len(self._devices)
        if n > 0:
            bus_y = y_router + icon_r + 26
            p.drawLine(QPointF(cx, y_router + icon_r + node_gap),
                       QPointF(cx, bus_y))
            xs = self._device_xs(w, n)
            if n > 1:
                p.drawLine(QPointF(xs[0], bus_y), QPointF(xs[-1], bus_y))
            for x in xs:
                p.drawLine(QPointF(x, bus_y),
                           QPointF(x, y_devices - icon_r - node_gap))

        # Internet node — icon green when online
        internet_color = QColor(Theme.SUCCESS) if self._online else QColor(Theme.TEXT_MUTED)
        self._draw_icon(p, cx, y_internet, "internet", internet_color, icon_r)
        self._draw_center_label(p, cx, y_internet + icon_r + 3,
                                "Internet", internet_color.name(), bold=True)

        # Router node — IP shown BESIDE the icon (to the right)
        self._draw_icon(p, cx, y_router, "dev_router", QColor(Theme.ACCENT), icon_r)
        router_label = self._router_vendor or "Router"
        # Name centered under icon
        self._draw_center_label(p, cx, y_router + icon_r + 3, router_label,
                                Theme.TEXT_BODY, bold=True)
        # IP to the right of the icon, vertically centered on it
        if self._gateway and self._gateway != "—":
            p.setPen(QColor(Theme.TEXT_MUTED))
            f = QFont(Theme.FONT_MONO, 8)
            p.setFont(f)
            p.drawText(QRectF(cx + icon_r + 8, y_router - 7, 130, 14),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       self._gateway)

        # Device nodes
        if n > 0:
            xs = self._device_xs(w, n)
            for x, dev in zip(xs, self._devices):
                self._draw_icon(p, x, y_devices, guess_device_icon(dev),
                                QColor(Theme.TEXT_SECONDARY), icon_r)
                name = dev.get("hostname") or dev.get("ip", "?")
                self._draw_center_label(p, x, y_devices + icon_r + 3,
                                        str(name)[:14], Theme.TEXT_BODY, bold=True)
                self._draw_center_label(p, x, y_devices + icon_r + 16,
                                        dev.get("ip", ""), Theme.TEXT_MUTED,
                                        mono=True)
        p.end()

    def _device_xs(self, w, n):
        if n == 1:
            return [w / 2]
        margin = 54
        span = w - 2 * margin
        return [margin + span * i / (n - 1) for i in range(n)]

    def _draw_icon(self, p, cx, cy, icon_name, color, icon_r):
        pm = Icons.pixmap(icon_name, icon_r * 2, color.name())
        p.drawPixmap(int(cx - icon_r), int(cy - icon_r), pm)

    def _draw_center_label(self, p, cx, y_top, text, color, bold=False, mono=False):
        p.setPen(QColor(color))
        family = Theme.FONT_MONO if mono else Theme.FONT_FAMILY
        f = QFont(family, 8)
        f.setBold(bold)
        p.setFont(f)
        p.drawText(QRectF(cx - 70, y_top, 140, 13),
                   Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, text)
