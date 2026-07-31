"""
NETWER — HostInput widget.

A QLineEdit for entering a host/IP, augmented with:
  • a history dropdown (recent + favorited hosts, from the persistent store)
  • a star toggle to favorite/unfavorite the current host

Drop-in replacement for the plain QLineEdit used on the scan pages. Emits
`submitted` when the user presses Enter, and exposes text()/setText() so the
existing page code keeps working.

    inp = HostInput(kind="ping", placeholder="IP or hostname")
    inp.submitted.connect(self._start)
    inp.text()          # current value
    inp.remember()      # call after a successful scan to add to history
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QLineEdit, QPushButton, QMenu
)
from PyQt6.QtGui import QAction

from app.theme import Theme
from app.resources import Icons
from app.store import store


class HostInput(QWidget):
    submitted = pyqtSignal()

    def __init__(self, kind="ping", placeholder="Host or IP", parent=None):
        super().__init__(parent)
        self._kind = kind

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self._edit = QLineEdit()
        self._edit.setPlaceholderText(placeholder)
        self._edit.setStyleSheet(
            f"QLineEdit {{ background: {Theme.GLASS_INPUT}; color: {Theme.TEXT_BODY};"
            f"border: 1px solid {Theme.BORDER_STRONG}; border-radius: 8px;"
            f"padding: 9px 12px; font-family: {Theme.FONT_MONO};"
            f"font-size: {Theme.FONT_SIZE_BODY}px; }}"
            f"QLineEdit:focus {{ border-color: {Theme.GLASS_BORDER_HI}; }}")
        self._edit.returnPressed.connect(self._on_submit)
        self._edit.textChanged.connect(lambda _=None: self._refresh_star())
        lay.addWidget(self._edit, 1)

        # History dropdown
        self._history_btn = QPushButton()
        self._history_btn.setIcon(Icons.get("history", Theme.TEXT_SECONDARY))
        self._history_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._history_btn.setFixedSize(38, 38)
        self._history_btn.setToolTip("Recent & favorite hosts")
        self._history_btn.setStyleSheet(self._icon_btn_style())
        self._history_btn.clicked.connect(self._show_history)
        lay.addWidget(self._history_btn)

        # Favorite star
        self._star_btn = QPushButton()
        self._star_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._star_btn.setFixedSize(38, 38)
        self._star_btn.setToolTip("Favorite this host")
        self._star_btn.setStyleSheet(self._icon_btn_style())
        self._star_btn.clicked.connect(self._toggle_favorite)
        lay.addWidget(self._star_btn)

        self._refresh_star()

    def _icon_btn_style(self):
        return (
            f"QPushButton {{ background: {Theme.BG_CARD};"
            f"border: 1px solid {Theme.BORDER}; border-radius: 8px; }}"
            f"QPushButton:hover {{ border-color: {Theme.BORDER_STRONG}; }}")

    # ── QLineEdit passthrough ──────────────────────────────────
    def text(self):
        return self._edit.text()

    def setText(self, value):
        self._edit.setText(value)

    def setPlaceholderText(self, value):
        self._edit.setPlaceholderText(value)

    def setEnabled(self, enabled):
        self._edit.setEnabled(enabled)
        self._history_btn.setEnabled(enabled)
        self._star_btn.setEnabled(enabled)

    def setFocus(self):
        self._edit.setFocus()

    @property
    def line_edit(self):
        return self._edit

    # ── Behavior ───────────────────────────────────────────────
    def _on_submit(self):
        self.submitted.emit()

    def remember(self):
        """Record the current host in recent history (call after a scan)."""
        store.add_recent_host(self.text().strip(), self._kind)

    def _show_history(self):
        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu {{ background: {Theme.BG_ELEVATED};"
            f"border: 1px solid {Theme.BORDER_STRONG}; border-radius: 8px;"
            f"padding: 4px; }}"
            f"QMenu::item {{ color: {Theme.TEXT_BODY}; padding: 6px 22px 6px 12px;"
            f"border-radius: 5px; font-size: {Theme.FONT_SIZE_SMALL}px; }}"
            f"QMenu::item:selected {{ background: {Theme.ACCENT}; color: white; }}"
            f"QMenu::separator {{ height: 1px; background: {Theme.BORDER};"
            f"margin: 4px 8px; }}")

        favs = store.favorites()
        if favs:
            header = QAction("★  Favorites", menu)
            header.setEnabled(False)
            menu.addAction(header)
            for f in favs:
                act = QAction(f"    {f['label']}", menu)
                act.triggered.connect(
                    lambda _=False, h=f["host"]: self._pick(h))
                menu.addAction(act)
            menu.addSeparator()

        recents = store.recent_hosts()
        if recents:
            header = QAction("Recent", menu)
            header.setEnabled(False)
            menu.addAction(header)
            for r in recents:
                act = QAction(f"    {r['host']}", menu)
                act.triggered.connect(
                    lambda _=False, h=r["host"]: self._pick(h))
                menu.addAction(act)

        if not favs and not recents:
            empty = QAction("No history yet", menu)
            empty.setEnabled(False)
            menu.addAction(empty)

        menu.exec(self._history_btn.mapToGlobal(
            self._history_btn.rect().bottomLeft()))

    def _pick(self, host):
        self._edit.setText(host)
        self._refresh_star()

    def _toggle_favorite(self):
        host = self.text().strip()
        if not host:
            return
        if store.is_favorite(host):
            store.remove_favorite(host)
        else:
            store.add_favorite(host)
        self._refresh_star()

    def _refresh_star(self):
        host = self.text().strip()
        is_fav = bool(host) and store.is_favorite(host)
        color = Theme.WARNING if is_fav else Theme.TEXT_FAINT
        icon = "star_filled" if is_fav else "star"
        self._star_btn.setIcon(Icons.get(icon, color))
        self._star_btn.setToolTip(
            "Remove from favorites" if is_fav else "Favorite this host")
