"""Central registry for theme-aware application icons."""

import os

import qtawesome as qta
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon, QPixmap

from app.theme import Theme

# Project root (two levels above app/resources.py)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS_DIR = os.path.join(_PROJECT_ROOT, "assets")
LOGO_PATH = os.path.join(ASSETS_DIR, "logo", "netwer_logo.png")


def logo_pixmap(size: int = 44) -> QPixmap:
    """NETWER logo, smoothly scaled to the given size."""
    pm = QPixmap(LOGO_PATH)
    if pm.isNull():
        # Fall back to the globe icon if the logo file isn't there
        return Icons.get("globe", Theme.ACCENT_GLOW).pixmap(size, size)
    return pm.scaled(
        size, size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


class Icons:
    _MAP = {
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
        "internet": "fa6s.globe",
        "download": "fa6s.download",
        "upload": "fa6s.upload",
        "packet_loss": "fa6s.bullseye",
        "uptime": "fa6s.clock",
        "summary": "fa6s.list",
        "devices": "fa6s.laptop",
        "resources": "fa6s.server",
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
        "dev_computer": "fa6s.desktop",
        "dev_media": "fa6s.photo-film",
    }

    @classmethod
    def get(cls, name: str, color: str = None) -> QIcon:
        """QIcon for a given name and color (for buttons and actions)."""
        fa_name = cls._MAP.get(name, "fa6s.circle")
        return qta.icon(fa_name, color=color or Theme.TEXT_SECONDARY)

    @classmethod
    def pixmap(cls, name: str, size: int = 16, color: str = None) -> QPixmap:
        """QPixmap at the given size (for QLabel icons inside cards)."""
        return cls.get(name, color).pixmap(size, size)

    #: Cache of the icon PNGs that QSS pulls in as image: url(...).
    _png_cache = {}

    @classmethod
    def png_path(cls, name: str, size: int = 16, color: str = "#ffffff") -> str:
        """Render an icon to a PNG on disk and return the path (with
        forward slashes). Needed because a Qt stylesheet can't draw a
        qtawesome icon directly, it wants image: url(path). Cached."""
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
        # QSS url() prefers forward slashes on Windows.
        url_path = path.replace("\\", "/")
        cls._png_cache[key] = url_path
        return url_path
