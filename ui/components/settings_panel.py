from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.resources import Icons
from app.store import store
from app.theme import ACCENT_PRESETS, THEMES, Theme, current_accent_name, current_theme_name


class _AdapterCombo(QComboBox):
    # Reloads the adapter list every time it opens
    def showPopup(self):
        self.reload()
        super().showPopup()

    def reload(self):
        from app.adapter_state import adapter_state
        from core import network
        current = adapter_state.get()
        try:
            adapters = network.list_adapters()
            adapters = adapters.get("items", adapters) if isinstance(adapters, dict) else adapters
        except Exception:
            adapters = []
        self.blockSignals(True)
        self.clear()
        self.addItem("Auto (recommended)", "")
        for a in sorted(adapters or [], key=lambda a: (a.get("status") != "Up", a.get("name", ""))):
            name, status = a.get("name", ""), a.get("status", "")
            if name:
                self.addItem(name if status == "Up" else f"{name}  ({status})", name)
        idx = self.findData(current)
        if idx < 0 and current:
            self.addItem(f"{current}  (not found)", current)
            idx = self.count() - 1
        self.setCurrentIndex(max(idx, 0))
        self.blockSignals(False)


class SettingsPanel(QWidget):
    theme_changed = pyqtSignal(str)      # theme name
    accent_changed = pyqtSignal(str)     # accent name
    glass_toggled = pyqtSignal(bool)     # glass effect on/off
    resolution_changed = pyqtSignal(str)         # resolution key, e.g. "auto"
    schedule_toggled = pyqtSignal(bool)          # background scanning on/off
    schedule_interval_changed = pyqtSignal(int)  # interval in minutes
    offline_mode_toggled = pyqtSignal(bool)
    closed = pyqtSignal()

    WIDTH = 340

    def __init__(self, parent=None):
        super().__init__(parent)
        # Start collapsed. main_window animates maximumWidth 0 <-> WIDTH.
        # An inner fixed-width container keeps content from squishing while
        # the outer panel width animates.
        self.setMinimumWidth(0)
        self.setMaximumWidth(0)
        self._build()
        self.refresh_theme()

    def _build(self):
        # Outer layout holds a fixed-width inner container. Animating the
        # panel's maximumWidth then clips the container cleanly instead of
        # reflowing all the controls.
        shell = QHBoxLayout(self)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        inner = QWidget()
        inner.setFixedWidth(self.WIDTH)
        shell.addWidget(inner)

        outer = QVBoxLayout(inner)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Header
        header = QHBoxLayout()
        header.setContentsMargins(18, 16, 14, 14)
        self._title = QLabel("Settings")
        self._title.setStyleSheet(
            f"color: {Theme.TEXT_PRIMARY}; font-size: 17px; font-weight: 600;"
            f"background: transparent;")
        header.addWidget(self._title)
        header.addStretch()
        self._close_btn = QPushButton()
        self._close_btn.setIcon(Icons.get("close", Theme.TEXT_SECONDARY))
        self._close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close_btn.setFixedSize(30, 30)
        self._close_btn.clicked.connect(self.closed.emit)
        header.addWidget(self._close_btn)
        outer.addLayout(header)

        # Scrollable body
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        self._body = QVBoxLayout(body)
        self._body.setContentsMargins(18, 4, 18, 18)
        self._body.setSpacing(6)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        # -- Appearance --
        self._section("Appearance")
        self.theme_combo = self._combo(
            "Theme", list(THEMES.keys()), current_theme_name(),
            self._on_theme)
        accent_names = list(ACCENT_PRESETS.keys())
        self.accent_combo = self._combo(
            "Accent color", accent_names, current_accent_name(),
            self._on_accent)
        self.glass_check = self._check(
            "Glass effect (blur-style cards)",
            store.get_setting("glass_enabled", True),
            lambda v: self.glass_toggled.emit(v))

        # -- Network --
        self._section("Network")
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 4, 0, 4)
        lbl = QLabel("Adapter")
        lbl.setObjectName("SettingsLabel")
        lbl.setStyleSheet(f"color: {Theme.TEXT_BODY}; font-size: {Theme.FONT_SIZE_SMALL}px;"
                          f"background: transparent;")
        rl.addWidget(lbl)
        rl.addStretch()
        self.adapter_combo = _AdapterCombo()
        self.adapter_combo.setFixedWidth(210)
        self.adapter_combo.setStyleSheet(self._combo_style())
        self.adapter_combo.reload()
        self.adapter_combo.currentIndexChanged.connect(self._on_adapter)
        rl.addWidget(self.adapter_combo)
        self._body.addWidget(row)
        hint = QLabel("Used by the Dashboard, Network Information, Network Health and scans.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {Theme.TEXT_FAINT}; font-size: {Theme.FONT_SIZE_TINY}px;"
                           f"background: transparent;")
        self._body.addWidget(hint)

        # -- Display --
        self._section("Display")
        from app import display as display_res
        self._resolution_labels = list(display_res.RESOLUTIONS.values()) + [display_res.CUSTOM_LABEL]
        self._resolution_keys = list(display_res.RESOLUTIONS.keys()) + ["custom"]
        current_res_key = store.get_setting("resolution", "auto")
        custom_now = display_res.parse_custom(current_res_key)
        current_res_label = (display_res.CUSTOM_LABEL if custom_now else
                             display_res.RESOLUTIONS.get(current_res_key, display_res.RESOLUTIONS["auto"]))
        self.resolution_combo = self._combo(
            "Resolution", self._resolution_labels, current_res_label,
            self._on_resolution)
        self.resolution_combo.setFixedWidth(190)
        self._build_custom_resolution(custom_now)

        # -- Scanning --
        self._section("Scanning")
        self.ping_to = self._combo(
            "Ping timeout", ["500 ms", "1000 ms", "2000 ms"],
            f"{store.get_setting('ping_timeout_ms', 1000)} ms",
            lambda v: store.set_setting("ping_timeout_ms", int(v.split()[0])))
        self.sweep_to = self._combo(
            "Sweep timeout", ["100 ms", "150 ms", "300 ms", "500 ms"],
            f"{store.get_setting('sweep_timeout_ms', 150)} ms",
            lambda v: store.set_setting("sweep_timeout_ms", int(v.split()[0])))
        self.port_to = self._combo(
            "Port scan timeout", ["300 ms", "600 ms", "1000 ms"],
            f"{store.get_setting('portscan_timeout_ms', 600)} ms",
            lambda v: store.set_setting("portscan_timeout_ms", int(v.split()[0])))

        # -- Notifications --
        self._section("Notifications")
        self.notif_down = self._check(
            "Alert when a host goes down",
            store.get_setting("notify_host_down", True),
            lambda v: store.set_setting("notify_host_down", v))
        self.notif_scan = self._check(
            "Alert when a scan completes",
            store.get_setting("notify_scan_done", True),
            lambda v: store.set_setting("notify_scan_done", v))
        self.notif_newdev = self._check(
            "Alert on a new device on the network",
            store.get_setting("notify_new_device", True),
            lambda v: store.set_setting("notify_new_device", v))
        self.notif_capture = self._check(
            "Alert on problems found in a packet capture",
            store.get_setting("notify_capture", True),
            lambda v: store.set_setting("notify_capture", v))

        # -- Monitoring --
        self._section("Monitoring")
        self.schedule_on = self._check(
            "Scan network in the background",
            store.get_setting("schedule_enabled", False),
            lambda v: self.schedule_toggled.emit(v))
        self.schedule_interval = self._combo(
            "Scan every",
            ["5 min", "10 min", "15 min", "30 min", "60 min"],
            f"{store.get_setting('schedule_interval_min', 10)} min",
            lambda v: self.schedule_interval_changed.emit(int(v.split()[0])))

        # -- Behaviour --
        self._section("Behaviour")
        self.offline_mode = self._check(
            "Offline privacy mode",
            store.get_setting("offline_mode", True),
            self.offline_mode_toggled.emit)
        self.offline_mode.setToolTip(
            "Blocks optional third-party vendor lookups. Local scans and any "
            "diagnostics you start still send network traffic.")
        self.remember = self._check(
            "Remember recent hosts",
            store.get_setting("remember_hosts", True),
            lambda v: store.set_setting("remember_hosts", v))

        # -- Data --
        self._section("Data")
        clear_btn = QPushButton("  Clear host history and favorites")
        clear_btn.setIcon(Icons.get("history", Theme.TEXT_SECONDARY))
        clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_btn.clicked.connect(self._clear_data)
        clear_btn.setStyleSheet(self._danger_btn_style())
        self._body.addWidget(clear_btn)
        self._clear_btn = clear_btn

        reset_btn = QPushButton("  Reset all settings")
        reset_btn.setIcon(Icons.get("refresh", Theme.TEXT_SECONDARY))
        reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        reset_btn.clicked.connect(self._reset)
        reset_btn.setStyleSheet(self._danger_btn_style())
        self._body.addWidget(reset_btn)
        self._reset_btn = reset_btn

        self._body.addStretch()

    # -- Builders --
    def _section(self, label):
        lbl = QLabel(label.upper())
        lbl.setObjectName("SettingsSection")
        lbl.setStyleSheet(
            f"color: {Theme.TEXT_FAINT}; font-size: 10px; font-weight: 600;"
            f"letter-spacing: 1.2px; background: transparent;"
            f"padding: 14px 0 4px 0;")
        self._body.addWidget(lbl)

    def _combo(self, label, options, current, on_change):
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 4, 0, 4)
        name = QLabel(label)
        name.setObjectName("SettingsLabel")
        name.setStyleSheet(
            f"color: {Theme.TEXT_BODY}; font-size: {Theme.FONT_SIZE_SMALL}px;"
            f"background: transparent;")
        rl.addWidget(name)
        rl.addStretch()
        combo = QComboBox()
        combo.addItems(options)
        if current in options:
            combo.setCurrentText(current)
        combo.setFixedWidth(130)
        combo.setStyleSheet(self._combo_style())
        combo.currentTextChanged.connect(on_change)
        rl.addWidget(combo)
        self._body.addWidget(row)
        return combo

    def _check(self, label, checked, on_change):
        cb = QCheckBox("  " + label)
        cb.setChecked(bool(checked))
        cb.setCursor(Qt.CursorShape.PointingHandCursor)
        cb.setStyleSheet(self._check_style())
        cb.toggled.connect(on_change)
        self._body.addWidget(cb)
        return cb

    # -- Actions --
    def _on_adapter(self, _index):
        from app.adapter_state import adapter_state
        adapter_state.set(self.adapter_combo.currentData() or "")

    def _on_theme(self, name):
        self.theme_changed.emit(name)

    def _on_accent(self, name):
        self.accent_changed.emit(name)

    def _build_custom_resolution(self, current):
        from PyQt6.QtWidgets import QSpinBox

        from app import display as display_res
        self._custom_row = QWidget()
        lay = QHBoxLayout(self._custom_row)
        lay.setContentsMargins(0, 2, 0, 6)
        lay.setSpacing(6)
        lay.addStretch()
        box_style = (f"QSpinBox {{ background: {Theme.BG_ELEVATED}; color: {Theme.TEXT_BODY};"
                     f"border: 1px solid {Theme.BORDER}; border-radius: 6px; padding: 5px 8px;"
                     f"font-size: {Theme.FONT_SIZE_SMALL}px; }}")
        self._custom_w = QSpinBox()
        self._custom_w.setRange(*(display_res.CUSTOM_MIN[0], display_res.CUSTOM_MAX[0]))
        self._custom_h = QSpinBox()
        self._custom_h.setRange(*(display_res.CUSTOM_MIN[1], display_res.CUSTOM_MAX[1]))
        for box, value in ((self._custom_w, (current or (1920, 1080))[0]), (self._custom_h, (current or (1920, 1080))[1])):
            box.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
            box.setFixedWidth(64)
            box.setValue(value)
            box.setStyleSheet(box_style)
        times = QLabel("\u00d7")
        times.setStyleSheet(f"color: {Theme.TEXT_MUTED}; background: transparent;")
        apply_btn = QPushButton("Apply")
        apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        apply_btn.setStyleSheet(
            f"QPushButton {{ background: {Theme.ACCENT}; color: white; border: none; border-radius: 6px;"
            f"padding: 5px 12px; font-size: {Theme.FONT_SIZE_SMALL}px; font-weight: 600; }}"
            f"QPushButton:hover {{ background: {Theme.ACCENT_HOVER}; }}")
        apply_btn.clicked.connect(self._apply_custom_resolution)
        for w in (self._custom_w, times, self._custom_h, apply_btn):
            lay.addWidget(w)
        self._body.addWidget(self._custom_row)
        hint = QLabel(f"Width {display_res.CUSTOM_MIN[0]}-{display_res.CUSTOM_MAX[0]}, "
                      f"height {display_res.CUSTOM_MIN[1]}-{display_res.CUSTOM_MAX[1]}. Press Apply to use it.")
        hint.setStyleSheet(f"color: {Theme.TEXT_FAINT}; font-size: {Theme.FONT_SIZE_TINY}px; background: transparent;")
        self._custom_hint = hint
        self._body.addWidget(hint)
        self._set_custom_visible(bool(current))

    def _set_custom_visible(self, visible):
        self._custom_row.setVisible(visible)
        self._custom_hint.setVisible(visible)

    def _apply_custom_resolution(self):
        from app import display as display_res
        key = display_res.custom_key(self._custom_w.value(), self._custom_h.value())
        w, h = display_res.parse_custom(key)
        self._custom_w.setValue(w)
        self._custom_h.setValue(h)
        self.resolution_changed.emit(key)

    def _on_resolution(self, label):
        try:
            idx = self._resolution_labels.index(label)
        except ValueError:
            return
        is_custom = self._resolution_keys[idx] == "custom"
        self._set_custom_visible(is_custom)
        if not is_custom:
            self.resolution_changed.emit(self._resolution_keys[idx])

    def _clear_data(self):
        store.clear_recent_hosts()
        for f in store.favorites():
            store.remove_favorite(f["host"])
        self._clear_btn.setText("  Cleared \u2713")

    def _reset(self):
        store.reset_settings()
        from app.adapter_state import adapter_state
        adapter_state.set("")
        self.adapter_combo.reload()
        self.offline_mode.setChecked(True)
        self.offline_mode_toggled.emit(True)
        self.schedule_on.setChecked(False)
        self._reset_btn.setText("  Reset \u2713 (restart to apply all)")

    # -- Styling --
    def _combo_style(self):
        return (
            f"QComboBox {{ background: {Theme.BG_ELEVATED}; color: {Theme.TEXT_BODY};"
            f"border: 1px solid {Theme.BORDER}; border-radius: 6px;"
            f"padding: 5px 8px; font-size: {Theme.FONT_SIZE_SMALL}px; }}"
            f"QComboBox::drop-down {{ border: none; width: 18px; }}"
            f"QComboBox QAbstractItemView {{ background: {Theme.BG_ELEVATED};"
            f"color: {Theme.TEXT_BODY}; selection-background-color: {Theme.ACCENT};"
            f"border: 1px solid {Theme.BORDER_STRONG}; outline: none; }}")

    def _check_style(self):
        check_png = Icons.png_path("checkmark", 12, "#ffffff")
        return (
            f"QCheckBox {{ color: {Theme.TEXT_BODY};"
            f"font-size: {Theme.FONT_SIZE_SMALL}px; spacing: 2px;"
            f"background: transparent; padding: 5px 0; }}"
            f"QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 5px;"
            f"border: 1px solid {Theme.BORDER_STRONG}; background: {Theme.BG_ELEVATED}; }}"
            f"QCheckBox::indicator:checked {{ background: {Theme.ACCENT};"
            f"border-color: {Theme.ACCENT}; image: url({check_png}); }}")

    def _danger_btn_style(self):
        return (
            f"QPushButton {{ background: transparent; color: {Theme.TEXT_SECONDARY};"
            f"border: 1px solid {Theme.BORDER}; border-radius: 8px;"
            f"padding: 8px 12px; font-size: {Theme.FONT_SIZE_SMALL}px;"
            f"text-align: left; }}"
            f"QPushButton:hover {{ border-color: {Theme.DANGER};"
            f"color: {Theme.DANGER}; }}")

    def refresh_theme(self):
        self.setObjectName("SettingsPanel")
        self.setStyleSheet(
            f"#SettingsPanel {{ background: {Theme.BG_SIDEBAR};"
            f"border-left: 1px solid {Theme.GLASS_BORDER_HI}; }}")
        self._title.setStyleSheet(
            f"color: {Theme.TEXT_PRIMARY}; font-size: 17px; font-weight: 600;"
            f"background: transparent;")
        self._close_btn.setIcon(Icons.get("close", Theme.TEXT_SECONDARY))
        self._close_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; border-radius: 6px; }}"
            f"QPushButton:hover {{ background: {Theme.BG_CARD_HOVER}; }}")
        # Restyle sections/labels/combos/checks
        for lbl in self.findChildren(QLabel):
            if lbl.objectName() == "SettingsSection":
                lbl.setStyleSheet(
                    f"color: {Theme.TEXT_FAINT}; font-size: 10px; font-weight: 600;"
                    f"letter-spacing: 1.2px; background: transparent;"
                    f"padding: 14px 0 4px 0;")
            elif lbl.objectName() == "SettingsLabel":
                lbl.setStyleSheet(
                    f"color: {Theme.TEXT_BODY}; font-size: {Theme.FONT_SIZE_SMALL}px;"
                    f"background: transparent;")
        for combo in self.findChildren(QComboBox):
            combo.setStyleSheet(self._combo_style())
        for cb in self.findChildren(QCheckBox):
            cb.setStyleSheet(self._check_style())
        for btn in (getattr(self, "_clear_btn", None), getattr(self, "_reset_btn", None)):
            if btn:
                btn.setStyleSheet(self._danger_btn_style())
