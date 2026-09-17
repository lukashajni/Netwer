"""
NETWER — Gauge widget (circular indicator)

Draws circular gauge (CPU / RAM / Disk on dashboard) using QPainter.
The value is animated to the new position instead of jumping.
Animation goes via QPropertyAnimation to the custom Qt property "value".
"""

from PyQt6.QtCore import Qt, QRectF, pyqtProperty, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QPainter, QColor, QPen, QFont
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel

from app.theme import Theme


class _Ring(QWidget):
    # The ring itself (without the label). Holds an animated value.

    def __init__(self, color: str, parent=None):
        super().__init__(parent)
        self._value = 0.0
        self._color = color
        self.setFixedSize(76, 76)
        self._anim = QPropertyAnimation(self, b"value")
        self._anim.setDuration(Theme.ANIM_SLOW)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def get_value(self) -> float:
        return self._value

    def set_value_prop(self, v: float) -> None:
        self._value = v
        self.update()

    value = pyqtProperty(float, fget=get_value, fset=set_value_prop)

    def animate_to(self, target: float) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._value)
        self._anim.setEndValue(max(0.0, min(100.0, target)))
        self._anim.start()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(8, 8, 60, 60)

        # Background ring
        pen_bg = QPen(QColor(Theme.BORDER), 6)
        pen_bg.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen_bg)
        p.drawArc(rect, 0, 360 * 16)
    
        # Active ring (from the top, clockwise)
        pen_fg = QPen(QColor(self._color), 6)
        pen_fg.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen_fg)
        span = int(-self._value / 100.0 * 360 * 16)
        p.drawArc(rect, 90 * 16, span)
        
        # Percentage in the center of the ring (compact - no space needed underneath, so
        # the card doesn't need to be tall).
        p.setPen(QColor(self._color))
        p.setFont(QFont(Theme.FONT_FAMILY_PRIMARY, 13, QFont.Weight.Bold))
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter,
                   f"{int(round(self._value))}%")
        p.end()


class Gauge(QWidget):
    def __init__(self, label: str, color: str, parent=None):
        super().__init__(parent)
        self.setFixedWidth(96)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)

        self._ring = _Ring(color)
        lay.addWidget(self._ring, 0, Qt.AlignmentFlag.AlignHCenter)
        
        # Only the name (CPU / Memory / Disk) is below the ring - the percentage is inside.
        self._label = QLabel(label)
        self._label.setFixedHeight(16)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet(
            f"color: {Theme.TEXT_SECONDARY}; font-family: {Theme.FONT_FAMILY};"
            f"font-size: {Theme.FONT_SIZE_SMALL}px; background: transparent;"
        )
        lay.addWidget(self._label, 0, Qt.AlignmentFlag.AlignHCenter)
        # 76 (ring) + 4 + 16 (label) = 96 - compact, fits in a small card.
        self.setFixedHeight(96)

    def set_value(self, percent: float, label: str | None = None) -> None:
        self._ring.animate_to(percent)
        if label is not None:
            self._label.setText(label)
