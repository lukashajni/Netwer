"""
NETWER — WiFiSignal widget.

A WiFi glyph drawn with QPainter that reflects connection state:
  - No adapter / disconnected - gray glyph with a diagonal strike-through
  - Connected - arcs fill green according to signal strength (0-100%)

Signal strength maps to how many of the three arcs light up, and the
color shifts (green = strong, amber = medium, red = weak).
"""

from PyQt6.QtCore import Qt, QRectF, QPointF
from PyQt6.QtGui import QPainter, QColor, QPen
from PyQt6.QtWidgets import QWidget

from app.theme import Theme


class WiFiSignal(QWidget):
    def __init__(self, size: int = 84, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setStyleSheet("background: transparent;")
        self._percent = None  # None - no adapter / disconnected

    def set_signal(self, percent) -> None:
        """percent: 0-100 for strength, or None for disconnected/no adapter."""
        self._percent = percent
        self.update()

    def set_disconnected(self) -> None:
        self._percent = None
        self.update()

    def _strength_color(self, pct: float) -> QColor:
        if pct >= 60:
            return QColor(Theme.SUCCESS)
        if pct >= 30:
            return QColor(Theme.WARNING)
        return QColor(Theme.DANGER)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        cx = w / 2
        cy = h * 0.72  # dot near the bottom, arcs fan upward

        disconnected = self._percent is None
        active_color = (QColor(Theme.TEXT_FAINT) if disconnected
                        else self._strength_color(self._percent))
        inactive_color = QColor(Theme.BORDER_STRONG)

        # Three arcs of increasing radius + the center dot
        arc_radii = [w * 0.16, w * 0.28, w * 0.40]
        pct = 0 if disconnected else self._percent
        # How many arcs light up: <33% = 1, <66% = 2, else 3
        lit = 0 if disconnected else (1 if pct < 33 else 2 if pct < 66 else 3)

        # Center dot
        dot_color = active_color if not disconnected else QColor(Theme.TEXT_FAINT)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(dot_color)
        p.drawEllipse(QPointF(cx, cy), w * 0.045, w * 0.045)

        # Arcs (span 90 centered on straight up: from 225 to 315)
        pen = QPen()
        pen.setWidthF(w * 0.055)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        start_angle = 55 * 16   # Qt angles: 0 at 3 o'clock, CCW, 1/16 deg
        span_angle = 70 * 16
        for i, r in enumerate(arc_radii):
            rect = QRectF(cx - r, cy - r, 2 * r, 2 * r)
            if i < lit:
                pen.setColor(active_color)
            else:
                pen.setColor(inactive_color)
            p.setPen(pen)
            p.drawArc(rect, start_angle, span_angle)

        # Strike-through when disconnected
        if disconnected:
            strike = QPen(QColor(Theme.DANGER), w * 0.05)
            strike.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(strike)
            m = w * 0.20
            p.drawLine(QPointF(m, m), QPointF(w - m, h - m))

        p.end()
