"""
NETWER — Sparkline (mini chart for stat cards).

A tiny inline chart that sits at the bottom of a StatCard, showing the
recent trend of a value (ping, download, upload, packet loss) — exactly
like the small wavy lines in the reference mockup. Drawn with QPainter,
no external chart engine, so it's cheap enough to have several on screen.
"""

from collections import deque

from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtGui import QPainter, QColor, QPen, QLinearGradient, QPainterPath, QBrush
from PyQt6.QtWidgets import QWidget

from app.theme import Theme


class Sparkline(QWidget):
    def __init__(self, color: str, max_points: int = 40, parent=None):
        super().__init__(parent)
        self._color = color
        self._data = deque(maxlen=max_points)
        self.setMinimumHeight(30)
        self.setMaximumHeight(34)
        self.setStyleSheet("background: transparent;")

    def push(self, value: float) -> None:
        self._data.append(float(value))
        self.update()

    def reset(self) -> None:
        self._data.clear()
        self.update()

    def paintEvent(self, event):
        if len(self._data) < 2:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        pad = 2

        vals = list(self._data)
        vmin = min(vals)
        vmax = max(vals)
        span = (vmax - vmin) or 1.0

        n = len(vals)
        dx = (w - 2 * pad) / (n - 1)

        def pt(i, v):
            x = pad + i * dx
            # invert Y (0 at bottom)
            y = h - pad - ((v - vmin) / span) * (h - 2 * pad)
            return QPointF(x, y)

        # Build the line path
        line = QPainterPath()
        line.moveTo(pt(0, vals[0]))
        for i in range(1, n):
            line.lineTo(pt(i, vals[i]))

        # Filled area under the line (subtle gradient)
        area = QPainterPath(line)
        area.lineTo(QPointF(pad + (n - 1) * dx, h - pad))
        area.lineTo(QPointF(pad, h - pad))
        area.closeSubpath()

        c = QColor(self._color)
        grad = QLinearGradient(0, 0, 0, h)
        fill_top = QColor(c); fill_top.setAlpha(70)
        fill_bot = QColor(c); fill_bot.setAlpha(0)
        grad.setColorAt(0.0, fill_top)
        grad.setColorAt(1.0, fill_bot)
        p.fillPath(area, QBrush(grad))

        # The line itself
        pen = QPen(c, 1.6)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.drawPath(line)
        p.end()
