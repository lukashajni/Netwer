"""
NETWER — Card widget.

Genericki panel-kontejner: naslov s pravom ikonom gore, pa proizvoljan
sadrzaj ispod (graf, tablica, redovi, gaugevi).
"""

from PyQt6.QtCore import QRectF
from PyQt6.QtGui import QPainter, QColor, QBrush, QPen, QPainterPath
from PyQt6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel

from app.theme import Theme
from app.resources import Icons


class Card(QFrame):
    def __init__(self, title: str, icon_name: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        # Background is painted in paintEvent (not via stylesheet) so it fills
        # the whole rounded rect UNDER child widgets — a stylesheet background
        # doesn't paint behind transparent children (gauges, charts), which
        # left a dark app-coloured band across the card.
        self.setStyleSheet(
            "#Card QLabel { background: transparent; border: none; }"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 18)
        outer.setSpacing(12)

        # Cards used as compact stat tiles pass an empty title — in that case
        # skip the header entirely, otherwise it eats ~30px of height and the
        # content gets clipped.
        self.header_layout = QHBoxLayout()
        if title or icon_name:
            header = self.header_layout
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
            outer.addLayout(header)
        else:
            outer.setContentsMargins(18, 16, 18, 16)
            outer.setSpacing(0)

        self.content_layout = QVBoxLayout()
        self.content_layout.setSpacing(6)
        outer.addLayout(self.content_layout)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = Theme.RADIUS_CARD
        path = QPainterPath()
        path.addRoundedRect(r, radius, radius)
        glass = getattr(Theme, "GLASS_ENABLED", True)
        fill = Theme.GLASS_CARD if glass else Theme.BG_CARD
        border = Theme.GLASS_BORDER if glass else Theme.BORDER
        p.fillPath(path, QBrush(QColor(fill)))
        p.setPen(QPen(QColor(border), 1))
        p.drawPath(path)
        p.end()


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
    font = Theme.FONT_MONO if mono else Theme.FONT_DATA
    v.setStyleSheet(
        f"color: {value_color or Theme.TEXT_BODY}; font-family: '{font}';"
        f"font-size: {Theme.FONT_SIZE_SMALL}px; background: transparent;"
    )
    row.addWidget(k)
    row.addStretch()
    row.addWidget(v)
    return container, v
