"""
NETWER — ProgressBar widget.

A thin, theme-styled horizontal progress bar drawn with QPainter, so it
always fills to the correct fraction of its own current width - no fragile
fixed-pixel math, and it reflows correctly when the window is resized.
"""

from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QPainter, QColor, QBrush
from PyQt6.QtWidgets import QWidget

from app.theme import Theme


class ProgressBar(QWidget):
    def __init__(self, height: int = 6, color: str = None, parent=None):
        super().__init__(parent)
        self._fraction = 0.0
        self._bar_height = height
        self._color = color or Theme.ACCENT
        self.setFixedHeight(height)
        self.setSizePolicy(self.sizePolicy().horizontalPolicy(),
                           self.sizePolicy().verticalPolicy())

    def set_color(self, color: str) -> None:
        # Change the fill color
        self._color = color
        self.update()

    def set_fraction(self, fraction: float) -> None:
        # Set fill from 0.0 to 1.0 and repaint.
        self._fraction = max(0.0, min(1.0, float(fraction)))
        self.update()

    def reset(self) -> None:
        self.set_fraction(0.0)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        w = self.width()
        h = self._bar_height
        radius = h / 2

        # Track
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(Theme.BORDER)))
        painter.drawRoundedRect(QRectF(0, 0, w, h), radius, radius)

        # Fill
        if self._fraction > 0:
            fill_w = max(h, w * self._fraction)  # keep the cap visible even at tiny values
            painter.setBrush(QBrush(QColor(self._color)))
            painter.drawRoundedRect(QRectF(0, 0, fill_w, h), radius, radius)
