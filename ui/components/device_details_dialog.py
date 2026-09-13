"""Device details popup.

Opens when a node on the Network Radar (or map) is clicked. Shows what we know
about the device — name, IP, MAC, vendor, RTT — and runs a live port scan so
you can see which ports are open/closed on that specific device, right there.

The scan runs on a StreamWorker (background thread) so the UI stays responsive,
and stops if the dialog is closed early.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QScrollArea, QWidget, QGridLayout, QLineEdit,
)

from app.theme import Theme
from app.resources import Icons
from workers import StreamWorker

try:
    from ui.widgets.network_map import device_display_name
except Exception:                                   # pragma: no cover
    def device_display_name(dev):
        return dev.get("hostname") or dev.get("ip", "?")


class DeviceDetailsDialog(QDialog):
    def __init__(self, core, device: dict, parent=None):
        super().__init__(parent)
        self._core = core
        self._dev = device
        self._worker = None
        self._open_ports = []
        self._vendor_edit = None
        self._vendor_widgets = []
        self._name_edit = None
        self._name_widgets = []

        self.setWindowTitle("Device details")
        self.setMinimumWidth(440)
        self.setStyleSheet(
            f"QDialog {{ background: {Theme.BG_SIDEBAR}; }}"
            f"QLabel {{ background: transparent; color: {Theme.TEXT_BODY}; }}")

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(14)

        # -- Header: icon + name + IP --
        head = QHBoxLayout()
        head.setSpacing(12)
        icon = QLabel()
        icon.setFixedSize(44, 44)
        icon.setObjectName("DevIcon")
        icon.setStyleSheet(
            f"#DevIcon {{ background: {Theme.GLASS_INPUT};"
            f"border: 1px solid {Theme.GLASS_BORDER}; border-radius: 12px; }}")
        from ui.widgets.network_map import guess_device_icon
        icon.setPixmap(Icons.pixmap(guess_device_icon(device), 22, Theme.ACCENT))
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        head.addWidget(icon)

        title_box = QVBoxLayout()
        title_box.setSpacing(1)
        name = QLabel(device_display_name(device))
        self._header_name = name
        name.setStyleSheet(
            f"color: {Theme.TEXT_PRIMARY}; font-size: 17px; font-weight: 700;")
        ip = QLabel(device.get("ip", ""))
        ip.setStyleSheet(
            f"color: {Theme.TEXT_SECONDARY}; font-size: 13px;"
            f"font-family: {Theme.FONT_MONO};")
        title_box.addWidget(name)
        title_box.addWidget(ip)
        head.addLayout(title_box)
        head.addStretch()
        root.addLayout(head)

        # -- Facts grid --
        facts = QFrame()
        facts.setObjectName("Facts")
        facts.setStyleSheet(
            f"#Facts {{ background: {Theme.GLASS_INPUT};"
            f"border: 1px solid {Theme.GLASS_BORDER}; border-radius: 12px; }}"
            f"#Facts QLabel {{ background: transparent; }}")
        fg = QGridLayout(facts)
        fg.setContentsMargins(14, 12, 14, 12)
        fg.setVerticalSpacing(8)
        fg.setHorizontalSpacing(14)
        rtt = device.get("rtt_ms")
        rtt_txt = f"{round(rtt)} ms" if isinstance(rtt, (int, float)) and rtt else "—"
        from core import device_names as _dn
        rows = [
            ("Name", _dn.get(device) or "\u2014"),
            ("MAC address", device.get("mac", "—") or "—"),
            ("Vendor", device.get("vendor", "—") or "—"),
            ("Hostname", device.get("hostname", "—") or "—"),
            ("Response", rtt_txt),
        ]
        for i, (k, v) in enumerate(rows):
            kl = QLabel(k)
            kl.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: 12px;")
            vl = QLabel(str(v))
            vl.setStyleSheet(
                f"color: {Theme.TEXT_BODY}; font-size: 13px; font-weight: 600;")
            vl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            fg.addWidget(kl, i, 0)
            if k == "Name":
                """ Let the user give the device a friendly name, it's stored by
                MAC and used everywhere the device appears. """
                self._name_lbl = vl
                nrow = QHBoxLayout()
                nrow.setContentsMargins(0, 0, 0, 0)
                nrow.setSpacing(8)
                self._name_row = nrow
                nrow.addWidget(vl)
                self._btn_rename = QPushButton("Rename")
                self._btn_rename.setCursor(Qt.CursorShape.PointingHandCursor)
                self._btn_rename.setStyleSheet(
                    f"QPushButton {{ background: transparent;"
                    f"color: {Theme.ACCENT}; border: 1px solid {Theme.GLASS_BORDER};"
                    f"border-radius: 7px; padding: 1px 9px; font-size: 11px; }}"
                    f"QPushButton:hover {{ border-color: {Theme.ACCENT};"
                    f"color: {Theme.TEXT_PRIMARY}; }}")
                self._btn_rename.clicked.connect(self._edit_name)
                nrow.addWidget(self._btn_rename)
                nrow.addStretch()
                fg.addLayout(nrow, i, 1)
            elif k == "Vendor":
                """ The vendor is a guess (OUI table / online lookup), so let the
                user correct it - NETWER remembers the correction for this
                manufacturer prefix from then on. """
                self._vendor_lbl = vl
                vrow = QHBoxLayout()
                vrow.setContentsMargins(0, 0, 0, 0)
                vrow.setSpacing(8)
                self._vendor_row = vrow
                vrow.addWidget(vl)
                self._btn_fix = QPushButton("Correct")
                self._btn_fix.setCursor(Qt.CursorShape.PointingHandCursor)
                self._btn_fix.setStyleSheet(
                    f"QPushButton {{ background: transparent;"
                    f"color: {Theme.ACCENT}; border: 1px solid {Theme.GLASS_BORDER};"
                    f"border-radius: 7px; padding: 1px 9px; font-size: 11px; }}"
                    f"QPushButton:hover {{ border-color: {Theme.ACCENT};"
                    f"color: {Theme.TEXT_PRIMARY}; }}")
                self._btn_fix.clicked.connect(self._edit_vendor)
                vrow.addWidget(self._btn_fix)
                vrow.addStretch()
                fg.addLayout(vrow, i, 1)
            else:
                fg.addWidget(vl, i, 1)
        fg.setColumnStretch(1, 1)
        root.addWidget(facts)

        # Feedback line for vendor corrections (hidden until used).
        self._learn_hint = QLabel("")
        self._learn_hint.setWordWrap(True)
        self._learn_hint.setStyleSheet(
            f"color: {Theme.SUCCESS}; font-size: 11.5px;")
        self._learn_hint.hide()
        root.addWidget(self._learn_hint)

        # -- Ports section --
        ports_head = QHBoxLayout()
        pt = QLabel("Open ports")
        pt.setStyleSheet(
            f"color: {Theme.TEXT_PRIMARY}; font-size: 14px; font-weight: 600;")
        ports_head.addWidget(pt)
        ports_head.addStretch()
        self._scan_status = QLabel("Scanning…")
        self._scan_status.setStyleSheet(
            f"color: {Theme.TEXT_MUTED}; font-size: 12px;")
        ports_head.addWidget(self._scan_status)
        root.addLayout(ports_head)

        self._ports_area = QScrollArea()
        self._ports_area.setWidgetResizable(True)
        self._ports_area.setFixedHeight(150)
        self._ports_area.setStyleSheet(
            f"QScrollArea {{ background: {Theme.GLASS_INPUT};"
            f"border: 1px solid {Theme.GLASS_BORDER}; border-radius: 12px; }}")
        self._ports_inner = QWidget()
        self._ports_inner.setStyleSheet("background: transparent;")
        self._ports_layout = QVBoxLayout(self._ports_inner)
        self._ports_layout.setContentsMargins(12, 10, 12, 10)
        self._ports_layout.setSpacing(6)
        self._ports_empty = QLabel("No open ports found yet…")
        self._ports_empty.setStyleSheet(
            f"color: {Theme.TEXT_MUTED}; font-size: 12.5px;")
        self._ports_layout.addWidget(self._ports_empty)
        self._ports_layout.addStretch()
        self._ports_area.setWidget(self._ports_inner)
        root.addWidget(self._ports_area)

        # -- Buttons --
        btns = QHBoxLayout()
        btns.addStretch()
        close = QPushButton("Close")
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.clicked.connect(self.accept)
        close.setStyleSheet(
            f"QPushButton {{ background: {Theme.GRAD_ACCENT}; color: white;"
            f"border: none; border-radius: {Theme.RADIUS_CONTROL}px;"
            f"padding: 9px 20px; font-weight: 600; }}")
        btns.addWidget(close)
        root.addLayout(btns)

        self._start_scan()

    # -- Custom device name --
    def _edit_name(self):
        if getattr(self, "_name_edit", None) is not None:
            return
        from core import device_names as _dn
        self._btn_rename.hide()
        self._name_lbl.hide()
        current = _dn.get(self._dev) or ""
        self._name_edit = QLineEdit(current)
        self._name_edit.setPlaceholderText("e.g. Mum's laptop")
        self._name_edit.setStyleSheet(
            f"QLineEdit {{ background: {Theme.BG_SIDEBAR};"
            f"color: {Theme.TEXT_PRIMARY};"
            f"border: 1px solid {Theme.GLASS_BORDER_HI}; border-radius: 7px;"
            f"padding: 3px 8px; font-size: 12.5px; }}")
        self._name_edit.returnPressed.connect(self._save_name)
        save = QPushButton("Save")
        save.setCursor(Qt.CursorShape.PointingHandCursor)
        save.setStyleSheet(
            f"QPushButton {{ background: {Theme.GRAD_ACCENT}; color: white;"
            f"border: none; border-radius: 7px; padding: 3px 11px;"
            f"font-size: 11px; font-weight: 600; }}")
        save.clicked.connect(self._save_name)
        cancel = QPushButton("Cancel")
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {Theme.TEXT_MUTED};"
            f"border: none; padding: 3px 6px; font-size: 11px; }}")
        cancel.clicked.connect(self._cancel_name)
        self._name_widgets = [self._name_edit, save, cancel]
        for i, wdg in enumerate(self._name_widgets):
            self._name_row.insertWidget(i, wdg)
        self._name_edit.setFocus()
        self._name_edit.selectAll()

    def _teardown_name_edit(self):
        for wdg in getattr(self, "_name_widgets", []):
            wdg.setParent(None)
        self._name_widgets = []
        self._name_edit = None
        self._name_lbl.show()
        self._btn_rename.show()

    def _cancel_name(self):
        self._teardown_name_edit()

    def _save_name(self):
        from core import device_names as _dn
        new = (self._name_edit.text() or "").strip()
        _dn.set_name(self._dev, new)
        self._name_lbl.setText(new or "\u2014")
        from ui.widgets.network_map import device_display_name as _n
        self._header_name.setText(new or _n(self._dev))
        self._teardown_name_edit()
        self._scan_status_hint(
            f"Saved \u2014 this device is now called \u201c{new}\u201d."
            if new else "Custom name cleared.")

    # -- Vendor correction (feeds the self-learning DB) --
    def _edit_vendor(self):
        """Swap the vendor label for an inline editor. Saving teaches NETWER
        this manufacturer for the device's OUI, so every device sharing that
        prefix is named correctly from now on - including offline."""
        mac = self._dev.get("mac") or ""
        if len(mac.replace(":", "").replace("-", "")) < 6:
            self._vendor_lbl.setText("No MAC \u2014 can't be taught")
            return
        if getattr(self, "_vendor_edit", None) is not None:
            return

        self._btn_fix.hide()
        self._vendor_lbl.hide()
        row = self._vendor_row

        self._vendor_edit = QLineEdit(self._dev.get("vendor", "") or "")
        self._vendor_edit.setPlaceholderText("e.g. TP-Link")
        self._vendor_edit.setStyleSheet(
            f"QLineEdit {{ background: {Theme.BG_SIDEBAR};"
            f"color: {Theme.TEXT_PRIMARY};"
            f"border: 1px solid {Theme.GLASS_BORDER_HI}; border-radius: 7px;"
            f"padding: 3px 8px; font-size: 12.5px; }}")
        self._vendor_edit.returnPressed.connect(self._save_vendor)
        save = QPushButton("Save")
        save.setCursor(Qt.CursorShape.PointingHandCursor)
        save.setStyleSheet(
            f"QPushButton {{ background: {Theme.GRAD_ACCENT}; color: white;"
            f"border: none; border-radius: 7px; padding: 3px 11px;"
            f"font-size: 11px; font-weight: 600; }}")
        save.clicked.connect(self._save_vendor)
        cancel = QPushButton("Cancel")
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {Theme.TEXT_MUTED};"
            f"border: none; padding: 3px 6px; font-size: 11px; }}")
        cancel.clicked.connect(self._cancel_vendor)

        self._vendor_widgets = [self._vendor_edit, save, cancel]
        for i, wdg in enumerate(self._vendor_widgets):
            row.insertWidget(i, wdg)
        self._vendor_edit.setFocus()
        self._vendor_edit.selectAll()

    def _teardown_vendor_edit(self):
        for wdg in getattr(self, "_vendor_widgets", []):
            wdg.setParent(None)
        self._vendor_widgets = []
        self._vendor_edit = None
        self._vendor_lbl.show()
        self._btn_fix.show()

    def _cancel_vendor(self):
        self._teardown_vendor_edit()

    def _save_vendor(self):
        new = (self._vendor_edit.text() or "").strip()
        mac = self._dev.get("mac") or ""
        try:
            self._core.teach_vendor(mac, new)
        except Exception:
            pass
        self._dev["vendor"] = new or "Unknown"
        self._vendor_lbl.setText(self._dev["vendor"])
        self._teardown_vendor_edit()
        # Confirm it stuck, so the learning is visible to the user.
        self._scan_status_hint(
            f"Saved \u2014 NETWER will call {mac[:8]}\u2026 devices "
            f"\u201c{self._dev['vendor']}\u201d from now on."
            if new else "Correction cleared.")

    def _scan_status_hint(self, text):
        if hasattr(self, "_learn_hint"):
            self._learn_hint.setText(text)
            self._learn_hint.show()

    # ── Port scan (background) ──
    def _start_scan(self):
        ip = self._dev.get("ip")
        if not ip:
            self._scan_status.setText("No IP to scan")
            return
        self._worker = StreamWorker(self._core.port_scan_stream, ip, "common")
        self._worker.result.connect(self._on_port)
        self._worker.done.connect(self._on_scan_done)
        self._worker.error.connect(self._on_scan_error)
        self._worker.start()

    def _on_port(self, res: dict):
        if res.get("state") == "open" and "port" in res:
            self._add_open_port(res)
        if "scanned" in res and "total" in res:
            pass  # could show progress, kept minimal

    def _add_open_port(self, res):
        if self._ports_empty is not None:
            self._ports_empty.setParent(None)
            self._ports_empty = None
        self._open_ports.append(res)
        row = QFrame()
        row.setStyleSheet("background: transparent;")
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(10)
        badge = QLabel(str(res["port"]))
        badge.setFixedWidth(56)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(
            f"color: {Theme.SUCCESS}; background: rgba(51,214,166,0.12);"
            f"border-radius: 7px; padding: 3px 0; font-weight: 700;"
            f"font-family: {Theme.FONT_MONO}; font-size: 12px;")
        rl.addWidget(badge)
        svc = QLabel(res.get("service", "") or "—")
        svc.setStyleSheet(f"color: {Theme.TEXT_BODY}; font-size: 13px;")
        rl.addWidget(svc)
        rl.addStretch()
        state = QLabel("open")
        state.setStyleSheet(f"color: {Theme.SUCCESS}; font-size: 12px;")
        rl.addWidget(state)
        # insert before the trailing stretch
        self._ports_layout.insertWidget(self._ports_layout.count() - 1, row)

    def _on_scan_done(self):
        n = len(self._open_ports)
        if n == 0:
            self._scan_status.setText("No open ports")
            if self._ports_empty:
                self._ports_empty.setText("No open ports — device isn't "
                                          "exposing common services.")
        else:
            self._scan_status.setText(f"{n} open")

    def _on_scan_error(self, err):
        self._scan_status.setText(self._core.friendly_error(err))

    def closeEvent(self, event):
        if self._worker is not None:
            try:
                self._worker.stop()
            except Exception:
                pass
        super().closeEvent(event)
