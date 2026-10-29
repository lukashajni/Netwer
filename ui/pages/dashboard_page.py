"""Main dashboard for network and system monitoring."""

import time

from PyQt6.QtCore import QRectF, Qt, QTimer
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
from app.theme import Theme
from app.traffic_history import traffic_history
from core.discovery import get_discovery_service
from ui.pages.base_page import BasePage
from ui.widgets.card import Card, kv_row
from ui.widgets.gauge import Gauge
from ui.widgets.live_chart import LiveChart
from ui.widgets.stat_card import StatCard
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


class DashboardPage(BasePage):
    PAGE_TITLE = "Dashboard"
    PAGE_SUBTITLE = "Overview of your network and system status"

    def __init__(self, core, parent=None):
        super().__init__(core, parent)

        self._monitor_worker = None
        self._closing = False
        self._last_sample = time.time()
        self._watchdog = QTimer(self)             # restarts the monitor if it stalls
        self._watchdog.setInterval(5000)
        self._watchdog.timeout.connect(self._check_monitor)
        adapter_state.changed.connect(self._on_adapter_setting)
        self._resource_timer = QTimer(self)
        self._resource_timer.setInterval(1500)
        self._resource_timer.timeout.connect(self._refresh_resources)
        self._resource_worker = None

        self._boot_epoch = None

        # Refresh connectivity for the ping and loss sparklines.
        self._ping_timer = QTimer(self)
        self._ping_timer.setInterval(5000)
        self._ping_timer.timeout.connect(self._refresh_internet)
        self._internet_worker = None

        # Refresh network details to reflect adapter and address changes.
        self._info_timer = QTimer(self)
        self._info_timer.setInterval(4000)
        self._info_timer.timeout.connect(self._refresh_info)
        self._wifi_worker = None
        self._eth_worker = None

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
        self._build_stat_cards()
        self._build_middle_row()
        self._build_bottom_row()
        self._build_info_row()

        self._hero_state = {"online": None, "ping": None, "loss": None}
        self._capture_timer = QTimer(self)
        self._capture_timer.setInterval(1000)
        self._capture_timer.timeout.connect(self._refresh_capture_card)

    # -- UI CONSTRUCTION --
    def _build_hero_row(self):
        from ui.widgets.ui_kit import button
        row = QHBoxLayout()
        row.setSpacing(Theme.GAP)

        hero = QFrame()
        hero.setObjectName("DashHero")
        hero.setStyleSheet(
            f"#DashHero {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {Theme.BG_ELEVATED},"
            f"stop:1 {Theme.GLASS_CARD}); border: 1px solid {Theme.GLASS_BORDER_HI};"
            f"border-radius: {Theme.RADIUS_CARD}px; }} #DashHero QLabel {{ background: transparent; }}")
        hero.setFixedHeight(150)
        lay = QHBoxLayout(hero)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(18)
        self.score_ring = _ScoreRing()
        lay.addWidget(self.score_ring)
        col = QVBoxLayout()
        col.setSpacing(4)
        eyebrow = QLabel("AT A GLANCE")
        eyebrow.setStyleSheet(f"color: {Theme.ACCENT_GLOW}; font-size: 10px; font-weight: 700; letter-spacing: 1.3px;")
        col.addWidget(eyebrow)
        self.hero_title = QLabel("Checking your network\u2026")
        self.hero_title.setStyleSheet(f"color: {Theme.TEXT_PRIMARY}; font-size: 18px; font-weight: 600;")
        col.addWidget(self.hero_title)
        self.hero_text = QLabel("")
        self.hero_text.setWordWrap(True)
        self.hero_text.setTextFormat(Qt.TextFormat.RichText)
        self.hero_text.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-size: {Theme.FONT_SIZE_SMALL}px;")
        col.addWidget(self.hero_text)
        btns = QHBoxLayout()
        self.btn_hero_ai = button("Ask Netwer AI what to improve", "ai", "ai")
        self.btn_hero_ai.clicked.connect(lambda: self._ask_ai(
            "Look at my network status, devices and traffic. Is anything wrong, and what should I improve?"))
        btns.addWidget(self.btn_hero_ai)
        btns.addStretch()
        col.addLayout(btns)
        lay.addLayout(col, 1)
        row.addWidget(hero, 5)

        self.capture_card = Card("Packet Capture", "capture")
        self.capture_card.setFixedHeight(150)
        self.btn_open_capture = button("Open", "capture")
        self.btn_open_capture.clicked.connect(lambda: self._window and self._window.goto("capture"))
        self.capture_card.header_layout.addWidget(self.btn_open_capture)
        self.capture_status = QLabel("Not capturing. Open Packet Capture and press Start.")
        self.capture_status.setWordWrap(True)
        self.capture_status.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-size: {Theme.FONT_SIZE_SMALL}px;")
        self.capture_card.content_layout.addWidget(self.capture_status)
        from ui.pages.capture_page import MixBar
        self.capture_mix = MixBar()
        self.capture_card.content_layout.addWidget(self.capture_mix)
        self.capture_hosts = QLabel("")
        self.capture_hosts.setTextFormat(Qt.TextFormat.RichText)
        self.capture_hosts.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: {Theme.FONT_SIZE_TINY}px;")
        self.capture_card.content_layout.addWidget(self.capture_hosts)
        self.capture_card.content_layout.addStretch()
        row.addWidget(self.capture_card, 3)
        self._grid.addLayout(row, 0)

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
        cap = get_capture_service()
        n = cap.count()
        if not n:
            self.capture_status.setText("Capturing\u2026 waiting for packets." if cap.running
                                        else "Not capturing. Open Packet Capture and press Start.")
            self.capture_mix.set_parts([])
            self.capture_hosts.setText("")
            return
        size = cap.total_bytes
        size_s = f"{size / 1048576:.1f} MB" if size >= 1048576 else f"{size / 1024:.0f} KB"
        state = "Capturing" if cap.running else "Stopped"
        self.capture_status.setText(f"{state} on {cap.iface}  \u00b7  {n:,} packets  \u00b7  {size_s}")
        self.capture_mix.set_parts(cap.proto_mix.most_common(8))
        top = sorted(cap.conv.items(), key=lambda kv: -kv[1]["bytes"])[:2]
        self.capture_hosts.setText("<br>".join(
            f"<span style='color:{Theme.TEXT_BODY}'>{cap.host(ip)}</span> \u00b7 {c['bytes'] / 1024:.0f} KB"
            for ip, c in top))
        self._update_hero()

    def _build_stat_cards(self):
        row = QHBoxLayout()
        row.setSpacing(Theme.GAP)
        self.card_internet = StatCard("internet", "Internet Status", spark_color=Theme.SUCCESS, extra_parallel=True)
        self.card_download = StatCard("download", "Receive Speed", spark_color=Theme.ACCENT)
        self.card_upload = StatCard("upload", "Send Speed", spark_color=Theme.ACCENT_PURPLE)
        self.card_loss = StatCard("packet_loss", "Packet Loss", spark_color=Theme.SUCCESS)
        self.card_devices = StatCard("devices", "Devices online")
        for c in (self.card_internet, self.card_download, self.card_upload,
                  self.card_loss, self.card_devices):
            c.setFixedHeight(180)
            row.addWidget(c)
        self._grid.addLayout(row, 0)

    def _build_middle_row(self):
        row = QHBoxLayout()
        row.setSpacing(Theme.GAP)

        MIDDLE_HEIGHT = 340  # minimum height so left and right columns align

        monitor_card = Card("Live Network Monitor", "monitor")
        monitor_card.setMinimumHeight(MIDDLE_HEIGHT)  # grows in fullscreen
        # Opens the detailed analysis (bandwidth, latency, packet loss).
        from PyQt6.QtWidgets import QPushButton
        self.btn_analysis = QPushButton(" Detailed analysis")
        self.btn_analysis.setIcon(Icons.get("monitor", Theme.TEXT_SECONDARY))
        self.btn_analysis.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_analysis.setStyleSheet(
            f"QPushButton {{ background: {Theme.BG_ELEVATED}; color: {Theme.TEXT_BODY};"
            f"border: 1px solid {Theme.BORDER_STRONG}; border-radius: 6px;"
            f"padding: 3px 10px; font-size: {Theme.FONT_SIZE_TINY}px; }}"
            f"QPushButton:hover {{ border-color: {Theme.ACCENT}; color: {Theme.ACCENT}; }}")
        self.btn_analysis.clicked.connect(self._open_traffic_analysis)
        monitor_card.header_layout.addWidget(self.btn_analysis)

        # Legend row (Receive = blue, Send = purple) + live peak/avg stats
        legend = QHBoxLayout()
        legend.setSpacing(16)
        legend.addWidget(self._legend_item("Receive", Theme.ACCENT))
        legend.addWidget(self._legend_item("Send", Theme.ACCENT_PURPLE))
        legend.addStretch()
        # Peak / Avg readouts (updated live, hover the graph for per-point).
        self.stat_peak = QLabel("Peak \u2014")
        self.stat_avg = QLabel("Avg \u2014")
        for lbl in (self.stat_peak, self.stat_avg):
            lbl.setStyleSheet(
                f"color: {Theme.TEXT_SECONDARY}; font-size: {Theme.FONT_SIZE_TINY}px;"
                f"font-family: {Theme.FONT_MONO}; background: transparent;")
            legend.addWidget(lbl)
        monitor_card.content_layout.addLayout(legend)

        self.chart = LiveChart(max_points=60)
        self.chart.clicked.connect(self._open_traffic_analysis)
        monitor_card.content_layout.addWidget(self.chart, 1)

        # Small label showing which adapter is currently monitored
        self.adapter_status = QLabel("Monitoring: detecting…")
        self.adapter_status.setStyleSheet(
            f"color: {Theme.TEXT_MUTED}; font-size: {Theme.FONT_SIZE_TINY}px;"
            f"background: transparent;"
        )
        monitor_card.content_layout.addWidget(self.adapter_status)

        row.addWidget(monitor_card, 3)

        from ui.widgets.network_map import NetworkMap
        self.map_card = Card("Network Map", "network")
        self.map_card.setMinimumHeight(MIDDLE_HEIGHT)
        self.btn_expand_map = QPushButton("  Expand")
        self.btn_expand_map.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_expand_map.setIcon(Icons.get("network", Theme.ACCENT))
        self.btn_expand_map.setStyleSheet(
            f"QPushButton {{ background: {Theme.GLASS_INPUT};"
            f"color: {Theme.TEXT_SECONDARY};"
            f"border: 1px solid {Theme.GLASS_BORDER};"
            f"border-radius: {Theme.RADIUS_CONTROL}px;"
            f"padding: 5px 12px; font-size: 12px; }}"
            f"QPushButton:hover {{ border-color: {Theme.GLASS_BORDER_HI};"
            f"color: {Theme.TEXT_PRIMARY}; }}")
        self.btn_expand_map.clicked.connect(self._open_topology)
        legend_map = QHBoxLayout()
        legend_map.setSpacing(12)
        legend_map.addWidget(self._legend_item("in", Theme.ACCENT))
        legend_map.addWidget(self._legend_item("out", Theme.ACCENT_PURPLE))
        self.map_card.header_layout.addLayout(legend_map)
        self.map_card.header_layout.addWidget(self.btn_expand_map)
        self.network_map = NetworkMap()
        self.network_map.node_clicked.connect(self._open_device_details)
        self.map_card.content_layout.addWidget(self.network_map, 1)
        row.addWidget(self.map_card, 2)
        self._grid.addLayout(row, 0)

    def _build_info_row(self):
        row = QHBoxLayout()
        row.setSpacing(Theme.GAP)

        self.summary_card = Card("Network Summary", "summary")
        self._summary_values = {}
        for key in ("Adapter", "Public IP", "Local IP", "Gateway", "DNS", "MAC Address"):
            container, val_lbl = kv_row(key, "\u2014", mono=True)
            self._summary_values[key] = val_lbl
            self.summary_card.content_layout.addWidget(container)

        self.wifi_card = Card("WiFi", "wifi")
        wifi_body = QHBoxLayout()
        wifi_body.setSpacing(14)
        wifi_left = QVBoxLayout()
        wifi_left.setSpacing(0)   # stretch springs handle spacing in fullscreen
        wifi_left.addStretch()
        self._wifi_values = {}
        wifi_keys = ("Connection", "SSID", "Signal", "Channel")
        for i, key in enumerate(wifi_keys):
            container, val_lbl = kv_row(key, "\u2014", mono=(key == "Signal"))
            self._wifi_values[key] = val_lbl
            wifi_left.addWidget(container)
            # Even vertical spring between rows (not after the last one), so the
            # rows spread out to fill the card when the window is maximized.
            if i < len(wifi_keys) - 1:
                wifi_left.addStretch(1)
        wifi_left.addStretch()
        wifi_body.addLayout(wifi_left, 1)
        from ui.widgets.wifi_signal import WiFiSignal
        self.wifi_signal = WiFiSignal(92)
        self.wifi_signal.set_disconnected()
        wifi_body.addWidget(self.wifi_signal, 0,
                            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter)
        self.wifi_card.content_layout.addLayout(wifi_body)
        row.addWidget(self.summary_card, 1)
        row.addWidget(self.wifi_card, 1)
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

        self.devices_card = Card("Top Devices", "devices")
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

        self.resources_card = Card("System Resources", "resources")
        self.resources_card.setFixedHeight(BOTTOM_HEIGHT)
        gauges = QHBoxLayout()
        gauges.setSpacing(0)
        gauges.setContentsMargins(8, 0, 8, 0)
        self.gauge_cpu = Gauge("CPU", Theme.ACCENT)
        self.gauge_ram = Gauge("Memory", Theme.ACCENT_PURPLE)
        self.gauge_disk = Gauge("Disk", Theme.SUCCESS)
        for g in (self.gauge_cpu, self.gauge_ram, self.gauge_disk):
            gauges.addStretch(1)
            gauges.addWidget(g)
            gauges.addStretch(1)
        self.resources_card.content_layout.addLayout(gauges)
        row.addWidget(self.resources_card, 2)

        self._grid.addLayout(row, 0)

    # -- LIFECYCLE --
    def on_enter(self):
        if not self._loaded_once:
            self._loaded_once = True
            self._begin_loading()
        else:
            # Restart timers stopped by on_leave().
            self._start_monitor()
            self._resource_timer.start()
            self._ping_timer.start()
            self._info_timer.start()
            self._refresh_resources()
            self._refresh_info()
            self._sync_discovery_snapshot()
        self._discovery_timer.start()
        self._capture_timer.start()
        self._refresh_capture_card()

    def on_leave(self):
        self._capture_timer.stop()
        self._resource_timer.stop()
        self._info_timer.stop()
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

        self._pending = {"internet", "sysinfo", "summary", "wifi", "resources"}

        self._load_internet_status()
        self._load_uptime()
        self._load_summary()
        self._load_wifi()
        self._refresh_resources(initial=True)
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
        self._resource_timer.start()
        self._ping_timer.start()
        self._info_timer.start()

    def _show_all_activity(self):
        # Open the full activity history in a dialog.
        from ui.components.activity_dialog import ActivityDialog
        dlg = ActivityDialog(self)
        dlg.exec()

    def _refresh_info(self):
        """Refresh Wi-Fi and Ethernet details periodically."""
        if self._wifi_worker is None or not self._wifi_worker.isRunning():
            w = OneshotWorker(self.core.get_wifi_info)
            w.result.connect(self._on_wifi)
            w.error.connect(lambda e: self._wifi_error())
            self._wifi_worker = w
            w.start()
        if self._eth_worker is None or not self._eth_worker.isRunning():
            w2 = OneshotWorker(self.core.get_ethernet_info)
            w2.result.connect(self._on_eth)
            w2.error.connect(lambda e: None)
            self._eth_worker = w2
            w2.start()

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
        w.error.connect(lambda e: self.card_internet.set_value("N/A", color=Theme.DANGER))
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
            self.card_internet.set_value("Offline", color=Theme.DANGER)
            self.card_loss.set_tile_tint("#351a24", "#ff6b8a")
            self.card_loss.set_value("100", "%", color=Theme.DANGER, subtitle="No response")
            self.card_loss.push_spark(100)
            traffic_history.add_connectivity(None, 100.0)
            return
        avg_ping = round(sum(r["avg"] for r in reachable) / len(reachable))
        avg_loss = round(sum(r["loss"] for r in reachable) / len(reachable), 1)
        traffic_history.add_connectivity(avg_ping, avg_loss)
        self._hero_state.update(online=True, ping=avg_ping, loss=avg_loss)
        self._update_hero()
        self.card_internet.set_value("Connected", color=Theme.SUCCESS,
                                     subtitle=f"Ping: {avg_ping} ms")
        if avg_loss < 1:
            loss_color, tile, note = Theme.SUCCESS, ("#123528", "#33d6a6"), "Excellent"
        elif avg_loss < 5:
            loss_color, tile, note = Theme.WARNING, ("#332916", "#f5b545"), "Fair"
        else:
            loss_color, tile, note = Theme.DANGER, ("#351a24", "#ff6b8a"), "Poor"
        self.card_loss.set_tile_tint(*tile)
        self.card_loss.set_value(f"{avg_loss}", "%", color=loss_color,
                                 subtitle=note)
        # Feed sparklines: ping trend on the internet card, loss on its card
        self.card_internet.push_spark(avg_ping)
        self.card_loss.push_spark(avg_loss)

    def _load_uptime(self):
        w = OneshotWorker(self.core.get_system_info)
        w.result.connect(self._on_sysinfo)
        w.error.connect(lambda e: None)
        w.done.connect(lambda: self._task_done("sysinfo"))
        self.register_worker(w)
        w.start()

    def _on_sysinfo(self, data: dict):
        d = data.get("days", 0)
        h = data.get("hours", 0)
        m = data.get("minutes", 0)
        self._boot_epoch = time.time() - (d * 86400 + h * 3600 + m * 60)

    def _tick_uptime(self):
        pass

    def _load_summary(self):
        w = OneshotWorker(self.core.get_ethernet_info)
        w.result.connect(self._on_eth)
        w.error.connect(lambda e: None)
        w.done.connect(lambda: self._task_done("summary"))
        self.register_worker(w)
        w.start()

    def _on_eth(self, d: dict):
        name = d.get("adapter") or adapter_state.get() or "\u2014"
        self._set_summary("Adapter", f"{name} (not connected)" if "error" in d else name)
        self._set_summary("Public IP", d.get("public_ip", "\u2014"))
        self._set_summary("Local IP", d.get("ip", "\u2014"))
        self._set_summary("Gateway", d.get("gateway", "\u2014"))
        self._set_summary("DNS", d.get("dns", "\u2014"))
        self._set_summary("MAC Address", d.get("mac", "\u2014"))
        # Remember gateway for the network map
        self._gateway = d.get("gateway", "\u2014")
        self._maybe_update_map()

    def _set_summary(self, key: str, value: str, color: str = None):
        lbl = self._summary_values.get(key)
        if lbl:
            lbl.setText(str(value))
            if color:
                lbl.setStyleSheet(
                    f"color: {color}; font-family: {Theme.FONT_MONO};"
                    f"font-size: {Theme.FONT_SIZE_SMALL}px; background: transparent;"
                )

    def _load_wifi(self):
        w = OneshotWorker(self.core.get_wifi_info)
        w.result.connect(self._on_wifi)
        w.error.connect(lambda e: self._wifi_error())
        w.done.connect(lambda: self._task_done("wifi"))
        self.register_worker(w)
        w.start()

    def _on_wifi(self, d: dict):
        if not d or d.get("ssid") in (None, "", "\u2014"):
            self._wifi_error()
            return
        self._set_wifi("Connection", "WiFi", Theme.SUCCESS)
        self._set_wifi("SSID", d.get("ssid", "\u2014"))
        signal = d.get("signal", "\u2014")
        self._set_wifi("Signal", str(signal), Theme.SUCCESS)
        self._set_wifi("Channel", str(d.get("channel", "\u2014")))
        # Update the visual signal indicator. signal may be like "-42 dBm"
        # or a percentage, try to derive a 0-100 strength.
        pct = self._signal_to_percent(signal)
        self.wifi_signal.set_signal(pct)

    def _signal_to_percent(self, signal) -> float:
        """Convert a percentage, dBm reading, or number to signal strength."""
        try:
            s = str(signal).strip().lower()
            if "%" in s:
                return max(0, min(100, float(s.replace("%", "").strip())))
            if "dbm" in s:
                dbm = float(s.replace("dbm", "").strip())
                # -30 dBm ≈ 100%, -90 dBm ≈ 0%
                return max(0, min(100, (dbm + 90) / 60 * 100))
            val = float(s)
            if val < 0:  # looks like dBm
                return max(0, min(100, (val + 90) / 60 * 100))
            return max(0, min(100, val))
        except (ValueError, TypeError):
            return 50.0

    def _wifi_error(self):
        self._set_wifi("Connection", "Wired / N/A", Theme.TEXT_MUTED)
        for k in ("SSID", "Signal", "Channel"):
            self._set_wifi(k, "\u2014")
        self.wifi_signal.set_disconnected()

    def _set_wifi(self, key: str, value: str, color: str = None):
        lbl = self._wifi_values.get(key)
        if lbl:
            lbl.setText(str(value))
            if color:
                font = Theme.FONT_MONO if key == "Signal" else Theme.FONT_DATA
                lbl.setStyleSheet(
                    f"color: {color}; font-family: '{font}';"
                    f"font-size: {Theme.FONT_SIZE_SMALL}px; background: transparent;"
                )

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
            else:
                self._device_progress.setValue(100)
                count = int(event.get("found", 0))
                self._devices_placeholder.setText(
                    f"Scan complete · {count} device(s) found." if count else
                    "No devices responded.")
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
            self._devices_placeholder.setText(
                f"Scan complete · {count} device(s) found." if count else
                "No devices responded.")
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
        self.card_devices.set_value(str(len(devices)), color=Theme.WARNING,
                                    subtitle=f"{responding} responding")
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
        gateway = getattr(self, "_gateway", None)
        devices = getattr(self, "_all_devices", None)
        if gateway and devices:
            # Find router vendor from the device whose IP is equal to the gateway
            router_vendor = ""
            for d in devices:
                if d.get("ip") == gateway:
                    router_vendor = d.get("vendor", "") or ""
                    break
            self.network_map.set_topology(gateway, devices, router_vendor,
                                          online=getattr(self, "_internet_online", True))

    @staticmethod
    def device_display_name(dev: dict) -> str:
        """Return the shared display name for a device."""
        from ui.widgets.network_map import device_display_name as _n
        return _n(dev)

    def _device_row(self, dev: dict) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 3, 0, 3)
        name = self.device_display_name(dev)
        from ui.widgets.network_map import guess_device_icon
        icon = QLabel()
        icon.setFixedSize(18, 18)
        icon.setPixmap(Icons.pixmap(guess_device_icon(dev), 16, Theme.TEXT_SECONDARY))
        icon.setStyleSheet("background: transparent;")
        n = QLabel(str(name)[:22])
        n.setStyleSheet(f"color: {Theme.TEXT_BODY}; font-family: {Theme.FONT_DATA}; font-size: {Theme.FONT_SIZE_SMALL}px; background: transparent;")
        ip = QLabel(dev.get("ip", ""))
        ip.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-family: {Theme.FONT_MONO}; font-size: {Theme.FONT_SIZE_TINY}px; background: transparent;")
        vendor_name = dev.get("vendor", "")
        if vendor_name == "Unknown":
            vendor_name = "—"
        vendor = QLabel(vendor_name)
        vendor.setStyleSheet(f"color: {Theme.ACCENT}; font-family: {Theme.FONT_DATA}; font-size: {Theme.FONT_SIZE_TINY}px; background: transparent;")
        reachability = dev.get("reachability")
        status_text, status_color = {
            "reachable": ("Responding", Theme.SUCCESS),
        }.get(reachability, ("Discovered", Theme.TEXT_MUTED))
        status = QLabel(status_text)
        status.setStyleSheet(f"color: {status_color}; font-size: {Theme.FONT_SIZE_TINY}px; background: transparent;")
        row.addWidget(icon)
        row.addSpacing(6)
        row.addWidget(n)
        row.addStretch()
        row.addWidget(ip)
        row.addSpacing(10)
        row.addWidget(vendor)
        row.addSpacing(10)
        row.addWidget(status)
        return w

    # -- Live monitor (stream) --
    def _open_traffic_analysis(self):
        # Open the detailed bandwidth / latency / packet-loss view.
        from ui.components.traffic_analysis_dialog import TrafficAnalysisDialog
        dlg = TrafficAnalysisDialog(self)
        dlg.exec()

    def _on_adapter_setting(self, _name=""):
        # The adapter was changed in Settings: restart the monitor and refresh the summary
        if self._monitor_worker is not None:
            self._monitor_worker.stop()
            self._monitor_worker = None
        self._start_monitor()
        self._set_summary("Adapter", "\u2026")
        self._refresh_info()

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
            self.chart.reset()
            self.card_download.set_value("0.0", "Kbps", color=Theme.ACCENT, subtitle="Live")
            self.card_upload.set_value("0.0", "Kbps", color=Theme.ACCENT_PURPLE, subtitle="Live")
        w = StreamWorker(self.core.monitor_stream, adapter_state.get())
        w.result.connect(self._on_monitor)
        w.error.connect(lambda e: self.adapter_status.setText(f"Monitoring: {e}"))
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
        # Show which adapter is actually being monitored
        adapter = d.get("adapter", "")
        if adapter:
            self.adapter_status.setText(f"Monitoring: {adapter}")
        self._last_sample = time.time()
        if "dl" in d and "ul" in d:
            traffic_history.set_adapter(adapter)
            traffic_history.add_bandwidth(d["dl"], d["ul"])
            self.chart.push(d["dl"], d["ul"])
            self.network_map.set_traffic(d["dl"], d["ul"])
            # Adaptive units: Kbps / Mbps / Gbps depending on the value
            dl_val, dl_unit = format_speed(d["dl"])
            ul_val, ul_unit = format_speed(d["ul"])
            self.card_download.set_value(dl_val, dl_unit,
                                         color=Theme.ACCENT, subtitle="Live")
            self.card_upload.set_value(ul_val, ul_unit,
                                       color=Theme.ACCENT_PURPLE, subtitle="Live")
            self.card_download.push_spark(d["dl"])
            self.card_upload.push_spark(d["ul"])
            # Live trend badge - % change vs the previous sample.
            self._update_trend(self.card_download, "_prev_dl", d["dl"])
            self._update_trend(self.card_upload, "_prev_ul", d["ul"])

            # Live peak/avg readouts from the chart's rolling buffer.
            st = self.chart.stats()
            dpk, dpk_u = format_speed(st["download"]["max"])
            upk, upk_u = format_speed(st["upload"]["max"])
            dav, dav_u = format_speed(st["download"]["avg"])
            uav, uav_u = format_speed(st["upload"]["avg"])
            self.stat_peak.setText(
                f"Peak \u2193{dpk}{dpk_u} \u2191{upk}{upk_u}")
            self.stat_avg.setText(
                f"Avg \u2193{dav}{dav_u} \u2191{uav}{uav_u}")

    # -- System resources (timer) --
    def _refresh_resources(self, initial: bool = False):
        if self._resource_worker is not None and self._resource_worker.isRunning():
            return
        w = OneshotWorker(self.core.get_system_resources)
        w.result.connect(self._on_resources)
        w.error.connect(lambda e: None)
        if initial:
            w.done.connect(lambda: self._task_done("resources"))
        self._resource_worker = w
        w.start()

    def _on_resources(self, d: dict):
        if "cpu_percent" in d:
            self.gauge_cpu.set_value(d["cpu_percent"])
            self.gauge_ram.set_value(d["ram_percent"], "Memory")
            self.gauge_disk.set_value(d["disk_percent"], "Disk")
