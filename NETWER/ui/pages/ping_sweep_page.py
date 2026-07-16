"""
NETWER — Ping Sweep page.

Discover every device on the local network: enter a subnet (defaults to the
auto-detected local /24), pick a per-host timeout, and hit Scan. Hosts appear
live in the table as they answer, a progress bar tracks how far the sweep has
gotten and how many devices were found, and the result can be exported to a
plain-text (.txt) report that opens cleanly in Notepad.

The sweep runs in a StreamWorker around netwer_core.ping_sweep_stream, which
pings the whole range in parallel (like Advanced/Angry IP Scanner) and yields
one dict per host plus periodic progress updates. Leaving the page cancels the
worker via the BasePage lifecycle.
"""

import os
from datetime import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QComboBox, QFrame, QScrollArea
)

from app.theme import Theme
from app.resources import Icons
from app.activity import activity
from ui.pages.base_page import BasePage
from ui.widgets.card import Card
from ui.widgets.progress_bar import ProgressBar
from workers import StreamWorker


TIMEOUT_OPTIONS = [
    ("Timeout: 100 ms", 100),
    ("Timeout: 150 ms", 150),
    ("Timeout: 300 ms", 300),
    ("Timeout: 500 ms", 500),
]


def _device_display_name(dev: dict) -> str:
    """Best available name: real hostname, else vendor, else IP — mirrors the
    dashboard's Top Devices so we never show a bare 'Unknown'."""
    hostname = (dev.get("hostname") or "").strip()
    if hostname and hostname.lower() not in ("unknown", "?", ""):
        return hostname
    vendor = (dev.get("vendor") or "").strip()
    if vendor and vendor.lower() != "unknown":
        return vendor
    return dev.get("ip", "") or "\u2014"


class PingSweepPage(BasePage):
    PAGE_TITLE = "Ping Sweep"
    PAGE_SUBTITLE = "Discover every device on your local network"

    # Table column widths (px); Hostname flexes.
    COL_DOT = 30
    COL_IP = 140
    COL_MAC = 160
    COL_VENDOR = 130
    COL_RTT = 74

    def __init__(self, core, parent=None):
        super().__init__(core, parent)

        self._worker = None
        self._running = False
        self._devices = []          # collected host dicts (for export)
        self._total = 254

        self._build_toolbar()
        self._build_progress()
        self._build_table()
        self.body_layout.addStretch(1)

    # ══════════════════════════════════════════════════════════
    # UI
    # ══════════════════════════════════════════════════════════
    def _build_toolbar(self):
        row = QHBoxLayout()
        row.setSpacing(8)

        self.subnet_input = QLineEdit()
        self.subnet_input.setPlaceholderText("Auto-detect (e.g. 192.168.1.0/24)")
        self.subnet_input.setStyleSheet(
            f"QLineEdit {{ background: {Theme.BG_CARD}; color: {Theme.TEXT_BODY};"
            f"border: 1px solid {Theme.BORDER_STRONG}; border-radius: 8px;"
            f"padding: 9px 12px; font-family: {Theme.FONT_MONO};"
            f"font-size: {Theme.FONT_SIZE_BODY}px; }}"
            f"QLineEdit:focus {{ border-color: {Theme.ACCENT}; }}")
        self.subnet_input.returnPressed.connect(self._toggle)
        row.addWidget(self.subnet_input, 1)

        self.timeout_combo = QComboBox()
        for label, value in TIMEOUT_OPTIONS:
            self.timeout_combo.addItem(label, value)
        self.timeout_combo.setCurrentIndex(1)   # 150 ms
        self.timeout_combo.setStyleSheet(
            f"QComboBox {{ background: {Theme.BG_CARD}; color: {Theme.TEXT_SECONDARY};"
            f"border: 1px solid {Theme.BORDER}; border-radius: 8px;"
            f"padding: 9px 12px; font-size: {Theme.FONT_SIZE_SMALL}px; }}"
            f"QComboBox::drop-down {{ border: none; width: 20px; }}"
            f"QComboBox QAbstractItemView {{ background: {Theme.BG_ELEVATED};"
            f"color: {Theme.TEXT_BODY}; selection-background-color: {Theme.ACCENT};"
            f"border: 1px solid {Theme.BORDER_STRONG}; outline: none; }}")
        row.addWidget(self.timeout_combo)

        self.btn_scan = QPushButton("  Scan")
        self.btn_scan.setIcon(Icons.get("ping_sweep", "#ffffff"))
        self.btn_scan.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_scan.setMinimumWidth(120)
        self._style_scan_button(running=False)
        self.btn_scan.clicked.connect(self._toggle)
        row.addWidget(self.btn_scan)

        self.btn_export = QPushButton("  Export")
        self.btn_export.setIcon(Icons.get("export", Theme.TEXT_SECONDARY))
        self.btn_export.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_export.setStyleSheet(
            f"QPushButton {{ background: {Theme.BG_CARD}; color: {Theme.TEXT_SECONDARY};"
            f"border: 1px solid {Theme.BORDER}; border-radius: 8px; padding: 9px 14px;"
            f"font-size: {Theme.FONT_SIZE_SMALL}px; }}"
            f"QPushButton:hover {{ border-color: {Theme.BORDER_STRONG};"
            f"color: {Theme.TEXT_BODY}; }}"
            f"QPushButton:disabled {{ color: {Theme.TEXT_FAINT}; }}")
        self.btn_export.clicked.connect(self._export)
        self.btn_export.setEnabled(False)
        row.addWidget(self.btn_export)

        self.body_layout.addLayout(row)

    def _style_scan_button(self, running: bool):
        color = Theme.DANGER if running else Theme.ACCENT
        hover = Theme.DANGER_HOVER if running else Theme.ACCENT_PURPLE
        self.btn_scan.setStyleSheet(
            f"QPushButton {{ background: {color}; color: white; border: none;"
            f"border-radius: 8px; padding: 9px 20px;"
            f"font-size: {Theme.FONT_SIZE_BODY}px; font-weight: 600; }}"
            f"QPushButton:hover {{ background: {hover}; }}")

    def _build_progress(self):
        card = QFrame()
        card.setObjectName("SweepProgress")
        card.setStyleSheet(
            f"#SweepProgress {{ background: {Theme.BG_CARD};"
            f"border: 1px solid {Theme.BORDER}; border-radius: {Theme.RADIUS_CARD}px; }}"
            f"#SweepProgress QLabel {{ background: transparent; border: none; }}")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(7)

        top = QHBoxLayout()
        self.progress_label = QLabel("Ready to scan")
        self.progress_label.setStyleSheet(
            f"color: {Theme.TEXT_SECONDARY}; font-size: {Theme.FONT_SIZE_BODY}px;")
        top.addWidget(self.progress_label)
        top.addStretch()
        self.count_label = QLabel("")
        self.count_label.setStyleSheet(
            f"color: {Theme.TEXT_BODY}; font-size: {Theme.FONT_SIZE_BODY}px;"
            f"font-weight: 500;")
        top.addWidget(self.count_label)
        lay.addLayout(top)

        # Progress bar (custom widget, resize-safe). Turns green once
        # the first device is found so success is visible at a glance.
        self.progress_bar = ProgressBar(height=8)
        lay.addWidget(self.progress_bar)

        self.body_layout.addWidget(card)

    def _build_table(self):
        card = Card("Discovered devices", "devices")
        card.setMinimumHeight(300)

        # Header row
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 6)
        header.setSpacing(0)
        for text, w in (("", self.COL_DOT), ("IP address", self.COL_IP),
                        ("Hostname", -1), ("MAC", self.COL_MAC),
                        ("Vendor", self.COL_VENDOR), ("RTT", self.COL_RTT),
                        ("PORTS", 30)):
            lbl = QLabel(text)
            align = (Qt.AlignmentFlag.AlignRight if text == "RTT"
                     else Qt.AlignmentFlag.AlignLeft)
            lbl.setAlignment(align | Qt.AlignmentFlag.AlignVCenter)
            lbl.setStyleSheet(
                f"color: {Theme.TEXT_FAINT}; font-size: 9px; font-weight: 600;"
                f"letter-spacing: 0.5px; background: transparent;")
            if w >= 0:
                lbl.setFixedWidth(w)
                header.addWidget(lbl)
            else:
                header.addWidget(lbl, 1)
        header_wrap = QFrame()
        header_wrap.setStyleSheet(
            f"border-bottom: 1px solid {Theme.BORDER}; background: transparent;")
        header_wrap.setLayout(header)
        card.content_layout.addWidget(header_wrap)

        # Scrollable rows container
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollBar:vertical { background: transparent; width: 8px; }"
            f"QScrollBar::handle:vertical {{ background: {Theme.BORDER_STRONG};"
            f"border-radius: 4px; min-height: 24px; }}"
            "QScrollBar::add-line, QScrollBar::sub-line { height: 0; }")

        self._rows_host = QWidget()
        self._rows_host.setStyleSheet("background: transparent;")
        self._rows_layout = QVBoxLayout(self._rows_host)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(0)

        self._empty_label = None
        self._rows_layout.addStretch(1)

        scroll.setWidget(self._rows_host)
        card.content_layout.addWidget(scroll, 1)

        self.body_layout.addWidget(card, 1)

        self._show_empty("No devices yet — run a scan to discover hosts.")

    def _add_device_row(self, dev: dict):
        if self._empty_label is not None:
            self._empty_label.deleteLater()
            self._empty_label = None

        is_gateway = dev.get("is_gateway")
        name = _device_display_name(dev)

        row = QFrame()
        row.setStyleSheet(
            f"QFrame {{ background: transparent;"
            f"border-bottom: 1px solid {Theme.BORDER}; }}"
            f"QFrame:hover {{ background: {Theme.BG_CARD_HOVER}; }}")
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 8, 0, 8)
        rl.setSpacing(0)

        # Status dot (green — device is online)
        dot_wrap = QLabel()
        dot_wrap.setFixedWidth(self.COL_DOT)
        dot_wrap.setText(
            f"<span style='color:{Theme.SUCCESS}; font-size:15px;'>\u25cf</span>")
        dot_wrap.setStyleSheet("background: transparent;")
        rl.addWidget(dot_wrap)

        # IP
        ip = QLabel(dev.get("ip", ""))
        ip.setFixedWidth(self.COL_IP)
        ip.setStyleSheet(
            f"color: {Theme.TEXT_BODY}; font-family: {Theme.FONT_MONO};"
            f"font-size: 13px; background: transparent;")
        rl.addWidget(ip)

        # Hostname (+ gateway tag)
        host_html = (f"<span style='color:{Theme.ACCENT}; font-size:14px;'>{name}</span>"
                     f" <span style='color:{Theme.TEXT_MUTED}; font-size:11px;'>\u00b7 gateway</span>"
                     if is_gateway else
                     f"<span style='color:{Theme.TEXT_BODY}; font-size:14px;'>{name}</span>")
        host = QLabel(host_html)
        host.setStyleSheet("background: transparent;")
        rl.addWidget(host, 1)

        # MAC
        mac = QLabel(dev.get("mac", "") or "\u2014")
        mac.setFixedWidth(self.COL_MAC)
        mac.setStyleSheet(
            f"color: {Theme.TEXT_SECONDARY}; font-family: {Theme.FONT_MONO};"
            f"font-size: 12px; background: transparent;")
        rl.addWidget(mac)

        # Vendor
        vendor_text = dev.get("vendor", "") or ""
        if vendor_text.lower() == "unknown":
            vendor_text = "\u2014"
        vendor = QLabel(vendor_text)
        vendor.setFixedWidth(self.COL_VENDOR)
        vendor.setStyleSheet(
            f"color: {Theme.ACCENT}; font-size: 13px; background: transparent;")
        rl.addWidget(vendor)

        # RTT
        rtt_ms = dev.get("rtt_ms")
        rtt_text = f"{rtt_ms} ms" if rtt_ms is not None else "\u2014"
        rtt = QLabel(rtt_text)
        rtt.setFixedWidth(self.COL_RTT)
        rtt.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        rtt.setStyleSheet(
            f"color: {Theme.SUCCESS if rtt_ms is not None else Theme.TEXT_MUTED};"
            f"font-family: {Theme.FONT_MONO}; font-size: 13px; background: transparent;")
        rl.addWidget(rtt)

        # Scan-ports action → jumps to the Port Scanner pre-targeted at this IP
        ip_addr = dev.get("ip", "")
        scan_btn = QPushButton()
        scan_btn.setIcon(Icons.get("port_scanner", Theme.TEXT_SECONDARY))
        scan_btn.setToolTip(f"Scan ports on {ip_addr}")
        scan_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        scan_btn.setFixedSize(30, 26)
        scan_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; }"
            f"QPushButton:hover {{ background: {Theme.BG_ELEVATED};"
            f"border-radius: 5px; }}")
        scan_btn.clicked.connect(lambda _=False, ip=ip_addr: self._scan_ports(ip))
        rl.addWidget(scan_btn)

        # Insert before the trailing stretch
        self._rows_layout.insertWidget(self._rows_layout.count() - 1, row)

    def _clear_rows(self):
        while self._rows_layout.count():
            item = self._rows_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._rows_layout.addStretch(1)
        self._empty_label = None

    def _scan_ports(self, ip):
        """Jump to the Port Scanner pre-targeted at this device's IP."""
        if ip and self._window is not None:
            self._window.scan_ports_for(ip)

    def _show_empty(self, text: str):
        """Show a centered placeholder message in the (empty) table body."""
        if self._empty_label is not None:
            self._empty_label.setText(text)
            return
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color: {Theme.TEXT_MUTED}; font-size: {Theme.FONT_SIZE_SMALL}px;"
            f"background: transparent; padding: 20px 4px;")
        self._rows_layout.insertWidget(self._rows_layout.count() - 1, lbl)
        self._empty_label = lbl

    # ══════════════════════════════════════════════════════════
    # Lifecycle
    # ══════════════════════════════════════════════════════════
    def on_leave(self):
        self._stop()
        super().on_leave()

    # ══════════════════════════════════════════════════════════
    # Run / stop
    # ══════════════════════════════════════════════════════════
    def _toggle(self):
        if self._running:
            self._stop()
        else:
            self._start()

    def _start(self):
        self._running = True
        self._devices = []
        self.btn_scan.setText("  Stop")
        self.btn_scan.setIcon(Icons.get("stop", "#ffffff"))
        self._style_scan_button(running=True)
        self.subnet_input.setEnabled(False)
        self.timeout_combo.setEnabled(False)
        self.btn_export.setEnabled(False)

        self._clear_rows()
        self.progress_bar.set_color(Theme.ACCENT)
        self._set_progress(0)
        self.count_label.setText("0 found")
        self.progress_label.setText("Starting scan…")

        subnet = self.subnet_input.text().strip() or None
        timeout = self.timeout_combo.currentData()

        w = StreamWorker(self.core.ping_sweep_stream, timeout, subnet)
        w.result.connect(self._on_event)
        w.error.connect(self._on_error)
        w.done.connect(self._on_finished)
        self.register_worker(w)
        self._worker = w
        w.start()

    def _stop(self):
        if self._worker is not None:
            self._worker.stop()
        self._running = False
        self.btn_scan.setText("  Scan")
        self.btn_scan.setIcon(Icons.get("ping_sweep", "#ffffff"))
        self._style_scan_button(running=False)
        self.subnet_input.setEnabled(True)
        self.timeout_combo.setEnabled(True)
        self.btn_export.setEnabled(len(self._devices) > 0)

    def _on_error(self, msg: str):
        self.progress_label.setText(str(msg))

    def _on_finished(self):
        if self._running:
            found = len(self._devices)
            self._set_progress(100)
            self.progress_label.setText("Scan complete")
            self.count_label.setText(f"{found} found")
            if found == 0:
                self._show_empty("No devices responded on this subnet.")
            activity.add("Ping sweep completed",
                         f"{found} device{'s' if found != 1 else ''} found",
                         kind="success")
        self._worker = None
        self._stop()

    # ══════════════════════════════════════════════════════════
    # Stream events
    # ══════════════════════════════════════════════════════════
    def _on_event(self, d: dict):
        # Network announced at the start of the sweep
        if "network" in d and not d.get("online"):
            net = d["network"]
            self.progress_label.setText(f"Scanning {net}.1 – 254")
            return

        # Progress ticks
        if "scanned" in d and not d.get("online") and not d.get("done"):
            self._set_progress(min(100, round(d["scanned"] / self._total * 100)))
            found = len(self._devices)
            found_html = (f"<span style='color:{Theme.SUCCESS};'>{found} found</span>"
                          if found else f"{found} found")
            self.count_label.setText(
                f"{d['scanned']} / {self._total}  \u00b7  {found_html}")
            return

        # A discovered host
        if d.get("online"):
            self._devices.append(d)
            self._add_device_row(d)
            # First device found → turn the progress bar green so success
            # is obvious even before the scan finishes.
            self.progress_bar.set_color(Theme.SUCCESS)
            self.count_label.setText(
                f"<span style='color:{Theme.SUCCESS};'>"
                f"{len(self._devices)} found</span>")
            return

        # Final summary
        if d.get("done"):
            return

    def _set_progress(self, pct: int):
        self.progress_bar.set_fraction(pct / 100)

    # ══════════════════════════════════════════════════════════
    # Export
    # ══════════════════════════════════════════════════════════
    def _export(self):
        if not self._devices:
            return
        from PyQt6.QtWidgets import QFileDialog
        default = os.path.join(
            os.path.join(os.path.expanduser("~"), "Desktop"),
            f"NETWER_Sweep_{datetime.now():%Y%m%d_%H%M}.txt")
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Ping Sweep", default, "Text files (*.txt)")
        if not path:
            return
        try:
            lines = []
            lines.append("NETWER — Ping Sweep Report")
            lines.append(f"Generated: {datetime.now():%Y-%m-%d %H:%M:%S}")
            lines.append(f"Devices found: {len(self._devices)}")
            lines.append("=" * 78)
            lines.append("")
            # Aligned columns so it reads cleanly in Notepad (monospace-ish).
            header = f"{'IP':<16}{'HOSTNAME':<26}{'MAC':<20}{'VENDOR':<18}{'RTT':>6}"
            lines.append(header)
            lines.append("-" * 78)
            for d in self._devices:
                rtt = d.get("rtt_ms")
                rtt_s = f"{rtt} ms" if rtt is not None else "-"
                name = _device_display_name(d)
                if d.get("is_gateway"):
                    name += " (gateway)"
                lines.append(
                    f"{d.get('ip',''):<16}{name:<26}"
                    f"{d.get('mac','') or '-':<20}"
                    f"{(d.get('vendor','') or '-'):<18}{rtt_s:>6}")
            lines.append("")
            lines.append("=" * 78)
            lines.append("Generated by NETWER — Network Diagnostic Suite")

            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))

            self.progress_label.setText(f"Exported \u2713  {path}")
            activity.add("Ping sweep exported", os.path.basename(path),
                         kind="success")
        except Exception as e:
            self.progress_label.setText(f"Export failed: {e}")
