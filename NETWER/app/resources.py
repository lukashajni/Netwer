"""
NETWER — Ikone (centralni registar).

Sve ikone aplikacije definirane su ovdje, kao što su boje u theme.py.
Koristimo qtawesome (Font Awesome 6) — prave vektorske ikone koje se
boje kroz temu i skaliraju bez gubitka kvalitete.

Korištenje:
    from app.resources import Icons
    label.setPixmap(Icons.pixmap("dashboard", 16, Theme.ACCENT))
    button.setIcon(Icons.get("wifi", Theme.TEXT_SECONDARY))

Nazivi ikona su naši (npr. "dashboard"), a mapiraju se na Font Awesome
imena u _MAP. Tako ako poželimo promijeniti izgled ikone, mijenjamo na
jednom mjestu.
"""

import os

import qtawesome as qta
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtCore import Qt

from app.theme import Theme


# Korijen projekta (dvije razine iznad app/resources.py)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS_DIR = os.path.join(_PROJECT_ROOT, "assets")
LOGO_PATH = os.path.join(ASSETS_DIR, "logo", "netwer_logo.png")


def logo_pixmap(size: int = 44) -> QPixmap:
    """Ucitaj NETWER logo skaliran na zadanu velicinu (glatko)."""
    pm = QPixmap(LOGO_PATH)
    if pm.isNull():
        # Fallback na globus ikonu ako logo nije nadjen
        return Icons.get("globe", Theme.ACCENT_GLOW).pixmap(size, size)
    return pm.scaled(
        size, size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


class Icons:
    # Naš naziv → Font Awesome 6 solid naziv
    _MAP = {
        # Navigacija
        "dashboard": "fa6s.house",
        "network": "fa6s.network-wired",
        "wifi": "fa6s.wifi",
        "system": "fa6s.microchip",
        "ping": "fa6s.satellite-dish",
        "ping_stability": "fa6s.wave-square",
        "ping_sweep": "fa6s.radar",
        "port_scanner": "fa6s.plug",
        "dns": "fa6s.magnifying-glass",
        "reverse_dns": "fa6s.right-left",
        "traceroute": "fa6s.route",
        "monitor": "fa6s.chart-line",
        "speedtest": "fa6s.gauge-high",
        "report": "fa6s.file-lines",
        "settings": "fa6s.gear",
        "about": "fa6s.circle-info",
        # Dashboard kartice
        "internet": "fa6s.globe",
        "download": "fa6s.download",
        "upload": "fa6s.upload",
        "packet_loss": "fa6s.bullseye",
        "uptime": "fa6s.clock",
        "summary": "fa6s.list",
        "devices": "fa6s.laptop",
        "resources": "fa6s.server",
        # Statusi / razno
        "check": "fa6s.circle-check",
        "warning": "fa6s.triangle-exclamation",
        "error": "fa6s.circle-xmark",
        "globe": "fa6s.globe",
    }

    @classmethod
    def get(cls, name: str, color: str = None) -> QIcon:
        """Vrati QIcon za dani naziv i boju (za gumbe, akcije)."""
        fa_name = cls._MAP.get(name, "fa6s.circle")
        return qta.icon(fa_name, color=color or Theme.TEXT_SECONDARY)

    @classmethod
    def pixmap(cls, name: str, size: int = 16, color: str = None) -> QPixmap:
        """Vrati QPixmap zadane veličine (za QLabel ikone u karticama)."""
        return cls.get(name, color).pixmap(size, size)
