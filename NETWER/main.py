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
from ui.pages.network_info_page import NetworkInfoPage
from ui.pages.wifi_info_page import WiFiInfoPage
from ui.pages.system_info_page import SystemInfoPage
from ui.pages.report_page import ReportPage
from ui.pages.about_page import AboutPage


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
    window.register_page(
        "network", "network", NetworkInfoPage(netwer_core), subtitle="IP, MAC, Adapter"
    )
    window.register_page(
        "wifi", "wifi", WiFiInfoPage(netwer_core), subtitle="Wireless Details"
    )
    window.register_page(
        "system", "system", SystemInfoPage(netwer_core), subtitle="Hardware & OS"
    )
    window.register_page(
        "report", "report", ReportPage(netwer_core), subtitle="Export PDF"
    )
    window.register_page(
        "about", "about", AboutPage(netwer_core), subtitle="About NETWER"
    )
    # Sljedece: wifi, system, ping, ping_stability, ping_sweep,
    # port_scanner, dns, reverse_dns, traceroute, monitor, speedtest,
    # report, settings, about

    window.finalize_sidebar()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("NETWER")
    app.setOrganizationName("Lukas Hajneman")
    app.setStyleSheet(GLOBAL_QSS)

    # Provjeri kljucnu ovisnost: psutil pokrece resurse, download/upload
    # i live monitor. Bez njega te funkcije ne rade — javi jasno.
    try:
        import psutil  # noqa: F401
    except ImportError:
        from PyQt6.QtWidgets import QMessageBox
        box = QMessageBox()
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("NETWER — Missing dependency")
        box.setText("The 'psutil' library is not installed.")
        box.setInformativeText(
            "System Resources, Download/Upload speed and the Live Network "
            "Monitor need it.\n\nInstall it with:\n    pip install psutil\n\n"
            "The app will still open, but those features will be empty."
        )
        box.exec()

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
