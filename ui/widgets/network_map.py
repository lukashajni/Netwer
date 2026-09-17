"""
NETWER — NetworkMap widget (rebuilt on real layouts, not hand-painted math).

Architecture: Internet / Router / Devices are real child widgets arranged
by Qt's layout engine (QVBoxLayout + QHBoxLayout), the same system that
lays out the whole Dashboard. Qt guarantees these never overlap, no matter
the widget's size - no more fragile pixel arithmetic.

Connector lines are drawn in NetworkMap's own paintEvent, which Qt always
renders behind child widgets. That means the icons are structurally
guaranteed to sit on top of the lines - a line can never visually cross a
logo, by construction, not by careful coordinate tuning.
"""

from PyQt6.QtCore import Qt, pyqtSignal, QPoint, QPointF
from PyQt6.QtGui import QPainter, QColor, QPen
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel

from app.theme import Theme
from app.resources import Icons


def guess_device_icon(dev: dict) -> str:
    """Pick an icon name based on hostname/vendor hints.
    A kind determined by fingerprinting (Bonjour name / port signature) is
    more reliable than guessing from text, so trust it first. """
    kind = (dev.get("kind") or "").strip()
    if kind.startswith("dev_"):
        return kind

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
    """Best available name, in order: a name the user gave the device, its real
    hostname, a real manufacturer, else the IP.
    A name the user typed always wins."""
    try:
        from core import device_names
        custom = device_names.get(dev)
        if custom:
            return custom
    except Exception:
        pass
    hostname = (dev.get("hostname") or "").strip()
    if hostname and hostname.lower() not in ("unknown", "?", ""):
        # A hostname that's just the IP repeated isn't a real name.
        if hostname != dev.get("ip", ""):
            return hostname
    vendor = (dev.get("vendor") or "").strip()
    generic = ("unknown", "private (randomized)", "private", "randomized", "")
    if vendor and vendor.lower() not in generic:
        # "Apple (private address)" is useful detail, but as a "name" the
        # manufacturer alone reads better under an icon.
        return vendor.replace(" (private address)", "")
    return dev.get("ip", "?")


class _LabeledIcon(QWidget):
    """Icon with title (+ optional subtitle) to its right.

    Layout trick: the node is symmetric around its ICON. Empty space of the
    same width as the text block is reserved on the left, so when the node
    is centered in the map, the ICON lands exactly on the map's centerline -
    the same centerline the device row centers on.
    """

    TEXT_WIDTH = 120   # room for "MikroTik" + an IP address

    def __init__(self, icon_name, icon_color, title, subtitle="",
                 subtitle_mono=False, title_color=None, icon_size=32, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(9)

        # Mirror spacer: same width as the text block, on the left.
        left_spacer = QWidget()
        left_spacer.setFixedWidth(self.TEXT_WIDTH)
        left_spacer.setStyleSheet("background: transparent;")
        lay.addWidget(left_spacer)

        self.icon_label = QLabel()
        self.icon_label.setFixedSize(icon_size, icon_size)
        self.icon_label.setStyleSheet("background: transparent;")
        lay.addWidget(self.icon_label)

        text_holder = QWidget()
        text_holder.setFixedWidth(self.TEXT_WIDTH)
        text_holder.setStyleSheet("background: transparent;")
        text_box = QVBoxLayout(text_holder)
        text_box.setSpacing(0)
        text_box.setContentsMargins(0, 0, 0, 0)
        text_box.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.title_label = QLabel(title)
        self.title_label.setStyleSheet("background: transparent;")
        text_box.addWidget(self.title_label)

        self.subtitle_label = None
        if subtitle:
            self.subtitle_label = QLabel(subtitle)
            self.subtitle_label.setStyleSheet("background: transparent;")
            text_box.addWidget(self.subtitle_label)

        lay.addWidget(text_holder)

        self._icon_name = icon_name
        self._subtitle_mono = subtitle_mono
        self.set_colors(icon_color, title_color or Theme.TEXT_BODY)

    def set_colors(self, icon_color, title_color):
        self.icon_label.setPixmap(Icons.pixmap(self._icon_name,
                                               self.icon_label.width(), icon_color))
        self.title_label.setStyleSheet(
            f"color: {title_color}; font-family: {Theme.FONT_FAMILY};"
            f"font-size: 12px; font-weight: 600; background: transparent;"
        )
        if self.subtitle_label:
            font = Theme.FONT_MONO if self._subtitle_mono else Theme.FONT_FAMILY
            self.subtitle_label.setStyleSheet(
                f"color: {Theme.TEXT_MUTED}; font-family: '{font}';"
                f"font-size: 11px; background: transparent;"
            )

    def set_title(self, text):
        self.title_label.setText(text)

    def set_subtitle(self, text):
        if self.subtitle_label:
            self.subtitle_label.setText(text)


class _DeviceNode(QWidget):
    """Icon centered above a name + IP, stacked below - used for devices.

    Clicking one asks the map to open that device's details, so the static map
    stays as useful as the radar."""

    def __init__(self, icon_name, icon_color, name, ip, icon_size=28,
                 device=None, on_click=None, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        self._device = device
        self._on_click = on_click
        if on_click is not None:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 0, 4, 0)
        lay.setSpacing(4)
        lay.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self.icon_label = QLabel()
        self.icon_label.setFixedSize(icon_size, icon_size)
        self.icon_label.setPixmap(Icons.pixmap(icon_name, icon_size, icon_color))
        self.icon_label.setStyleSheet("background: transparent;")
        lay.addWidget(self.icon_label, alignment=Qt.AlignmentFlag.AlignHCenter)

        name_lbl = QLabel(name)
        name_lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        name_lbl.setStyleSheet(
            f"color: {Theme.TEXT_BODY}; font-family: {Theme.FONT_FAMILY};"
            f"font-size: 11px; font-weight: 600; background: transparent;"
        )
        lay.addWidget(name_lbl)

        ip_lbl = QLabel(ip)
        ip_lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        ip_lbl.setStyleSheet(
            f"color: {Theme.TEXT_MUTED}; font-family: {Theme.FONT_MONO};"
            f"font-size: 10px; background: transparent;"
        )
        lay.addWidget(ip_lbl)


    def mousePressEvent(self, event):
        if (event.button() == Qt.MouseButton.LeftButton
                and self._on_click and self._device):
            self._on_click(self._device)


class NetworkMap(QWidget):
    # Emitted with the device dict when a device node is clicked.
    node_clicked = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        self.setMinimumHeight(180)
        self._online = True
        self._gateway = "—"
        self._router_vendor = ""
        self._devices = []

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 10, 6, 8)
        root.setSpacing(0)

        self._internet_node = _LabeledIcon(
            "internet", Theme.SUCCESS, "Internet", icon_size=32)
        root.addWidget(self._internet_node, alignment=Qt.AlignmentFlag.AlignHCenter)

        root.addStretch(1)

        self._router_node = _LabeledIcon(
            "dev_router", Theme.ACCENT, "Router", "—",
            subtitle_mono=True, icon_size=32)
        root.addWidget(self._router_node, alignment=Qt.AlignmentFlag.AlignHCenter)

        root.addStretch(1)

        self._devices_container = QWidget()
        self._devices_container.setStyleSheet("background: transparent;")
        self._devices_layout = QHBoxLayout(self._devices_container)
        self._devices_layout.setContentsMargins(0, 0, 0, 0)
        self._devices_layout.setSpacing(2)
        root.addWidget(self._devices_container)

    def set_topology(self, gateway, devices, router_vendor="", online=True):
        self._gateway = gateway or "—"
        self._router_vendor = router_vendor
        self._online = online
        self._devices = [d for d in devices if d.get("ip") != gateway][:5]

        # Internet node reflects connection state
        icol = Theme.SUCCESS if online else Theme.TEXT_MUTED
        self._internet_node.set_colors(icol, icol)

        # Router node: name above IP, to the right of the icon
        rv = (self._router_vendor or "").strip()
        if not rv or rv.lower() in ("unknown", "private (randomized)"):
            rv = "Router"
        self._router_node.set_title(rv)
        self._router_node.set_subtitle(self._gateway)

        # Rebuild the device row
        while self._devices_layout.count():
            item = self._devices_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        if self._devices:
            self._devices_layout.addStretch(1)
            for dev in self._devices:
                ip = dev.get("ip", "")
                name = device_display_name(dev)
                """ If the only thing we have is the IP, show a friendly generic
                name instead (so the title isn't identical to the subtitle
                IP below it). "Private (randomized)" MACs are usually phones. """
                if name == ip or not name or name == "?":
                    vendor = (dev.get("vendor") or "").lower()
                    if "private" in vendor or "random" in vendor:
                        name = "Device (private)"
                    else:
                        name = "Device"
                name = name[:16]
                icon_name = guess_device_icon(dev)
                node = _DeviceNode(icon_name, Theme.TEXT_SECONDARY, name, ip,
                                   device=dev,
                                   on_click=self.node_clicked.emit)
                self._devices_layout.addWidget(node)
                self._devices_layout.addStretch(1)

        self.update()

    def paintEvent(self, event):
        """ Lines are painted here, in the parent's paintEvent - Qt always
        composites child widgets (the icons) on top of this, so a line
        can never visually cover an icon, regardless of layout size. """
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        link_color = QColor(Theme.SUCCESS) if self._online else QColor(Theme.TEXT_FAINT)
        pen = QPen(link_color, 2.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)

        def top_of(widget: QLabel) -> QPointF:
            return QPointF(widget.mapTo(self, QPoint(widget.width() // 2, 0)))

        def bottom_of(widget: QLabel) -> QPointF:
            return QPointF(widget.mapTo(self, QPoint(widget.width() // 2, widget.height())))

        internet_bottom = bottom_of(self._internet_node.icon_label)
        router_top = top_of(self._router_node.icon_label)
        router_bottom = bottom_of(self._router_node.icon_label)

        # Internet -> Router
        p.drawLine(internet_bottom, router_top)

        # Router -> bus -> devices
        device_tops = []
        for i in range(self._devices_layout.count()):
            item = self._devices_layout.itemAt(i)
            w = item.widget()
            if isinstance(w, _DeviceNode):
                device_tops.append(top_of(w.icon_label))

        if device_tops:
            bus_y = (router_bottom.y() + device_tops[0].y()) / 2
            cx = router_bottom.x()
            p.drawLine(QPointF(cx, router_bottom.y()), QPointF(cx, bus_y))
            xs = [pt.x() for pt in device_tops]
            if len(xs) > 1:
                p.drawLine(QPointF(min(xs), bus_y), QPointF(max(xs), bus_y))
            for pt in device_tops:
                p.drawLine(QPointF(pt.x(), bus_y), pt)

        p.end()
