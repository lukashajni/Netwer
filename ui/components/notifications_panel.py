"""
NETWER — Notifications panel (slides in from the right).

Renders the global notification stream (from app.notifications) with a
type icon, title, detail and relative time per row, plus a "mark all read"
action. Subscribes to the notification center so it updates live.
"""

from datetime import datetime

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QFrame
)

from app.theme import Theme
from app.resources import Icons
from app.notifications import notifications


def _relative_time(ts):
    delta = datetime.now() - ts
    s = int(delta.total_seconds())
    if s < 60:
        return "just now"
    if s < 3600:
        return f"{s // 60}m ago"
    if s < 86400:
        return f"{s // 3600}h ago"
    return f"{s // 86400}d ago"


_KIND_ICON = {
    "success": ("notif_success", "SUCCESS"),
    "warning": ("notif_warning", "WARNING"),
    "error": ("notif_error", "DANGER"),
    "info": ("notif_info", "ACCENT"),
}


class NotificationsPanel(QWidget):
    closed = pyqtSignal()
    WIDTH = 340

    def __init__(self, parent=None):
        super().__init__(parent)
        # Start collapsed, main_window animates maximumWidth 0 <-> WIDTH.
        self.setMinimumWidth(0)
        self.setMaximumWidth(0)
        self._build()
        self.refresh_theme()
        notifications.subscribe(self.refresh_list)
        self.refresh_list()

    def _build(self):
        # Fixed-width inner container so content doesn't reflow mid-animation.
        shell = QHBoxLayout(self)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        inner = QWidget()
        inner.setFixedWidth(self.WIDTH)
        shell.addWidget(inner)

        outer = QVBoxLayout(inner)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QHBoxLayout()
        header.setContentsMargins(18, 16, 14, 12)
        self._title = QLabel("Notifications")
        self._title.setStyleSheet(
            f"color: {Theme.TEXT_PRIMARY}; font-size: 17px; font-weight: 600;"
            f"background: transparent;")
        header.addWidget(self._title)
        header.addStretch()
        self._close_btn = QPushButton()
        self._close_btn.setIcon(Icons.get("close", Theme.TEXT_SECONDARY))
        self._close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close_btn.setFixedSize(30, 30)
        self._close_btn.clicked.connect(self.closed.emit)
        header.addWidget(self._close_btn)
        outer.addLayout(header)

        # Mark all read
        act_row = QHBoxLayout()
        act_row.setContentsMargins(18, 0, 18, 8)
        act_row.addStretch()
        self._mark_btn = QPushButton("Mark all read")
        self._mark_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mark_btn.clicked.connect(notifications.mark_all_read)
        act_row.addWidget(self._mark_btn)
        outer.addLayout(act_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._list_host = QWidget()
        self._list = QVBoxLayout(self._list_host)
        self._list.setContentsMargins(12, 0, 12, 16)
        self._list.setSpacing(4)
        self._list.addStretch()
        scroll.setWidget(self._list_host)
        outer.addWidget(scroll, 1)

    def refresh_list(self):
        # Clear the list
        while self._list.count():
            item = self._list.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        items = notifications.items()
        if not items:
            empty = QLabel("No notifications yet.")
            empty.setStyleSheet(
                f"color: {Theme.TEXT_MUTED}; font-size: {Theme.FONT_SIZE_SMALL}px;"
                f"background: transparent; padding: 20px 8px;")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._list.addWidget(empty)
        else:
            for n in items:
                self._list.addWidget(self._row(n))
        self._list.addStretch()

    def _row(self, n):
        icon_key, color_attr = _KIND_ICON.get(n.kind, ("notif_info", "ACCENT"))
        color = getattr(Theme, color_attr)

        row = QFrame()
        row.setStyleSheet(
            f"QFrame {{ background: {Theme.BG_CARD};"
            f"border-radius: 8px}}")
        rl = QHBoxLayout(row)
        rl.setContentsMargins(12, 10, 12, 10)
        rl.setSpacing(10)

        icon = QLabel()
        icon.setPixmap(Icons.pixmap(icon_key, 16, color))
        icon.setAlignment(Qt.AlignmentFlag.AlignTop)
        icon.setStyleSheet("background: transparent;")
        rl.addWidget(icon)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        title = QLabel(n.title)
        title.setWordWrap(True)
        weight = "400" if n.read else "600"
        title.setStyleSheet(
            f"color: {Theme.TEXT_BODY}; font-size: {Theme.FONT_SIZE_SMALL}px;"
            f"font-weight: {weight}; background: transparent;")
        text_col.addWidget(title)
        if n.detail:
            detail = QLabel(n.detail)
            detail.setWordWrap(True)
            detail.setStyleSheet(
                f"color: {Theme.TEXT_MUTED}; font-size: {Theme.FONT_SIZE_TINY}px;"
                f"background: transparent;")
            text_col.addWidget(detail)
        rl.addLayout(text_col, 1)

        time_lbl = QLabel(_relative_time(n.ts))
        time_lbl.setStyleSheet(
            f"color: {Theme.TEXT_FAINT}; font-size: 10px; background: transparent;")
        time_lbl.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)
        rl.addWidget(time_lbl)
        return row

    def refresh_theme(self):
        self.setObjectName("NotificationsPanel")
        self.setStyleSheet(
            f"#NotificationsPanel {{ background: {Theme.BG_SIDEBAR};"
            f"border-left: 1px solid {Theme.GLASS_BORDER_HI}; }}")
        self._title.setStyleSheet(
            f"color: {Theme.TEXT_PRIMARY}; font-size: 17px; font-weight: 600;"
            f"background: transparent;")
        self._close_btn.setIcon(Icons.get("close", Theme.TEXT_SECONDARY))
        self._close_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; border-radius: 6px; }}"
            f"QPushButton:hover {{ background: {Theme.BG_CARD_HOVER}; }}")
        self._mark_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {Theme.ACCENT};"
            f"border: none; font-size: {Theme.FONT_SIZE_SMALL}px; }}"
            f"QPushButton:hover {{ color: {Theme.ACCENT_PURPLE}; }}")
        self.refresh_list()
