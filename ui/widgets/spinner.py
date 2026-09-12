"""
NETWER — Spinner (inline).

A small rotating-arc spinner for inline "loading…" states (e.g. while a PDF
preview renders or a scan spins up). Same visual language as the fullscreen
LoadingOverlay spinner, but standalone and embeddable anywhere.

    spin = Spinner(size=28)
    spin.start()   # begins animating
    spin.stop()    # freezes + you typically hide() it
"""

from PyQt6.QtCore import Qt, QTimer, QRectF
from PyQt6.QtGui import QPainter, QColor, QPen
from PyQt6.QtWidgets import QWidget

from app.theme import Theme


class Spinner(QWidget):
    def __init__(self, size: int = 28, color: str = None, parent=None):
        super().__init__(parent)
        self._angle = 0
        self._color = color or Theme.ACCENT
        self._size = size
        self.setFixedSize(size, size)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._rotate)

    def start(self):
        if not self._timer.isActive():
            self._timer.start(16)
        self.show()

    def stop(self):
        self._timer.stop()

    def _rotate(self):
        self._angle = (self._angle + 6) % 360
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        m = max(3, self._size // 10)
        rect = QRectF(m, m, self.width() - 2 * m, self.height() - 2 * m)
        pen_bg = QPen(QColor(Theme.BORDER), 3)
        pen_bg.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen_bg)
        p.drawArc(rect, 0, 360 * 16)
        pen = QPen(QColor(self._color), 3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawArc(rect, -self._angle * 16, 100 * 16)
        p.end()
