"""Main dashboard for network and system monitoring."""

import time

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.adapter_state import adapter_state
from app.formatting import format_speed
from app.resources import Icons
from app.theme import Theme, card_bg, card_border
from app.traffic_history import traffic_history
from core.discovery import get_discovery_service
from ui.pages.base_page import BasePage
from ui.widgets.card import Card
from workers import OneshotWorker, StreamWorker


class _ScoreRing(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(96, 96)
        self._score = None

    def set_score(self, score):
        self._score = score
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(8, 8, 80, 80)
        p.setPen(QPen(QColor(Theme.BORDER), 8))
        p.drawEllipse(r)
        s = self._score
        color = QColor(Theme.TEXT_MUTED if s is None else Theme.SUCCESS if s >= 85
                       else Theme.WARNING if s >= 65 else Theme.DANGER)
        if s is not None:
            pen = QPen(color, 8)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawArc(r, 90 * 16, -int(360 * 16 * s / 100))
        f = QFont(Theme.FONT_MONO_PRIMARY)
        f.setPixelSize(22)
        f.setBold(True)
        p.setFont(f)
        p.setPen(color)
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, "\u2014" if s is None else str(s))
        p.end()


class _Kpi(QFrame):
    def __init__(self, label, icon=None, parent=None):
        super().__init__(parent)
        self.setObjectName("Kpi")
        self.setStyleSheet(f"#Kpi {{ background: {card_bg()}; border: 1px solid {card_border()};"
                           f"border-radius: {Theme.RADIUS_CARD}px; }} #Kpi QLabel {{ background: transparent; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(3)
        head = QHBoxLayout()
        head.setSpacing(6)
        if icon:
            ic = QLabel()
            ic.setPixmap(Icons.pixmap(icon, 13, Theme.ACCENT if icon == "download" else Theme.ACCENT_PURPLE))
            head.addWidget(ic)
        t = QLabel(label)
        t.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: {Theme.FONT_SIZE_TINY + 0.5}px;")
        head.addWidget(t)
        head.addStretch()
        lay.addLayout(head)
        self._value = QLabel("—")
        self._value.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self._value)
        self._sub = QLabel("")
        lay.addWidget(self._sub)
        lay.addStretch()
        self.set_value("—")

    def set_value(self, value, unit="", color=None, subtitle="", sub_color=None):
        col = color or Theme.TEXT_PRIMARY
        self._value.setText(
            f"<span style='color:{col}; font-family:{Theme.FONT_MONO}; font-size:22px; font-weight:600;'>{value}</span>"
            + (f"<span style='color:{Theme.TEXT_MUTED}; font-size:11px;'> {unit}</span>" if unit else ""))
        self._sub.setText(subtitle)
        self._sub.setStyleSheet(f"color: {sub_color or Theme.TEXT_MUTED}; font-size: {Theme.FONT_SIZE_TINY}px;")


class _AuroraHero(QFrame):
    """Card with slowly drifting colour blobs behind its content."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self._t = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _tick(self):
        if self.isVisible():
            self._t += 0.04
            self.update()

    def paintEvent(self, _):
        import math
        from PyQt6.QtGui import QPainterPath, QRadialGradient
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, Theme.RADIUS_CARD, Theme.RADIUS_CARD)
        p.setClipPath(path)
        p.fillRect(self.rect(), QColor("#121a36"))
        w, h, t = self.width(), self.height(), self._t
        blobs = [("#5b8cff", 0.25 + 0.18 * math.sin(t * 0.7), 0.30 + 0.25 * math.cos(t * 0.5), 0.50, 80),
                 ("#8b6dff", 0.65 + 0.20 * math.cos(t * 0.6), 0.65 + 0.20 * math.sin(t * 0.8), 0.55, 85),
                 ("#33d6a6", 0.85 + 0.12 * math.sin(t * 0.9 + 1), 0.15 + 0.20 * math.cos(t * 0.7 + 2), 0.35, 45),
                 ("#c86dff", 0.10 + 0.10 * math.cos(t * 0.5 + 3), 0.85 + 0.10 * math.sin(t * 0.6), 0.40, 50)]
        for color, fx, fy, fr, alpha in blobs:
            g = QRadialGradient(QPointF(w * fx, h * fy), w * fr)
            c = QColor(color)
            c.setAlpha(alpha)
            g.setColorAt(0, c)
            c2 = QColor(color)
            c2.setAlpha(0)
            g.setColorAt(1, c2)
            p.fillRect(self.rect(), g)
        p.setClipping(False)
        p.setPen(QPen(QColor("#2b3561"), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        p.end()


class _ShareBar(QWidget):
    def __init__(self, fraction, parent=None):
        super().__init__(parent)
        self._f = max(0.0, min(1.0, fraction))
        self.setFixedHeight(5)

    def paintEvent(self, _):
        from PyQt6.QtGui import QLinearGradient
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(Theme.BORDER))
        p.drawRoundedRect(QRectF(self.rect()), 2.5, 2.5)
        g = QLinearGradient(0, 0, self.width(), 0)
        g.setColorAt(0, QColor(Theme.ACCENT))
        g.setColorAt(1, QColor(Theme.ACCENT_PURPLE))
        p.setBrush(g)
        p.drawRoundedRect(QRectF(0, 0, self.width() * self._f, self.height()), 2.5, 2.5)
        p.end()


class DashboardPage(BasePage):
    PAGE_TITLE = "Dashboard"
    PAGE_SUBTITLE = "Your network at a glance"

    def _build_header(self):
        super()._build_header()
        # the subtitle shows adapter, address and gateway once they are known
        labels = [w for w in self.findChildren(QLabel) if w.text() == self.PAGE_SUBTITLE]
        self._subtitle_label = labels[0] if labels else None

    def __init__(self, core, parent=None):
        super().__init__(core, parent)

        self._monitor_worker = None
        self._closing = False
        self._last_sample = time.time()
        self._watchdog = QTimer(self)             # restarts the monitor if it stalls
        self._watchdog.setInterval(5000)
        self._watchdog.timeout.connect(self._check_monitor)
        adapter_state.changed.connect(self._on_adapter_setting)

        # Refresh connectivity for the ping and loss sparklines.
        self._ping_timer = QTimer(self)
        self._ping_timer.setInterval(5000)
        self._ping_timer.timeout.connect(self._refresh_internet)
        self._internet_worker = None

        self._loaded_once = False
        self._pending = set()
        self._devices_scanning = False
        self._silent_scan = False
        self._discovery_service = get_discovery_service()
        self._discovery_worker = None
        self._discovery_segments = []
        self._device_signature = None
        self._discovery_timer = QTimer(self)
        self._discovery_timer.setInterval(1000)
        self._discovery_timer.timeout.connect(self._sync_discovery_snapshot)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        self._grid = QVBoxLayout(inner)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(Theme.GAP)
        scroll.setWidget(inner)
        self.body_layout.addWidget(scroll)

        self._build_hero_row()
        self._build_middle_row()
        self._build_bottom_row()
        self._grid.addStretch(1)

        from ui.widgets.ui_kit import button
        btn = button("Open Packet Capture", "capture")
        btn.clicked.connect(lambda: self._window and self._window.goto("capture"))
        self.header_actions.addWidget(btn)

        self._hero_state = {"online": None, "ping": None, "loss": None}
        self._capture_timer = QTimer(self)
        self._capture_timer.setInterval(1000)
        self._capture_timer.timeout.connect(self._refresh_capture_card)
        self._capture_timer.timeout.connect(self._maybe_update_map)

    # -- UI CONSTRUCTION --
    def _build_hero_row(self):
        from ui.widgets.ui_kit import button
        row = QHBoxLayout()
        row.setSpacing(Theme.GAP)

        hero = _AuroraHero()
        hero.setFixedHeight(142)
        lay = QHBoxLayout(hero)
        lay.setContentsMargins(20, 14, 20, 14)
        lay.setSpacing(18)
        self.score_ring = _ScoreRing()
        lay.addWidget(self.score_ring)
        col = QVBoxLayout()
        col.setSpacing(4)
        eyebrow = QHBoxLayout()
        eyebrow.setSpacing(6)
        spark = QLabel()
        spark.setPixmap(Icons.pixmap("ai", 12, "#c9bdff"))
        spark.setStyleSheet("background: transparent;")
        eyebrow.addWidget(spark)
        tag = QLabel("NETWER AI SUMMARY")
        tag.setStyleSheet("color: #c9bdff; font-size: 10px; font-weight: 700; letter-spacing: 1.3px;"
                          "background: transparent;")
        eyebrow.addWidget(tag)
        eyebrow.addStretch()
        col.addLayout(eyebrow)
        self.hero_title = QLabel("Checking your network…")
        # the card is always dark, so its text keeps light colours in every theme
        self.hero_title.setStyleSheet("color: #eef2ff; font-size: 17px; font-weight: 600; background: transparent;")
        col.addWidget(self.hero_title)
        self.hero_text = QLabel("")
        self.hero_text.setWordWrap(True)
        self.hero_text.setTextFormat(Qt.TextFormat.RichText)
        self.hero_text.setStyleSheet(f"color: #c9d2ee; font-size: {Theme.FONT_SIZE_SMALL}px; background: transparent;")
        col.addWidget(self.hero_text)
        btns = QHBoxLayout()
        self.btn_hero_ai = button("Ask what to improve", kind="ai")
        self.btn_hero_ai.clicked.connect(lambda: self._ask_ai(
            "Look at my network status, devices and traffic. Is anything wrong, and what should I improve?"))
        btns.addWidget(self.btn_hero_ai)
        btns.addStretch()
        col.addLayout(btns)
        lay.addLayout(col, 1)
        row.addWidget(hero, 5)

        kpis = QHBoxLayout()
        kpis.setSpacing(Theme.GAP)
        self.card_download = _Kpi("Download", "download")
        self.card_upload = _Kpi("Upload", "upload")
        self.card_internet = _Kpi("Latency")
        self.card_retrans = _Kpi("TCP retransmits")
        self.card_devices = _Kpi("Devices")
        for c in (self.card_download, self.card_upload, self.card_internet, self.card_retrans, self.card_devices):
            c.setFixedHeight(142)
            kpis.addWidget(c)
        self.card_retrans.set_value("—", subtitle="start a packet capture")
        row.addLayout(kpis, 7)
        self._grid.addLayout(row, 0)

    def _build_capture_card(self, height):
        from ui.pages.capture_page import MixBar
        from ui.widgets.ui_kit import button
        self.capture_card = Card("Packet capture")
        self.capture_card.setFixedHeight(height)
        self.capture_count = QLabel("")
        self.capture_count.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-family: {Theme.FONT_MONO}; font-size: 11px;")
        self.capture_card.header_layout.insertWidget(1, self.capture_count)
        self.btn_open_capture = button("Open")
        self.btn_open_capture.clicked.connect(lambda: self._window and self._window.goto("capture"))
        self.capture_card.header_layout.addWidget(self.btn_open_capture)
        self.capture_status = QLabel("Not capturing. Open Packet Capture and press Start.")
        self.capture_status.setWordWrap(True)
        self.capture_status.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: {Theme.FONT_SIZE_SMALL}px;")
        self.capture_card.content_layout.addWidget(self.capture_status)
        self.capture_mix = MixBar()
        self.capture_mix.setFixedHeight(9)
        self.capture_card.content_layout.addWidget(self.capture_mix)
        self.capture_legend = QLabel("")
        self.capture_legend.setTextFormat(Qt.TextFormat.RichText)
        self.capture_legend.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-size: {Theme.FONT_SIZE_TINY}px;")
        self.capture_card.content_layout.addWidget(self.capture_legend)
        self._capture_hosts = QVBoxLayout()
        self._capture_hosts.setSpacing(8)
        self.capture_card.content_layout.addSpacing(6)
        self.capture_card.content_layout.addLayout(self._capture_hosts)
        self.capture_card.content_layout.addStretch()
        return self.capture_card

    def _ask_ai(self, question):
        win = self._window or self.window()
        if hasattr(win, "ask_ai"):
            win.ask_ai(question)

    def _update_hero(self):
        st = self._hero_state
        online, ping, loss = st["online"], st["ping"], st["loss"]
        if online is None:
            return
        devices = len(getattr(self, "_all_devices", None) or [])
        from core.capture import get_capture_service
        cap = get_capture_service()
        if not online:
            score, title = 5, "You are offline"
            text = "Netwer gets no answer from the internet. Run Network Health to find where it stops."
        else:
            score = 100
            score -= 25 if loss >= 5 else 10 if loss >= 1 else 0
            score -= 15 if ping > 120 else 6 if ping > 60 else 0
            tcp = sum(c["tcp"] for c in cap.conv.values())
            rpct = cap.retrans / tcp * 100 if tcp else 0
            score -= 10 if rpct > 3 else 3 if rpct > 1 else 0
            score -= 3 if cap.plaintext else 0
            title = ("Your network is healthy" if score >= 85 else
                     "Your network works, with a few issues" if score >= 65 else "Your connection has problems")
            text = f"Internet answers in <b>{ping} ms</b> with <b>{loss}%</b> packet loss"
            text += f", {devices} device{'s' if devices != 1 else ''} online." if devices else "."
            if cap.count():
                if cap.retrans:
                    worst = max(cap.conv.items(), key=lambda kv: kv[1]["retrans"])
                    text += f" The capture shows {cap.retrans} TCP retransmissions, mostly to {cap.host(worst[0])}."
                if cap.plaintext:
                    proto, host = next(iter(cap.plaintext))
                    text += f" One connection to {host} uses unencrypted {proto}."
        self.score_ring.set_score(max(0, min(100, score)))
        self.hero_title.setText(title)
        self.hero_text.setText(text)

    def _refresh_capture_card(self):
        from core.capture import get_capture_service
        from ui.pages.capture_page import MIX_COLORS
        cap = get_capture_service()
        n = cap.count()
        while self._capture_hosts.count():
            item = self._capture_hosts.takeAt(0)
            if item.layout() is not None:
                while item.layout().count():
                    w = item.layout().takeAt(0).widget()
                    if w is not None:
                        w.deleteLater()
            elif item.widget() is not None:
                item.widget().deleteLater()
        tcp = sum(c["tcp"] for c in cap.conv.values())
        if tcp:
            worst = max(cap.conv.items(), key=lambda kv: kv[1]["retrans"])
            self.card_retrans.set_value(f"{cap.retrans / tcp * 100:.1f}", "%",
                                        color=Theme.WARNING if cap.retrans / tcp > 0.02 else Theme.TEXT_PRIMARY,
                                        subtitle=f"{cap.retrans} resent" + (f" · {cap.host(worst[0])}" if cap.retrans else ""))
        if not n:
            self.capture_count.setText("")
            self.capture_status.setText("Capturing… waiting for packets." if cap.running
                                        else "Not capturing. Open Packet Capture and press Start.")
            self.capture_status.show()
            self.capture_mix.set_parts([])
            self.capture_legend.setText("")
            return
        self.capture_status.hide()
        size = cap.total_bytes
        size_s = f"{size / 1048576:.2f} MB" if size >= 1048576 else f"{size / 1024:.0f} KB"
        self.capture_count.setText(f"{n:,} packets · {size_s}")
        parts = cap.proto_mix.most_common(8)
        self.capture_mix.set_parts(parts)
        tot = sum(v for _, v in parts) or 1
        self.capture_legend.setText("&nbsp;&nbsp;".join(
            f"<span style='color:{MIX_COLORS.get(k, Theme.TEXT_MUTED)}'>■</span> {k} "
            f"<span style='color:{Theme.TEXT_MUTED}; font-family:{Theme.FONT_MONO}'>{v * 100 / tot:.1f}%</span>"
            for k, v in parts[:7]))
        top = sorted(cap.conv.items(), key=lambda kv: -kv[1]["bytes"])[:4]
        biggest = top[0][1]["bytes"] if top else 1
        for ip, c in top:
            line = QHBoxLayout()
            name = QLabel(cap.host(ip))
            name.setStyleSheet(f"color: {Theme.TEXT_BODY}; font-size: {Theme.FONT_SIZE_SMALL}px; background: transparent;")
            size = QLabel(f"{c['bytes'] / 1024:.1f} KB")
            size.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-family: {Theme.FONT_MONO}; font-size: 11px; background: transparent;")
            line.addWidget(name)
            line.addStretch()
            line.addWidget(size)
            self._capture_hosts.addLayout(line)
            self._capture_hosts.addWidget(_ShareBar(c["bytes"] / biggest))
        self._update_hero()

    def _build_middle_row(self):
        from ui.widgets.network_map import NetworkMap
        from ui.widgets.throughput_chart import ThroughputChart
        row = QHBoxLayout()
        row.setSpacing(Theme.GAP)
        HEIGHT = 310

        chart_card = Card("Throughput")
        chart_card.setFixedHeight(HEIGHT)
        legend = QHBoxLayout()
        legend.setSpacing(12)
        legend.addWidget(self._legend_item("Download", Theme.ACCENT))
        legend.addWidget(self._legend_item("Upload", Theme.ACCENT_PURPLE))
        chart_card.header_layout.addLayout(legend)
        self.chart = ThroughputChart()
        self.chart.clicked.connect(self._open_traffic_analysis)
        chart_card.content_layout.addWidget(self.chart, 1)
        row.addWidget(chart_card, 7)

        self.map_card = Card("Network map")
        self.map_card.setFixedHeight(HEIGHT)
        self.map_count = QLabel("")
        self.map_count.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-family: {Theme.FONT_MONO}; font-size: 11px;")
        self.map_card.header_layout.insertWidget(1, self.map_count)
        legend_map = QHBoxLayout()
        legend_map.setSpacing(12)
        legend_map.addWidget(self._legend_item("in", Theme.ACCENT))
        legend_map.addWidget(self._legend_item("out", Theme.ACCENT_PURPLE))
        legend_map.addWidget(self._legend_item("multicast", "#7d86a0"))
        self.map_card.header_layout.addLayout(legend_map)
        self.network_map = NetworkMap()
        self.network_map.node_clicked.connect(self._open_device_details)
        self.map_card.content_layout.addWidget(self.network_map, 1)
        row.addWidget(self.map_card, 5)
        self._grid.addLayout(row, 0)

    def _legend_item(self, text, color):
        # A small colored dot + label for the chart legend.
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        dot = QLabel()
        dot.setFixedSize(10, 10)
        dot.setStyleSheet(
            f"background: {color}; border-radius: 5px;")
        lay.addWidget(dot)
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color: {Theme.TEXT_SECONDARY}; font-size: {Theme.FONT_SIZE_TINY}px;"
            f"background: transparent;")
        lay.addWidget(lbl)
        return w

    def _build_bottom_row(self):
        row = QHBoxLayout()
        row.setSpacing(Theme.GAP)

        BOTTOM_HEIGHT = 300

        self.devices_card = Card("Devices", "devices")
        self.devices_card.setFixedHeight(BOTTOM_HEIGHT)

        # Rescan button in the card header - re-runs the network scan,
        # refreshing both "Top Devices" and the "Network Map".
        self.btn_rescan = QPushButton("  Rescan")
        self.btn_rescan.setIcon(Icons.get("refresh", Theme.TEXT_BODY))
        self.btn_rescan.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_rescan.setStyleSheet(
            f"QPushButton {{ background: {Theme.BG_ELEVATED}; color: {Theme.TEXT_SECONDARY};"
            f"border: 1px solid {Theme.BORDER_STRONG}; border-radius: 6px;"
            f"padding: 3px 12px; font-size: {Theme.FONT_SIZE_TINY}px; }}"
            f"QPushButton:hover {{ border-color: {Theme.ACCENT}; color: {Theme.TEXT_BODY}; }}"
            f"QPushButton:disabled {{ color: {Theme.TEXT_FAINT}; }}")
        self.btn_rescan.clicked.connect(self._on_rescan_clicked)
        self.devices_card.header_layout.addWidget(self.btn_rescan)
        self.btn_cancel_scan = QPushButton("Cancel")
        self.btn_cancel_scan.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cancel_scan.setStyleSheet(
            f"QPushButton {{ background: {Theme.DANGER}; color: white;"
            "border: none; border-radius: 6px; padding: 3px 10px;"
            f"font-size: {Theme.FONT_SIZE_TINY}px; }}")
        self.btn_cancel_scan.clicked.connect(self._cancel_network_scan)
        self.btn_cancel_scan.hide()
        self.devices_card.header_layout.addWidget(self.btn_cancel_scan)
        self._device_progress = QProgressBar()
        self._device_progress.setRange(0, 100)
        self._device_progress.setValue(0)
        self._device_progress.setTextVisible(False)
        self._device_progress.setFixedHeight(7)
        self._device_progress.setStyleSheet(
            f"QProgressBar {{ background: {Theme.GLASS_INPUT}; border: none;"
            "border-radius: 3px; }"
            f"QProgressBar::chunk {{ background: {Theme.ACCENT}; border-radius: 3px; }}")
        self._device_progress.hide()
        self.devices_card.content_layout.addWidget(self._device_progress)
        # Scrollable device list so it adapts to any number of devices
        from PyQt6.QtWidgets import QFrame as _QFrame
        from PyQt6.QtWidgets import QScrollArea
        dev_scroll = QScrollArea()
        dev_scroll.setWidgetResizable(True)
        dev_scroll.setFrameShape(_QFrame.Shape.NoFrame)
        dev_scroll.setStyleSheet("background: transparent; border: none;")
        dev_holder = QWidget()
        dev_holder.setStyleSheet("background: transparent;")
        self._devices_container = QVBoxLayout(dev_holder)
        self._devices_container.setContentsMargins(0, 0, 0, 0)
        self._devices_container.setSpacing(4)
        self._devices_placeholder = QLabel("Press Rescan to discover devices.")
        self._devices_placeholder.setStyleSheet(
            f"color: {Theme.TEXT_MUTED}; font-size: {Theme.FONT_SIZE_SMALL}px;"
            f"background: transparent;"
        )
        self._devices_container.addWidget(self._devices_placeholder)
        self._devices_container.addStretch()
        dev_scroll.setWidget(dev_holder)
        self.devices_card.content_layout.addWidget(dev_scroll)
        row.addWidget(self.devices_card, 2)

        row.addWidget(self._build_capture_card(BOTTOM_HEIGHT), 2)

        from ui.widgets.recent_activity import RecentActivity
        self.activity_card = Card("Recent Activity", "check")
        self.activity_card.setFixedHeight(BOTTOM_HEIGHT)

        self.btn_view_all = QPushButton("View All")
        self.btn_view_all.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_view_all.setStyleSheet(
            f"QPushButton {{ background: {Theme.BG_ELEVATED}; color: {Theme.TEXT_SECONDARY};"
            f"border: 1px solid {Theme.BORDER_STRONG}; border-radius: 6px;"
            f"padding: 3px 10px; font-size: {Theme.FONT_SIZE_TINY}px; }}"
            f"QPushButton:hover {{ border-color: {Theme.ACCENT}; color: {Theme.TEXT_BODY}; }}")
        self.btn_view_all.clicked.connect(self._show_all_activity)
        self.activity_card.header_layout.addWidget(self.btn_view_all)

        self.recent_activity = RecentActivity(limit=5)
        self.activity_card.content_layout.addWidget(self.recent_activity)
        row.addWidget(self.activity_card, 2)

        self._grid.addLayout(row, 0)

    # -- LIFECYCLE --
    def on_enter(self):
        if not self._loaded_once:
            self._loaded_once = True
            self._begin_loading()
        else:
            # Restart timers stopped by on_leave().
            self._start_monitor()
            self._ping_timer.start()
            self._sync_discovery_snapshot()
        self._discovery_timer.start()
        self._capture_timer.start()
        self._refresh_capture_card()

    def on_leave(self):
        self._capture_timer.stop()
        self._discovery_timer.stop()
        # Traffic monitor and ping timer keep running so the history stays continuous
        if self._monitor_worker in self._workers:
            self._workers.remove(self._monitor_worker)
        if self._devices_scanning:
            self._devices_placeholder.setText(
                "Discovery is stopping because Dashboard was left. "
                "Partial results remain available when the scan finishes.")
            self._devices_placeholder.setWordWrap(True)
            self._discovery_service.cancel()
            if self._discovery_worker is not None:
                self._discovery_worker.stop()
        super().on_leave()

    # -- LOADING PHASE - fetch everything, then reveal (app-wide screen) -- 
    def _begin_loading(self):
        if self._window:
            self._window.begin_loading()
            self._window.loading_progress("Checking connectivity…")

        self._pending = {"internet"}

        self._load_internet_status()
        self._start_monitor()
        # Fill Top Devices and the Network Map right away; Rescan stays
        # available for a manual refresh.
        self._sync_discovery_snapshot()
        self._start_startup_scan()

    def _task_done(self, name: str):
        self._pending.discard(name)
        if not self._pending:
            self._reveal()

    def _reveal(self):
        if self._window:
            self._window.loading_progress("Ready")
            self._window.end_loading()
        self._ping_timer.start()

    def _show_all_activity(self):
        # Open the full activity history in a dialog.
        from ui.components.activity_dialog import ActivityDialog
        dlg = ActivityDialog(self)
        dlg.exec()

    def _refresh_internet(self):
        if self._internet_worker is not None and self._internet_worker.isRunning():
            return
        w = OneshotWorker(self.core.ping_quick)
        w.result.connect(self._on_internet)
        w.error.connect(lambda e: None)
        self._internet_worker = w
        w.start()

    # -- DATA LOADING --
    def _load_internet_status(self):
        w = OneshotWorker(self.core.ping_quick)
        w.result.connect(self._on_internet)
        w.error.connect(lambda e: self.card_internet.set_value("—", "ms", color=Theme.DANGER, subtitle="No answer"))
        w.done.connect(lambda: self._task_done("internet"))
        self.register_worker(w)
        w.start()

    def _on_internet(self, data: dict):
        items = data.get("items", [])
        reachable = [r for r in items if not r.get("unreachable")]
        self._internet_online = bool(reachable)
        if not reachable:
            self._hero_state.update(online=False)
            self._update_hero()
            self.card_internet.set_value("—", "ms", color=Theme.DANGER, subtitle="Offline")
            traffic_history.add_connectivity(None, 100.0)
            return
        avg_ping = round(sum(r["avg"] for r in reachable) / len(reachable))
        avg_loss = round(sum(r["loss"] for r in reachable) / len(reachable), 1)
        traffic_history.add_connectivity(avg_ping, avg_loss)
        self._hero_state.update(online=True, ping=avg_ping, loss=avg_loss)
        self._update_hero()
        ping_color = Theme.SUCCESS if avg_ping < 60 else Theme.WARNING if avg_ping < 150 else Theme.DANGER
        self.card_internet.set_value(f"{avg_ping}", "ms", color=ping_color, subtitle=f"ping · {avg_loss}% loss",
                                     sub_color=Theme.SUCCESS if avg_loss < 1 else Theme.WARNING)
        self.network_map.set_wan(f"{avg_ping} ms")

    def _on_rescan_clicked(self):
        self._silent_scan = False
        self._rescan_network()

    def _start_startup_scan(self):
        """Run the first device scan automatically, without a toast popup."""
        self._silent_scan = True
        self._rescan_network()

    def _rescan_network(self):
        """Start the configured, bounded subnet discovery operation."""
        if self._discovery_service.snapshot()["active"]:
            return
        self._devices_scanning = True
        self.btn_rescan.setEnabled(False)
        self.btn_rescan.setText("  Scanning…")
        self.btn_cancel_scan.show()
        self.btn_cancel_scan.setEnabled(True)
        self._device_progress.setValue(0)
        self._device_progress.show()
        self._devices_placeholder.setText("Preparing subnet discovery…")
        self._devices_placeholder.show()
        self._device_signature = None
        self._load_devices()

    def _load_devices(self):
        """Run the shared discovery service without blocking the GUI thread."""
        self._devices_scanning = True
        self.btn_rescan.setEnabled(False)
        self.btn_rescan.setText("  Scanning…")
        w = StreamWorker(self._discovery_service.scan_stream)
        w.result.connect(self._on_discovery_event)
        w.error.connect(self._on_scan_error)
        w.done.connect(self._on_scan_done)
        self.register_worker(w)
        self._discovery_worker = w
        self._discovery_timer.start()
        w.start()

    def _cancel_network_scan(self):
        if not self._devices_scanning:
            return
        self.btn_cancel_scan.setEnabled(False)
        self._devices_placeholder.setText("Cancelling discovery; retaining partial results…")
        self._discovery_service.cancel()
        if self._discovery_worker is not None:
            self._discovery_worker.stop()

    def _on_scan_error(self, err):
        from core.netwer_core import friendly_error
        msg = friendly_error(err) if err else "Couldn't scan the network right now."
        self._devices_placeholder.setText(msg)
        self._devices_placeholder.setWordWrap(True)
        self._devices_placeholder.show()

    def _on_discovery_event(self, event):
        if event.get("event") == "started":
            segments = event.get("segments", [])
            self._devices_placeholder.setText(
                f"Scanning {len(segments)} subnet(s) · {event.get('total', 0):,} hosts")
            self._device_progress.setValue(0)
            return
        if event.get("event") == "segment":
            segment = event.get("segment", {})
            self._devices_placeholder.setText(
                f"Scanning {segment.get('label', 'subnet')} · {segment.get('cidr', '')}")
            return
        if event.get("event") == "enriching":
            self._device_progress.setValue(100)
            self._devices_placeholder.setText("Identifying devices…")
            self._devices_placeholder.show()
            return
        if event.get("event") == "progress":
            total = max(1, int(event.get("total", 1)))
            scanned = min(total, int(event.get("scanned", 0)))
            self._device_progress.setValue(round(scanned * 100 / total))
            self._devices_placeholder.setText(
                f"{event.get('current_subnet', '')} · {scanned:,}/{total:,} hosts · "
                f"{event.get('found', 0):,} discovered")
            return
        if event.get("online"):
            self._sync_discovery_snapshot()
            return
        if event.get("done"):
            self._device_progress.setValue(
                round(int(event.get("scanned", 0)) * 100 /
                      max(1, int(event.get("total", 1)))))
            if event.get("cancelled"):
                self._devices_placeholder.setText(
                    f"Scan cancelled · {event.get('found', 0)} partial result(s) retained.")
                self._devices_placeholder.show()
            else:
                self._device_progress.hide()
                if not int(event.get("found", 0)):
                    self._devices_placeholder.setText("No devices responded.")
                    self._devices_placeholder.show()
            self._sync_discovery_snapshot()

    def _on_scan_done(self):
        snapshot = self._discovery_service.snapshot()
        self._discovery_worker = None
        self._discovery_timer.stop()
        self._devices_scanning = False
        self.btn_rescan.setEnabled(True)
        self.btn_rescan.setText("  Rescan")
        self.btn_cancel_scan.hide()
        self._sync_discovery_snapshot()
        if snapshot["status"] == "partial":
            self._devices_placeholder.setText(
                f"Scan cancelled · {len(snapshot['devices'])} partial result(s) retained.")
            self._devices_placeholder.show()
        elif snapshot["status"] == "complete":
            count = len(snapshot["devices"])
            self._device_progress.hide()
            if not count:
                self._devices_placeholder.setText("No devices responded.")
                self._devices_placeholder.show()
            from app.activity import activity
            activity.add("Network scan completed", f"{count} devices found", kind="success")
            if not self._silent_scan:
                from app.notifications import notifications
                notifications.notify_scan_done("Network scan complete", f"{count} devices found")
            self._silent_scan = False

    def _sync_discovery_snapshot(self):
        snapshot = self._discovery_service.snapshot()
        if snapshot.get("segments"):
            self._discovery_segments = snapshot["segments"]
        elif not self._discovery_segments:
            from core.discovery import configured_subnets
            self._discovery_segments = configured_subnets()
            self._discovery_service.set_segments(self._discovery_segments)
        devices = sorted(snapshot.get("devices", []), key=self._device_sort_key)
        signature = tuple((d.get("segment_id", ""), d.get("ip", ""),
                           d.get("mac", ""), d.get("reachability", ""),
                           d.get("rtt_ms"), d.get("hostname", ""),
                           d.get("kind", "")) for d in devices)
        if signature == self._device_signature:
            return
        self._device_signature = signature
        self._all_devices = devices

        # Collect first, then remove
        stale = []
        for index in range(self._devices_container.count()):
            item = self._devices_container.itemAt(index)
            widget = item.widget() if item else None
            if widget and widget is not self._devices_placeholder:
                stale.append(widget)
        for widget in stale:
            self._devices_container.removeWidget(widget)
            widget.setParent(None)
            widget.deleteLater()
        if not devices:
            self.card_devices.set_value("0" if snapshot.get("status") == "complete" else "—",
                                        color=Theme.TEXT_MUTED,
                                        subtitle="On configured subnets")
            if snapshot.get("status") in ("idle", "complete"):
                self._devices_placeholder.setText(
                    "Press Rescan to discover devices." if snapshot.get("status") == "idle"
                    else "No devices responded.")
                self._devices_placeholder.show()
            return
        responding = sum(1 for d in devices if d.get("reachability") == "reachable")
        self.card_devices.set_value(str(len(devices)), subtitle=f"{responding} responding")
        self._devices_placeholder.hide()
        for dev in devices[:100]:
            idx = max(0, self._devices_container.count() - 2)
            self._devices_container.insertWidget(idx, self._device_row(dev))
        self._maybe_update_map()

    @staticmethod
    def _device_sort_key(dev: dict):
        """Router first, then by IP address (numerically)."""
        try:
            import ipaddress
            ip = int(ipaddress.ip_address(dev.get("ip", "0.0.0.0")))
        except ValueError:
            ip = 0
        return (not dev.get("is_gateway"), ip)

    def _on_devices(self, data: dict):
        devices = data.get("devices", [])
        self._all_devices = devices
        self._device_signature = None
        self._sync_discovery_snapshot()

    def _open_topology(self):
        # Open the full-screen topology view with the current scan data.
        from ui.components.topology_dialog import TopologyDialog
        gateway = getattr(self, "_gateway", "") or ""
        devices = getattr(self, "_all_devices", None) or []
        router_vendor = ""
        for d in devices:
            if d.get("ip") == gateway:
                router_vendor = d.get("vendor", "") or ""
                break
        dlg = TopologyDialog(self.core, gateway, devices, router_vendor,
                             online=getattr(self, "_internet_online", True),
                             parent=self)
        dlg.exec()

    def _open_device_details(self, device: dict):
        """Open the details popup for a clicked radar node (ports, MAC, etc.)."""
        from ui.components.device_details_dialog import DeviceDetailsDialog
        dlg = DeviceDetailsDialog(self.core, device, self)
        dlg.exec()

    def _maybe_update_map(self):
        """Update the topology map once we have both gateway and devices."""
        devices = list(getattr(self, "_all_devices", None) or [])
        gateway = getattr(self, "_gateway", None) or next(
            (d.get("ip") for d in devices if d.get("is_gateway")), None)
        if not (gateway and devices):
            return
        router_vendor = next((d.get("vendor", "") or "" for d in devices if d.get("ip") == gateway), "")
        # devices only the packet capture has seen show up on the map as new
        from core.capture import get_capture_service
        known = {d.get("ip") for d in devices}
        new = [v["ip"] for v in get_capture_service().lan_macs.values()
               if v.get("ip") and ":" not in v["ip"] and v["ip"] not in known and v["ip"] != gateway]
        devices += [{"ip": ip, "hostname": "", "vendor": "", "kind": ""} for ip in dict.fromkeys(new)]
        self.network_map.set_topology(gateway, devices, router_vendor,
                                      online=getattr(self, "_internet_online", True))
        self.network_map.set_new(new)
        shown = len(devices)
        self.map_count.setText(f"{shown} devices" + (f" · {len(set(new))} new" if new else ""))
        if new:
            self.card_devices.set_value(str(shown), subtitle=f"{len(set(new))} new via capture",
                                        sub_color=Theme.ACCENT_GLOW)
        self._update_subtitle()

    @staticmethod
    def device_display_name(dev: dict) -> str:
        """Return the shared display name for a device."""
        from ui.widgets.network_map import device_display_name as _n
        return _n(dev)

    def _device_row(self, dev: dict) -> QWidget:
        from ui.widgets.network_map import guess_device_icon
        w = QFrame()
        w.setObjectName("DevRow")
        w.setStyleSheet(f"#DevRow {{ background: transparent; border: none; border-top: 1px solid {card_border()}; }}"
                        "#DevRow QLabel { background: transparent; border: none; }")
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 9, 0, 9)
        row.setSpacing(10)
        icon = QLabel()
        icon.setFixedSize(32, 32)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        kind = guess_device_icon(dev)
        icon.setPixmap(Icons.pixmap(kind if kind in ("dev_pc", "dev_router", "dev_phone", "dev_tv", "dev_laptop")
                                    else "dev_generic", 16, Theme.TEXT_SECONDARY))
        icon.setStyleSheet(f"background: {Theme.BG_ELEVATED}; border: 1px solid {card_border()}; border-radius: 8px;")
        row.addWidget(icon)
        col = QVBoxLayout()
        col.setSpacing(1)
        name = self.device_display_name(dev)
        if dev.get("is_self"):
            name = f"{name} (this device)"
        n = QLabel(str(name)[:34])
        n.setStyleSheet(f"color: {Theme.TEXT_PRIMARY}; font-size: {Theme.FONT_SIZE_SMALL}px; font-weight: 500;")
        col.addWidget(n)
        vendor = dev.get("vendor", "")
        detail = (dev.get("mac") or "")[:8].lower() if dev.get("is_gateway") else vendor
        sub = QLabel(dev.get("ip", "") + (f" · {detail}" if detail and detail != "Unknown" else ""))
        sub.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-family: {Theme.FONT_MONO}; font-size: 11px;")
        col.addWidget(sub)
        row.addLayout(col, 1)
        if dev.get("is_gateway"):
            text, color = "Gateway", Theme.SUCCESS
        elif dev.get("reachability") == "reachable" or dev.get("is_self"):
            text, color = "Online", Theme.SUCCESS
        else:
            text, color = "Seen earlier", Theme.TEXT_MUTED
        badge = QLabel(text)
        badge.setStyleSheet(f"color: {color}; border: 1px solid {color}; border-radius: 5px; padding: 1px 6px;"
                            f"font-size: 10.5px;")
        row.addWidget(badge)
        return w

    # -- Live monitor (stream) --
    def _open_traffic_analysis(self):
        # Open the detailed bandwidth / latency / packet-loss view.
        from ui.components.traffic_analysis_dialog import TrafficAnalysisDialog
        dlg = TrafficAnalysisDialog(self)
        dlg.exec()

    def _on_adapter_setting(self, _name=""):
        # The adapter was changed in Settings: restart the monitor
        if self._monitor_worker is not None:
            self._monitor_worker.stop()
            self._monitor_worker = None
        self._start_monitor()

    def shutdown(self):
        # Called when the app closes or pages are rebuilt
        self._closing = True
        self._watchdog.stop()
        self._ping_timer.stop()
        if self._monitor_worker is not None:
            self._monitor_worker.stop()
            self._monitor_worker.wait(1500)
            self._monitor_worker = None

    def _start_monitor(self, reset=True):
        if self._monitor_worker is not None or self._closing:
            return
        if reset:
            self.card_download.set_value("0.0", "Kbps", color=Theme.ACCENT, subtitle="Live")
            self.card_upload.set_value("0.0", "Kbps", color=Theme.ACCENT_PURPLE, subtitle="Live")
        w = StreamWorker(self.core.monitor_stream, adapter_state.get())
        w.result.connect(self._on_monitor)
        w.error.connect(lambda e: None)
        w.done.connect(lambda w=w: self._monitor_ended(w))
        self.register_worker(w)
        self._monitor_worker = w
        self._last_sample = time.time()
        self._watchdog.start()
        w.start()

    def _monitor_ended(self, w):
        # The stream stopped on its own: start it again
        if w is self._monitor_worker and not self._closing:
            self._monitor_worker = None
            QTimer.singleShot(1500, lambda: self._start_monitor(reset=False))

    def _check_monitor(self):
        if self._monitor_worker is not None and time.time() - self._last_sample > 8:
            self._monitor_worker.stop()
            self._monitor_worker = None
            self._start_monitor(reset=False)

    def _update_trend(self, card, attr, value):
        """Update the trend badge when both samples are meaningful."""
        prev = getattr(self, attr, None)
        setattr(self, attr, value)
        if not prev or prev < 1 or value < 1:
            card.set_badge("")
            return
        pct = round((value - prev) / prev * 100)
        if pct == 0:
            card.set_badge("")
        elif pct > 0:
            card.set_badge(f"\u2191 {pct}%", positive=True)
        else:
            card.set_badge(f"\u2193 {abs(pct)}%", positive=False)

    def _on_monitor(self, d: dict):
        adapter = d.get("adapter", "")
        self._last_sample = time.time()
        if adapter and adapter != getattr(self, "_adapter_name", ""):
            self._adapter_name = adapter
            self.network_map.set_link_label(adapter)
            self._update_subtitle()
        if "dl" in d and "ul" in d:
            traffic_history.set_adapter(adapter)
            traffic_history.add_bandwidth(d["dl"], d["ul"])
            self.chart.push(d["dl"], d["ul"])
            self.network_map.set_traffic(d["dl"], d["ul"], self._lan_talkers())
            dl_val, dl_unit = format_speed(d["dl"])
            ul_val, ul_unit = format_speed(d["ul"])
            self.card_download.set_value(dl_val, dl_unit.lower(), subtitle="live")
            self.card_upload.set_value(ul_val, ul_unit.lower(), subtitle="live")

    def _lan_talkers(self):
        # LAN devices that sent multicast or broadcast in the last second of the capture
        from core.capture import get_capture_service
        cap = get_capture_service()
        if not cap.running or not cap.count():
            return set()
        now = cap.packets[-1].rel
        out = set()
        for p in reversed(cap.packets[-400:]):
            if p.rel < now - 1:
                break
            if p.dis.proto in ("MDNS", "SSDP", "LLMNR", "NBNS", "ARP"):
                out.add(p.dis.ip_src or p.dis.fields.get("arp.src.proto_ipv4"))
        return out

    def _update_subtitle(self):
        from ui.pages.capture_page import local_ipv4
        parts = [getattr(self, "_adapter_name", "")] + [local_ipv4()]
        devices = getattr(self, "_all_devices", None) or []
        gw = next((d for d in devices if d.get("is_gateway")), None)
        if gw:
            parts.append(f"gateway {self.device_display_name(gw)} {gw.get('ip', '')}")
        text = " · ".join(x for x in parts if x)
        if text and getattr(self, "_subtitle_label", None) is not None:
            self._subtitle_label.setText(text)

