"""
NETWER — Dashboard (full version).

Main monitoring screen. On first entry it triggers the app-wide loading
screen (owned by MainWindow) while ALL data is fetched in the background,
then reveals the fully populated app at once.

Data sources (all through the worker layer, never blocking the UI):
  - Stat cards   → ping_quick, get_system_info
  - Live chart   → monitor_stream (streaming)
  - Net Summary  → get_ethernet_info
  - WiFi card    → get_wifi_info  (separate card)
  - Top Devices  → get_top_devices (with extended vendor resolution)
  - Gauges       → get_system_resources (on a timer)
  - Uptime       → ticks live via a local QTimer (no restart needed)
"""

import time

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QPushButton
)

from app.theme import Theme
from app.resources import Icons
from app.formatting import format_speed, scale_for_axis
from ui.pages.base_page import BasePage
from ui.widgets.stat_card import StatCard
from ui.widgets.gauge import Gauge
from ui.widgets.live_chart import LiveChart
from ui.widgets.card import Card, kv_row
from workers import OneshotWorker, StreamWorker


class DashboardPage(BasePage):
    PAGE_TITLE = "Dashboard"
    PAGE_SUBTITLE = "Overview of your network and system status"

    def __init__(self, core, parent=None):
        super().__init__(core, parent)

        self._monitor_worker = None
        self._resource_timer = QTimer(self)
        self._resource_timer.setInterval(1500)
        self._resource_timer.timeout.connect(self._refresh_resources)
        self._resource_worker = None

        # Uptime: track boot moment, tick every second so it updates live.
        self._boot_epoch = None
        self._uptime_timer = QTimer(self)
        self._uptime_timer.setInterval(1000)
        self._uptime_timer.timeout.connect(self._tick_uptime)

        # Ping refresh: re-check connectivity every 5s so the ping/loss
        # sparklines keep moving (not just one reading at startup).
        self._ping_timer = QTimer(self)
        self._ping_timer.setInterval(5000)
        self._ping_timer.timeout.connect(self._refresh_internet)
        self._internet_worker = None

        # Live info refresh: re-read WiFi + Network Summary every few seconds
        # so plugging in a WiFi adapter (or IP changes) shows up immediately,
        # with no app restart.
        self._info_timer = QTimer(self)
        self._info_timer.setInterval(4000)
        self._info_timer.timeout.connect(self._refresh_info)
        self._wifi_worker = None
        self._eth_worker = None

        self._loaded_once = False
        self._pending = set()

        # Content (scrollable)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        self._grid = QVBoxLayout(inner)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(Theme.GAP)
        scroll.setWidget(inner)
        self.body_layout.addWidget(scroll)

        self._build_stat_cards()
        self._build_middle_row()
        self._build_bottom_row()
        # Spotify-style: cards keep a sensible fixed size; extra vertical
        # space when maximized goes into this trailing stretch instead of
        # ballooning the cards.
        self._grid.addStretch(1)

    # ══════════════════════════════════════════════════════════
    # UI CONSTRUCTION
    # ══════════════════════════════════════════════════════════
    def _build_stat_cards(self):
        row = QHBoxLayout()
        row.setSpacing(Theme.GAP)
        self.card_internet = StatCard("internet", "Internet Status", spark_color=Theme.SUCCESS)
        self.card_download = StatCard("download", "Download Speed", spark_color=Theme.ACCENT)
        self.card_upload = StatCard("upload", "Upload Speed", spark_color=Theme.ACCENT_PURPLE)
        self.card_loss = StatCard("packet_loss", "Packet Loss", spark_color=Theme.SUCCESS)
        self.card_uptime = StatCard("uptime", "System Uptime")
        for c in (self.card_internet, self.card_download, self.card_upload,
                  self.card_loss, self.card_uptime):
            c.setFixedHeight(120)
            row.addWidget(c)
        self._grid.addLayout(row, 0)

    def _build_middle_row(self):
        row = QHBoxLayout()
        row.setSpacing(Theme.GAP)

        MIDDLE_HEIGHT = 340  # fixed height so left and right columns align

        monitor_card = Card("Live Network Monitor", "monitor")
        monitor_card.setFixedHeight(MIDDLE_HEIGHT)
        # Adapter selector in the card header (right side)
        from PyQt6.QtWidgets import QComboBox
        self.adapter_combo = QComboBox()
        self.adapter_combo.setMinimumWidth(180)
        self.adapter_combo.setStyleSheet(
            f"QComboBox {{ background: {Theme.BG_ELEVATED}; color: {Theme.TEXT_BODY};"
            f"border: 1px solid {Theme.BORDER_STRONG}; border-radius: 6px;"
            f"padding: 3px 8px; font-size: {Theme.FONT_SIZE_TINY}px; }}"
            f"QComboBox::drop-down {{ border: none; width: 18px; }}"
            f"QComboBox QAbstractItemView {{ background: {Theme.BG_ELEVATED};"
            f"color: {Theme.TEXT_BODY}; selection-background-color: {Theme.ACCENT};"
            f"border: 1px solid {Theme.BORDER_STRONG}; outline: none; }}"
        )
        self.adapter_combo.addItem("Auto (recommended)", "")
        self.adapter_combo.currentIndexChanged.connect(self._on_adapter_changed)
        monitor_card.header_layout.addWidget(self.adapter_combo)

        # Legend row (Download = blue, Upload = purple)
        legend = QHBoxLayout()
        legend.setSpacing(16)
        legend.addWidget(self._legend_item("Download", Theme.ACCENT))
        legend.addWidget(self._legend_item("Upload", Theme.ACCENT_PURPLE))
        legend.addStretch()
        monitor_card.content_layout.addLayout(legend)

        self.chart = LiveChart(max_points=60)
        monitor_card.content_layout.addWidget(self.chart, 1)

        # Small label showing which adapter is currently monitored
        self.adapter_status = QLabel("Monitoring: detecting…")
        self.adapter_status.setStyleSheet(
            f"color: {Theme.TEXT_MUTED}; font-size: {Theme.FONT_SIZE_TINY}px;"
            f"background: transparent;"
        )
        monitor_card.content_layout.addWidget(self.adapter_status)

        row.addWidget(monitor_card, 3)

        right_col = QVBoxLayout()
        right_col.setSpacing(Theme.GAP)

        self.summary_card = Card("Network Summary", "summary")
        self._summary_values = {}
        for key in ("Public IP", "Local IP", "Gateway", "DNS", "MAC Address"):
            container, val_lbl = kv_row(key, "\u2014", mono=True)
            self._summary_values[key] = val_lbl
            self.summary_card.content_layout.addWidget(container)
        right_col.addWidget(self.summary_card)

        self.wifi_card = Card("WiFi", "wifi")
        wifi_body = QHBoxLayout()
        wifi_body.setSpacing(14)
        wifi_left = QVBoxLayout()
        wifi_left.setSpacing(6)
        wifi_left.addStretch()
        self._wifi_values = {}
        for key in ("Connection", "SSID", "Signal", "Channel"):
            container, val_lbl = kv_row(key, "\u2014", mono=(key == "Signal"))
            self._wifi_values[key] = val_lbl
            wifi_left.addWidget(container)
        wifi_left.addStretch()
        wifi_body.addLayout(wifi_left, 1)
        from ui.widgets.wifi_signal import WiFiSignal
        self.wifi_signal = WiFiSignal(92)
        self.wifi_signal.set_disconnected()
        wifi_body.addWidget(self.wifi_signal, 0,
                            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter)
        self.wifi_card.content_layout.addLayout(wifi_body)
        right_col.addWidget(self.wifi_card)

        row.addLayout(right_col, 2)
        self._grid.addLayout(row, 0)

    def _legend_item(self, text, color):
        """A small colored dot + label for the chart legend."""
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

        # Network Map (moved here from the middle column; more room)
        from ui.widgets.network_map import NetworkMap
        self.map_card = Card("Network Map", "network")
        self.map_card.setFixedHeight(BOTTOM_HEIGHT)
        self.network_map = NetworkMap()
        self.map_card.content_layout.addWidget(self.network_map)
        row.addWidget(self.map_card, 2)

        self.devices_card = Card("Top Devices", "devices")
        self.devices_card.setFixedHeight(BOTTOM_HEIGHT)

        # Rescan button in the card header — re-runs the network scan,
        # refreshing both Top Devices and the Network Map.
        self.btn_rescan = QPushButton("  Rescan")
        self.btn_rescan.setIcon(Icons.get("refresh", Theme.TEXT_BODY))
        self.btn_rescan.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_rescan.setStyleSheet(
            f"QPushButton {{ background: {Theme.BG_ELEVATED}; color: {Theme.TEXT_SECONDARY};"
            f"border: 1px solid {Theme.BORDER_STRONG}; border-radius: 6px;"
            f"padding: 3px 12px; font-size: {Theme.FONT_SIZE_TINY}px; }}"
            f"QPushButton:hover {{ border-color: {Theme.ACCENT}; color: {Theme.TEXT_BODY}; }}"
            f"QPushButton:disabled {{ color: {Theme.TEXT_FAINT}; }}")
        self.btn_rescan.clicked.connect(self._rescan_network)
        self.devices_card.header_layout.addWidget(self.btn_rescan)
        # Scrollable device list so it adapts to any number of devices
        from PyQt6.QtWidgets import QScrollArea, QFrame as _QFrame
        dev_scroll = QScrollArea()
        dev_scroll.setWidgetResizable(True)
        dev_scroll.setFrameShape(_QFrame.Shape.NoFrame)
        dev_scroll.setStyleSheet("background: transparent; border: none;")
        dev_holder = QWidget()
        dev_holder.setStyleSheet("background: transparent;")
        self._devices_container = QVBoxLayout(dev_holder)
        self._devices_container.setContentsMargins(0, 0, 0, 0)
        self._devices_container.setSpacing(4)
        self._devices_placeholder = QLabel("No devices found")
        self._devices_placeholder.setStyleSheet(
            f"color: {Theme.TEXT_MUTED}; font-size: {Theme.FONT_SIZE_SMALL}px;"
            f"background: transparent;"
        )
        self._devices_placeholder.hide()
        self._devices_container.addWidget(self._devices_placeholder)
        self._devices_container.addStretch()
        dev_scroll.setWidget(dev_holder)
        self.devices_card.content_layout.addWidget(dev_scroll)
        row.addWidget(self.devices_card, 2)

        # Third column: Recent Activity stacked ABOVE System Resources
        right_col = QVBoxLayout()
        right_col.setSpacing(Theme.GAP)

        from ui.widgets.recent_activity import RecentActivity
        self.activity_card = Card("Recent Activity", "check")
        self.activity_card.setFixedHeight(150)

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
        right_col.addWidget(self.activity_card)

        self.resources_card = Card("System Resources", "resources")
        self.resources_card.setFixedHeight(BOTTOM_HEIGHT - 150 - Theme.GAP)
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
        right_col.addWidget(self.resources_card)

        row.addLayout(right_col, 2)

        self._grid.addLayout(row, 0)

    # ══════════════════════════════════════════════════════════
    # LIFECYCLE
    # ══════════════════════════════════════════════════════════
    def on_enter(self):
        if not self._loaded_once:
            self._loaded_once = True
            self._begin_loading()
        else:
            # Returning to the page: restart EVERY live timer that on_leave
            # stopped. Missing one here (info/ping) silently kills live
            # refresh — e.g. a WiFi adapter plugged in later never shows up.
            self._start_monitor()
            self._resource_timer.start()
            self._ping_timer.start()
            self._info_timer.start()
            self._refresh_resources()
            self._refresh_info()
            if self._boot_epoch is not None:
                self._uptime_timer.start()

    def on_leave(self):
        self._resource_timer.stop()
        self._uptime_timer.stop()
        self._ping_timer.stop()
        self._info_timer.stop()
        self._monitor_worker = None
        super().on_leave()

    # ══════════════════════════════════════════════════════════
    # LOADING PHASE — fetch everything, then reveal (app-wide screen)
    # ══════════════════════════════════════════════════════════
    def _begin_loading(self):
        if self._window:
            self._window.begin_loading()
            self._window.loading_progress("Checking connectivity…")

        # Loading waits ONLY on fast tasks. Network scan (get_top_devices)
        # takes 10-30s scanning 254 addresses — we DON'T block on it. It
        # fills in the background after the app is revealed.
        self._pending = {"internet", "uptime", "summary", "wifi", "resources"}

        self._load_internet_status()
        self._load_uptime()
        self._load_summary()
        self._load_wifi()
        self._refresh_resources(initial=True)
        self._start_monitor()
        # Device scan starts but does NOT gate the reveal.
        self._load_devices()
        # Adapter list also loads in background.
        self._load_adapters()

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
        if self._boot_epoch is not None:
            self._uptime_timer.start()

    def _show_all_activity(self):
        """Open the full activity history in a dialog."""
        from ui.components.activity_dialog import ActivityDialog
        dlg = ActivityDialog(self)
        dlg.exec()

    def _refresh_info(self):
        """Periodically re-read WiFi + Ethernet so changes (like plugging in
        a WiFi adapter) appear live without restarting the app."""
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

    # ══════════════════════════════════════════════════════════
    # DATA LOADING
    # ══════════════════════════════════════════════════════════
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
            self.card_internet.set_value("Offline", color=Theme.DANGER)
            self.card_loss.set_value("100", "%", color=Theme.DANGER, subtitle="No response")
            self.card_loss.push_spark(100)
            return
        avg_ping = round(sum(r["avg"] for r in reachable) / len(reachable))
        avg_loss = round(sum(r["loss"] for r in reachable) / len(reachable), 1)
        self.card_internet.set_value("Connected", color=Theme.SUCCESS,
                                     subtitle=f"Ping: {avg_ping} ms")
        loss_color = Theme.SUCCESS if avg_loss < 1 else Theme.WARNING
        self.card_loss.set_value(f"{avg_loss}", "%", color=loss_color,
                                 subtitle="Excellent" if avg_loss < 1 else "Fair")
        # Feed sparklines: ping trend on the internet card, loss on its card
        self.card_internet.push_spark(avg_ping)
        self.card_loss.push_spark(avg_loss)

    def _load_uptime(self):
        w = OneshotWorker(self.core.get_system_info)
        w.result.connect(self._on_sysinfo)
        w.error.connect(lambda e: None)
        w.done.connect(lambda: self._task_done("uptime"))
        self.register_worker(w)
        w.start()

    def _on_sysinfo(self, data: dict):
        # Compute boot epoch from reported uptime so we can tick locally.
        d = data.get("days", 0)
        h = data.get("hours", 0)
        m = data.get("minutes", 0)
        uptime_seconds = d * 86400 + h * 3600 + m * 60
        self._boot_epoch = time.time() - uptime_seconds
        self._tick_uptime()

    def _tick_uptime(self):
        if self._boot_epoch is None:
            return
        elapsed = int(time.time() - self._boot_epoch)
        days = elapsed // 86400
        hours = (elapsed % 86400) // 3600
        minutes = (elapsed % 3600) // 60
        self.card_uptime.set_value(f"{days}d {hours}h {minutes}m",
                                   color=Theme.WARNING, subtitle="Since last boot")

    def _load_summary(self):
        w = OneshotWorker(self.core.get_ethernet_info)
        w.result.connect(self._on_eth)
        w.error.connect(lambda e: None)
        w.done.connect(lambda: self._task_done("summary"))
        self.register_worker(w)
        w.start()

    def _on_eth(self, d: dict):
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
        # or a percentage; try to derive a 0-100 strength.
        pct = self._signal_to_percent(signal)
        self.wifi_signal.set_signal(pct)

    def _signal_to_percent(self, signal) -> float:
        """Convert a signal reading to 0-100%. Accepts percent strings,
        dBm values, or plain numbers."""
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

    def _rescan_network(self):
        """Manually re-run the network scan (button in Top Devices header).
        Clears the current list/map and scans again — picks up devices that
        came online since the last scan."""
        if getattr(self, "_devices_scanning", False):
            return
        self._devices_scanning = True
        self.btn_rescan.setEnabled(False)
        self.btn_rescan.setText("  Scanning…")

        # Clear existing device rows (keep placeholder + trailing stretch)
        while self._devices_container.count() > 2:
            item = self._devices_container.takeAt(0)
            w = item.widget()
            if w and w is not self._devices_placeholder:
                w.setParent(None)
                w.deleteLater()
        self._all_devices = []
        self._load_devices()

    def _load_devices(self):
        # Runs in background — shows its own inline spinner text.
        self._devices_placeholder.setText("Scanning local network…")
        self._devices_placeholder.show()
        w = OneshotWorker(self.core.get_top_devices, 12)
        w.result.connect(self._on_devices)
        w.error.connect(lambda e: self._on_scan_error())
        w.done.connect(self._on_scan_done)
        self.register_worker(w)
        w.start()

    def _on_scan_error(self):
        self._devices_placeholder.setText("Scan unavailable")

    def _on_scan_done(self):
        self._devices_scanning = False
        self.btn_rescan.setEnabled(True)
        self.btn_rescan.setText("  Rescan")

    def _on_devices(self, data: dict):
        devices = data.get("devices", [])
        if not devices:
            self._devices_placeholder.setText("No devices found")
            self._devices_placeholder.show()
            return
        self._devices_placeholder.hide()
        for dev in devices:
            # Insert before the placeholder + trailing stretch (last two items)
            idx = max(0, self._devices_container.count() - 2)
            self._devices_container.insertWidget(idx, self._device_row(dev))
        from app.activity import activity
        activity.add("Network scan completed",
                     f"{len(devices)} devices found", kind="success")
        self._all_devices = devices
        self._maybe_update_map()

    def _maybe_update_map(self):
        """Update the topology map once we have both gateway and devices."""
        gateway = getattr(self, "_gateway", None)
        devices = getattr(self, "_all_devices", None)
        if gateway and devices:
            # Find router vendor from the device whose IP == gateway
            router_vendor = ""
            for d in devices:
                if d.get("ip") == gateway:
                    router_vendor = d.get("vendor", "") or ""
                    break
            self.network_map.set_topology(gateway, devices, router_vendor,
                                          online=getattr(self, "_internet_online", True))

    @staticmethod
    def device_display_name(dev: dict) -> str:
        """Best available name for a device: real hostname, else the vendor
        (e.g. 'LG Electronics'), else the IP. Avoids showing 'Unknown' when
        we actually know the manufacturer."""
        hostname = (dev.get("hostname") or "").strip()
        if hostname and hostname.lower() not in ("unknown", "?", ""):
            return hostname
        vendor = (dev.get("vendor") or "").strip()
        if vendor and vendor.lower() != "unknown":
            return vendor
        return dev.get("ip", "?")

    def _device_row(self, dev: dict) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 3, 0, 3)
        name = self.device_display_name(dev)
        n = QLabel(str(name)[:18])
        n.setStyleSheet(f"color: {Theme.TEXT_BODY}; font-family: {Theme.FONT_DATA}; font-size: {Theme.FONT_SIZE_SMALL}px; background: transparent;")
        ip = QLabel(dev.get("ip", ""))
        ip.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-family: {Theme.FONT_MONO}; font-size: {Theme.FONT_SIZE_TINY}px; background: transparent;")
        vendor_name = dev.get("vendor", "")
        if vendor_name == "Unknown":
            vendor_name = "—"
        vendor = QLabel(vendor_name)
        vendor.setStyleSheet(f"color: {Theme.ACCENT}; font-family: {Theme.FONT_DATA}; font-size: {Theme.FONT_SIZE_TINY}px; background: transparent;")
        status = QLabel("Online")
        status.setStyleSheet(f"color: {Theme.SUCCESS}; font-size: {Theme.FONT_SIZE_TINY}px; background: transparent;")
        row.addWidget(n)
        row.addStretch()
        row.addWidget(ip)
        row.addSpacing(10)
        row.addWidget(vendor)
        row.addSpacing(10)
        row.addWidget(status)
        return w

    # ── Live monitor (stream) ──────────────────────────────────
    # ── Adapter selection ──────────────────────────────────────
    def _load_adapters(self):
        """Populate the adapter dropdown (background, after reveal)."""
        w = OneshotWorker(self.core.list_adapters)
        w.result.connect(self._on_adapters)
        w.error.connect(lambda e: None)
        self.register_worker(w)
        w.start()

    def _on_adapters(self, data):
        adapters = data.get("items", data) if isinstance(data, dict) else data
        if not isinstance(adapters, list):
            return
        current = self.adapter_combo.currentData()
        self.adapter_combo.blockSignals(True)
        # Keep the Auto entry, add real adapters that are Up
        for a in adapters:
            if not isinstance(a, dict):
                continue
            name = a.get("name", "")
            status = a.get("status", "")
            if not name:
                continue
            label = f"{name}" + ("" if status == "Up" else f"  ({status})")
            self.adapter_combo.addItem(label, name)
        self.adapter_combo.blockSignals(False)

    def _on_adapter_changed(self, index):
        """User picked a different adapter — restart monitor on it."""
        selected = self.adapter_combo.currentData()
        # Stop current monitor
        if self._monitor_worker is not None:
            self._monitor_worker.stop()
            self._monitor_worker = None
        self._selected_adapter = selected or ""
        self._start_monitor()

    def _start_monitor(self):
        if self._monitor_worker is not None:
            return
        self.chart.reset()
        self.card_download.set_value("0.0", "Kbps", color=Theme.ACCENT, subtitle="Live")
        self.card_upload.set_value("0.0", "Kbps", color=Theme.ACCENT_PURPLE, subtitle="Live")
        adapter = getattr(self, "_selected_adapter", "")
        w = StreamWorker(self.core.monitor_stream, adapter)
        w.result.connect(self._on_monitor)
        w.error.connect(lambda e: self.adapter_status.setText(f"Monitoring: {e}"))
        self.register_worker(w)
        self._monitor_worker = w
        w.start()

    def _on_monitor(self, d: dict):
        # Show which adapter is actually being monitored
        adapter = d.get("adapter", "")
        if adapter:
            self.adapter_status.setText(f"Monitoring: {adapter}")
        if "dl" in d and "ul" in d:
            self.chart.push(d["dl"], d["ul"])
            # Adaptive units: Kbps / Mbps / Gbps depending on the value
            dl_val, dl_unit = format_speed(d["dl"])
            ul_val, ul_unit = format_speed(d["ul"])
            self.card_download.set_value(dl_val, dl_unit,
                                         color=Theme.ACCENT, subtitle="Live")
            self.card_upload.set_value(ul_val, ul_unit,
                                       color=Theme.ACCENT_PURPLE, subtitle="Live")
            self.card_download.push_spark(d["dl"])
            self.card_upload.push_spark(d["ul"])

    # ── System resources (timer) ───────────────────────────────
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
