"""
NETWER — System Information page.

Hardware and OS details plus live resource usage. Static details (CPU model,
core count, OS build) are fetched once; live usage (CPU/RAM/Disk) updates on
a timer using horizontal bars — a denser read than the dashboard's gauges,
which suits a detail page.
"""

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel

from app.theme import Theme
from app.resources import Icons
from ui.pages.base_page import BasePage
from ui.widgets.card import Card, kv_row
from ui.widgets.usage_bar import UsageBar
from workers import OneshotWorker


class SystemInfoPage(BasePage):
    PAGE_TITLE = "System Information"
    PAGE_SUBTITLE = "Hardware, operating system, and live resources"

    def __init__(self, core, parent=None):
        super().__init__(core, parent)

        self._loaded_once = False
        self._resource_worker = None
        self._boot_epoch = None

        self._resource_timer = QTimer(self)
        self._resource_timer.setInterval(1500)
        self._resource_timer.timeout.connect(self._refresh_resources)

        self._uptime_timer = QTimer(self)
        self._uptime_timer.setInterval(1000)
        self._uptime_timer.timeout.connect(self._tick_uptime)

        self._build_headline_row()
        self._build_detail_row()
        self.body_layout.addStretch(1)

    # ══════════════════════════════════════════════════════════
    # UI
    # ══════════════════════════════════════════════════════════
    def _build_headline_row(self):
        row = QHBoxLayout()
        row.setSpacing(Theme.GAP)

        self.card_cpu = self._stat_card("system", "Processor", Theme.TEXT_PRIMARY)
        self.card_ram = self._stat_card("resources", "Memory", Theme.ACCENT_PURPLE)
        self.card_disk = self._stat_card("save", "Storage", Theme.SUCCESS)
        self.card_uptime = self._stat_card("uptime", "Uptime", Theme.WARNING)

        for c in (self.card_cpu, self.card_ram, self.card_disk, self.card_uptime):
            row.addWidget(c["card"])
        self.body_layout.addLayout(row)

    def _stat_card(self, icon_name, label, value_color):
        card = Card("", "")
        card.setFixedHeight(88)

        top = QHBoxLayout()
        top.setSpacing(6)
        icon = QLabel()
        icon.setPixmap(Icons.pixmap(icon_name, 13, Theme.TEXT_SECONDARY))
        icon.setStyleSheet("background: transparent;")
        top.addWidget(icon)
        lbl = QLabel(label)
        lbl.setStyleSheet(
            f"color: {Theme.TEXT_SECONDARY}; font-size: {Theme.FONT_SIZE_TINY}px;"
            f"background: transparent;")
        top.addWidget(lbl)
        top.addStretch()
        card.content_layout.addLayout(top)

        value = QLabel("\u2014")
        value.setStyleSheet(
            f"color: {value_color}; font-family: {Theme.FONT_DATA};"
            f"font-size: 15px; font-weight: 600; background: transparent;")
        card.content_layout.addWidget(value)

        sub = QLabel("")
        sub.setStyleSheet(
            f"color: {Theme.TEXT_FAINT}; font-size: {Theme.FONT_SIZE_TINY}px;"
            f"background: transparent;")
        card.content_layout.addWidget(sub)
        card.content_layout.addStretch()

        return {"card": card, "value": value, "sub": sub, "color": value_color}

    def _build_detail_row(self):
        row = QHBoxLayout()
        row.setSpacing(Theme.GAP)
        H = 300

        # System details table
        self.details_card = Card("System Details", "system")
        self.details_card.setFixedHeight(H)
        self._details = {}
        for key in ("Computer Name", "Operating System", "OS Build", "Processor",
                    "Cores", "Architecture", "Total RAM", "Python Version"):
            mono = key in ("OS Build", "Architecture", "Python Version", "Cores")
            container, lbl = kv_row(key, "\u2014", mono=mono)
            self._details[key] = lbl
            self.details_card.content_layout.addWidget(container)
        self.details_card.content_layout.addStretch()
        row.addWidget(self.details_card, 13)

        # Live usage bars
        self.usage_card = Card("Live Usage", "monitor")
        self.usage_card.setFixedHeight(H)
        self.usage_card.content_layout.addSpacing(6)
        self.bar_cpu = UsageBar("CPU", Theme.ACCENT)
        self.bar_ram = UsageBar("Memory", Theme.ACCENT_PURPLE)
        self.bar_disk = UsageBar("Disk", Theme.SUCCESS)
        for b in (self.bar_cpu, self.bar_ram, self.bar_disk):
            self.usage_card.content_layout.addWidget(b)
        self.usage_card.content_layout.addStretch()
        row.addWidget(self.usage_card, 10)

        self.body_layout.addLayout(row)

    # ══════════════════════════════════════════════════════════
    # Lifecycle
    # ══════════════════════════════════════════════════════════
    def preload(self):
        """Učitaj hardverske/OS detalje u pozadini pri pokretanju."""
        if not self._loaded_once:
            self._loaded_once = True
            self._load_details()

    def on_enter(self):
        if not self._loaded_once:
            self._loaded_once = True
            self._load_details()
        self._refresh_resources()
        self._resource_timer.start()
        if self._boot_epoch is not None:
            self._uptime_timer.start()

    def on_leave(self):
        self._resource_timer.stop()
        self._uptime_timer.stop()
        super().on_leave()

    # ══════════════════════════════════════════════════════════
    # Data
    # ══════════════════════════════════════════════════════════
    def _load_details(self):
        w = OneshotWorker(self.core.get_system_details)
        w.result.connect(self._on_details)
        w.error.connect(lambda e: None)
        self.register_worker(w)
        w.start()

    def _on_details(self, d: dict):
        import time

        cpu_name = d.get("cpu", "\u2014")
        # Trim the long Intel/AMD marketing string down to the model
        short_cpu = cpu_name
        for marker in ("Core(TM) ", "Ryzen "):
            if marker in cpu_name:
                short_cpu = cpu_name.split(marker)[-1]
                if marker == "Ryzen ":
                    short_cpu = "Ryzen " + short_cpu
                break

        phys = d.get("cores_physical", 0)
        logi = d.get("cores_logical", 0)
        cores_text = f"{phys} cores · {logi} threads" if phys else ""

        self.card_cpu["value"].setText(str(short_cpu)[:18])
        self.card_cpu["sub"].setText(cores_text)

        ram_total = d.get("ram_total_gb") or d.get("ram") or 0
        ram_used = d.get("ram_used_gb", 0)
        self.card_ram["value"].setText(f"{ram_total} GB")
        self.card_ram["sub"].setText(f"{ram_used} GB in use" if ram_used else "")

        disks = d.get("disks", [])
        if disks:
            main = disks[0]
            self.card_disk["value"].setText(f"{main['total_gb']} GB")
            self.card_disk["sub"].setText(f"{main['used_gb']} GB used")

        boot = d.get("boot_time")
        if boot:
            self._boot_epoch = boot
        else:
            days = d.get("days", 0); hours = d.get("hours", 0); mins = d.get("minutes", 0)
            self._boot_epoch = time.time() - (days * 86400 + hours * 3600 + mins * 60)
        self._tick_uptime()
        self._uptime_timer.start()

        # Detail table
        self._set("Computer Name", d.get("computer") or d.get("hostname"))
        self._set("Operating System", d.get("os"))
        self._set("OS Build", d.get("os_build"))
        self._set("Processor", cpu_name)
        self._set("Cores", cores_text)
        self._set("Architecture", d.get("architecture"))
        self._set("Total RAM", f"{ram_total} GB" if ram_total else None)
        self._set("Python Version", d.get("python_version"))

    def _set(self, key, value):
        lbl = self._details.get(key)
        if lbl:
            lbl.setText(str(value) if value else "\u2014")

    def _tick_uptime(self):
        import time
        if self._boot_epoch is None:
            return
        elapsed = int(time.time() - self._boot_epoch)
        d = elapsed // 86400
        h = (elapsed % 86400) // 3600
        m = (elapsed % 3600) // 60
        self.card_uptime["value"].setText(f"{d}d {h}h {m}m")
        self.card_uptime["sub"].setText("Since last boot")

    def _refresh_resources(self):
        if self._resource_worker is not None and self._resource_worker.isRunning():
            return
        w = OneshotWorker(self.core.get_system_resources)
        w.result.connect(self._on_resources)
        w.error.connect(lambda e: None)
        self._resource_worker = w
        w.start()

    def _on_resources(self, d: dict):
        if "cpu_percent" not in d:
            return
        self.bar_cpu.set_value(d["cpu_percent"])
        self.bar_ram.set_value(
            d["ram_percent"],
            f"{d.get('ram_used_gb', 0)} / {d.get('ram_total_gb', 0)} GB")
        self.bar_disk.set_value(
            d["disk_percent"],
            f"{d.get('disk_used_gb', 0)} / {d.get('disk_total_gb', 0)} GB")
        # Keep the memory headline card in sync with live usage
        self.card_ram["sub"].setText(f"{d.get('ram_used_gb', 0)} GB in use")
