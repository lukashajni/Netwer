"""
NETWER — Sidebar navigacija.

Lijeva navigacijska traka: logo, popis stranica (s pravim ikonama),
statusni indikator na dnu. Emitira navigate(key) na odabir stranice.
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame
)

from app.theme import Theme, card_bg, card_border
from app.resources import Icons


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
                f"QFrame {{ background: {Theme.GRAD_ACCENT_SOFT};"
                f"border: 1px solid {Theme.GLASS_BORDER_HI};"
                f"border-radius: {Theme.RADIUS_CONTROL}px; }}"
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
                f"border-radius: {Theme.RADIUS_CONTROL}px; }}"
                f"QFrame:hover {{ background: {Theme.GLASS_CARD}; }}"
                f"QLabel {{ background: transparent; border: none; }}"
            )
            self._icon.setPixmap(Icons.pixmap(self._icon_name, 17, Theme.TEXT_SECONDARY))
            self._title.setStyleSheet(
                f"color: {Theme.TEXT_SECONDARY}; font-size: {Theme.FONT_SIZE_BODY}px;"
                f"font-weight: 500; background: transparent; border: none;"
            )

    def mousePressEvent(self, event):
        self.clicked.emit(self.key)
        super().mousePressEvent(event)


class Sidebar(QWidget):
    """Cijela lijeva navigacija. Emitira navigate(key)."""
    navigate = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(230)
        self.setObjectName("Sidebar")
        self.setStyleSheet(
            f"#Sidebar {{ background: {card_bg()};"
            f"border: 1px solid {card_border()};"
            f"border-radius: {Theme.RADIUS_CARD}px; }}")
        self._items: dict[str, NavItem] = {}
        self._status_row = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 18, 14, 14)
        lay.setSpacing(2)

        # Brand block: gradient logo tile + wordmark, like the preview.
        self._brand = self._build_brand()
        lay.addWidget(self._brand)

        self._top_spacer = QLabel("")
        self._top_spacer.setFixedHeight(4)
        self._top_spacer.setStyleSheet("background: transparent;")
        lay.addWidget(self._top_spacer)

    def _build_brand(self) -> QWidget:
        brand = QFrame()
        brand.setStyleSheet("background: transparent; border: none;")
        b = QHBoxLayout(brand)
        b.setContentsMargins(6, 2, 6, 14)
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
        txtbox = QVBoxLayout()
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
        b.addLayout(txtbox)
        b.addStretch()
        return brand

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
        # The "All systems operational" status now lives ONLY in the top bar
        # (top-right). Here we just push the nav items up with a stretch, so
        # the status pill isn't duplicated at the bottom of the sidebar.
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
        """Remove all nav items, sections and the status row so the sidebar
        can be rebuilt (used on theme change). Keeps the brand + spacer."""
        lay = self.layout()
        # Keep the brand (index 0) and top spacer (index 1); remove the rest.
        while lay.count() > 2:
            item = lay.takeAt(2)
            w = item.widget()
            if w:
                w.setParent(None)   # detach immediately (not just deleteLater)
                w.deleteLater()
        self._items.clear()
        self._status_row = None

    def refresh_theme(self) -> None:
        self.setStyleSheet(
            f"#Sidebar {{ background: {card_bg()};"
            f"border: 1px solid {card_border()};"
            f"border-radius: {Theme.RADIUS_CARD}px; }}")
        # Rebuild the brand block so the logo gradient + wordmark follow the
        # new theme's accent colours.
        lay = self.layout()
        old = self._brand
        self._brand = self._build_brand()
        lay.replaceWidget(old, self._brand)
        old.setParent(None)
        old.deleteLater()
