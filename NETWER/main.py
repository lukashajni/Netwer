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
from ui.pages.health_page import HealthPage
from ui.pages.ping_page import PingPage
from ui.pages.ping_sweep_page import PingSweepPage
from ui.pages.port_scanner_page import PortScannerPage
from ui.pages.dns_tools_page import DnsToolsPage
from ui.pages.speedtest_page import SpeedTestPage
from ui.pages.system_info_page import SystemInfoPage
from ui.pages.report_page import ReportPage
from ui.pages.about_page import AboutPage


# Globalni stylesheet — rjesava "crni selektirani" izgled tako sto
# eksplicitno postavlja pozadine, boje teksta i uklanja default obrube
# koje Qt crta na ugnijezdenim widgetima i scroll area.
def build_global_qss():
    """Sagradi globalni stylesheet iz TRENUTNIH Theme boja. Poziva se pri
    pokretanju i ponovno kad korisnik promijeni temu."""
    # Suptilni gradijenti (glow) u pozadini cijelog prozora — plavi, ljubičasti
    # i tirkizni, kao u dizajn previewu. Qt nema pravi backdrop-blur, pa se
    # "glass" postiže gradijentnom pozadinom + poluprozirnim karticama.
    app_gradient = (
        f"qlineargradient(x1:0, y1:0, x2:1, y2:1, "
        f"stop:0 {Theme.BG_SIDEBAR}, stop:0.5 {Theme.BG_APP}, "
        f"stop:1 {Theme.BG_SIDEBAR})"
    )
    return f"""
* {{
    outline: none;
    font-family: {Theme.FONT_FAMILY};
    color: {Theme.TEXT_BODY};
}}
QMainWindow, #AppRoot {{
    background: {app_gradient};
}}
QWidget {{
    background: transparent;
}}
QScrollArea, QScrollArea > QWidget, QScrollArea > QWidget > QWidget {{
    background: transparent;
    border: none;
}}
QScrollBar:vertical {{
    background: transparent;
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
    border: 1px solid {Theme.GLASS_BORDER_HI};
    border-radius: 6px;
    padding: 5px 9px;
}}
"""


# Zadržano radi kompatibilnosti (neki testovi importaju GLOBAL_QSS).
GLOBAL_QSS = build_global_qss()


def _register_pages(window: MainWindow) -> None:
    """Registriraj sve stranice. Zasad samo Dashboard; ostale dolaze
    jedna po jedna. Prvi argument je nas naziv ikone iz Icons registra."""
    window.register_section("Overview")
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
    window.register_section("Diagnostics")
    window.register_page(
        "health", "resources", HealthPage(netwer_core),
        subtitle="Diagnose problems"
    )
    window.register_page(
        "ping", "ping", PingPage(netwer_core), subtitle="Test Connectivity"
    )
    window.register_page(
        "ping_sweep", "ping_sweep", PingSweepPage(netwer_core),
        subtitle="Discover Devices"
    )
    window.register_page(
        "port_scanner", "port_scanner", PortScannerPage(netwer_core),
        subtitle="Open & Filtered Ports"
    )
    window.register_page(
        "dns_tools", "dns_tools", DnsToolsPage(netwer_core),
        subtitle="DNS, Reverse DNS, Traceroute"
    )
    window.register_page(
        "speedtest", "speedtest", SpeedTestPage(netwer_core),
        subtitle="Bandwidth Test"
    )
    window.register_section("More")
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

    # Load the user's saved theme/accent before building any styles.
    from app.theme import apply_theme, apply_accent, Theme
    from app.store import store
    saved_theme = store.get_setting("theme", "Dark Blue")
    saved_accent = store.get_setting("accent", "Default")
    apply_theme(saved_theme, saved_accent)
    Theme.GLASS_ENABLED = store.get_setting("glass_enabled", True)

    app.setStyleSheet(build_global_qss())

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

    # Font stack: Segoe UI Variable (Win11) -> Segoe UI (Win10) -> sans.
    # Registriramo fallback lanac tako da Qt zna čime zamijeniti primarni
    # font ako ga OS nema (npr. Windows 10, Linux). Bez ovoga bi na tim
    # sustavima tekst pao na ružni Qt default i vidljivost bi patila.
    QFont.insertSubstitutions(Theme.FONT_FAMILY_PRIMARY, [
        "Segoe UI Variable", "Segoe UI", "Inter", "Helvetica Neue",
        "Arial", "sans-serif",
    ])
    QFont.insertSubstitutions(Theme.FONT_MONO_PRIMARY, [
        "Cascadia Mono", "Consolas", "JetBrains Mono",
        "DejaVu Sans Mono", "monospace",
    ])
    font = QFont(Theme.FONT_FAMILY_PRIMARY, 10)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(font)

    window = MainWindow(netwer_core)
    _register_pages(window)
    window.start("dashboard")
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
