"""
NETWER — MainWindow.

Main application window ("skeleton"):
  - holds Sidebar (left) + stacked pages (right)
  - shows a FULL-WINDOW loading overlay on startup (over everything,
    sidebar included); when the first page signals it's ready, the
    overlay fades out revealing the populated app at once
  - handles navigation lifecycle (on_leave / on_enter) + fade transitions
"""

from PyQt6.QtCore import Qt, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QStackedWidget, QGraphicsOpacityEffect
)

from app.theme import Theme
from app.resources import LOGO_PATH
from ui.components.sidebar import Sidebar
from ui.pages.base_page import BasePage
from ui.widgets.loading_overlay import LoadingOverlay


class MainWindow(QMainWindow):
    def __init__(self, core):
        super().__init__()
        self.core = core
        self.setWindowTitle("NETWER — Network Diagnostic Suite")
        self.setWindowIcon(QIcon(LOGO_PATH))
        self.resize(1400, 860)
        self.setMinimumSize(1100, 700)
        self.setStyleSheet(f"background: {Theme.BG_APP};")

        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.sidebar = Sidebar()
        self.sidebar.navigate.connect(self._navigate)
        root.addWidget(self.sidebar)

        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)

        self._pages: dict[str, BasePage] = {}
        self._current_key: str | None = None
        self._fade_anim: QPropertyAnimation | None = None

        # Full-window loading overlay (child of the window, covers all).
        self._overlay = LoadingOverlay(self, message="Starting up…")
        self._overlay.hide()
        self._loading_active = False

    # ── Loading overlay covers the whole window ────────────────
    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._overlay is not None:
            self._overlay.setGeometry(self.rect())

    def begin_loading(self) -> None:
        """Show the full-window loading screen."""
        self._loading_active = True
        self._overlay.setGeometry(self.rect())
        self._overlay.show_loading()

    def loading_progress(self, text: str) -> None:
        self._overlay.set_progress(text)

    def end_loading(self) -> None:
        """Fade out the loading screen, revealing the populated app."""
        if not self._loading_active:
            return
        self._loading_active = False
        self._overlay.finish()

    # ── Page registration ──────────────────────────────────────
    def register_page(self, key: str, icon_name: str, page: BasePage,
                      subtitle: str = "") -> None:
        self._pages[key] = page
        self.stack.addWidget(page)
        self.sidebar.add_item(key, icon_name, page.PAGE_TITLE, subtitle)
        # Let the page talk back to the window for loading coordination.
        page.set_window(self)

    def register_section(self, label: str) -> None:
        """Dodaj naslov sekcije u sidebar prije sljedećih stranica."""
        self.sidebar.add_section(label)

    def finalize_sidebar(self) -> None:
        self.sidebar.add_stretch_and_status()

    def start(self, first_key: str) -> None:
        self.sidebar.set_active(first_key)
        self._navigate(first_key)

    # ── Navigation ─────────────────────────────────────────────
    def _navigate(self, key: str) -> None:
        if key not in self._pages or key == self._current_key:
            return
        if self._current_key is not None:
            self._pages[self._current_key].on_leave()
        new_page = self._pages[key]
        self.stack.setCurrentWidget(new_page)
        self._current_key = key
        new_page.on_enter()
        # Only fade the page if we're not in the startup loading screen
        if not self._loading_active:
            self._fade_in(new_page)
        # Keep overlay on top if still loading
        if self._loading_active:
            self._overlay.raise_()

    def goto(self, key: str) -> None:
        """Public navigation used by cross-page actions (e.g. Ping Sweep
        jumping to the Port Scanner). Updates the sidebar highlight too."""
        if key in self._pages:
            self.sidebar.set_active(key)
            self._navigate(key)

    def scan_ports_for(self, ip: str) -> None:
        """Jump to the Port Scanner pre-targeted at ip and start scanning."""
        page = self._pages.get("port_scanner")
        if page is None:
            return
        self.goto("port_scanner")
        if hasattr(page, "set_target"):
            page.set_target(ip, autostart=True)

    def _fade_in(self, widget: QWidget) -> None:
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity")
        anim.setDuration(Theme.ANIM_NORMAL)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(lambda: widget.setGraphicsEffect(None))
        anim.start()
        self._fade_anim = anim

    def closeEvent(self, event):
        if self._current_key is not None:
            self._pages[self._current_key].on_leave()
        super().closeEvent(event)
