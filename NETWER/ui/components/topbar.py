"""
NETWER — TopBar.

Full-width bar across the top of the window: brand on the left, then the
theme switcher, a notifications bell (with unread badge), and a settings
gear on the right. The bell and gear toggle sliding panels; the theme
switcher opens a small menu of available themes.

Signals:
    toggle_notifications — bell clicked
    toggle_settings      — gear clicked
    theme_selected(str)  — a theme name was picked from the switcher
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QPushButton, QMenu, QLineEdit
)
from PyQt6.QtGui import QAction

from app.theme import Theme, THEMES, current_theme_name, is_dark, card_bg, card_border
from app.resources import Icons


class TopBar(QWidget):
    toggle_notifications = pyqtSignal()
    toggle_settings = pyqtSignal()
    theme_selected = pyqtSignal(str)
    search_submitted = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(60)
        self._unread = 0
        self._build()
        self.refresh_theme()

    def _build(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 10, 14, 10)
        lay.setSpacing(12)

        # Search field (visual, like the preview) — a read-only prompt that
        # focuses the global search. Fills the available width.
        self._search = QLineEdit()
        self._search.setPlaceholderText(
            "Search devices, run a trace, jump to a tool…")
        self._search.setClearButtonEnabled(True)
        self._search.returnPressed.connect(self._on_search_submit)
        lay.addWidget(self._search, 1)

        # Status pill — "All systems operational".
        self._status_pill = QLabel("  \u25CF  All systems operational  ")
        lay.addWidget(self._status_pill)

        # Theme switcher
        self._theme_btn = QPushButton()
        self._theme_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._theme_btn.clicked.connect(self._show_theme_menu)
        lay.addWidget(self._theme_btn)

        # Notifications bell
        self._bell = QPushButton()
        self._bell.setCursor(Qt.CursorShape.PointingHandCursor)
        self._bell.setFixedSize(38, 38)
        self._bell.clicked.connect(self.toggle_notifications.emit)
        lay.addWidget(self._bell)

        # Settings gear
        self._gear = QPushButton()
        self._gear.setCursor(Qt.CursorShape.PointingHandCursor)
        self._gear.setFixedSize(38, 38)
        self._gear.clicked.connect(self.toggle_settings.emit)
        lay.addWidget(self._gear)

    # ── Search ─────────────────────────────────────────────────
    def _on_search_submit(self):
        text = self._search.text().strip()
        if text:
            self.search_submitted.emit(text)
            self._search.clear()

    # ── Theme menu ─────────────────────────────────────────────
    def _show_theme_menu(self):
        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu {{ background: {Theme.BG_ELEVATED};"
            f"border: 1px solid {Theme.BORDER_STRONG}; border-radius: 8px;"
            f"padding: 4px; }}"
            f"QMenu::item {{ color: {Theme.TEXT_BODY}; padding: 7px 26px 7px 12px;"
            f"border-radius: 5px; font-size: {Theme.FONT_SIZE_SMALL}px; }}"
            f"QMenu::item:selected {{ background: {Theme.ACCENT}; color: white; }}")
        cur = current_theme_name()
        for name, pal in THEMES.items():
            mark = "\u2713  " if name == cur else "     "
            act = QAction(f"{mark}{name}", menu)
            act.triggered.connect(lambda _=False, n=name: self.theme_selected.emit(n))
            menu.addAction(act)
        menu.exec(self._theme_btn.mapToGlobal(
            self._theme_btn.rect().bottomLeft()))

    # ── Notifications badge ────────────────────────────────────
    def set_unread(self, count: int):
        self._unread = count
        self._render_bell()

    # ── Theme application ──────────────────────────────────────
    def refresh_theme(self):
        """Re-skin the bar to the current theme (called after a theme change)."""
        self.setObjectName("TopBar")
        self.setStyleSheet(
            f"#TopBar {{ background: {card_bg()};"
            f"border: 1px solid {card_border()};"
            f"border-radius: {Theme.RADIUS_CARD}px; }}")
        self._search.setStyleSheet(
            f"QLineEdit {{ background: {Theme.GLASS_INPUT};"
            f"color: {Theme.TEXT_BODY}; border: 1px solid {Theme.GLASS_BORDER};"
            f"border-radius: {Theme.RADIUS_CONTROL}px; padding: 9px 13px;"
            f"font-size: {Theme.FONT_SIZE_SMALL}px; }}"
            f"QLineEdit:focus {{ border-color: {Theme.GLASS_BORDER_HI}; }}")
        self._status_pill.setStyleSheet(
            f"color: {Theme.SUCCESS}; background: {Theme.GLASS_INPUT};"
            f"border: 1px solid {card_border()};"
            f"border-radius: {Theme.RADIUS_CONTROL}px;"
            f"font-size: {Theme.FONT_SIZE_SMALL}px; font-weight: 500;")

        icon = "moon" if is_dark() else "sun"
        accent = Theme.ACCENT_PURPLE if is_dark() else Theme.WARNING
        self._theme_btn.setText(f"  {current_theme_name()}  ")
        self._theme_btn.setIcon(Icons.get(icon, accent))
        self._theme_btn.setStyleSheet(
            f"QPushButton {{ background: {Theme.GLASS_INPUT};"
            f"color: {Theme.TEXT_BODY}; border: 1px solid {Theme.GLASS_BORDER};"
            f"border-radius: {Theme.RADIUS_CONTROL}px; padding: 7px 13px;"
            f"font-size: {Theme.FONT_SIZE_SMALL}px; }}"
            f"QPushButton:hover {{ border-color: {Theme.GLASS_BORDER_HI}; }}")

        self._icon_btn_style(self._gear, "settings")
        self._render_bell()

    def _icon_btn_style(self, btn, icon_name):
        btn.setIcon(Icons.get(icon_name, Theme.TEXT_SECONDARY))
        btn.setStyleSheet(
            f"QPushButton {{ background: {Theme.GLASS_INPUT};"
            f"border: 1px solid {card_border()};"
            f"border-radius: {Theme.RADIUS_CONTROL}px; }}"
            f"QPushButton:hover {{ border-color: {Theme.GLASS_BORDER_HI}; }}")

    def _render_bell(self):
        self._icon_btn_style(self._bell, "bell")
        # Badge is drawn via a child label overlay.
        if not hasattr(self, "_badge"):
            self._badge = QLabel(self._bell)
            self._badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        if self._unread > 0:
            self._badge.setText(str(self._unread if self._unread < 100 else "99+"))
            self._badge.setStyleSheet(
                f"background: {Theme.DANGER}; color: white; font-size: 9px;"
                f"font-weight: 600; border-radius: 8px; padding: 1px 4px;")
            self._badge.adjustSize()
            self._badge.move(self._bell.width() - self._badge.width() - 2, 2)
            self._badge.show()
        else:
            self._badge.hide()
