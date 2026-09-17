"""
NETWER — UsageBar widget.

A labelled horizontal progress bar for resource usage (CPU / memory / disk).
Denser than a circular gauge, which suits the "System Information" detail page
where several readings sit stacked. The fill animates to new values so
updates read as movement rather than jumps.
"""

from PyQt6.QtCore import Qt, QPropertyAnimation, QEasingCurve, pyqtProperty, QRectF
from PyQt6.QtGui import QPainter, QColor
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel

from app.theme import Theme


class _Bar(QWidget):
    # The bar itself - animated fill

    def __init__(self, color: str, parent=None):
        super().__init__(parent)
        self._color = color
        self._value = 0.0
        self.setFixedHeight(8)
        self.setStyleSheet("background: transparent;")
        self._anim = QPropertyAnimation(self, b"value", self)
        self._anim.setDuration(Theme.ANIM_NORMAL)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def get_value(self):
        return self._value

    def set_value_prop(self, v):
        self._value = v
        self.update()

    value = pyqtProperty(float, get_value, set_value_prop)

    def animate_to(self, target: float):
        self._anim.stop()
        self._anim.setStartValue(self._value)
        self._anim.setEndValue(max(0.0, min(100.0, float(target))))
        self._anim.start()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        r = h / 2

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(Theme.BORDER))
        p.drawRoundedRect(QRectF(0, 0, w, h), r, r)

        fill_w = w * (self._value / 100.0)
        if fill_w > 0:
            p.setBrush(QColor(self._color))
            p.drawRoundedRect(QRectF(0, 0, max(fill_w, h), h), r, r)
        p.end()


class UsageBar(QWidget):
    def __init__(self, label: str, color: str, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 12)
        lay.setSpacing(5)

        top = QHBoxLayout()
        top.setSpacing(8)
        self._label = QLabel(label)
        self._label.setStyleSheet(
            f"color: {Theme.TEXT_SECONDARY}; font-size: {Theme.FONT_SIZE_SMALL}px;"
            f"background: transparent;")
        top.addWidget(self._label)

        self._detail = QLabel("")
        self._detail.setStyleSheet(
            f"color: {Theme.TEXT_FAINT}; font-family: {Theme.FONT_MONO};"
            f"font-size: {Theme.FONT_SIZE_TINY}px; background: transparent;")
        top.addWidget(self._detail)
        top.addStretch()

        self._value_label = QLabel("0%")
        self._value_label.setStyleSheet(
            f"color: {color}; font-family: {Theme.FONT_DATA};"
            f"font-size: {Theme.FONT_SIZE_BODY}px; font-weight: 600;"
            f"background: transparent;")
        top.addWidget(self._value_label)
        lay.addLayout(top)

        self._bar = _Bar(color)
        lay.addWidget(self._bar)

    def set_value(self, percent: float, detail: str = ""):
        pct = max(0.0, min(100.0, float(percent)))
        self._bar.animate_to(pct)
        self._value_label.setText(f"{pct:.0f}%")
        if detail:
            self._detail.setText(detail)
