"""
NETWER — Sidebar navigacija.

Lijeva navigacijska traka: logo, popis stranica (s pravim ikonama),
statusni indikator na dnu. Emitira navigate(key) na odabir stranice.
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame
)

from app.theme import Theme
from app.resources import Icons, logo_pixmap


class NavItem(QFrame):
    """Jedna klikabilna stavka navigacije. Klik emitira clicked(key)."""
    clicked = pyqtSignal(str)

    def __init__(self, key: str, icon_name: str, title: str,
                 subtitle: str = "", parent=None):
        super().__init__(parent)
        self.key = key
        self._icon_name = icon_name
        self._active = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(46 if subtitle else 40)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 4, 12, 4)
        lay.setSpacing(11)

        self._icon = QLabel()
        self._icon.setFixedWidth(20)
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._icon)

        text_box = QVBoxLayout()
        text_box.setSpacing(0)
        self._title = QLabel(title)
        text_box.addWidget(self._title)
        self._subtitle = None
        if subtitle:
            self._subtitle = QLabel(subtitle)
            self._subtitle.setStyleSheet(
                f"color: {Theme.TEXT_FAINT}; font-size: {Theme.FONT_SIZE_TINY}px;"
                f"background: transparent;"
            )
            text_box.addWidget(self._subtitle)
        lay.addLayout(text_box)
        lay.addStretch()

        self._refresh_style()

    def set_active(self, active: bool) -> None:
        self._active = active
        self._refresh_style()

    def _refresh_style(self) -> None:
        if self._active:
            self.setStyleSheet(
                f"QFrame {{ background: {Theme.BG_ELEVATED};"
                f"border-radius: {Theme.RADIUS_CONTROL}px; }}"
                f"QLabel {{ background: transparent; }}"
            )
            self._icon.setPixmap(Icons.pixmap(self._icon_name, 17, Theme.ACCENT))
            self._title.setStyleSheet(
                f"color: {Theme.TEXT_BODY}; font-size: {Theme.FONT_SIZE_BODY}px;"
                f"font-weight: 500; background: transparent;"
            )
        else:
            self.setStyleSheet(
                f"QFrame {{ background: transparent;"
                f"border-radius: {Theme.RADIUS_CONTROL}px; }}"
                f"QFrame:hover {{ background: {Theme.BG_CARD}; }}"
                f"QLabel {{ background: transparent; }}"
            )
            self._icon.setPixmap(Icons.pixmap(self._icon_name, 17, Theme.TEXT_SECONDARY))
            self._title.setStyleSheet(
                f"color: {Theme.TEXT_SECONDARY}; font-size: {Theme.FONT_SIZE_BODY}px;"
                f"background: transparent;"
            )

    def mousePressEvent(self, event):
        self.clicked.emit(self.key)
        super().mousePressEvent(event)


class Sidebar(QWidget):
    """Cijela lijeva navigacija. Emitira navigate(key)."""
    navigate = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(210)
        self.setStyleSheet(f"background: {Theme.BG_SIDEBAR};")
        self._items: dict[str, NavItem] = {}

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 18, 0, 12)
        lay.setSpacing(2)

        self._build_logo(lay)
        lay.addSpacing(10)

    def _build_logo(self, lay: QVBoxLayout) -> None:
        # Pravi NETWER logo (gradijent globus, prozirna pozadina).
        logo = QLabel()
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setPixmap(logo_pixmap(72))
        logo.setStyleSheet("background: transparent;")
        lay.addWidget(logo)

        name = QLabel("NETWER")
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name.setStyleSheet(
            f"color: {Theme.TEXT_PRIMARY}; font-size: 19px; font-weight: 600;"
            f"letter-spacing: 4px; background: transparent; padding-top: 6px;"
        )
        lay.addWidget(name)

        ver = QLabel("v4.0")
        ver.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ver.setStyleSheet(
            f"color: {Theme.TEXT_FAINT}; font-size: {Theme.FONT_SIZE_TINY}px;"
            f"background: transparent;"
        )
        lay.addWidget(ver)

    def add_section(self, label: str) -> None:
        """Suptilni naslov sekcije koji grupira stavke ispod sebe
        (npr. 'Tools' iznad DNS/Reverse DNS/Traceroute). Prazan label
        ubaci samo mali razmak kao vizualni odjeljivač."""
        if not label:
            spacer = QLabel("")
            spacer.setFixedHeight(10)
            spacer.setStyleSheet("background: transparent;")
            self.layout().addWidget(spacer)
            return
        header = QLabel(label.upper())
        header.setStyleSheet(
            f"color: {Theme.TEXT_FAINT}; font-size: 10px; font-weight: 600;"
            f"letter-spacing: 1.5px; background: transparent;"
            f"padding: 14px 0 4px 16px;"
        )
        self.layout().addWidget(header)

    def add_item(self, key: str, icon_name: str, title: str,
                 subtitle: str = "") -> None:
        item = NavItem(key, icon_name, title, subtitle)
        item.clicked.connect(self._on_item_clicked)
        self._items[key] = item
        # Ubaci prije zavrsnog stretcha (ako postoji jos nije dodan)
        self.layout().addWidget(item)

    def add_stretch_and_status(self) -> None:
        self.layout().addStretch()
        status = QFrame()
        status.setStyleSheet("background: transparent;")
        s_lay = QHBoxLayout(status)
        s_lay.setContentsMargins(16, 4, 12, 4)
        s_lay.setSpacing(8)
        dot = QLabel("\u25CF")
        dot.setStyleSheet(f"color: {Theme.SUCCESS}; font-size: 9px; background: transparent;")
        s_lay.addWidget(dot)
        txt = QLabel("All systems operational")
        txt.setStyleSheet(
            f"color: {Theme.SUCCESS}; font-size: {Theme.FONT_SIZE_TINY}px;"
            f"background: transparent;"
        )
        s_lay.addWidget(txt)
        s_lay.addStretch()
        self.layout().addWidget(status)

    def _on_item_clicked(self, key: str) -> None:
        self.set_active(key)
        self.navigate.emit(key)

    def set_active(self, key: str) -> None:
        for k, item in self._items.items():
            item.set_active(k == key)
