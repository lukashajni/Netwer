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
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea
)

from app.theme import Theme
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

    # ══════════════════════════════════════════════════════════
    # UI CONSTRUCTION
    # ══════════════════════════════════════════════════════════
    def _build_stat_cards(self):
        row = QHBoxLayout()
        row.setSpacing(Theme.GAP)
        self.card_internet = StatCard("internet", "Internet Status")
        self.card_download = StatCard("download", "Download Speed")
        self.card_upload = StatCard("upload", "Upload Speed")
        self.card_loss = StatCard("packet_loss", "Packet Loss")
        self.card_uptime = StatCard("uptime", "System Uptime")
        for c in (self.card_internet, self.card_download, self.card_upload,
                  self.card_loss, self.card_uptime):
            row.addWidget(c)
        self._grid.addLayout(row)

    def _build_middle_row(self):
        row = QHBoxLayout()
        row.setSpacing(Theme.GAP)

        monitor_card = Card("Live Network Monitor", "monitor")
        self.chart = LiveChart(max_points=60)
        self.chart.setMinimumHeight(200)
        monitor_card.content_layout.addWidget(self.chart)
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
        self._wifi_values = {}
        for key in ("Connection", "SSID", "Signal", "Channel"):
            container, val_lbl = kv_row(key, "\u2014", mono=(key == "Signal"))
            self._wifi_values[key] = val_lbl
            self.wifi_card.content_layout.addWidget(container)
        right_col.addWidget(self.wifi_card)
        right_col.addStretch()

        row.addLayout(right_col, 2)
        self._grid.addLayout(row)

    def _build_bottom_row(self):
        row = QHBoxLayout()
        row.setSpacing(Theme.GAP)

        self.devices_card = Card("Top Devices", "devices")
        self._devices_container = QVBoxLayout()
        self._devices_container.setSpacing(4)
        self.devices_card.content_layout.addLayout(self._devices_container)
        self._devices_placeholder = QLabel("No devices found")
        self._devices_placeholder.setStyleSheet(
            f"color: {Theme.TEXT_MUTED}; font-size: {Theme.FONT_SIZE_SMALL}px;"
            f"background: transparent;"
        )
        self._devices_placeholder.hide()
        self._devices_container.addWidget(self._devices_placeholder)
        row.addWidget(self.devices_card, 1)

        self.resources_card = Card("System Resources", "resources")
        gauges = QHBoxLayout()
        gauges.setSpacing(8)
        self.gauge_cpu = Gauge("CPU", Theme.ACCENT)
        self.gauge_ram = Gauge("Memory", Theme.ACCENT_PURPLE)
        self.gauge_disk = Gauge("Disk", Theme.SUCCESS)
        for g in (self.gauge_cpu, self.gauge_ram, self.gauge_disk):
            gauges.addWidget(g)
        self.resources_card.content_layout.addLayout(gauges)
        row.addWidget(self.resources_card, 1)

        self._grid.addLayout(row)

    # ══════════════════════════════════════════════════════════
    # LIFECYCLE
    # ══════════════════════════════════════════════════════════
    def on_enter(self):
        if not self._loaded_once:
            self._loaded_once = True
            self._begin_loading()
        else:
            self._start_monitor()
            self._resource_timer.start()
            self._refresh_resources()
            if self._boot_epoch is not None:
                self._uptime_timer.start()

    def on_leave(self):
        self._resource_timer.stop()
        self._uptime_timer.stop()
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

    def _task_done(self, name: str):
        self._pending.discard(name)
        if not self._pending:
            self._reveal()

    def _reveal(self):
        if self._window:
            self._window.loading_progress("Ready")
            self._window.end_loading()
        self._resource_timer.start()
        if self._boot_epoch is not None:
            self._uptime_timer.start()

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
        if not reachable:
            self.card_internet.set_value("Offline", color=Theme.DANGER)
            self.card_loss.set_value("100", "%", color=Theme.DANGER, subtitle="No response")
            return
        avg_ping = round(sum(r["avg"] for r in reachable) / len(reachable))
        avg_loss = round(sum(r["loss"] for r in reachable) / len(reachable), 1)
        self.card_internet.set_value("Connected", color=Theme.SUCCESS,
                                     subtitle=f"Ping: {avg_ping} ms")
        loss_color = Theme.SUCCESS if avg_loss < 1 else Theme.WARNING
        self.card_loss.set_value(f"{avg_loss}", "%", color=loss_color,
                                 subtitle="Excellent" if avg_loss < 1 else "Fair")

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

    def _set_summary(self, key: str, value: str, color: str = None):
        lbl = self._summary_values.get(key)
        if lbl:
            lbl.setText(str(value))
            if color:
                lbl.setStyleSheet(
                    f"color: {color}; font-family: '{Theme.FONT_MONO}';"
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
        self._set_wifi("Signal", str(d.get("signal", "\u2014")), Theme.SUCCESS)
        self._set_wifi("Channel", str(d.get("channel", "\u2014")))

    def _wifi_error(self):
        self._set_wifi("Connection", "Wired / N/A", Theme.TEXT_MUTED)
        for k in ("SSID", "Signal", "Channel"):
            self._set_wifi(k, "\u2014")

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

    def _load_devices(self):
        # Runs in background AFTER reveal — shows its own inline spinner text.
        self._devices_placeholder.setText("Scanning local network…")
        self._devices_placeholder.show()
        w = OneshotWorker(self.core.get_top_devices, 6)
        w.result.connect(self._on_devices)
        w.error.connect(lambda e: self._devices_placeholder.setText("Scan unavailable"))
        self.register_worker(w)
        w.start()

    def _on_devices(self, data: dict):
        devices = data.get("devices", [])
        if not devices:
            self._devices_placeholder.setText("No devices found")
            self._devices_placeholder.show()
            return
        self._devices_placeholder.hide()
        for dev in devices:
            self._devices_container.addWidget(self._device_row(dev))

    def _device_row(self, dev: dict) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 3, 0, 3)
        name = dev.get("hostname") or dev.get("ip", "?")
        n = QLabel(str(name)[:18])
        n.setStyleSheet(f"color: {Theme.TEXT_BODY}; font-family: '{Theme.FONT_DATA}'; font-size: {Theme.FONT_SIZE_SMALL}px; background: transparent;")
        ip = QLabel(dev.get("ip", ""))
        ip.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-family: '{Theme.FONT_MONO}'; font-size: {Theme.FONT_SIZE_TINY}px; background: transparent;")
        vendor_name = dev.get("vendor", "")
        if vendor_name == "Unknown":
            vendor_name = "—"
        vendor = QLabel(vendor_name)
        vendor.setStyleSheet(f"color: {Theme.ACCENT}; font-family: '{Theme.FONT_DATA}'; font-size: {Theme.FONT_SIZE_TINY}px; background: transparent;")
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
    def _start_monitor(self):
        if self._monitor_worker is not None:
            return
        self.chart.reset()
        self.card_download.set_value("0.0", "Mbps", color=Theme.ACCENT, subtitle="Live")
        self.card_upload.set_value("0.0", "Mbps", color=Theme.ACCENT_PURPLE, subtitle="Live")
        w = StreamWorker(self.core.monitor_stream, "")
        w.result.connect(self._on_monitor)
        w.error.connect(lambda e: None)
        self.register_worker(w)
        self._monitor_worker = w
        w.start()

    def _on_monitor(self, d: dict):
        if "dl" in d and "ul" in d:
            self.chart.push(d["dl"], d["ul"])
            self.card_download.set_value(f"{d['dl']:.1f}", "Mbps",
                                         color=Theme.ACCENT, subtitle="Live")
            self.card_upload.set_value(f"{d['ul']:.1f}", "Mbps",
                                       color=Theme.ACCENT_PURPLE, subtitle="Live")

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
