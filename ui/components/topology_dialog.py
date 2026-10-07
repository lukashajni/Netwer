from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.theme import Theme
from core.discovery import configured_subnets, get_discovery_service
from ui.components.device_details_dialog import DeviceDetailsDialog
from ui.components.subnet_dialog import SubnetConfigurationDialog
from ui.widgets.topology_map import TopologyGraphView
from workers import StreamWorker


class _DeviceListRow(QFrame):
    def __init__(self, device, selected=False, on_select=None, parent=None):
        super().__init__(parent)
        self.device = device
        self.on_select = on_select
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setObjectName("TopologyDeviceListRow")
        self._set_style(selected)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(9)
        label = QLabel(device.get("ip", ""))
        label.setStyleSheet(
            f"color: {Theme.TEXT_PRIMARY}; font-family: {Theme.FONT_MONO};"
            "font-size: 11px; background: transparent;")
        layout.addWidget(label)
        details = QVBoxLayout()
        name = QLabel(device.get("hostname") or device.get("vendor") or device.get("ip", ""))
        name.setStyleSheet(
            f"color: {Theme.TEXT_BODY}; font-size: 12px; font-weight: 600;"
            "background: transparent;")
        details.addWidget(name)
        mac = QLabel(device.get("mac") or device.get("vendor") or "No MAC learned")
        mac.setStyleSheet(
            f"color: {Theme.TEXT_MUTED}; font-size: 10px; background: transparent;")
        details.addWidget(mac)
        layout.addLayout(details, 1)
        state = QLabel(device.get("reachability", "unknown").replace("_", " "))
        state.setStyleSheet(
            f"color: {Theme.ACCENT if device.get('reachability') == 'reachable' else Theme.WARNING};"
            "font-size: 10px; background: transparent;")
        layout.addWidget(state)

    def _set_style(self, selected):
        border = Theme.ACCENT if selected else Theme.GLASS_BORDER
        self.setStyleSheet(
            f"#TopologyDeviceListRow {{ background: {Theme.GLASS_INPUT};"
            f"border: 1px solid {border}; border-radius: 8px; }}"
            f"#TopologyDeviceListRow:hover {{ border-color: {Theme.GLASS_BORDER_HI}; }}")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.on_select:
            event.accept()
            self.on_select(self.device)
            return
        super().mousePressEvent(event)


class TopologyDialog(QDialog):
    """Subnet-aware discovery view with a searchable, synchronized device map."""

    def __init__(self, core, parent=None):
        super().__init__(parent)
        self._core = core
        self._service = get_discovery_service()
        self._worker = None
        self._details_dialog = None
        self._selected_ip = ""
        self._segments = configured_subnets()
        self._devices = []
        self._render_signature = None
        self.setWindowTitle("Network Topology")
        self.setModal(True)
        self.resize(1380, 860)
        self.setMinimumSize(1050, 680)
        self.setStyleSheet(
            f"QDialog {{ background: {Theme.BG_APP}; }}"
            f"QLabel {{ color: {Theme.TEXT_BODY}; background: transparent; }}")

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)
        root.addLayout(self._build_header())
        root.addLayout(self._build_summary())
        root.addLayout(self._build_controls())

        body = QHBoxLayout()
        body.setSpacing(12)
        map_card = QFrame()
        map_card.setObjectName("TopologyMapCard")
        map_card.setStyleSheet(
            f"#TopologyMapCard {{ background: {Theme.GLASS_CARD};"
            f"border: 1px solid {Theme.GLASS_BORDER}; border-radius: 14px; }}")
        map_layout = QVBoxLayout(map_card)
        map_layout.setContentsMargins(12, 10, 12, 12)
        map_head = QHBoxLayout()
        map_head.addWidget(QLabel("Network map"), 1)
        self.map = TopologyGraphView()
        for label, callback in (("−", self.map.zoom_out), ("+", self.map.zoom_in),
                                ("Fit", self.map.fit_graph), ("Reset", self.map.reset_zoom)):
            button = QPushButton(label)
            button.clicked.connect(callback)
            map_head.addWidget(button)
        map_layout.addLayout(map_head)
        self.map.device_selected.connect(self._select_device)
        map_layout.addWidget(self.map, 1)
        body.addWidget(map_card, 3)

        list_card = QFrame()
        list_card.setObjectName("TopologyDeviceCard")
        list_card.setStyleSheet(
            f"#TopologyDeviceCard {{ background: {Theme.GLASS_CARD};"
            f"border: 1px solid {Theme.GLASS_BORDER}; border-radius: 14px; }}")
        list_layout = QVBoxLayout(list_card)
        list_layout.setContentsMargins(12, 10, 12, 12)
        list_layout.setSpacing(7)
        head = QHBoxLayout()
        head.addWidget(QLabel("Discovered devices"))
        head.addStretch()
        self.device_count = QLabel("0")
        self.device_count.setStyleSheet(f"color: {Theme.ACCENT}; font-weight: 700;")
        head.addWidget(self.device_count)
        list_layout.addLayout(head)
        self.device_scroll = QScrollArea()
        self.device_scroll.setWidgetResizable(True)
        self.device_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.device_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        host = QWidget()
        host.setStyleSheet("background: transparent;")
        self.device_rows = QVBoxLayout(host)
        self.device_rows.setContentsMargins(1, 1, 4, 1)
        self.device_rows.setSpacing(5)
        self.device_scroll.setWidget(host)
        list_layout.addWidget(self.device_scroll, 1)
        body.addWidget(list_card, 2)
        root.addLayout(body, 1)

        footer = QHBoxLayout()
        self.status = QLabel("Ready. Choose subnets and click Scan.")
        self.status.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-size: 11px;")
        footer.addWidget(self.status, 1)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.accept)
        footer.addWidget(self.close_button)
        root.addLayout(footer)

        self._poll = QTimer(self)
        self._poll.setInterval(750)
        self._poll.timeout.connect(self._refresh_snapshot)
        self._refresh_snapshot()
        QTimer.singleShot(0, self.map.fit_graph)
        if self._service.snapshot()["active"]:
            self._set_scanning(True)
            self._poll.start()

    def _build_header(self):
        row = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("Network Topology")
        title.setStyleSheet(f"color: {Theme.TEXT_PRIMARY}; font-size: 20px; font-weight: 700;")
        subtitle = QLabel("Live devices grouped by their local or routed IPv4 subnet")
        subtitle.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-size: 11px;")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        row.addLayout(title_box, 1)
        self.manage_button = QPushButton("Manage subnets")
        self.manage_button.clicked.connect(self._manage_subnets)
        row.addWidget(self.manage_button)
        self.scan_button = QPushButton("Start scan")
        self.scan_button.clicked.connect(self._toggle_scan)
        row.addWidget(self.scan_button)
        return row

    def _build_summary(self):
        row = QHBoxLayout()
        row.setSpacing(8)
        self._summary_values = {}
        for title in ("Discovered", "Responding", "Neighbor cache", "Local L2", "Routed L3"):
            card = QFrame()
            card.setObjectName("TopoSummary")
            card.setStyleSheet(
                f"#TopoSummary {{ background: {Theme.GLASS_CARD};"
                f"border: 1px solid {Theme.GLASS_BORDER}; border-radius: 9px; }}")
            box = QVBoxLayout(card)
            box.setContentsMargins(10, 7, 10, 7)
            key = QLabel(title)
            key.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: 10px;")
            val = QLabel("0")
            val.setStyleSheet(f"color: {Theme.TEXT_PRIMARY}; font-size: 14px; font-weight: 700;")
            box.addWidget(key)
            box.addWidget(val)
            row.addWidget(card, 1)
            self._summary_values[title] = val
        return row

    def _build_controls(self):
        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search IP, hostname, MAC, vendor, or subnet")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filter)
        row.addWidget(self.search, 1)
        self.filter = QComboBox()
        self.filter.addItems(["All devices", "Responding", "Neighbor cache",
                              "Gateways", "Unidentified"])
        self.filter.currentTextChanged.connect(self._apply_filter)
        row.addWidget(self.filter)
        return row

    def _set_scanning(self, active):
        status = self._service.snapshot()["status"]
        self.scan_button.setText(
            "Cancel" if active else
            ("Rescan" if status in ("complete", "partial") else "Start scan"))
        self.manage_button.setEnabled(not active)

    def _toggle_scan(self):
        if self._service.snapshot()["active"]:
            self.status.setText("Cancelling scan and keeping partial results…")
            self.scan_button.setEnabled(False)
            self._service.cancel()
            if self._worker is not None:
                self._worker.stop()
            return
        self._start_scan()

    def _start_scan(self):
        self._devices = []
        self._selected_ip = ""
        self._set_scanning(True)
        self.scan_button.setEnabled(True)
        self.status.setText("Starting subnet discovery…")
        self._worker = StreamWorker(self._service.scan_stream)
        self._worker.result.connect(self._on_scan_event)
        self._worker.error.connect(self._on_scan_error)
        self._worker.done.connect(self._on_scan_done)
        self._worker.start()
        self._poll.start()

    def _on_scan_event(self, event):
        if event.get("event") == "segment":
            segment = event.get("segment", {})
            self.status.setText(
                f"Scanning {segment.get('label', 'subnet')} · {segment.get('cidr', '')} · "
                f"{event.get('total', 0):,} hosts")
        elif event.get("event") == "progress":
            segment = event.get("segment", {})
            self.status.setText(
                f"{segment.get('cidr', '')}: {event.get('scanned', 0):,}/"
                f"{event.get('total', 0):,} hosts · {event.get('found', 0):,} discovered")
        elif event.get("done"):
            self.status.setText(
                f"{'Scan cancelled — partial results' if event.get('cancelled') else 'Scan complete'} · "
                f"{event.get('found', 0):,} discovered from {len(event.get('segments', []))} subnet(s)")
        # Coalesce high-volume device/progress signals through the polling timer.
        # Rebuilding the entire map and list once per discovered host starves the
        # GUI event loop on large local subnets.

    def _on_scan_error(self, message):
        self.status.setText(f"Scan error: {message}")

    def _on_scan_done(self):
        self._worker = None
        self.scan_button.setEnabled(True)
        snapshot = self._service.snapshot()
        self._set_scanning(snapshot["active"])
        if not snapshot["active"]:
            self._poll.stop()
            if snapshot["status"] == "partial":
                self.status.setText(
                    f"Scan cancelled · {len(snapshot['devices'])} partial result(s) retained.")
            elif snapshot["status"] == "complete":
                self.status.setText(
                    f"Scan complete · {len(snapshot['devices'])} device(s) in "
                    f"{len(snapshot['segments'])} subnet(s)")
        self._refresh_snapshot()

    def _manage_subnets(self):
        dialog = SubnetConfigurationDialog(self)
        if dialog.exec():
            self._segments = configured_subnets()
            self._refresh_snapshot()

    def _refresh_snapshot(self):
        snapshot = self._service.snapshot()
        if snapshot["status"] == "scanning" and snapshot["segments"]:
            self._segments = snapshot["segments"]
        elif not self._segments:
            self._segments = configured_subnets()
        self._devices = snapshot["devices"]
        responding = sum(1 for d in self._devices if d.get("reachability") == "reachable")
        cached = sum(1 for d in self._devices if d.get("reachability") == "cached")
        self._summary_values["Discovered"].setText(str(len(self._devices)))
        self._summary_values["Responding"].setText(str(responding))
        self._summary_values["Neighbor cache"].setText(str(cached))
        self._summary_values["Local L2"].setText(
            str(sum(1 for s in self._segments if s.get("kind") == "local" and s.get("enabled", True))))
        self._summary_values["Routed L3"].setText(
            str(sum(1 for s in self._segments if s.get("kind") == "routed" and s.get("enabled", True))))
        signature = (
            tuple((s.get("id"), s.get("cidr"), s.get("label"), s.get("kind"),
                   s.get("gateway"), s.get("enabled", True)) for s in self._segments),
            tuple(sorted((d.get("ip"), d.get("hostname"), d.get("mac"), d.get("vendor"),
                          d.get("reachability"), d.get("cidr"), d.get("segment"),
                          d.get("is_gateway"), d.get("is_self")) for d in self._devices)),
            self.search.text(), self.filter.currentText(), self._selected_ip,
        )
        if signature != self._render_signature:
            self._render_signature = signature
            self._rebuild_devices()

    def _apply_filter(self, *_):
        text = self.search.text()
        kind = self.filter.currentText()
        self.map.update_graph(
            self._segments,
            self._devices,
            (device.get("ip") for device in self._filtered(text, kind)),
            self._selected_ip,
        )
        self._rebuild_list(text, kind)

    def _filtered(self, text=None, kind=None):
        text = self.search.text() if text is None else text
        kind = self.filter.currentText() if kind is None else kind
        query = (text or "").casefold().strip()
        out = []
        for device in self._devices:
            values = " ".join(str(device.get(k, "")) for k in
                              ("ip", "hostname", "mac", "vendor", "cidr", "segment")).casefold()
            if query and query not in values:
                continue
            reachability = device.get("reachability")
            if kind == "Responding" and reachability != "reachable":
                continue
            if kind == "Neighbor cache" and reachability != "cached":
                continue
            if kind == "Gateways" and not device.get("is_gateway"):
                continue
            if (kind == "Unidentified"
                    and (device.get("vendor") or "Unknown").casefold()
                    not in ("unknown", "private (randomized)", "")):
                continue
            out.append(device)
        return out

    def _rebuild_devices(self):
        self.map.update_graph(
            self._segments,
            self._devices,
            (device.get("ip") for device in self._filtered()),
            self._selected_ip,
        )
        self._rebuild_list()

    def _rebuild_list(self, text=None, kind=None):
        while self.device_rows.count():
            item = self.device_rows.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)
                widget.deleteLater()
        devices = sorted(self._filtered(text, kind), key=lambda d: (
            d.get("cidr", ""), tuple(int(part) for part in d.get("ip", "0.0.0.0").split("."))))
        self.device_count.setText(str(len(devices)))
        if not devices:
            empty = QLabel("No devices match this filter.")
            empty.setStyleSheet(f"color: {Theme.TEXT_MUTED}; padding: 12px;")
            self.device_rows.addWidget(empty)
        else:
            for device in devices:
                row = _DeviceListRow(device, device.get("ip") == self._selected_ip,
                                     self._select_device)
                self.device_rows.addWidget(row)
        self.device_rows.addStretch()

    def _select_device(self, device):
        # exec() runs a nested event loop. Ignore any duplicate activation
        # delivered while a details dialog is already open.
        if self._details_dialog is not None:
            return
        self._selected_ip = device.get("ip", "")
        self._rebuild_devices()
        self.map.center_device(self._selected_ip)
        self._details_dialog = DeviceDetailsDialog(self._core, device, self)
        try:
            self._details_dialog.exec()
        finally:
            self._details_dialog.deleteLater()
            self._details_dialog = None

    def closeEvent(self, event):
        if self._worker is not None:
            self._service.cancel()
            self._worker.stop()
        self._poll.stop()
        super().closeEvent(event)
