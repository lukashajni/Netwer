"""
NETWER — MainWindow.

Glavni prozor aplikacije. Odgovoran je za "kostur":
  - drži Sidebar (lijevo) i QStackedWidget sa stranicama (desno)
  - registrira stranice i mapira ih na navigacijske ključeve
  - na promjenu navigacije: poziva on_leave() staroj stranici i
    on_enter() novoj (lifecycle), pa animira prijelaz (fade-in)

Stranice se registriraju kroz register_page() — dodavanje nove stranice
je jedan poziv, bez diranja postojećih. Zasad je registrirana samo
Dashboard; ostale ćemo dodavati jednu po jednu.
"""

from PyQt6.QtCore import Qt, QPropertyAnimation, QEasingCurve
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QStackedWidget, QGraphicsOpacityEffect
)

from app.theme import Theme
from ui.components.sidebar import Sidebar
from ui.pages.base_page import BasePage


class MainWindow(QMainWindow):
    def __init__(self, core):
        super().__init__()
        self.core = core
        self.setWindowTitle("NETWER — Network Diagnostic Suite")
        self.resize(1400, 860)
        self.setMinimumSize(1100, 700)
        self.setStyleSheet(f"background: {Theme.BG_APP};")

        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Sidebar ────────────────────────────────────────────
        self.sidebar = Sidebar()
        self.sidebar.navigate.connect(self._navigate)
        root.addWidget(self.sidebar)

        # ── Stog stranica ──────────────────────────────────────
        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)

        self._pages: dict[str, BasePage] = {}
        self._current_key: str | None = None
        self._fade_anim: QPropertyAnimation | None = None

    # ── Registracija stranica ──────────────────────────────────
    def register_page(self, key: str, icon_name: str, page: BasePage,
                      subtitle: str = "") -> None:
        """Dodaj stranicu u aplikaciju. icon_name je nas naziv iz Icons
        registra (npr. 'dashboard'). Jedan poziv = jedna nova stranica."""
        self._pages[key] = page
        self.stack.addWidget(page)
        self.sidebar.add_item(key, icon_name, page.PAGE_TITLE, subtitle)

    def finalize_sidebar(self) -> None:
        """Pozovi nakon registracije svih stranica — dodaje status na dno."""
        self.sidebar.add_stretch_and_status()

    def start(self, first_key: str) -> None:
        """Prikaži početnu stranicu i aktiviraj je."""
        self.sidebar.set_active(first_key)
        self._navigate(first_key)

    # ── Navigacija ─────────────────────────────────────────────
    def _navigate(self, key: str) -> None:
        if key not in self._pages or key == self._current_key:
            return

        # Lifecycle: napusti staru stranicu (gasi njene workere/tajmere)
        if self._current_key is not None:
            self._pages[self._current_key].on_leave()

        new_page = self._pages[key]
        self.stack.setCurrentWidget(new_page)
        self._current_key = key

        # Lifecycle: uđi u novu stranicu (pokreće njeno učitavanje)
        new_page.on_enter()

        self._fade_in(new_page)

    def _fade_in(self, widget: QWidget) -> None:
        """Suptilan fade-in prijelaz (≤250ms) — daje 'premium' osjećaj."""
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity")
        anim.setDuration(Theme.ANIM_NORMAL)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(lambda: widget.setGraphicsEffect(None))
        anim.start()
        self._fade_anim = anim  # zadrži referencu da ga GC ne pobere

    def closeEvent(self, event):
        """Pri zatvaranju aplikacije uredno ugasi workere trenutne stranice."""
        if self._current_key is not None:
            self._pages[self._current_key].on_leave()
        super().closeEvent(event)
