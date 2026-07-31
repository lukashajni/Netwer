"""
NETWER — Gauge widget (kružni indikator).

Crta kružni gauge (CPU / RAM / Disk na dashboardu) pomoću QPainter-a.
Vrijednost se ANIMIRA do nove pozicije umjesto da skoči — to daje onaj
"premium" osjećaj (kao MSI Center). Animacija ide preko QPropertyAnimation
na custom Qt property "value".

Korištenje:
    g = Gauge("CPU", Theme.ACCENT)
    g.set_value(23)     # animira se od trenutne do 23%
"""

from PyQt6.QtCore import Qt, QRectF, pyqtProperty, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QPainter, QColor, QPen, QFont
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel

from app.theme import Theme


class _Ring(QWidget):
    """Sam prsten (bez labele). Drži animiranu vrijednost."""

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

        # Pozadinski prsten
        pen_bg = QPen(QColor(Theme.BORDER), 6)
        pen_bg.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen_bg)
        p.drawArc(rect, 0, 360 * 16)

        # Aktivni prsten (od vrha, u smjeru kazaljke)
        pen_fg = QPen(QColor(self._color), 6)
        pen_fg.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen_fg)
        span = int(-self._value / 100.0 * 360 * 16)
        p.drawArc(rect, 90 * 16, span)
        # (Postotak se više NE crta unutar prstena — ispisuje se ispod, kao
        #  zaseban natpis, po želji korisnika.)
        p.end()


class Gauge(QWidget):
    def __init__(self, label: str, color: str, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._ring = _Ring(color)
        lay.addWidget(self._ring, alignment=Qt.AlignmentFlag.AlignCenter)

        lay.addSpacing(10)

        # Postotak (velik) ISPOD prstena.
        self._value_lbl = QLabel("0%")
        self._value_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._value_lbl.setStyleSheet(
            f"color: {color}; font-family: {Theme.FONT_DATA};"
            f"font-size: 18px; font-weight: 700; background: transparent;"
        )
        lay.addWidget(self._value_lbl)

        # Naziv (CPU / Memory / Disk) ispod postotka.
        self._label = QLabel(label)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet(
            f"color: {Theme.TEXT_SECONDARY}; font-family: {Theme.FONT_FAMILY};"
            f"font-size: {Theme.FONT_SIZE_SMALL}px; background: transparent;"
        )
        lay.addWidget(self._label)

    def set_value(self, percent: float, label: str | None = None) -> None:
        self._ring.animate_to(percent)
        self._value_lbl.setText(f"{int(round(percent))}%")
        if label is not None:
            self._label.setText(label)
