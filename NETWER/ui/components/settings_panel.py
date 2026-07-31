"""
NETWER — Settings panel (slides in from the right).

Grouped settings backed by the persistent store. Changing the theme or accent
applies live via callbacks the MainWindow wires up. Other settings (scan
timeouts, notification toggles, behaviour) persist immediately.
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QCheckBox, QScrollArea, QFrame
)

from app.theme import (
    Theme, THEMES, ACCENT_PRESETS, current_theme_name, current_accent_name
)
from app.resources import Icons
from app.store import store


class SettingsPanel(QWidget):
    theme_changed = pyqtSignal(str)      # theme name
    accent_changed = pyqtSignal(str)     # accent name
    glass_toggled = pyqtSignal(bool)     # glass effect on/off
    schedule_toggled = pyqtSignal(bool)          # background scanning on/off
    schedule_interval_changed = pyqtSignal(int)  # interval in minutes
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

        # ── Appearance ─────────────────────────────────────────
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

        # ── Scanning ───────────────────────────────────────────
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

        # ── Notifications ──────────────────────────────────────
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

        # ── Monitoring ─────────────────────────────────────────
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

        # ── Behaviour ──────────────────────────────────────────
        self._section("Behaviour")
        self.remember = self._check(
            "Remember recent hosts",
            store.get_setting("remember_hosts", True),
            lambda v: store.set_setting("remember_hosts", v))

        # ── Data ───────────────────────────────────────────────
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

    # ── Builders ───────────────────────────────────────────────
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

    # ── Actions ────────────────────────────────────────────────
    def _on_theme(self, name):
        self.theme_changed.emit(name)

    def _on_accent(self, name):
        self.accent_changed.emit(name)

    def _clear_data(self):
        store.clear_recent_hosts()
        for f in store.favorites():
            store.remove_favorite(f["host"])
        self._clear_btn.setText("  Cleared \u2713")

    def _reset(self):
        store.reset_settings()
        self._reset_btn.setText("  Reset \u2713 (restart to apply all)")

    # ── Styling ────────────────────────────────────────────────
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
