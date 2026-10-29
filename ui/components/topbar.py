from PyQt6.QtCore import QRectF, QStringListModel, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QPainter, QRadialGradient
from PyQt6.QtWidgets import (
    QCompleter,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
)

from app.resources import Icons
from app.theme import Theme, card_bg, card_border


class _GlowDot(QWidget):
    """Draw a status dot with a soft halo."""

    def __init__(self, color: str, size: int = 16, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
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
    toggle_ai = pyqtSignal()
    open_capture = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(Theme.TOPBAR_HEIGHT)
        self._unread = 0
        self._capturing = False
        self._build()
        self.refresh_theme()

    def _build(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 10, 16, 10)
        lay.setSpacing(10)

        # search box: jumps to a tool, or asks Netwer AI when it reads like a question
        self._search_box = QFrame()
        self._search_box.setObjectName("SearchBox")
        sb = QHBoxLayout(self._search_box)
        sb.setContentsMargins(10, 0, 8, 0)
        sb.setSpacing(8)
        self._search_icon = QLabel()
        sb.addWidget(self._search_icon)
        self._search = QLineEdit()
        self._search.setPlaceholderText("Ask Netwer AI about your network, or jump to a tool…")
        self._search.returnPressed.connect(self._on_search_submit)
        self._search.textEdited.connect(self._on_search_typed)
        sb.addWidget(self._search, 1)
        self._kbd = QLabel("Ctrl K")
        sb.addWidget(self._kbd)
        lay.addWidget(self._search_box, 1)

        # QCompleter owns the popup lifecycle and keyboard handling.
        self._suggest_model = QStringListModel([])
        self._completer = QCompleter(self._suggest_model, self._search)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer.setCompletionMode(
            QCompleter.CompletionMode.UnfilteredPopupCompletion)
        self._completer.activated[str].connect(self._on_suggestion_activated)
        self._search.setCompleter(self._completer)
        self._style_completer_popup()
        # popup label -> the suggestion dict behind it
        self._suggest_index = {}
        # callable set by MainWindow: (text) -> list of suggestion dicts
        self.suggestion_provider = None

        # adapter in use
        self._adapter_pill = QFrame()
        self._adapter_pill.setObjectName("Pill")
        ap = QHBoxLayout(self._adapter_pill)
        ap.setContentsMargins(11, 0, 12, 0)
        ap.setSpacing(7)
        self._adapter_icon = QLabel()
        ap.addWidget(self._adapter_icon)
        self._adapter_text = QLabel("Detecting adapter…")
        self._adapter_text.setTextFormat(Qt.TextFormat.RichText)
        ap.addWidget(self._adapter_text)
        lay.addWidget(self._adapter_pill)

        # capture state, click opens Packet Capture
        self._status_pill = QPushButton()
        self._status_pill.setObjectName("CapPill")
        self._status_pill.setCursor(Qt.CursorShape.PointingHandCursor)
        self._status_pill.clicked.connect(self.open_capture.emit)
        sp = QHBoxLayout(self._status_pill)
        sp.setContentsMargins(10, 0, 12, 0)
        sp.setSpacing(7)
        self._status_dot = _GlowDot(Theme.TEXT_MUTED, 14)
        sp.addWidget(self._status_dot, 0, Qt.AlignmentFlag.AlignVCenter)
        self._status_text = QLabel("Capture off")
        sp.addWidget(self._status_text)
        lay.addWidget(self._status_pill)

        self._ai_btn = QPushButton("  Netwer AI")
        self._ai_btn.setCheckable(True)
        self._ai_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._ai_btn.clicked.connect(self.toggle_ai.emit)
        lay.addWidget(self._ai_btn)

        # Notifications bell
        self._bell = QPushButton()
        self._bell.setCursor(Qt.CursorShape.PointingHandCursor)
        self._bell.setFixedSize(34, 34)
        self._bell.setToolTip("Notifications")
        self._bell.clicked.connect(self.toggle_notifications.emit)
        lay.addWidget(self._bell)

        # Settings gear
        self._gear = QPushButton()
        self._gear.setCursor(Qt.CursorShape.PointingHandCursor)
        self._gear.setFixedSize(34, 34)
        self._gear.setToolTip("Settings")
        self._gear.clicked.connect(self.toggle_settings.emit)
        lay.addWidget(self._gear)

    # -- Search --
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
        # Refresh the suggestion list as the user types.
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
        self._suggest_model.setStringList([])
        self._suggest_index = {}
        if item:
            self.suggestion_chosen.emit(item)
        # QCompleter may write its accepted label into the line edit after
        # emitting activated; clear on the next event-loop turn to avoid
        # leaving the suggestion text in the global search field.
        QTimer.singleShot(0, self._search.clear)

    def _on_search_submit(self):
        popup = self._completer.popup()
        if popup is not None and popup.isVisible():
            return   # Enter is choosing a suggestion, QCompleter handles it
        text = self._search.text().strip()
        if text:
            self.search_submitted.emit(text)
            self._search.clear()

    # -- Notifications badge --
    def set_unread(self, count: int):
        self._unread = count
        self._render_bell()

    # -- Theme application --
    def refresh_theme(self):
        """Re-skin the bar to the current theme (called after a theme change)."""
        self.setFixedHeight(54)
        self.setObjectName("TopBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            f"#TopBar {{ background: {Theme.BG_APP}; border: none; border-bottom: 1px solid {card_border()}; }}"
            f"QLabel {{ background: transparent; }}")
        box = f"background: {card_bg()}; border: 1px solid {card_border()}; border-radius: 9px;"
        self._search_box.setFixedHeight(34)
        self._search_box.setStyleSheet(f"#SearchBox {{ {box} }}")
        self._search.setStyleSheet(
            f"QLineEdit {{ background: transparent; border: none; color: {Theme.TEXT_PRIMARY};"
            f"font-size: {Theme.FONT_SIZE_SMALL}px; padding: 0; }}")
        self._search_icon.setPixmap(Icons.pixmap("search", 15, Theme.TEXT_MUTED))
        self._kbd.setStyleSheet(
            f"color: {Theme.TEXT_MUTED}; font-family: {Theme.FONT_MONO}; font-size: 10px;"
            f"border: 1px solid {Theme.BORDER_STRONG}; border-radius: 5px; padding: 1px 5px;")
        for pill in (self._adapter_pill, self._status_pill):
            pill.setFixedHeight(34)
        self._adapter_pill.setStyleSheet(f"#Pill {{ {box} }}")
        self._adapter_icon.setPixmap(Icons.pixmap("dev_pc", 15, Theme.TEXT_SECONDARY))
        self._adapter_text.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-size: {Theme.FONT_SIZE_SMALL}px;")
        self._status_pill.setStyleSheet(
            f"#CapPill {{ {box} }} #CapPill:hover {{ border-color: {Theme.GLASS_BORDER_HI}; }}")
        self._render_status()
        self._ai_btn.setFixedHeight(34)
        self._ai_btn.setIcon(Icons.get("ai", "#d9d0ff"))
        self._ai_btn.setStyleSheet(
            f"QPushButton {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #2a2550, stop:1 #1c2445);"
            f"color: #d9d0ff; border: 1px solid #5a4a9a; border-radius: 9px;"
            f"padding: 0 13px; font-size: {Theme.FONT_SIZE_SMALL}px; font-weight: 500; }}"
            f"QPushButton:hover {{ border-color: {Theme.ACCENT_GLOW}; }}"
            f"QPushButton:checked {{ background: #3a3070; }}")
        self._icon_btn_style(self._gear, "settings")
        self._render_bell()

    def focus_search(self):
        self._search.setFocus()
        self._search.selectAll()

    def set_adapter(self, name: str, ip: str):
        if name:
            self._adapter_text.setText(
                f"{name} · <span style='font-family:{Theme.FONT_MONO}'>{ip}</span>" if ip else name)

    def set_capture_rate(self, pps):
        self._rate = pps
        self._render_status()

    def set_ai_open(self, on: bool):
        self._ai_btn.setChecked(on)

    def set_capturing(self, on: bool):
        self._capturing = on
        self._render_status()

    def _render_status(self):
        color = Theme.DANGER if self._capturing else Theme.TEXT_MUTED
        rate = getattr(self, "_rate", None)
        if self._capturing:
            text = f"Capturing · {rate} pkt/s" if rate is not None else "Capturing"
        else:
            text = "Capture off"
        self._status_text.setText(text)
        self._status_text.setStyleSheet(
            f"color: {Theme.TEXT_SECONDARY}; background: transparent; font-size: {Theme.FONT_SIZE_SMALL}px;")
        self._status_dot.set_color(color)
        # a QPushButton does not size itself to a child layout
        self._status_pill.setFixedWidth(self._status_pill.layout().sizeHint().width())

    def _icon_btn_style(self, btn, icon_name):
        btn.setIcon(Icons.get(icon_name, Theme.TEXT_SECONDARY))
        btn.setStyleSheet(
            f"QPushButton {{ background: {card_bg()};"
            f"border: 1px solid {card_border()};"
            f"border-radius: 9px; }}"
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
