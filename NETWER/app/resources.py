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
        "ping_sweep": "mdi.radar",
        "port_scanner": "fa6s.plug",
        "dns": "fa6s.magnifying-glass",
        "dns_tools": "fa6s.signs-post",
        "reverse_dns": "fa6s.right-left",
        "traceroute": "fa6s.route",
        "monitor": "fa6s.chart-line",
        "speedtest": "fa6s.gauge-high",
        "report": "fa6s.file-lines",
        "settings": "fa6s.gear",
        "moon": "fa6s.moon",
        "sun": "fa6s.sun",
        "bell": "fa6s.bell",
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
        "checkmark": "fa6s.check",
        "warning": "fa6s.triangle-exclamation",
        "error": "fa6s.circle-xmark",
        "globe": "fa6s.globe",
        "copy": "fa6s.copy",
        "history": "fa6s.clock-rotate-left",
        "star": "fa6s.star",
        "power": "fa6s.power-off",
        "star_filled": "fa6s.star",
        "export": "fa6s.file-export",
        "refresh": "fa6s.rotate",
        "close": "fa6s.xmark",
        "notif_success": "fa6s.circle-check",
        "notif_warning": "fa6s.triangle-exclamation",
        "notif_error": "fa6s.circle-exclamation",
        "notif_info": "fa6s.circle-info",
        "save": "fa6s.floppy-disk",
        "github": "fa6b.github",
        "play": "fa6s.play",
        "stop": "fa6s.stop",
        "route": "fa6s.route",
        "list": "fa6s.list-ul",
        "terminal": "fa6s.terminal",
        # Device types (for Network Map)
        "dev_pc": "fa6s.desktop",
        "dev_laptop": "fa6s.laptop",
        "dev_phone": "fa6s.mobile-screen",
        "dev_tv": "mdi.television",
        "dev_nas": "fa6s.hard-drive",
        "dev_printer": "fa6s.print",
        "dev_router": "mdi.router-wireless",
        "dev_console": "fa6s.gamepad",
        "dev_iot": "fa6s.lightbulb",
        "dev_camera": "mdi.cctv",
        "dev_speaker": "fa6s.volume-high",
        "dev_watch": "mdi.watch",
        "dev_tablet": "fa6s.tablet-screen-button",
        "dev_generic": "fa6s.microchip",
        # Aliases used by detect_device_type() keys.
        "dev_computer": "fa6s.desktop",
        "dev_media": "fa6s.photo-film",
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

    #: Cache za PNG-ove ikona koje QSS koristi kao image: url(...).
    _png_cache = {}

    @classmethod
    def png_path(cls, name: str, size: int = 16, color: str = "#ffffff") -> str:
        """Renderiraj ikonu u PNG na disk i vrati putanju (s file-URL slash
        formatom). Potrebno jer Qt stylesheet ne može crtati qtawesome ikonu
        izravno — treba mu image: url(putanja). Rezultat se kešira."""
        key = (name, size, color)
        if key in cls._png_cache and os.path.isfile(cls._png_cache[key]):
            return cls._png_cache[key]
        import tempfile
        pm = cls.pixmap(name, size, color)
        out_dir = os.path.join(tempfile.gettempdir(), "netwer_icons")
        os.makedirs(out_dir, exist_ok=True)
        safe = name.replace("/", "_") + f"_{size}_{color.lstrip('#')}.png"
        path = os.path.join(out_dir, safe)
        pm.save(path, "PNG")
        # QSS url() na Windowsu voli forward-slashe.
        url_path = path.replace("\\", "/")
        cls._png_cache[key] = url_path
        return url_path
