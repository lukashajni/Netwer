"""Edit the local and explicitly routed IPv4 discovery scopes."""

import ipaddress

from PyQt6.QtWidgets import (
    QCheckBox,
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
from core.discovery import (
    MAX_DISCOVERY_HOSTS,
    configured_subnets,
    get_discovery_service,
    ipv4_host_count,
    manual_subnet,
    parse_ipv4_cidr,
    save_configured_subnets,
    validate_subnet_list,
)


class SubnetConfigurationDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Discovery Subnets")
        self.resize(850, 520)
        self.setStyleSheet(
            f"QDialog {{ background: {Theme.BG_APP}; color: {Theme.TEXT_BODY}; }}"
            f"QLabel {{ color: {Theme.TEXT_BODY}; background: transparent; }}")
        self._entries = configured_subnets()

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)
        title = QLabel("Discovery subnets")
        title.setStyleSheet(f"font-size: 18px; font-weight: 700; color: {Theme.TEXT_PRIMARY};")
        root.addWidget(title)
        hint = QLabel(
            f"Local scopes use the adapter's actual prefix. Add routed IPv4 CIDRs explicitly. "
            f"Enabled scans are capped at {MAX_DISCOVERY_HOSTS:,} total hosts.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {Theme.TEXT_SECONDARY};")
        root.addWidget(hint)

        self.rows_scroll = QScrollArea()
        self.rows_scroll.setWidgetResizable(True)
        self.rows_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.rows_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.rows_host = QWidget()
        self.rows_host.setStyleSheet("background: transparent;")
        self.rows_layout = QVBoxLayout(self.rows_host)
        self.rows_layout.setContentsMargins(0, 0, 4, 0)
        self.rows_layout.setSpacing(6)
        self.rows_scroll.setWidget(self.rows_host)
        root.addWidget(self.rows_scroll, 1)

        add_row = QHBoxLayout()
        self.cidr_input = QLineEdit()
        self.cidr_input.setPlaceholderText("Add routed IPv4 CIDR (e.g. 10.40.8.0/24)")
        self.cidr_input.setStyleSheet(
            f"QLineEdit {{ background: {Theme.GLASS_INPUT}; color: {Theme.TEXT_BODY};"
            f"border: 1px solid {Theme.BORDER}; border-radius: 7px; padding: 7px; }}")
        self.cidr_input.returnPressed.connect(self._add)
        add_row.addWidget(self.cidr_input, 1)
        self.add_button = QPushButton("Add subnet")
        self.add_button.clicked.connect(self._add)
        add_row.addWidget(self.add_button)
        root.addLayout(add_row)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet(f"color: {Theme.TEXT_MUTED};")
        root.addWidget(self.status)

        footer = QHBoxLayout()
        footer.addStretch()
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        self.save_button = QPushButton("Save subnets")
        self.save_button.setStyleSheet(
            f"QPushButton {{ background: {Theme.ACCENT}; color: white; border: none;"
            f"border-radius: 7px; padding: 8px 16px; font-weight: 600; }}")
        self.save_button.clicked.connect(self._save)
        footer.addWidget(self.cancel_button)
        footer.addWidget(self.save_button)
        root.addLayout(footer)
        self._render()

    def _render(self):
        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)
                widget.deleteLater()
        self._row_widgets = []
        for entry in self._entries:
            frame = QFrame()
            frame.setObjectName("SubnetRow")
            frame.setStyleSheet(
                f"#SubnetRow {{ background: {Theme.GLASS_CARD};"
                f"border: 1px solid {Theme.GLASS_BORDER}; border-radius: 8px; }}")
            layout = QHBoxLayout(frame)
            layout.setContentsMargins(9, 6, 9, 6)
            layout.setSpacing(9)
            enabled = QCheckBox()
            enabled.setChecked(bool(entry.get("enabled", True)))
            enabled.setAccessibleName(f"Enable {entry['cidr']}")
            enabled.setToolTip("Include this subnet in Start/Rescan")
            layout.addWidget(enabled)
            label = entry.get("label") or entry["cidr"]
            if entry.get("kind") == "local":
                label = f"{label} (local L2)"
            else:
                label = f"{label} (routed L3)"
            name = QLabel(label)
            name.setMinimumWidth(230)
            name.setStyleSheet(f"color: {Theme.TEXT_BODY}; background: transparent;")
            layout.addWidget(name)
            cidr_widget = QLabel(entry["cidr"])
            if entry.get("kind") == "routed":
                cidr_widget = QLineEdit(entry["cidr"])
                cidr_widget.setAccessibleName(f"CIDR {entry['cidr']}")
                cidr_widget.setFixedWidth(180)
                cidr_widget.setStyleSheet(
                    f"QLineEdit {{ background: {Theme.GLASS_INPUT}; color: {Theme.TEXT_BODY};"
                    f"border: 1px solid {Theme.BORDER}; border-radius: 5px; padding: 4px; }}")
            else:
                cidr_widget.setStyleSheet(
                    f"color: {Theme.TEXT_SECONDARY}; font-family: {Theme.FONT_MONO};"
                    "background: transparent;")
            layout.addWidget(cidr_widget, 1)
            net = ipaddress.ip_network(entry["cidr"], strict=False)
            hosts = QLabel(f"{ipv4_host_count(net):,} hosts")
            hosts.setMinimumWidth(82)
            hosts.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: 10px; background: transparent;")
            layout.addWidget(hosts)
            remove = QPushButton("Remove")
            remove.setEnabled(entry.get("kind") == "routed")
            remove.setToolTip("Local adapter scopes can be disabled but not removed")
            remove.clicked.connect(lambda _=False, i=len(self._row_widgets): self._remove(i))
            layout.addWidget(remove)
            self.rows_layout.addWidget(frame)
            self._row_widgets.append({"entry": entry, "enabled": enabled,
                                      "cidr": cidr_widget})
        self.rows_layout.addStretch()

    def _remove(self, row):
        if 0 <= row < len(self._entries) and self._entries[row].get("kind") == "routed":
            self._entries.pop(row)
            self._render()
            self.status.setText("Routed subnet removed. Save to persist changes.")

    def _add(self):
        try:
            net = parse_ipv4_cidr(self.cidr_input.text())
            if any(net.overlaps(ipaddress.ip_network(entry["cidr"], strict=False))
                   for entry in self._entries):
                raise ValueError(f"{net} overlaps an existing discovery subnet")
            entry = manual_subnet(str(net))
            entry["label"] = f"Routed {net}"
            validate_subnet_list(self._entries + [entry])
            self._entries.append(entry)
            self.cidr_input.clear()
            self._render()
            self.status.setText(f"Added {net} ({ipv4_host_count(net):,} hosts).")
            self.status.setStyleSheet(f"color: {Theme.TEXT_MUTED};")
        except ValueError as exc:
            self.status.setText(str(exc))
            self.status.setStyleSheet(f"color: {Theme.DANGER};")

    def _save(self):
        try:
            entries = []
            for widgets in self._row_widgets:
                original = widgets["entry"]
                entry = dict(original)
                entry["enabled"] = widgets["enabled"].isChecked()
                entry["cidr"] = widgets["cidr"].text().strip()
                if entry.get("kind") == "routed":
                    updated = manual_subnet(str(parse_ipv4_cidr(entry["cidr"])))
                    updated["label"] = entry.get("label", updated["label"])
                    updated["enabled"] = entry["enabled"]
                    entry = updated
                entries.append(entry)
            saved = save_configured_subnets(entries)
            get_discovery_service().set_segments(saved)
        except ValueError as exc:
            self.status.setText(str(exc))
            self.status.setStyleSheet(f"color: {Theme.DANGER};")
            return
        enabled_count = sum(1 for entry in saved if entry["enabled"])
        self.status.setText(f"Saved {enabled_count} enabled subnet(s).")
        self.accept()
