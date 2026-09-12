"""
NETWER — RecentActivity widget.

Shows the most recent actions the user performed (scans, tests, reports),
each with a status icon, title, detail line and relative timestamp. Reads
from the app-wide activity log and refreshes itself whenever it changes.
"""

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QFrame
)

from app.theme import Theme
from app.resources import Icons
from app.activity import activity, time_ago


_KIND_ICON = {
    "success": ("check", Theme.SUCCESS),
    "warning": ("warning", Theme.WARNING),
    "error": ("error", Theme.DANGER),
    "info": ("check", Theme.ACCENT),
}


class RecentActivity(QWidget):
    def __init__(self, limit: int = 6, parent=None):
        super().__init__(parent)
        self._limit = limit
        self.setStyleSheet("background: transparent;")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent; border: none;")
        holder = QWidget()
        holder.setStyleSheet("background: transparent;")
        self._list = QVBoxLayout(holder)
        self._list.setContentsMargins(0, 0, 0, 0)
        self._list.setSpacing(2)
        self._list.addStretch()
        scroll.setWidget(holder)
        outer.addWidget(scroll)

        activity.changed.connect(self.refresh)

        # Refresh the relative timestamps periodically ("2m ago" → "3m ago")
        self._tick = QTimer(self)
        self._tick.setInterval(30000)
        self._tick.timeout.connect(self.refresh)
        self._tick.start()

        # refresh() builds either the rows or the empty-state label, so we
        # don't keep a permanent placeholder around — an earlier version did,
        # and it stayed visible under the list once entries appeared.
        self.refresh()

    def refresh(self):
        # Remove every row (the trailing stretch is the last item and stays).
        # setParent(None) detaches immediately; deleteLater() alone would let
        # the old widget linger visibly until Qt's event loop got round to it.
        while self._list.count() > 1:
            item = self._list.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()

        entries = activity.entries(self._limit)
        if not entries:
            empty = QLabel("No activity yet")
            empty.setStyleSheet(
                f"color: {Theme.TEXT_MUTED}; font-size: {Theme.FONT_SIZE_SMALL}px;"
                f"background: transparent; padding: 6px 0;"
            )
            self._list.insertWidget(0, empty)
            return

        for i, e in enumerate(entries):
            self._list.insertWidget(i, self._row(e))

    def _row(self, entry: dict) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 5, 0, 5)
        row.setSpacing(9)

        icon_name, color = _KIND_ICON.get(entry.get("kind", "success"),
                                          _KIND_ICON["success"])
        icon = QLabel()
        icon.setPixmap(Icons.pixmap(icon_name, 14, color))
        icon.setStyleSheet("background: transparent;")
        icon.setAlignment(Qt.AlignmentFlag.AlignTop)
        row.addWidget(icon)

        text_box = QVBoxLayout()
        text_box.setSpacing(1)
        title = QLabel(entry.get("title", ""))
        title.setStyleSheet(
            f"color: {Theme.TEXT_BODY}; font-family: {Theme.FONT_FAMILY};"
            f"font-size: {Theme.FONT_SIZE_SMALL}px; background: transparent;"
        )
        text_box.addWidget(title)

        detail = entry.get("detail", "")
        if detail:
            d = QLabel(detail)
            d.setStyleSheet(
                f"color: {Theme.TEXT_MUTED}; font-family: {Theme.FONT_MONO};"
                f"font-size: {Theme.FONT_SIZE_TINY}px; background: transparent;"
            )
            text_box.addWidget(d)
        row.addLayout(text_box, 1)

        ts = QLabel(time_ago(entry.get("time", 0)))
        ts.setStyleSheet(
            f"color: {Theme.TEXT_FAINT}; font-size: {Theme.FONT_SIZE_TINY}px;"
            f"background: transparent;"
        )
        ts.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)
        row.addWidget(ts)

        return w
