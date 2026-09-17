"""
NETWER — SignalBars widget.

Four ascending bars showing wireless signal strength, colored by quality
(green = strong, amber = fair, red = weak). Used in the available-networks
list, where a compact per-row indicator reads better than a full glyph.
"""

from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QPainter, QColor
from PyQt6.QtWidgets import QWidget

from app.theme import Theme


def signal_color(dbm: float) -> str:
    if dbm >= -60:
        return Theme.SUCCESS
    if dbm >= -75:
        return Theme.WARNING
    return Theme.DANGER


def signal_quality(dbm: float) -> str:
    if dbm >= -50:
        return "Excellent"
    if dbm >= -60:
        return "Good"
    if dbm >= -70:
        return "Fair"
    if dbm >= -80:
        return "Weak"
    return "Very weak"


def dbm_to_percent(dbm: float) -> int:
    # Approximate signal percentage from dBm (-90 = 0%, -30 = 100%).
    pct = (dbm + 90) / 60 * 100
    return max(0, min(100, round(pct)))


class SignalBars(QWidget):
    def __init__(self, dbm: float = -100, parent=None):
        super().__init__(parent)
        self._dbm = dbm
        self.setFixedSize(24, 16)
        self.setStyleSheet("background: transparent;")

    def set_signal(self, dbm: float):
        self._dbm = dbm
        self.update()

    def _active_bars(self) -> int:
        if self._dbm >= -50:
            return 4
        if self._dbm >= -65:
            return 3
        if self._dbm >= -75:
            return 2
        if self._dbm >= -90:
            return 1
        return 0

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        active = self._active_bars()
        color = QColor(signal_color(self._dbm))
        inactive = QColor(Theme.BORDER_STRONG)

        bar_w = 3.5
        gap = 2
        h = self.height()

        p.setPen(Qt.PenStyle.NoPen)
        for i in range(4):
            bar_h = 4 + i * 3.5
            x = i * (bar_w + gap)
            y = h - bar_h
            p.setBrush(color if i < active else inactive)
            p.drawRoundedRect(QRectF(x, y, bar_w, bar_h), 1.5, 1.5)
        p.end()
