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

from PyQt6.QtCore import Qt, pyqtSignal, QRectF, QStringListModel
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QPushButton, QMenu, QLineEdit, QFrame,
    QCompleter
)
from PyQt6.QtGui import QAction, QPainter, QColor, QRadialGradient, QBrush

from app.theme import Theme, THEMES, current_theme_name, is_dark, card_bg, card_border
from app.resources import Icons


class _GlowDot(QWidget):
    """A small status dot with a soft glow/halo around it, like the preview.

    The glow is a radial gradient painted behind a solid dot — no OS shadow,
    so it renders identically on every platform."""

    def __init__(self, color: str, size: int = 16, parent=None):
        super().__init__(parent)
        self._color = QColor(color)
        self.setFixedSize(size, size)

    def set_color(self, color: str):
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        cx = cy = w / 2
        # Soft halo
        halo = QRadialGradient(cx, cy, w / 2)
        g = QColor(self._color)
        g.setAlpha(150)
        halo.setColorAt(0.0, g)
        mid = QColor(self._color)
        mid.setAlpha(60)
        halo.setColorAt(0.5, mid)
        edge = QColor(self._color)
        edge.setAlpha(0)
        halo.setColorAt(1.0, edge)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(halo))
        p.drawEllipse(QRectF(0, 0, w, w))
        # Solid core dot
        p.setBrush(self._color)
        r = w * 0.28
        p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))
        p.end()


class TopBar(QWidget):
    toggle_notifications = pyqtSignal()
    toggle_settings = pyqtSignal()
    theme_selected = pyqtSignal(str)
    search_submitted = pyqtSignal(str)
    suggestion_chosen = pyqtSignal(dict)

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
        self._search.textEdited.connect(self._on_search_typed)
        lay.addWidget(self._search, 1)

        # Live suggestions. Qt's own QCompleter owns the popup, its lifetime
        # and the keyboard handling — a hand-rolled Qt.Popup list parented to
        # the top bar was unstable: it grabs mouse/keyboard input and can
        # outlive its parent when pages are rebuilt.
        self._suggest_model = QStringListModel([])
        self._completer = QCompleter(self._suggest_model, self._search)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer.setCompletionMode(
            QCompleter.CompletionMode.UnfilteredPopupCompletion)
        self._completer.activated[str].connect(self._on_suggestion_activated)
        self._search.setCompleter(self._completer)
        self._style_completer_popup()
        #: popup label -> the suggestion dict behind it
        self._suggest_index = {}
        #: callable set by MainWindow: (text) -> list of suggestion dicts
        self.suggestion_provider = None

        # Status pill — a glowing dot + "All systems operational".
        self._status_pill = QFrame()
        self._status_pill.setObjectName("StatusPill")
        sp = QHBoxLayout(self._status_pill)
        sp.setContentsMargins(13, 6, 14, 6)
        sp.setSpacing(8)
        self._status_dot = _GlowDot(Theme.SUCCESS)
        sp.addWidget(self._status_dot, 0, Qt.AlignmentFlag.AlignVCenter)
        self._status_text = QLabel("All systems operational")
        sp.addWidget(self._status_text)
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
    def _style_completer_popup(self):
        popup = self._completer.popup()
        if popup is None:
            return
        popup.setStyleSheet(
            f"QListView {{ background: {Theme.BG_SIDEBAR};"
            f"border: 1px solid {Theme.GLASS_BORDER_HI};"
            f"border-radius: {Theme.RADIUS_CONTROL}px;"
            f"padding: 5px; outline: none;"
            f"color: {Theme.TEXT_BODY}; font-size: 13px; }}"
            f"QListView::item {{ padding: 7px 9px; border-radius: 8px; }}"
            f"QListView::item:selected {{ background: {Theme.GLASS_CARD};"
            f"color: {Theme.TEXT_PRIMARY}; }}")

    def _on_search_typed(self, text):
        """Refresh the suggestion list as the user types."""
        if not self.suggestion_provider:
            return
        try:
            items = self.suggestion_provider(text) or []
        except Exception:
            items = []

        labels, index = [], {}
        for it in items:
            label = it["title"]
            if it.get("subtitle"):
                label = it["title"] + "  \u2014  " + it["subtitle"]
            if label in index:            # keep labels unique
                label = label + " (" + str(it.get("key", "")) + ")"
            labels.append(label)
            index[label] = it
        self._suggest_index = index
        self._suggest_model.setStringList(labels)
        if labels:
            self._completer.complete()
        else:
            popup = self._completer.popup()
            if popup is not None:
                popup.hide()

    def _on_suggestion_activated(self, label):
        item = self._suggest_index.get(label)
        self._search.clear()
        self._suggest_model.setStringList([])
        self._suggest_index = {}
        if item:
            self.suggestion_chosen.emit(item)

    def _on_search_submit(self):
        popup = self._completer.popup()
        if popup is not None and popup.isVisible():
            return   # Enter is choosing a suggestion; QCompleter handles it
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
            f"#StatusPill {{ background: {Theme.GLASS_INPUT};"
            f"border: 1px solid {card_border()};"
            f"border-radius: {Theme.RADIUS_CONTROL}px; }}")
        self._status_text.setStyleSheet(
            f"color: {Theme.SUCCESS}; background: transparent;"
            f"font-size: {Theme.FONT_SIZE_SMALL}px; font-weight: 500;")
        self._status_dot.set_color(Theme.SUCCESS)

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
