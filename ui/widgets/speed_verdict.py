from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout

from app.resources import Icons
from app.theme import Theme
from core import speed_rating
from ui.widgets.card import Card

ICONS = {"web": "internet", "stream": "film", "calls": "video", "gaming": "gamepad",
         "download": "download", "cloud": "cloud_up"}
LEVEL_COLOR = ("DANGER", "WARNING", "ACCENT", "SUCCESS")


class _Tile(QFrame):
    def __init__(self, item):
        super().__init__()
        color = getattr(Theme, LEVEL_COLOR[item["level"]])
        self.setObjectName("VTile")
        self.setStyleSheet(f"#VTile {{ background: {Theme.GLASS_INPUT}; border: 1px solid {Theme.GLASS_BORDER};"
                           f"border-radius: 12px; }} #VTile QLabel {{ background: transparent; border: none; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(6)
        top = QHBoxLayout()
        top.setSpacing(10)
        icon = QLabel()
        icon.setPixmap(Icons.pixmap(ICONS[item["key"]], 18, color))
        top.addWidget(icon)
        title = QLabel(item["title"])
        title.setStyleSheet(f"color: {Theme.TEXT_PRIMARY}; font-size: {Theme.FONT_SIZE_BODY}px; font-weight: 600;")
        top.addWidget(title, 1)
        chip = QLabel(item["rating"])
        chip.setStyleSheet(f"color: {color}; font-size: {Theme.FONT_SIZE_TINY}px; font-weight: 700;"
                           f"border: 1px solid {color}; border-radius: 9px; padding: 2px 10px;")
        top.addWidget(chip)
        lay.addLayout(top)
        detail = QLabel(item["detail"])
        detail.setWordWrap(True)
        detail.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-size: {Theme.FONT_SIZE_SMALL}px;")
        lay.addWidget(detail)


class ConnectionVerdict(Card):
    """What the measured speed is good for: browsing, streaming, calls, gaming..."""

    def __init__(self, parent=None):
        super().__init__("What this connection is good for", "speedtest", parent)
        self._summary = QLabel("")
        self._summary.setWordWrap(True)
        self._summary.setStyleSheet(f"color: {Theme.TEXT_BODY}; font-size: {Theme.FONT_SIZE_BODY}px;")
        self.content_layout.addWidget(self._summary)
        self._grid_host = QFrame()
        self._grid_host.setStyleSheet("background: transparent;")
        self._grid = QGridLayout(self._grid_host)
        self._grid.setContentsMargins(0, 4, 0, 0)
        self._grid.setSpacing(10)
        self.content_layout.addWidget(self._grid_host)
        note = QLabel("Based on this test's download, upload, ping and jitter. Rules of thumb, not a guarantee.")
        note.setStyleSheet(f"color: {Theme.TEXT_FAINT}; font-size: {Theme.FONT_SIZE_TINY}px;")
        self.content_layout.addWidget(note)
        self.hide()

    def clear(self):
        self.hide()

    def set_result(self, dl, ul, ping, jitter=None, loss=None):
        while self._grid.count():
            w = self._grid.takeAt(0).widget()
            if w is not None:
                w.setParent(None)
        items = speed_rating.rate(dl, ul, ping, jitter, loss)
        self._summary.setText(speed_rating.summary(items))
        for i, item in enumerate(items):
            self._grid.addWidget(_Tile(item), i // 3, i % 3)
        for c in range(3):
            self._grid.setColumnStretch(c, 1)
        self.show()
