"""
NETWER — Port Scanner page.

Scan a host's TCP ports in parallel and classify each result the way a real
scanner does: open (service listening), closed (host refused - reachable but
nothing there), or filtered (no response - firewall dropping packets). Each
row shows the port number, the well-known service, its transport protocol,
and a colored state badge. A summary strip tallies open/closed/filtered.

The scan streams live from netwer_core.port_scan_stream, which pings every
port at once through a thread pool. The target can be pre-filled from the
Ping Sweep page (click a device - "Scan ports") via set_target().
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QComboBox, QFrame, QScrollArea, QApplication
)

from app.theme import Theme
from app.resources import Icons
from app.activity import activity
from app.notifications import notifications
from ui.pages.base_page import BasePage
from ui.widgets.card import Card
from ui.widgets.progress_bar import ProgressBar
from ui.widgets.host_input import HostInput
from workers import StreamWorker


# (label shown in dropdown, spec passed to backend)
PROFILE_OPTIONS = [
    ("Common ports", "common"),
    ("All known (top ~60)", "top100"),
    ("Web servers", "web"),
    ("Databases", "database"),
    ("Remote access", "remote"),
    ("Custom…", "__custom__"),
]

STATE_COLORS = {
    "open": Theme.SUCCESS,
    "closed": Theme.DANGER,
    "filtered": Theme.WARNING,
}


class PortScannerPage(BasePage):
    PAGE_TITLE = "Port Scanner"
    PAGE_SUBTITLE = "Discover open, closed and filtered ports on any host"

    COL_PORT = 90
    COL_PROTO = 90
    COL_STATE = 110

    def __init__(self, core, parent=None):
        super().__init__(core, parent)
        self._worker = None
        self._running = False
        self._total = 0
        self._results = []          # collected port dicts (for export)
        self._counts = {"open": 0, "closed": 0, "filtered": 0}
        self._show_all = False      # toggle - show closed/filtered or open-only

        self._build_toolbar()
        self._build_summary()
        self._build_table()
        self.body_layout.addStretch(0)

    # -- Public: pre-target from another page --
    def set_target(self, ip, autostart=False):
        """Fill the target field (used when jumping here from Ping Sweep)."""
        self.target_input.setText(ip)
        if autostart:
            self._start()

    # -- UI --
    def _build_toolbar(self):
        row = QHBoxLayout()
        row.setSpacing(8)

        self.target_input = HostInput(kind="portscan",
                                      placeholder="Host or IP (e.g. 192.168.1.1)")
        self.target_input.submitted.connect(self._toggle)
        row.addWidget(self.target_input, 1)

        self.profile_combo = QComboBox()
        for label, _spec in PROFILE_OPTIONS:
            self.profile_combo.addItem(label)
        self.profile_combo.setStyleSheet(self._combo_style())
        self.profile_combo.currentIndexChanged.connect(self._on_profile_changed)
        row.addWidget(self.profile_combo)

        self.custom_input = QLineEdit()
        self.custom_input.setPlaceholderText("e.g. 22,80,443,8000-8100")
        self.custom_input.setFixedWidth(200)
        self.custom_input.setStyleSheet(
            f"QLineEdit {{ background: {Theme.GLASS_INPUT}; color: {Theme.TEXT_BODY};"
            f"border: 1px solid {Theme.BORDER}; border-radius: 8px;"
            f"padding: 9px 12px; font-family: {Theme.FONT_MONO};"
            f"font-size: {Theme.FONT_SIZE_SMALL}px; }}"
            f"QLineEdit:focus {{ border-color: {Theme.GLASS_BORDER_HI}; }}")
        self.custom_input.setVisible(False)
        self.custom_input.returnPressed.connect(self._toggle)
        row.addWidget(self.custom_input)

        self.btn_scan = QPushButton("  Scan")
        self.btn_scan.setIcon(Icons.get("port_scanner", "#ffffff"))
        self.btn_scan.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_scan.setMinimumWidth(110)
        self._style_scan_button(running=False)
        self.btn_scan.clicked.connect(self._toggle)
        row.addWidget(self.btn_scan)

        self.body_layout.addLayout(row)

    def _combo_style(self):
        return (
            f"QComboBox {{ background: {Theme.GLASS_INPUT}; color: {Theme.TEXT_SECONDARY};"
            f"border: 1px solid {Theme.BORDER}; border-radius: 8px;"
            f"padding: 9px 12px; font-size: {Theme.FONT_SIZE_SMALL}px; }}"
            f"QComboBox::drop-down {{ border: none; width: 20px; }}"
            f"QComboBox QAbstractItemView {{ background: {Theme.BG_ELEVATED};"
            f"color: {Theme.TEXT_BODY}; selection-background-color: {Theme.ACCENT};"
            f"border: 1px solid {Theme.BORDER_STRONG}; outline: none; }}")

    def _style_scan_button(self, running: bool):
        color = Theme.DANGER if running else Theme.ACCENT
        hover = Theme.DANGER_HOVER if running else Theme.ACCENT_PURPLE
        self.btn_scan.setStyleSheet(
            f"QPushButton {{ background: {color}; color: white; border: none;"
            f"border-radius: 8px; padding: 9px 20px;"
            f"font-size: {Theme.FONT_SIZE_BODY}px; font-weight: 600; }}"
            f"QPushButton:hover {{ background: {hover}; }}")

    def _on_profile_changed(self, idx):
        is_custom = PROFILE_OPTIONS[idx][1] == "__custom__"
        self.custom_input.setVisible(is_custom)
        if is_custom:
            self.custom_input.setFocus()

    def _build_summary(self):
        card = QFrame()
        card.setObjectName("PortSummary")
        card.setStyleSheet(
            f"#PortSummary {{ background: {Theme.BG_CARD};"
            f"border: 1px solid {Theme.BORDER}; border-radius: {Theme.RADIUS_CARD}px; }}"
            f"#PortSummary QLabel {{ background: transparent; border: none; }}")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)

        top = QHBoxLayout()
        self.status_label = QLabel("Ready to scan")
        self.status_label.setStyleSheet(
            f"color: {Theme.TEXT_SECONDARY}; font-size: {Theme.FONT_SIZE_BODY}px;")
        top.addWidget(self.status_label)

        # Device-type badge (icon + label), hidden until a scan identifies one.
        self.device_badge_wrap = QFrame()
        self.device_badge_wrap.setStyleSheet(
            f"background: {Theme.BG_ELEVATED}; border-radius: 6px;")
        badge_lay = QHBoxLayout(self.device_badge_wrap)
        badge_lay.setContentsMargins(8, 3, 10, 3)
        badge_lay.setSpacing(6)
        self.device_badge_icon = QLabel()
        badge_lay.addWidget(self.device_badge_icon)
        self.device_badge = QLabel("")
        self.device_badge.setStyleSheet(
            f"color: {Theme.ACCENT}; font-size: {Theme.FONT_SIZE_SMALL}px;"
            f"font-weight: 600; background: transparent;")
        badge_lay.addWidget(self.device_badge)
        self.device_badge_wrap.setVisible(False)
        top.addSpacing(10)
        top.addWidget(self.device_badge_wrap)

        top.addStretch()

        # Count chips
        self.chip_open = self._chip("0 open", Theme.SUCCESS)
        self.chip_closed = self._chip("0 closed", Theme.DANGER)
        self.chip_filtered = self._chip("0 filtered", Theme.WARNING)
        for chip in (self.chip_open, self.chip_closed, self.chip_filtered):
            top.addWidget(chip)
        lay.addLayout(top)

        self.progress = ProgressBar(height=8)
        lay.addWidget(self.progress)

        self.body_layout.addWidget(card)

    def _chip(self, text, color):
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color: {color}; font-size: {Theme.FONT_SIZE_SMALL}px; font-weight: 600;"
            f"background: transparent; padding: 2px 6px;")
        return lbl

    def _build_table(self):
        card = Card("Scan results", "port_scanner")
        card.setMinimumHeight(300)

        # Header + "show all / open only" toggle
        head_row = QHBoxLayout()
        head_row.setContentsMargins(0, 0, 0, 6)
        for text, w in (("Port", self.COL_PORT), ("Service", -1),
                        ("Protocol", self.COL_PROTO), ("State", self.COL_STATE)):
            lbl = QLabel(text)
            lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            lbl.setStyleSheet(
                f"color: {Theme.TEXT_FAINT}; font-size: 11px; font-weight: 600;"
                f"letter-spacing: 0.5px; background: transparent;")
            if w >= 0:
                lbl.setFixedWidth(w)
                head_row.addWidget(lbl)
            else:
                head_row.addWidget(lbl, 1)
        head_wrap = QFrame()
        head_wrap.setStyleSheet(
            f"border-bottom: 1px solid {Theme.BORDER}; background: transparent;")
        head_wrap.setLayout(head_row)
        card.content_layout.addWidget(head_wrap)

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
        self._rows_layout.addStretch(1)
        self._empty = None

        scroll.setWidget(self._rows_host)
        card.content_layout.addWidget(scroll, 1)

        # Footer: filter toggle + export
        footer = QHBoxLayout()
        self.toggle_btn = QPushButton("Show all ports")
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {Theme.TEXT_SECONDARY};"
            f"border: 1px solid {Theme.BORDER}; border-radius: 6px;"
            f"padding: 5px 12px; font-size: {Theme.FONT_SIZE_SMALL}px; }}"
            f"QPushButton:hover {{ border-color: {Theme.BORDER_STRONG};"
            f"color: {Theme.TEXT_BODY}; }}"
            f"QPushButton:checked {{ background: {Theme.BG_ELEVATED};"
            f"color: {Theme.TEXT_BODY}; border-color: {Theme.ACCENT}; }}")
        self.toggle_btn.clicked.connect(self._toggle_show_all)
        footer.addWidget(self.toggle_btn)
        footer.addStretch()

        self.btn_export = QPushButton("  Export")
        self.btn_export.setIcon(Icons.get("export", Theme.TEXT_SECONDARY))
        self.btn_export.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_export.setEnabled(False)
        self.btn_export.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {Theme.TEXT_SECONDARY};"
            f"border: 1px solid {Theme.BORDER}; border-radius: 6px;"
            f"padding: 5px 12px; font-size: {Theme.FONT_SIZE_SMALL}px; }}"
            f"QPushButton:hover {{ border-color: {Theme.BORDER_STRONG};"
            f"color: {Theme.TEXT_BODY}; }}"
            f"QPushButton:disabled {{ color: {Theme.TEXT_FAINT}; }}")
        self.btn_export.clicked.connect(self._export)
        footer.addWidget(self.btn_export)
        card.content_layout.addLayout(footer)

        self.body_layout.addWidget(card, 1)
        self._show_empty("Enter a host and press Scan.")

    def _show_empty(self, text):
        if self._empty is not None:
            self._empty.setText(text)
            return
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color: {Theme.TEXT_MUTED}; font-size: {Theme.FONT_SIZE_SMALL}px;"
            f"background: transparent; padding: 16px 2px;")
        self._rows_layout.insertWidget(self._rows_layout.count() - 1, lbl)
        self._empty = lbl

    def _clear_rows(self):
        while self._rows_layout.count():
            item = self._rows_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._rows_layout.addStretch(1)
        self._empty = None

    def _port_row(self, res):
        state = res["state"]
        row = QFrame()
        row.setObjectName("PortRow")
        row.setProperty("state", state)
        row.setStyleSheet(
            f"QFrame {{ background: transparent;"
            f"border-bottom: 1px solid {Theme.BORDER}; }}"
            f"QFrame:hover {{ background: {Theme.BG_CARD_HOVER}; }}")
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 8, 0, 8)

        port = QLabel(str(res["port"]))
        port.setFixedWidth(self.COL_PORT)
        port.setStyleSheet(
            f"color: {Theme.TEXT_BODY}; font-family: {Theme.FONT_MONO};"
            f"font-size: 14px; font-weight: 500; background: transparent;")
        rl.addWidget(port)

        svc = res.get("service", "Unknown")
        svc_color = Theme.ACCENT if state == "open" else Theme.TEXT_SECONDARY
        banner = (res.get("banner") or "").strip()
        service = QLabel()
        if banner:
            # Service name on top, grabbed banner underneath in muted mono.
            import html as _html
            safe_banner = _html.escape(banner)
            service.setText(
                f"<span style='color:{svc_color}; font-size:14px;'>{svc}</span>"
                f"<br><span style='color:{Theme.TEXT_MUTED}; font-size:11px;"
                f"font-family:{Theme.FONT_MONO};'>{safe_banner}</span>")
        else:
            service.setText(
                f"<span style='color:{svc_color}; font-size:14px;'>{svc}</span>")
        service.setStyleSheet("background: transparent;")
        rl.addWidget(service, 1)

        proto = QLabel(res.get("protocol", "TCP"))
        proto.setFixedWidth(self.COL_PROTO)
        proto.setStyleSheet(
            f"color: {Theme.TEXT_SECONDARY}; font-family: {Theme.FONT_MONO};"
            f"font-size: 12px; background: transparent;")
        rl.addWidget(proto)

        color = STATE_COLORS.get(state, Theme.TEXT_MUTED)
        badge = QLabel(f"  {state}")
        badge.setFixedWidth(self.COL_STATE)
        badge.setText(
            f"<span style='color:{color};'>\u25cf</span> "
            f"<span style='color:{color}; font-size:13px;'>{state}</span>")
        badge.setStyleSheet("background: transparent;")
        rl.addWidget(badge)

        return row

    def _repaint_rows(self):
        """Rebuild visible rows honoring the show-all toggle and sorting
        (open first, then closed, then filtered, each by port number)."""
        self._clear_rows()
        order = {"open": 0, "closed": 1, "filtered": 2}
        rows = sorted(self._results,
                      key=lambda r: (order.get(r["state"], 3), r["port"]))
        if not self._show_all:
            rows = [r for r in rows if r["state"] == "open"]
        if not rows:
            msg = ("No open ports found." if self._results
                   else "Enter a host and press Scan.")
            self._show_empty(msg)
            return
        for r in rows:
            self._rows_layout.insertWidget(self._rows_layout.count() - 1,
                                           self._port_row(r))

    def _toggle_show_all(self):
        self._show_all = self.toggle_btn.isChecked()
        self.toggle_btn.setText("Open ports only" if self._show_all
                                else "Show all ports")
        self._repaint_rows()

    # -- Lifecycle --
    def on_leave(self):
        self._stop()
        super().on_leave()

    # -- Run / stop --
    def _toggle(self):
        if self._running:
            self._stop()
        else:
            self._start()

    def _current_spec(self):
        idx = self.profile_combo.currentIndex()
        spec = PROFILE_OPTIONS[idx][1]
        if spec == "__custom__":
            return self.custom_input.text().strip() or "common"
        return spec

    def _start(self):
        target = self.target_input.text().strip()
        if not target:
            self.status_label.setText("Enter a host to scan.")
            return
        self._running = True
        self._results = []
        self._counts = {"open": 0, "closed": 0, "filtered": 0}
        self.btn_scan.setText("  Stop")
        self.btn_scan.setIcon(Icons.get("stop", "#ffffff"))
        self._style_scan_button(running=True)
        self.target_input.setEnabled(False)
        self.profile_combo.setEnabled(False)
        self.custom_input.setEnabled(False)
        self.btn_export.setEnabled(False)

        self._clear_rows()
        self.progress.set_color(Theme.ACCENT)
        self.device_badge_wrap.setVisible(False)
        self.progress.set_fraction(0.02)
        self._update_chips()
        self.status_label.setText(f"Scanning {target}…")

        spec = self._current_spec()
        from app.store import store
        timeout = store.get_setting("portscan_timeout_ms", 600)
        w = StreamWorker(self.core.port_scan_stream, target, spec, timeout)
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
        self.btn_scan.setIcon(Icons.get("port_scanner", "#ffffff"))
        self._style_scan_button(running=False)
        self.target_input.setEnabled(True)
        self.profile_combo.setEnabled(True)
        self.custom_input.setEnabled(True)
        self.btn_export.setEnabled(len(self._results) > 0)

    def _on_event(self, d: dict):
        if "total" in d and "resolved" in d:
            self._total = d["total"]
            self.status_label.setText(
                f"Scanning {d['resolved']} \u2014 {d['total']} ports")
            return
        if d.get("done"):
            return
        if "state" in d:
            self._results.append(d)
            self._counts[d["state"]] = self._counts.get(d["state"], 0) + 1
            scanned = d.get("scanned", len(self._results))
            if self._total:
                self.progress.set_fraction(min(1.0, scanned / self._total))
            # Turn green once at least one open port is found.
            if self._counts["open"] > 0:
                self.progress.set_color(Theme.SUCCESS)
            self._update_chips()
            # Live-add open ports immediately, closed/filtered only when
            # "show all" is active (keeps the view focused during scan).
            if d["state"] == "open" or self._show_all:
                if self._empty is not None:
                    self._empty.deleteLater()
                    self._empty = None
                self._rows_layout.insertWidget(
                    self._rows_layout.count() - 1, self._port_row(d))

    def _update_chips(self):
        self.chip_open.setText(f"{self._counts['open']} open")
        self.chip_closed.setText(f"{self._counts['closed']} closed")
        self.chip_filtered.setText(f"{self._counts['filtered']} filtered")

    def _on_error(self, msg):
        self.status_label.setText(str(msg))
        self.status_label.setStyleSheet(
            f"color: {Theme.DANGER}; font-size: {Theme.FONT_SIZE_BODY}px;")

    def _on_finished(self):
        if self._running:
            self.progress.set_fraction(1.0)
            n_open = self._counts["open"]
            open_ports = [r["port"] for r in self._results
                          if r["state"] == "open"]
            # Infer what kind of device this is from its open ports.
            dtype = self.core.detect_device_type(
                open_ports=open_ports,
                hostname=self.target_input.text().strip())
            self._set_device_type(dtype)
            self.status_label.setText(
                f"Scan complete \u2014 {n_open} open "
                f"port{'s' if n_open != 1 else ''} found")
            self.status_label.setStyleSheet(
                f"color: {Theme.TEXT_SECONDARY}; font-size: {Theme.FONT_SIZE_BODY}px;")
            self._repaint_rows()
            activity.add("Port scan",
                         f"{self.target_input.text().strip()} \u00b7 "
                         f"{n_open} open", kind="success")
            notifications.notify_scan_done(
                "Port scan complete",
                f"{self.target_input.text().strip()} \u00b7 {n_open} open ports")
            self.target_input.remember()
            # Persist for the PDF report's optional port-scan section.
            from app.store import store
            store.set_last_scan("port_scanner", {
                "target": self.target_input.text().strip(),
                "device_type": dtype,
                "results": [r for r in self._results if r["state"] == "open"],
                "counts": dict(self._counts),
            })
        self._worker = None
        self._stop()

    def _set_device_type(self, dtype):
        """Show a device-type badge (icon + label) once a scan identifies
        what kind of host this is."""
        if not hasattr(self, "device_badge"):
            return
        labels = {
            "router": "Router", "printer": "Printer", "nas": "NAS",
            "tv": "Smart TV", "phone": "Phone", "camera": "Camera",
            "console": "Game console", "media": "Media server",
            "computer": "Computer", "generic": "Device",
        }
        icon_key = f"dev_{dtype}" if dtype != "generic" else "dev_generic"
        self.device_badge_icon.setPixmap(Icons.pixmap(icon_key, 15, Theme.ACCENT))
        self.device_badge.setText(labels.get(dtype, "Device"))
        self.device_badge_wrap.setVisible(True)

    # -- Export --
    def _export(self):
        if not self._results:
            return
        import os
        from datetime import datetime
        from PyQt6.QtWidgets import QFileDialog
        target = self.target_input.text().strip() or "host"
        default = os.path.join(
            os.path.join(os.path.expanduser("~"), "Desktop"),
            f"NETWER_PortScan_{datetime.now():%Y%m%d_%H%M}.txt")
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Port Scan", default, "Text files (*.txt)")
        if not path:
            return
        try:
            order = {"open": 0, "closed": 1, "filtered": 2}
            rows = sorted(self._results,
                          key=lambda r: (order.get(r["state"], 3), r["port"]))
            lines = ["NETWER — Port Scan Report",
                     f"Target: {target}",
                     f"Generated: {datetime.now():%Y-%m-%d %H:%M:%S}",
                     f"Open: {self._counts['open']}  "
                     f"Closed: {self._counts['closed']}  "
                     f"Filtered: {self._counts['filtered']}",
                     "=" * 78, "",
                     f"{'PORT':<8}{'SERVICE':<20}{'PROTO':<10}{'STATE':<10}{'BANNER'}",
                     "-" * 78]
            for r in rows:
                banner = (r.get("banner") or "").strip()
                lines.append(
                    f"{r['port']:<8}{r.get('service','Unknown'):<20}"
                    f"{r.get('protocol','TCP'):<10}{r['state']:<10}{banner}")
            lines += ["", "=" * 78,
                      "Generated by NETWER — Network Diagnostic Suite"]
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            self.status_label.setText(f"Exported \u2713  {path}")
            activity.add("Port scan exported", os.path.basename(path),
                         kind="success")
        except Exception as e:
            self.status_label.setText(f"Export failed: {e}")
