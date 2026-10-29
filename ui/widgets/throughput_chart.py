"""Download and upload chart for the last 60 seconds, drawn like the redesign preview."""

from collections import deque

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QWidget

from app.theme import Theme

POINTS = 60


class ThroughputChart(QWidget):
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dl = deque([0.0] * POINTS, maxlen=POINTS)
        self._ul = deque([0.0] * POINTS, maxlen=POINTS)
        self.setMinimumHeight(180)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Open detailed analysis")

    def push(self, dl_mbps, ul_mbps):
        # stored as kbit/s
        self._dl.append(max(0.0, dl_mbps) * 1000)
        self._ul.append(max(0.0, ul_mbps) * 1000)
        self.update()

    def mousePressEvent(self, e):
        self.clicked.emit()

    def _scale(self):
        raw = max(50.0, *self._dl, *self._ul)
        for step in (50, 100, 200, 250, 500, 1000, 2000, 2500, 5000, 10000, 25000, 50000, 100000, 250000):
            if step * 4 >= raw:
                return step
        return 500000

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        left, right, top, bottom = 56, 10, 8, 24
        pw, ph = w - left - right, h - top - bottom
        step = self._scale()
        top_value = step * 4

        font = QFont(Theme.FONT_MONO_PRIMARY)
        font.setPixelSize(11)
        p.setFont(font)
        grid = QColor(Theme.BORDER)
        muted = QColor(Theme.TEXT_MUTED)
        for k in range(5):
            v = step * k
            y = top + ph - v / top_value * ph
            p.setPen(QPen(grid, 1))
            p.drawLine(QPointF(left, round(y) + 0.5), QPointF(w - right, round(y) + 0.5))
            p.setPen(muted)
            label = f"{v / 1000:g} Mb" if v >= 1000 else f"{v:g} kb"
            p.drawText(QRectF(0, y - 8, left - 8, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, label)
        for s in (60, 45, 30, 15, 0):
            x = left + (POINTS - 1 - s) / (POINTS - 1) * pw
            x = min(max(x, left + 14), w - right - 14)
            p.drawText(QRectF(x - 30, h - bottom + 6, 60, 16), Qt.AlignmentFlag.AlignCenter, f"-{s}s" if s else "now")

        def series(values, color, fill_alpha):
            pts = [QPointF(left + i / (POINTS - 1) * pw, top + ph - min(v, top_value) / top_value * ph)
                   for i, v in enumerate(values)]
            line = QPainterPath(pts[0])
            for pt in pts[1:]:
                line.lineTo(pt)
            area = QPainterPath(line)
            area.lineTo(left + pw, top + ph)
            area.lineTo(left, top + ph)
            area.closeSubpath()
            grad = QLinearGradient(0, top, 0, top + ph)
            c = QColor(color)
            c.setAlpha(fill_alpha)
            grad.setColorAt(0, c)
            c2 = QColor(color)
            c2.setAlpha(0)
            grad.setColorAt(1, c2)
            p.fillPath(area, grad)
            pen = QPen(QColor(color), 1.8)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(line)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(color))
            p.drawEllipse(pts[-1], 3.5, 3.5)

        series(self._dl, Theme.ACCENT, 70)
        series(self._ul, Theme.ACCENT_PURPLE, 50)
        p.end()
