"""
NETWER — Card widget.

Genericki panel-kontejner: naslov s pravom ikonom gore, pa proizvoljan
sadrzaj ispod (graf, tablica, redovi, gaugevi).
"""

from PyQt6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel

from app.theme import Theme
from app.resources import Icons


class Card(QFrame):
    def __init__(self, title: str, icon_name: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setStyleSheet(
            f"#Card {{ background: {Theme.BG_CARD};"
            f"border: 1px solid {Theme.BORDER};"
            f"border-radius: {Theme.RADIUS_CARD}px; }}"
            f"#Card QLabel {{ background: transparent; border: none; }}"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 14)
        outer.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(7)
        if icon_name:
            icon_lbl = QLabel()
            icon_lbl.setPixmap(Icons.pixmap(icon_name, 14, Theme.TEXT_SECONDARY))
            header.addWidget(icon_lbl)
        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(
            f"color: {Theme.TEXT_BODY}; font-size: {Theme.FONT_SIZE_BODY}px;"
            f"font-weight: 500;"
        )
        header.addWidget(title_lbl)
        header.addStretch()
        self.header_layout = header
        outer.addLayout(header)

        self.content_layout = QVBoxLayout()
        self.content_layout.setSpacing(6)
        outer.addLayout(self.content_layout)


def kv_row(key: str, value: str, value_color: str = None, mono: bool = False):
    """Redak 'oznaka .... vrijednost' za Network Summary."""
    container = QFrame()
    container.setStyleSheet("background: transparent; border: none;")
    row = QHBoxLayout(container)
    row.setContentsMargins(0, 0, 0, 0)
    k = QLabel(key)
    k.setStyleSheet(
        f"color: {Theme.TEXT_SECONDARY}; font-size: {Theme.FONT_SIZE_SMALL}px;"
        f"background: transparent;"
    )
    v = QLabel(value)
    font = Theme.FONT_MONO if mono else Theme.FONT_FAMILY
    v.setStyleSheet(
        f"color: {value_color or Theme.TEXT_BODY}; font-family: '{font}';"
        f"font-size: {Theme.FONT_SIZE_SMALL}px; background: transparent;"
    )
    row.addWidget(k)
    row.addStretch()
    row.addWidget(v)
    return container, v
