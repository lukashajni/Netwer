"""
NETWER — Dashboard (puna verzija).

Glavna nadzorna ploča. Sklapa se od ponovno iskoristivih widgeta i puni
pravim podacima iz backenda kroz worker sloj. Testira sva tri obrasca:

  - STAT KARTICE (gornji red)     → OneshotWorker: ping_quick, get_system_info
  - LIVE GRAF (sredina)           → StreamWorker: monitor_stream
  - NETWORK SUMMARY (sredina)     → OneshotWorker: get_ethernet_info, get_wifi_info
  - TOP DEVICES (dno)             → OneshotWorker: get_top_devices
  - GAUGEVI CPU/RAM/DISK (dno)    → QTimer + OneshotWorker: get_system_resources

Lifecycle:
  on_enter()  → pokreće učitavanje i live monitor + tajmer za resurse
  on_leave()  → BasePage.stop_workers() gasi sve; tajmer se ovdje zaustavlja
"""

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QScrollArea
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
        self._loaded_once = False

        # Sadržaj ide u scroll area da dashboard radi i na manjim ekranima
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            f"QScrollArea {{ border: none; background: {Theme.BG_APP}; }}"
        )
        inner = QWidget()
        inner.setStyleSheet(f"background: {Theme.BG_APP};")
        self._grid = QVBoxLayout(inner)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(Theme.GAP)
        scroll.setWidget(inner)
        self.body_layout.addWidget(scroll)

        self._build_stat_cards()
        self._build_middle_row()
        self._build_bottom_row()

    # ══════════════════════════════════════════════════════════
    # IZGRADNJA UI-ja
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

        # Live graf (širi)
        monitor_card = Card("Live Network Monitor", "monitor")
        self.chart = LiveChart(max_points=60)
        self.chart.setMinimumHeight(200)
        monitor_card.content_layout.addWidget(self.chart)
        row.addWidget(monitor_card, 3)

        # Network Summary (uži)
        self.summary_card = Card("Network Summary", "summary")
        self._summary_values = {}
        for key in ("Public IP", "Local IP", "Gateway", "DNS", "MAC Address",
                    "Connection", "SSID", "Signal", "Channel"):
            container, val_lbl = kv_row(key, "\u2014", mono=(key in
                                        ("Public IP", "Local IP", "Gateway",
                                         "DNS", "MAC Address")))
            self._summary_values[key] = val_lbl
            self.summary_card.content_layout.addWidget(container)
        self.summary_card.content_layout.addStretch()
        row.addWidget(self.summary_card, 2)

        self._grid.addLayout(row)

    def _build_bottom_row(self):
        row = QHBoxLayout()
        row.setSpacing(Theme.GAP)

        # Top Devices
        self.devices_card = Card("Top Devices", "devices")
        self._devices_container = QVBoxLayout()
        self._devices_container.setSpacing(4)
        self.devices_card.content_layout.addLayout(self._devices_container)
        self._devices_loading = QLabel("Skeniram lokalnu mre\u017eu\u2026")
        self._devices_loading.setStyleSheet(
            f"color: {Theme.TEXT_MUTED}; font-size: {Theme.FONT_SIZE_SMALL}px;"
        )
        self._devices_container.addWidget(self._devices_loading)
        row.addWidget(self.devices_card, 1)

        # System Resources (gaugevi)
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
        # Statične/spore podatke učitaj jednom; live stvari pokreni svaki put.
        if not self._loaded_once:
            self._load_internet_status()
            self._load_uptime()
            self._load_summary()
            self._load_devices()
            self._loaded_once = True

        self._start_monitor()
        self._resource_timer.start()
        self._refresh_resources()

    def on_leave(self):
        self._resource_timer.stop()
        self._monitor_worker = None
        super().on_leave()  # gasi sve registrirane workere

    # ══════════════════════════════════════════════════════════
    # UČITAVANJE PODATAKA (svako kroz worker — nikad ne blokira UI)
    # ══════════════════════════════════════════════════════════
    def _load_internet_status(self):
        self.card_internet.set_value("provjeravam\u2026", color=Theme.TEXT_MUTED)
        w = OneshotWorker(self.core.ping_quick)
        w.result.connect(self._on_internet)
        w.error.connect(lambda e: self.card_internet.set_value("N/A", color=Theme.DANGER))
        self.register_worker(w)
        w.start()

    def _on_internet(self, data: dict):
        items = data.get("items", [])
        reachable = [r for r in items if not r.get("unreachable")]
        if not reachable:
            self.card_internet.set_value("Offline", color=Theme.DANGER)
            self.card_download.set_value("\u2014")
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
        self.register_worker(w)
        w.start()

    def _on_sysinfo(self, data: dict):
        d, h, m = data.get("days", 0), data.get("hours", 0), data.get("minutes", 0)
        self.card_uptime.set_value(f"{d}d {h}h {m}m", color=Theme.WARNING,
                                   subtitle="Since last boot")

    def _load_summary(self):
        w = OneshotWorker(self.core.get_ethernet_info)
        w.result.connect(self._on_eth)
        self.register_worker(w)
        w.start()
        w2 = OneshotWorker(self.core.get_wifi_info)
        w2.result.connect(self._on_wifi)
        w2.error.connect(lambda e: self._set_summary("Connection", "Wired / N/A"))
        self.register_worker(w2)
        w2.start()

    def _on_eth(self, d: dict):
        self._set_summary("Public IP", d.get("public_ip", "\u2014"))
        self._set_summary("Local IP", d.get("ip", "\u2014"))
        self._set_summary("Gateway", d.get("gateway", "\u2014"))
        self._set_summary("DNS", d.get("dns", "\u2014"))
        self._set_summary("MAC Address", d.get("mac", "\u2014"))

    def _on_wifi(self, d: dict):
        self._set_summary("Connection", "WiFi")
        self._set_summary("SSID", d.get("ssid", "\u2014"))
        sig = d.get("signal", "\u2014")
        self._set_summary("Signal", sig, Theme.SUCCESS)
        self._set_summary("Channel", str(d.get("channel", "\u2014")))

    def _set_summary(self, key: str, value: str, color: str = None):
        lbl = self._summary_values.get(key)
        if lbl:
            lbl.setText(str(value))
            if color:
                font = Theme.FONT_MONO if key in ("Public IP", "Local IP",
                        "Gateway", "DNS", "MAC Address") else Theme.FONT_FAMILY
                lbl.setStyleSheet(
                    f"color: {color}; font-family: '{font}';"
                    f"font-size: {Theme.FONT_SIZE_SMALL}px;"
                )

    def _load_devices(self):
        w = OneshotWorker(self.core.get_top_devices, 6)
        w.result.connect(self._on_devices)
        w.error.connect(lambda e: self._devices_loading.setText("Nedostupno"))
        self.register_worker(w)
        w.start()

    def _on_devices(self, data: dict):
        self._devices_loading.hide()
        devices = data.get("devices", [])
        if not devices:
            self._devices_loading.setText("Nema prona\u0111enih ure\u0111aja")
            self._devices_loading.show()
            return
        for dev in devices:
            self._devices_container.addWidget(self._device_row(dev))

    def _device_row(self, dev: dict) -> QWidget:
        row = QHBoxLayout()
        row.setContentsMargins(0, 3, 0, 3)
        name = dev.get("hostname", "Unknown")
        if name == "Unknown":
            name = dev.get("ip", "?")
        n = QLabel(name[:16])
        n.setStyleSheet(f"color: {Theme.TEXT_BODY}; font-size: {Theme.FONT_SIZE_SMALL}px;")
        ip = QLabel(dev.get("ip", ""))
        ip.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-family: '{Theme.FONT_MONO}'; font-size: {Theme.FONT_SIZE_TINY}px;")
        vendor = QLabel(dev.get("vendor", ""))
        vendor.setStyleSheet(f"color: {Theme.ACCENT_GLOW}; font-size: {Theme.FONT_SIZE_TINY}px;")
        status = QLabel("Online")
        status.setStyleSheet(f"color: {Theme.SUCCESS}; font-size: {Theme.FONT_SIZE_TINY}px;")
        row.addWidget(n)
        row.addStretch()
        row.addWidget(ip)
        row.addSpacing(10)
        row.addWidget(vendor)
        row.addSpacing(10)
        row.addWidget(status)
        w = QWidget()
        w.setLayout(row)
        w.setStyleSheet(f"background: transparent;")
        return w

    # ── Live monitor (stream) ──────────────────────────────────
    def _start_monitor(self):
        if self._monitor_worker is not None:
            return
        self.chart.reset()
        w = StreamWorker(self.core.monitor_stream, "")
        w.result.connect(self._on_monitor)
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

    # ── System resources (tajmer) ──────────────────────────────
    def _refresh_resources(self):
        if self._resource_worker is not None and self._resource_worker.isRunning():
            return  # preskoči ako prethodni još traje
        w = OneshotWorker(self.core.get_system_resources)
        w.result.connect(self._on_resources)
        self._resource_worker = w
        w.start()

    def _on_resources(self, d: dict):
        if "cpu_percent" in d:
            self.gauge_cpu.set_value(d["cpu_percent"])
            self.gauge_ram.set_value(d["ram_percent"], f"RAM {d['ram_percent']:.0f}%")
            self.gauge_disk.set_value(d["disk_percent"], f"Disk {d['disk_percent']:.0f}%")
