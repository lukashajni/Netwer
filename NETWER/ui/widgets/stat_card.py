"""
NETWER — StatCard widget.

Kartica za jednu kljucnu vrijednost (Internet Status, Download, Upload,
Packet Loss, Uptime — gornji red dashboarda). Ikona je prava (qtawesome).
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel

from app.theme import Theme
from app.resources import Icons


class StatCard(QFrame):
    def __init__(self, icon_name: str, label: str, parent=None):
        super().__init__(parent)
        self.setObjectName("StatCard")
        self.setStyleSheet(
            f"#StatCard {{ background: {Theme.BG_CARD};"
            f"border: 1px solid {Theme.BORDER};"
            f"border-radius: {Theme.RADIUS_CARD}px; }}"
            f"#StatCard QLabel {{ background: transparent; border: none; }}"
        )

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
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

    def set_value(self, value: str, unit: str = "", color: str | None = None,
                  subtitle: str = "") -> None:
        col = color or Theme.TEXT_PRIMARY
        if unit:
            self._value.setText(
                f"<span style='color:{col}; font-size:18px; font-weight:600;'>{value}</span>"
                f" <span style='color:{Theme.TEXT_MUTED}; font-size:11px;'>{unit}</span>"
            )
        else:
            self._value.setText(
                f"<span style='color:{col}; font-size:18px; font-weight:600;'>{value}</span>"
            )
        self._sub.setText(subtitle)

    def set_loading(self) -> None:
        self._value.setText(
            f"<span style='color:{Theme.TEXT_MUTED}; font-size:14px;'>u\u010ditavam\u2026</span>"
        )
        self._sub.setText("")
