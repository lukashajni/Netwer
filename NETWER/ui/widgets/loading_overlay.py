"""
NETWER — LoadingOverlay (fullscreen).

A full-window loading screen: centered NETWER logo, an animated ring
spinner beneath it, and a status line. Shown over the ENTIRE app (sidebar
included) on startup. When all initial data is ready, it fades out and
reveals the fully populated application at once.
"""

from PyQt6.QtCore import Qt, QTimer, QRectF, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QPainter, QColor, QPen, QPixmap
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QGraphicsOpacityEffect

from app.theme import Theme
from app.resources import LOGO_PATH


class _Spinner(QWidget):
    """Rotating arc spinner."""

    def __init__(self, color: str, size: int = 46, parent=None):
        super().__init__(parent)
        self._angle = 0
        self._color = color
        self.setFixedSize(size, size)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._rotate)

    def start(self):
        self._timer.start(16)

    def stop(self):
        self._timer.stop()

    def _rotate(self):
        self._angle = (self._angle + 6) % 360
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        m = 5
        rect = QRectF(m, m, self.width() - 2 * m, self.height() - 2 * m)
        pen_bg = QPen(QColor(Theme.BORDER), 4)
        pen_bg.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen_bg)
        p.drawArc(rect, 0, 360 * 16)
        pen = QPen(QColor(self._color), 4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawArc(rect, -self._angle * 16, 100 * 16)
        p.end()


class LoadingOverlay(QWidget):
    """Full-window overlay. Call show_loading() then finish(on_done)."""

    def __init__(self, parent=None, message: str = "Loading network data…"):
        super().__init__(parent)
        # Opaque app-colored background so nothing shows through.
        self.setStyleSheet(f"background: {Theme.BG_APP};")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.setSpacing(22)

        # Logo
        logo = QLabel()
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pm = QPixmap(LOGO_PATH)
        if not pm.isNull():
            logo.setPixmap(pm.scaled(
                96, 96, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
        logo.setStyleSheet("background: transparent;")
        lay.addWidget(logo, alignment=Qt.AlignmentFlag.AlignCenter)

        # Wordmark
        name = QLabel("NETWER")
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name.setStyleSheet(
            f"color: {Theme.TEXT_PRIMARY}; font-family: '{Theme.FONT_FAMILY}';"
            f"font-size: 26px; font-weight: 600; letter-spacing: 8px;"
            f"background: transparent;"
        )
        lay.addWidget(name, alignment=Qt.AlignmentFlag.AlignCenter)

        # Spinner
        self._spinner = _Spinner(Theme.ACCENT, 44)
        lay.addWidget(self._spinner, alignment=Qt.AlignmentFlag.AlignCenter)

        # Status line
        self._sub = QLabel(message)
        self._sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._sub.setStyleSheet(
            f"color: {Theme.TEXT_MUTED}; font-family: '{Theme.FONT_FAMILY}';"
            f"font-size: {Theme.FONT_SIZE_BODY}px; background: transparent;"
        )
        lay.addWidget(self._sub, alignment=Qt.AlignmentFlag.AlignCenter)

        self._fade = None

    def set_progress(self, text: str) -> None:
        self._sub.setText(text)

    def show_loading(self) -> None:
        self.setGraphicsEffect(None)
        self.show()
        self.raise_()
        self._spinner.start()

    def finish(self, on_done=None) -> None:
        self._spinner.stop()
        effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity")
        anim.setDuration(Theme.ANIM_SLOW)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        def _cleanup():
            self.hide()
            self.setGraphicsEffect(None)
            if on_done:
                on_done()

        anim.finished.connect(_cleanup)
        anim.start()
        self._fade = anim
