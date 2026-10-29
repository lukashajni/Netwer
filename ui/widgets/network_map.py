"""NETWER — NetworkMap widget"""

import math
import random
import time

from PyQt6.QtCore import Qt, pyqtSignal, QPoint, QPointF, QTimer
from PyQt6.QtGui import QPainter, QColor, QPen
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel

from app.theme import Theme
from app.resources import Icons


def guess_device_icon(dev: dict) -> str:
    """Pick an icon name for a device."""
    kind = (dev.get("kind") or "").strip()
    if kind.startswith("dev_"):
        return kind
    try:
        from core import device_fingerprint
        return device_fingerprint.classify_kind(dev)
    except Exception:
        return "dev_generic"


def device_display_name(dev: dict) -> str:
    """Best available name, in order: a name the user gave the device, its real
    hostname, a real manufacturer, else what kind of device it is."""
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
    try:
        from core.device_fingerprint import KIND_LABELS
        label = KIND_LABELS.get(guess_device_icon(dev))
    except Exception:
        label = None
    return label or "Unknown device"


class _LabeledIcon(QWidget):
    """Icon with title (+ optional subtitle) to its right."""

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
        self._on_click = None
        self.set_colors(icon_color, title_color or Theme.TEXT_BODY)

    def set_click(self, callback):
        self._on_click = callback
        self.setCursor(Qt.CursorShape.PointingHandCursor if callback else Qt.CursorShape.ArrowCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._on_click:
            self._on_click()

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
    """Icon centered above a name + IP, stacked below - used for devices."""

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
        self._self_node = None
        # moving dots that show live traffic on the links
        self._dots = []
        self._anim = QTimer(self)
        self._anim.setInterval(30)
        self._anim.timeout.connect(self._step_dots)

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

        # Clicking the router opens its details and open ports, like any device
        gw = next((d for d in devices if d.get("ip") == gateway), None)
        gw_dev = dict(gw or {"ip": gateway, "hostname": "", "vendor": router_vendor})
        gw_dev["is_gateway"] = True
        has_gw = bool(gateway) and gateway != "\u2014"
        self._router_node.set_click((lambda: self.node_clicked.emit(gw_dev)) if has_gw else None)

        # Rebuild the device row
        self._self_node = None
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
                if dev.get("is_self"):
                    self._self_node = node

        self.update()

    def paintEvent(self, event):
        """Lines are painted here, in the parent's paintEvent"""
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

        # Everything hangs off the router icon's axis. Odd widths make the
        # other icons land 1 px to the side, which showed as a jog in the line.
        cx = router_top.x()
        internet_bottom.setX(cx)

        # Internet -> Router
        p.drawLine(internet_bottom, router_top)

        # Router -> bus -> devices
        device_tops = []
        for i in range(self._devices_layout.count()):
            item = self._devices_layout.itemAt(i)
            w = item.widget()
            if isinstance(w, _DeviceNode):
                pt = top_of(w.icon_label)
                if abs(pt.x() - cx) <= 3:      # rounding, not a real offset
                    pt.setX(cx)
                device_tops.append(pt)

        route = [internet_bottom, router_top]
        if device_tops:
            bus_y = (router_bottom.y() + device_tops[0].y()) / 2
            p.drawLine(QPointF(cx, router_bottom.y()), QPointF(cx, bus_y))
            xs = [pt.x() for pt in device_tops]
            if len(xs) > 1:
                p.drawLine(QPointF(min(xs), bus_y), QPointF(max(xs), bus_y))
            for pt in device_tops:
                p.drawLine(QPointF(pt.x(), bus_y), pt)
            if self._self_node is not None:
                me = top_of(self._self_node.icon_label)
                route += [QPointF(cx, router_bottom.y()), QPointF(cx, bus_y), QPointF(me.x(), bus_y), me]

        self._paint_dots(p, route)
        p.end()

    # -- live traffic dots --
    def set_traffic(self, dl_mbps: float, ul_mbps: float) -> None:
        """Spawn dots for one second of traffic: blue flows in, purple flows out."""
        if not self._online or not self.isVisible():
            return
        now = time.monotonic()
        for mbps, down in ((dl_mbps, True), (ul_mbps, False)):
            kbps = max(0.0, mbps) * 1000
            n = min(8, int(round(math.log2(1 + kbps / 20)))) if kbps > 1 else 0
            for _ in range(n):
                self._dots.append((now + random.random(), 1.1 + random.random() * 0.3, down))
        if self._dots and not self._anim.isActive():
            self._anim.start()

    def _step_dots(self):
        now = time.monotonic()
        self._dots = [d for d in self._dots if now < d[0] + d[1]]
        if not self._dots:
            self._anim.stop()
        self.update()

    def _paint_dots(self, p, route):
        if not self._dots or len(route) < 2:
            return
        segs = [(route[i], route[i + 1]) for i in range(len(route) - 1)]
        lens = [math.hypot(b.x() - a.x(), b.y() - a.y()) for a, b in segs]
        total = sum(lens) or 1
        now = time.monotonic()
        p.setPen(Qt.PenStyle.NoPen)
        for start, dur, down in self._dots:
            f = (now - start) / dur
            if not 0 <= f <= 1:
                continue
            x = (f if down else 1 - f) * total
            for i, ((a, b), ln) in enumerate(zip(segs, lens)):
                if x <= ln or i == len(segs) - 1:
                    k = x / ln if ln else 0
                    pt = QPointF(a.x() + (b.x() - a.x()) * k, a.y() + (b.y() - a.y()) * k)
                    break
                x -= ln
            color = QColor(Theme.ACCENT if down else Theme.ACCENT_PURPLE)
            color.setAlphaF(min(1.0, f * 6, (1 - f) * 6))
            p.setBrush(color)
            p.drawEllipse(pt, 3.2, 3.2)
