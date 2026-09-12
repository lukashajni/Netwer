"""
NETWER — Activity history dialog.

Full-history view behind the dashboard's "View All" button. Shows every
recorded action (the card only shows the latest few), with a Clear button.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
)

from app.theme import Theme
from app.activity import activity
from ui.widgets.recent_activity import RecentActivity


class ActivityDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Activity History")
        self.setMinimumSize(520, 440)
        self.setStyleSheet(f"background: {Theme.BG_APP};")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel("Activity History")
        title.setStyleSheet(
            f"color: {Theme.TEXT_PRIMARY}; font-family: {Theme.FONT_FAMILY};"
            f"font-size: 17px; font-weight: 600; background: transparent;")
        header.addWidget(title)
        header.addStretch()

        self.btn_clear = QPushButton("Clear")
        self.btn_clear.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_clear.setStyleSheet(
            f"QPushButton {{ background: {Theme.BG_ELEVATED}; color: {Theme.TEXT_SECONDARY};"
            f"border: 1px solid {Theme.BORDER_STRONG}; border-radius: 6px;"
            f"padding: 5px 14px; font-size: {Theme.FONT_SIZE_SMALL}px; }}"
            f"QPushButton:hover {{ border-color: {Theme.DANGER}; color: {Theme.DANGER}; }}")
        self.btn_clear.clicked.connect(activity.clear)
        header.addWidget(self.btn_clear)
        lay.addLayout(header)

        # Full list (no limit)
        self._list = RecentActivity(limit=None)
        self._list.setStyleSheet(
            f"background: {Theme.BG_CARD}; border: 1px solid {Theme.BORDER};"
            f"border-radius: {Theme.RADIUS_CARD}px;")
        lay.addWidget(self._list, 1)

        close = QPushButton("Close")
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setStyleSheet(
            f"QPushButton {{ background: {Theme.GRAD_ACCENT}; color: white; border: none;"
            f"border-radius: 6px; padding: 8px 20px;"
            f"font-size: {Theme.FONT_SIZE_SMALL}px; font-weight: 600; }}"
            f"QPushButton:hover {{ background: {Theme.ACCENT_PURPLE}; }}")
        close.clicked.connect(self.accept)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(close)
        lay.addLayout(btn_row)
