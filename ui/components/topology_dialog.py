"""Full-screen network topology view.

Opens from the Network Radar card on the dashboard. Gives the whole local
network room to breathe - a large live radar on the left, and a panel on the
right listing every discovered device with its vendor, IP and response time.
Clicking a device (in the radar or the list) opens the per-device details with
its open ports.

It reuses the same NetworkRadar widget as the dashboard, just in "detailed"
mode where every node is labelled.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QScrollArea, QWidget, QGraphicsDropShadowEffect,
)

from app.theme import Theme
from app.resources import Icons
from ui.widgets.network_radar import NetworkRadar

try:
    from ui.widgets.network_map import device_display_name, guess_device_icon
except Exception:                                    # pragma: no cover
    def device_display_name(dev):
        return dev.get("hostname") or dev.get("ip", "?")

    def guess_device_icon(dev):
        return "devices"


class _DeviceRow(QFrame):
    # One clickable device entry in the side panel.

    def __init__(self, dev, on_click, parent=None):
        super().__init__(parent)
        self._dev = dev
        self._on_click = on_click
        self.setObjectName("DevRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_style(False)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(11, 9, 11, 9)
        lay.setSpacing(11)

        icon = QLabel()
        icon.setPixmap(Icons.pixmap(guess_device_icon(dev), 17,
                                    self._accent_for(dev)))
        icon.setFixedWidth(20)
        lay.addWidget(icon)

        box = QVBoxLayout()
        box.setSpacing(1)
        name = QLabel(device_display_name(dev))
        name.setStyleSheet(
            f"color: {Theme.TEXT_PRIMARY}; font-size: 13px; font-weight: 600;"
            f"background: transparent;")
        sub = QLabel(dev.get("ip", ""))
        sub.setStyleSheet(
            f"color: {Theme.TEXT_MUTED}; font-size: 11.5px;"
            f"font-family: {Theme.FONT_MONO}; background: transparent;")
        box.addWidget(name)
        box.addWidget(sub)
        lay.addLayout(box)
        lay.addStretch()

        rtt = dev.get("rtt_ms")
        if isinstance(rtt, (int, float)) and rtt > 0:
            t = QLabel(f"{round(rtt)} ms")
            t.setStyleSheet(
                f"color: {Theme.SUCCESS}; font-size: 11.5px;"
                f"font-family: {Theme.FONT_MONO}; background: transparent;")
            lay.addWidget(t)

    @staticmethod
    def _accent_for(dev):
        if dev.get("is_gateway"):
            return Theme.SUCCESS
        vendor = (dev.get("vendor") or "").lower()
        if "private" in vendor or "unknown" in vendor or not vendor:
            return Theme.DANGER
        return Theme.ACCENT

    def _apply_style(self, hover):
        border = Theme.GLASS_BORDER_HI if hover else Theme.GLASS_BORDER
        self.setStyleSheet(
            f"#DevRow {{ background: {Theme.GLASS_INPUT};"
            f"border: 1px solid {border}; border-radius: 11px; }}")

    def enterEvent(self, e):
        self._apply_style(True)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._apply_style(False)
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._on_click(self._dev)


class TopologyDialog(QDialog):
    def __init__(self, core, gateway, devices, router_vendor="", online=True,
                 parent=None):
        super().__init__(parent)
        self._core = core
        self._devices = list(devices or [])

        self.setWindowTitle("Network Topology")
        self.setModal(True)
        self.setStyleSheet(
            f"QDialog {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1,"
            f"stop:0 {Theme.BG_SIDEBAR}, stop:0.5 {Theme.BG_APP},"
            f"stop:1 {Theme.BG_SIDEBAR}); }}"
            f"QLabel {{ background: transparent; color: {Theme.TEXT_BODY}; }}")

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 24)
        root.setSpacing(16)

        root.addLayout(self._build_header(gateway, online))
        root.addLayout(self._build_stats(gateway, online))

        body = QHBoxLayout()
        body.setSpacing(16)

        # -- Left: the big radar --
        radar_card = QFrame()
        radar_card.setObjectName("RadarCard")
        radar_card.setStyleSheet(
            f"#RadarCard {{ background: {Theme.GLASS_CARD};"
            f"border: 1px solid {Theme.GLASS_BORDER}; border-radius: 16px; }}")
        rl = QVBoxLayout(radar_card)
        rl.setContentsMargins(16, 14, 16, 14)
        rl.setSpacing(10)

        self.radar = NetworkRadar()
        self.radar.set_detailed(True)
        self.radar.node_clicked.connect(self._open_details)
        self.radar.set_topology(gateway, self._devices, router_vendor, online)
        rl.addWidget(self.radar, 1)
        rl.addLayout(self._build_legend())
        body.addWidget(radar_card, 3)

        # -- Right: device list --
        body.addWidget(self._build_device_panel(), 1)
        root.addLayout(body, 1)

        # -- Footer --
        foot = QHBoxLayout()
        hint = QLabel("Click any device \u2014 in the radar or the list \u2014 "
                      "to see its details and open ports.")
        hint.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: 12px;")
        foot.addWidget(hint)
        foot.addStretch()
        close = QPushButton("Close")
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.clicked.connect(self.accept)
        close.setStyleSheet(
            f"QPushButton {{ background: {Theme.GRAD_ACCENT}; color: white;"
            f"border: none; border-radius: {Theme.RADIUS_CONTROL}px;"
            f"padding: 10px 24px; font-weight: 600; }}")
        foot.addWidget(close)
        root.addLayout(foot)

        self.resize(1180, 760)

    # -- Pieces --
    def _build_header(self, gateway, online):
        head = QHBoxLayout()
        head.setSpacing(12)

        tile = QLabel()
        tile.setFixedSize(42, 42)
        tile.setObjectName("HeadTile")
        tile.setStyleSheet(
            f"#HeadTile {{ background: {Theme.GRAD_ACCENT_SOFT};"
            f"border: 1px solid {Theme.GLASS_BORDER}; border-radius: 12px; }}")
        tile.setPixmap(Icons.pixmap("network", 20, Theme.ACCENT))
        tile.setAlignment(Qt.AlignmentFlag.AlignCenter)
        head.addWidget(tile)

        box = QVBoxLayout()
        box.setSpacing(2)
        t = QLabel("Network Topology")
        t.setStyleSheet(
            f"color: {Theme.TEXT_PRIMARY}; font-size: 21px; font-weight: 700;")
        s = QLabel("Live view of every device on your local network")
        s.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-size: 13px;")
        box.addWidget(t)
        box.addWidget(s)
        head.addLayout(box)
        head.addStretch()
        return head

    def _build_stats(self, gateway, online):
        row = QHBoxLayout()
        row.setSpacing(12)
        subnet = ".".join(gateway.split(".")[:3]) + ".0/24" if gateway else "\u2014"
        unknown = sum(1 for d in self._devices
                      if ("private" in (d.get("vendor") or "").lower()
                          or "unknown" in (d.get("vendor") or "").lower()))
        stats = [
            ("Devices online", str(len(self._devices)), Theme.WARNING),
            ("Gateway", gateway or "\u2014", Theme.SUCCESS),
            ("Subnet", subnet, Theme.ACCENT),
            ("Unidentified", str(unknown),
             Theme.DANGER if unknown else Theme.TEXT_SECONDARY),
            ("Internet", "Online" if online else "Offline",
             Theme.SUCCESS if online else Theme.DANGER),
        ]
        for label, value, col in stats:
            f = QFrame()
            f.setObjectName("StatTile")
            f.setStyleSheet(
                f"#StatTile {{ background: {Theme.GLASS_CARD};"
                f"border: 1px solid {Theme.GLASS_BORDER};"
                f"border-radius: 12px; }}")
            fl = QVBoxLayout(f)
            fl.setContentsMargins(14, 10, 14, 10)
            fl.setSpacing(2)
            k = QLabel(label)
            k.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: 11.5px;")
            v = QLabel(value)
            v.setStyleSheet(
                f"color: {col}; font-size: 16px; font-weight: 700;"
                f"font-family: {Theme.FONT_MONO};")
            fl.addWidget(k)
            fl.addWidget(v)
            row.addWidget(f, 1)
        return row

    def _build_legend(self):
        row = QHBoxLayout()
        row.setSpacing(18)
        items = [("You / router", Theme.SUCCESS),
                 ("Active device", Theme.ACCENT),
                 ("Unidentified", Theme.DANGER),
                 ("Traffic", Theme.ACCENT_PURPLE)]
        for text, col in items:
            dot = QLabel("\u25CF")
            dot.setStyleSheet(f"color: {col}; font-size: 11px;")
            lbl = QLabel(text)
            lbl.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: 12px;")
            row.addWidget(dot)
            row.addWidget(lbl)
            row.addSpacing(6)
        row.addStretch()
        return row

    def _build_device_panel(self):
        panel = QFrame()
        panel.setObjectName("DevPanel")
        panel.setMinimumWidth(300)
        panel.setStyleSheet(
            f"#DevPanel {{ background: {Theme.GLASS_CARD};"
            f"border: 1px solid {Theme.GLASS_BORDER}; border-radius: 16px; }}")
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(16, 14, 16, 14)
        pl.setSpacing(10)

        head = QHBoxLayout()
        t = QLabel("Devices")
        t.setStyleSheet(
            f"color: {Theme.TEXT_PRIMARY}; font-size: 14px; font-weight: 600;")
        head.addWidget(t)
        head.addStretch()
        n = QLabel(str(len(self._devices)))
        n.setStyleSheet(
            f"color: {Theme.WARNING}; font-size: 13px; font-weight: 700;"
            f"font-family: {Theme.FONT_MONO};")
        head.addWidget(n)
        pl.addLayout(head)

        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        il = QVBoxLayout(inner)
        il.setContentsMargins(0, 0, 6, 0)
        il.setSpacing(8)
        if self._devices:
            for dev in self._devices:
                il.addWidget(_DeviceRow(dev, self._open_details))
        else:
            empty = QLabel("No devices discovered yet.")
            empty.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: 12.5px;")
            il.addWidget(empty)
        il.addStretch()
        area.setWidget(inner)
        pl.addWidget(area, 1)
        return panel

    # -- Actions --
    def _open_details(self, device: dict):
        from ui.components.device_details_dialog import DeviceDetailsDialog
        DeviceDetailsDialog(self._core, device, self).exec()
