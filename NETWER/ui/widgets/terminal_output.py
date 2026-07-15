"""
NETWER — TerminalOutput widget.

A scrolling, monospace log panel that reads like a real terminal — used for
ping replies, traceroute hops and scan output. New lines append at the
bottom and the view auto-scrolls, unless the user has scrolled up to read
history (then it stays put, so output doesn't yank the view away mid-read).

Lines are colour-coded by kind: success (green), error (red), muted
(informational), plain.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QFrame
)

from app.theme import Theme


_KIND_COLOR = {
    "ok": Theme.SUCCESS,
    "error": Theme.DANGER,
    "warn": Theme.WARNING,
    "info": Theme.TEXT_MUTED,
    "plain": Theme.TEXT_SECONDARY,
}


class TerminalOutput(QWidget):
    MAX_LINES = 500

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setStyleSheet("background: transparent; border: none;")

        holder = QWidget()
        holder.setStyleSheet("background: transparent;")
        self._lines = QVBoxLayout(holder)
        self._lines.setContentsMargins(0, 0, 0, 0)
        self._lines.setSpacing(1)
        self._lines.addStretch()
        self._scroll.setWidget(holder)
        outer.addWidget(self._scroll)

        self._count = 0

    def append(self, text: str, value: str = "", kind: str = "plain") -> None:
        """Add a line. `value` is right-aligned (e.g. 'time=14ms')."""
        was_at_bottom = self._at_bottom()

        row = QWidget()
        row.setStyleSheet("background: transparent;")
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 1, 0, 1)
        h.setSpacing(8)

        color = _KIND_COLOR.get(kind, Theme.TEXT_SECONDARY)

        left = QLabel(text)
        left.setStyleSheet(
            f"color: {color if kind == 'error' else Theme.TEXT_SECONDARY};"
            f"font-family: '{Theme.FONT_MONO}';"
            f"font-size: {Theme.FONT_SIZE_TINY}px; background: transparent;")
        h.addWidget(left)
        h.addStretch()

        if value:
            right = QLabel(value)
            right.setStyleSheet(
                f"color: {color}; font-family: '{Theme.FONT_MONO}';"
                f"font-size: {Theme.FONT_SIZE_TINY}px; background: transparent;")
            h.addWidget(right)

        self._lines.insertWidget(self._lines.count() - 1, row)
        self._count += 1

        # Trim old lines so a long continuous ping doesn't grow forever
        while self._count > self.MAX_LINES:
            item = self._lines.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
            self._count -= 1

        if was_at_bottom:
            self._scroll_to_bottom()

    def clear(self) -> None:
        while self._lines.count() > 1:
            item = self._lines.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        self._count = 0

    def _at_bottom(self) -> bool:
        bar = self._scroll.verticalScrollBar()
        return bar.value() >= bar.maximum() - 4

    def _scroll_to_bottom(self) -> None:
        # Defer: the new row isn't laid out yet at the moment we append it
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, lambda: self._scroll.verticalScrollBar().setValue(
            self._scroll.verticalScrollBar().maximum()))
