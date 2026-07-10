"""
NETWER — InfoTable widget.

A compact two-column key/value table for detailed information pages
(Network Information, System Information). Rows alternate subtly for
readability; values use the mono/data font depending on content type.
Supports copying the whole table to clipboard as text.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QWidget
)

from app.theme import Theme


class InfoTable(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("InfoTable")
        self.setStyleSheet(
            f"#InfoTable {{ background: transparent; border: none; }}"
        )
        self._rows = []  # list of (key, value) for copy/export
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(0)

    def clear(self):
        while self._lay.count():
            item = self._lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._rows = []

    def add_row(self, key: str, value: str, mono: bool = False,
                value_color: str = None):
        idx = len(self._rows)
        self._rows.append((key, value))

        row = QWidget()
        bg = Theme.BG_CARD if idx % 2 == 0 else Theme.BG_CARD_HOVER
        row.setStyleSheet(f"background: {bg}; border: none;")
        h = QHBoxLayout(row)
        h.setContentsMargins(14, 9, 14, 9)
        h.setSpacing(12)

        k = QLabel(key)
        k.setStyleSheet(
            f"color: {Theme.TEXT_SECONDARY}; font-family: '{Theme.FONT_FAMILY}';"
            f"font-size: {Theme.FONT_SIZE_SMALL}px; background: transparent;"
        )
        k.setMinimumWidth(150)
        h.addWidget(k)

        font = Theme.FONT_MONO if mono else Theme.FONT_DATA
        v = QLabel(str(value) if value not in (None, "") else "\u2014")
        v.setStyleSheet(
            f"color: {value_color or Theme.TEXT_BODY}; font-family: '{font}';"
            f"font-size: {Theme.FONT_SIZE_SMALL}px; background: transparent;"
        )
        v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        v.setWordWrap(True)
        h.addWidget(v, 1)

        self._lay.addWidget(row)

    def add_section(self, title: str):
        """A subtle section header row."""
        self._rows.append((f"--- {title} ---", ""))
        lbl = QLabel(title)
        lbl.setStyleSheet(
            f"color: {Theme.ACCENT}; font-family: '{Theme.FONT_FAMILY}';"
            f"font-size: {Theme.FONT_SIZE_TINY}px; font-weight: 600;"
            f"background: transparent; padding: 10px 14px 4px 14px;"
            f"text-transform: uppercase; letter-spacing: 1px;"
        )
        self._lay.addWidget(lbl)

    def to_text(self) -> str:
        """Render the table as plain text for clipboard/export."""
        lines = []
        for key, value in self._rows:
            if key.startswith("---"):
                lines.append("")
                lines.append(key.strip("- "))
            else:
                lines.append(f"{key:<20} {value}")
        return "\n".join(lines)
