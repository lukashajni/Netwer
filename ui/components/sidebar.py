from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer, pyqtProperty, pyqtSignal
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.resources import Icons
from app.theme import Theme, card_bg, card_border

RAIL_WIDTH = 64


class NavItem(QFrame):
    # One clickable navigation item. A click emits 'clicked(key)'.
    clicked = pyqtSignal(str)

    def __init__(self, key: str, icon_name: str, title: str,
                 subtitle: str = "", badge: str = "", parent=None):
        super().__init__(parent)
        self.key = key
        self._icon_name = icon_name
        self._active = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(40)
        self.setToolTip(subtitle)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 4, 12, 4)
        lay.setSpacing(13)

        self._icon = QLabel()
        self._icon.setFixedWidth(20)
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._icon)

        self._title = QLabel(title)
        lay.addWidget(self._title)
        lay.addStretch()
        self._badge = None
        self._dot = None
        if badge:
            self._badge = QLabel(badge)
            self._badge.setFixedHeight(16)
            self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lay.addWidget(self._badge, 0, Qt.AlignmentFlag.AlignVCenter)
            self._dot = QLabel(self)
            self._dot.setFixedSize(7, 7)
            self._dot.setStyleSheet(f"background: {Theme.ACCENT_GLOW}; border-radius: 3px;")
            self._dot.move(31, 9)

        self._bar = QLabel(self)
        self._bar.setFixedSize(3, 22)
        self._bar.move(0, 9)
        self._refresh_style()

    def set_compact(self, compact: bool) -> None:
        self._title.setVisible(not compact)
        if self._badge is not None:
            self._badge.setVisible(not compact)
            self._dot.setVisible(compact)

    def set_active(self, active: bool) -> None:
        self._active = active
        self._refresh_style()

    def _refresh_style(self) -> None:
        if self._active:
            self.setStyleSheet(
                f"QFrame {{ background: {Theme.BG_ELEVATED}; border: none;"
                f"border-radius: 8px; }}"
                f"QLabel {{ background: transparent; border: none; }}"
            )
            self._icon.setPixmap(Icons.pixmap(self._icon_name, 17, Theme.ACCENT))
            self._title.setStyleSheet(
                f"color: {Theme.TEXT_PRIMARY}; font-size: {Theme.FONT_SIZE_BODY}px;"
                f"font-weight: 600; background: transparent; border: none;"
            )
        else:
            self.setStyleSheet(
                f"QFrame {{ background: transparent; border: none;"
                f"border-radius: 8px; }}"
                f"QFrame:hover {{ background: {card_bg()}; }}"
                f"QLabel {{ background: transparent; border: none; }}"
            )
            self._icon.setPixmap(Icons.pixmap(self._icon_name, 17, Theme.TEXT_SECONDARY))
            self._title.setStyleSheet(
                f"color: {Theme.TEXT_SECONDARY}; font-size: {Theme.FONT_SIZE_BODY}px;"
                f"font-weight: 500; background: transparent; border: none;"
            )
        self._bar.setStyleSheet(f"background: {Theme.ACCENT}; border-radius: 1px;")
        self._bar.setVisible(self._active)
        if self._badge is not None:
            self._badge.setStyleSheet(
                f"QLabel {{ background: {Theme.ACCENT_GLOW}; color: {Theme.BG_APP}; border-radius: 4px;"
                f"padding: 0 5px; font-size: 9px; font-weight: 700; }}")

    def mousePressEvent(self, event):
        self.clicked.emit(self.key)
        super().mousePressEvent(event)


class _SectionHeader(QWidget):

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self.setFixedHeight(34)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 12, 0, 4)
        self._text = QLabel(label.upper())
        self._text.setStyleSheet(
            f"color: {Theme.TEXT_FAINT}; font-size: 10px; font-weight: 600;"
            f"letter-spacing: 1.5px; background: transparent; padding-left: 14px;")
        lay.addWidget(self._text)
        self._line = QFrame()
        self._line.setFixedSize(24, 1)
        self._line.setStyleSheet(f"background: {Theme.BORDER_STRONG};")
        lay.addWidget(self._line, 0, Qt.AlignmentFlag.AlignHCenter)

    def set_compact(self, compact: bool) -> None:
        self._text.setVisible(not compact)
        self._line.setVisible(compact)


class Sidebar(QWidget):
    navigate = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._items: dict[str, NavItem] = {}
        self._sections: list[_SectionHeader] = []
        self._status_row = None
        self._compact = True
        self._width = RAIL_WIDTH
        self.resize(RAIL_WIDTH, self.height())
        self._apply_style()

        self._anim = QPropertyAnimation(self, b"railWidth", self)
        self._anim.setDuration(170)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        # small delay so it doesn't open when the mouse just passes over
        self._open_timer = QTimer(self)
        self._open_timer.setSingleShot(True)
        self._open_timer.setInterval(120)
        self._open_timer.timeout.connect(lambda: self._animate_to(Theme.SIDEBAR_WIDTH))

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 16, 10, 14)
        lay.setSpacing(2)

        # Brand block: gradient logo tile + wordmark.
        self._brand = self._build_brand()
        lay.addWidget(self._brand)

        self._top_spacer = QLabel("")
        self._top_spacer.setFixedHeight(4)
        self._top_spacer.setStyleSheet("background: transparent;")
        lay.addWidget(self._top_spacer)

    def _apply_style(self):
        self.setStyleSheet(
            f"#Sidebar {{ background: {Theme.BG_SIDEBAR}; border: none;"
            f"border-right: 1px solid {card_border()}; }}")

    def _get_width(self):
        return self._width

    def _set_width(self, w):
        self._width = int(w)
        self.resize(self._width, self.height())
        compact = self._width < Theme.SIDEBAR_WIDTH - 40
        if compact != self._compact:
            self._set_compact(compact)

    railWidth = pyqtProperty(int, _get_width, _set_width)

    def _animate_to(self, target):
        self._anim.stop()
        self._anim.setStartValue(self._width)
        self._anim.setEndValue(target)
        self._anim.start()
        if target > RAIL_WIDTH:
            self.raise_()

    def enterEvent(self, event):
        self._open_timer.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._open_timer.stop()
        self._animate_to(RAIL_WIDTH)
        super().leaveEvent(event)

    def _set_compact(self, compact: bool):
        self._compact = compact
        self._wordmark.setVisible(not compact)
        for item in self._items.values():
            item.set_compact(compact)
        for s in self._sections:
            s.set_compact(compact)

    def _build_brand(self) -> QWidget:
        brand = QFrame()
        brand.setStyleSheet("background: transparent; border: none;")
        b = QHBoxLayout(brand)
        b.setContentsMargins(5, 2, 0, 14)
        b.setSpacing(11)
        # Gradient logo tile with a globe glyph.
        logo = QLabel()
        logo.setFixedSize(34, 34)
        logo.setObjectName("BrandLogo")
        logo.setStyleSheet(
            f"#BrandLogo {{ background: {Theme.GRAD_ACCENT};"
            f"border-radius: 10px; }}")
        lg = QVBoxLayout(logo)
        lg.setContentsMargins(0, 0, 0, 0)
        gl = QLabel()
        gl.setPixmap(Icons.pixmap("globe", 18, "#ffffff"))
        gl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        gl.setStyleSheet("background: transparent;")
        lg.addWidget(gl)
        b.addWidget(logo)
        # Wordmark + sublabel.
        self._wordmark = QWidget()
        txtbox = QVBoxLayout(self._wordmark)
        txtbox.setContentsMargins(0, 0, 0, 0)
        txtbox.setSpacing(0)
        name = QLabel("NETWER")
        name.setStyleSheet(
            f"color: {Theme.TEXT_PRIMARY}; font-size: 17px; font-weight: 700;"
            f"letter-spacing: 0.5px; background: transparent;")
        sub = QLabel("DIAGNOSTICS")
        sub.setStyleSheet(
            f"color: {Theme.TEXT_MUTED}; font-size: 9px; font-weight: 600;"
            f"letter-spacing: 1.5px; background: transparent;")
        txtbox.addWidget(name)
        txtbox.addWidget(sub)
        b.addWidget(self._wordmark)
        b.addStretch()
        self._wordmark.setVisible(not self._compact)
        return brand

    def add_section(self, label: str) -> None:
        if not label:
            spacer = QLabel("")
            spacer.setFixedHeight(10)
            spacer.setStyleSheet("background: transparent;")
            self.layout().addWidget(spacer)
            return
        header = _SectionHeader(label)
        header.set_compact(self._compact)
        self._sections.append(header)
        self.layout().addWidget(header)

    def add_item(self, key: str, icon_name: str, title: str,
                 subtitle: str = "", badge: str = "") -> None:
        item = NavItem(key, icon_name, title, subtitle, badge)
        item.set_compact(self._compact)
        item.clicked.connect(self._on_item_clicked)
        self._items[key] = item
        self.layout().addWidget(item)

    def add_stretch_and_status(self) -> None:
        if getattr(self, "_status_row", None) is not None:
            return
        self.layout().addStretch()
        self._status_row = True   # marker so we don't add the stretch twice

    def _on_item_clicked(self, key: str) -> None:
        self.set_active(key)
        self.navigate.emit(key)

    def set_active(self, key: str) -> None:
        for k, item in self._items.items():
            item.set_active(k == key)

    def clear_items(self) -> None:
        lay = self.layout()
        # Keep the brand (index 0) and top spacer (index 1); remove the rest.
        while lay.count() > 2:
            item = lay.takeAt(2)
            w = item.widget()
            if w:
                w.setParent(None)   # detach immediately (not just deleteLater)
                w.deleteLater()
        self._items.clear()
        self._sections.clear()
        self._status_row = None

    def refresh_theme(self) -> None:
        self._apply_style()
        # Rebuild the brand block so the logo gradient + wordmark follow the
        # new theme's accent colours.
        lay = self.layout()
        old = self._brand
        self._brand = self._build_brand()
        lay.replaceWidget(old, self._brand)
        old.setParent(None)
        old.deleteLater()
