"""
NETWER — Ulazna tocka aplikacije.

Pokreni s:  python main.py

Ovdje se:
  1. kreira QApplication
  2. postavi globalni stil (font + reset Qt defaulta koji kvare tamnu temu)
  3. instancira backend (netwer_core)
  4. sklopi MainWindow i registriraju stranice
  5. pokrene event loop
"""

import sys

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFont

from app.theme import Theme
from core import netwer_core
from ui.main_window import MainWindow
from ui.pages.dashboard_page import DashboardPage


# Globalni stylesheet — rjesava "crni selektirani" izgled tako sto
# eksplicitno postavlja pozadine, boje teksta i uklanja default obrube
# koje Qt crta na ugnijezdenim widgetima i scroll area.
GLOBAL_QSS = f"""
* {{
    outline: none;
    font-family: "{Theme.FONT_FAMILY}";
    color: {Theme.TEXT_BODY};
}}
QWidget {{
    background: {Theme.BG_APP};
}}
QScrollArea, QScrollArea > QWidget, QScrollArea > QWidget > QWidget {{
    background: {Theme.BG_APP};
    border: none;
}}
QScrollBar:vertical {{
    background: {Theme.BG_APP};
    width: 10px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {Theme.BORDER_STRONG};
    border-radius: 5px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: {Theme.TEXT_FAINT};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: none;
}}
QToolTip {{
    background: {Theme.BG_ELEVATED};
    color: {Theme.TEXT_BODY};
    border: 1px solid {Theme.BORDER_STRONG};
    border-radius: 4px;
    padding: 4px 8px;
}}
"""


def _register_pages(window: MainWindow) -> None:
    """Registriraj sve stranice. Zasad samo Dashboard; ostale dolaze
    jedna po jedna. Prvi argument je nas naziv ikone iz Icons registra."""
    window.register_page(
        "dashboard", "dashboard", DashboardPage(netwer_core), subtitle="Dashboard"
    )
    # Sljedece: network, wifi, system, ping, ping_stability, ping_sweep,
    # port_scanner, dns, reverse_dns, traceroute, monitor, speedtest,
    # report, settings, about

    window.finalize_sidebar()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("NETWER")
    app.setOrganizationName("Lukas Hajneman")
    app.setStyleSheet(GLOBAL_QSS)

    # Font stack: Segoe UI Variable (Win11) -> Segoe UI -> fallback
    font = QFont(Theme.FONT_FAMILY, 10)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(font)

    window = MainWindow(netwer_core)
    _register_pages(window)
    window.start("dashboard")
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
