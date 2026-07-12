"""
NETWER — StatCard widget.

Card for one key metric (Internet Status, Download, Upload, Packet Loss,
Uptime — the dashboard's top row). Real qtawesome icon, modern data font,
and an optional sparkline (mini trend chart) at the bottom like the mockup.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel, QWidget

from app.theme import Theme
from app.resources import Icons
from ui.widgets.sparkline import Sparkline


class StatCard(QFrame):
    def __init__(self, icon_name: str, label: str, spark_color: str = None,
                 parent=None):
        super().__init__(parent)
        self.setObjectName("StatCard")
        self.setStyleSheet(
            f"#StatCard {{ background: {Theme.BG_CARD};"
            f"border: 1px solid {Theme.BORDER};"
            f"border-radius: {Theme.RADIUS_CARD}px; }}"
            f"#StatCard QLabel {{ background: transparent; border: none; }}"
        )

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 10)
        lay.setSpacing(4)

        top = QHBoxLayout()
        top.setSpacing(7)
        self._icon = QLabel()
        self._icon.setPixmap(Icons.pixmap(icon_name, 14, Theme.TEXT_SECONDARY))
        top.addWidget(self._icon)
        lbl = QLabel(label)
        lbl.setStyleSheet(
            f"color: {Theme.TEXT_SECONDARY}; font-size: {Theme.FONT_SIZE_TINY}px;"
        )
        top.addWidget(lbl)
        top.addStretch()
        lay.addLayout(top)

        self._value = QLabel("\u2014")
        self._value.setStyleSheet(
            f"color: {Theme.TEXT_PRIMARY}; font-size: 18px; font-weight: 600;"
        )
        lay.addWidget(self._value)

        self._sub = QLabel("")
        self._sub.setStyleSheet(
            f"color: {Theme.TEXT_FAINT}; font-size: {Theme.FONT_SIZE_TINY}px;"
        )
        lay.addWidget(self._sub)

        # Sparkline at the bottom. Cards WITHOUT one still reserve the same
        # vertical space, so the header/value text lines up across every card
        # in the row (otherwise a no-sparkline card sits lower than the rest).
        self.spark = None
        if spark_color:
            self.spark = Sparkline(spark_color)
            lay.addWidget(self.spark)
        else:
            filler = QWidget()
            filler.setFixedHeight(Sparkline.HEIGHT)
            filler.setStyleSheet("background: transparent;")
            lay.addWidget(filler)

    def set_value(self, value: str, unit: str = "", color: str | None = None,
                  subtitle: str = "") -> None:
        col = color or Theme.TEXT_PRIMARY
        if unit:
            self._value.setText(
                f"<span style='color:{col}; font-family:\"{Theme.FONT_DATA}\"; font-size:18px; font-weight:600;'>{value}</span>"
                f" <span style='color:{Theme.TEXT_MUTED}; font-size:11px;'>{unit}</span>"
            )
        else:
            self._value.setText(
                f"<span style='color:{col}; font-family:\"{Theme.FONT_DATA}\"; font-size:18px; font-weight:600;'>{value}</span>"
            )
        self._sub.setText(subtitle)

    def push_spark(self, value: float) -> None:
        """Add a point to the sparkline (if this card has one)."""
        if self.spark is not None:
            self.spark.push(value)
