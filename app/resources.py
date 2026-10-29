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


# thin line icons from the redesign; everything else still comes from qtawesome
_SVG = {
    "dashboard": '<rect x="3" y="3" width="7" height="9" rx="1"/><rect x="14" y="3" width="7" height="5" rx="1"/>'
                 '<rect x="14" y="12" width="7" height="9" rx="1"/><rect x="3" y="16" width="7" height="5" rx="1"/>',
    "network": '<rect x="9" y="2" width="6" height="6" rx="1"/><rect x="2" y="16" width="6" height="6" rx="1"/>'
               '<rect x="16" y="16" width="6" height="6" rx="1"/><path d="M12 8v4M5 16v-2h14v2"/>',
    "wifi": '<path d="M5 12.5a10 10 0 0 1 14 0M8.5 16a5 5 0 0 1 7 0M2 9a15 15 0 0 1 20 0"/><circle cx="12" cy="19.5" r="1"/>',
    "system": '<rect x="5" y="5" width="14" height="14" rx="2"/><rect x="9" y="9" width="6" height="6"/>'
              '<path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3"/>',
    "resources": '<path d="M3 12h4l2-5 4 10 2-5h6"/>',
    "capture": '<path d="M3 17c4 0 6-2 8-6 1.5-3 3.5-7 9-8-2 4-2 9 0 14z"/>'
               '<path d="M2 21c2 0 2-1 4-1s2 1 4 1 2-1 4-1 2 1 4 1 2-1 4-1"/>',
    "ping": '<circle cx="12" cy="12" r="2"/><path d="M16.2 7.8a6 6 0 0 1 0 8.4M7.8 16.2a6 6 0 0 1 0-8.4'
            'M19 5a10 10 0 0 1 0 14M5 19A10 10 0 0 1 5 5"/>',
    "ping_sweep": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><path d="M12 12l6-6"/>',
    "port_scanner": '<path d="M9 2v6M15 2v6M6 8h12v4a6 6 0 0 1-12 0zM12 18v4"/>',
    "dns_tools": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>',
    "globe": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>',
    "speedtest": '<path d="M12 14l4-4"/><path d="M3.5 18a10 10 0 1 1 17 0"/>',
    "report": '<path d="M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8z"/><path d="M14 3v5h5M9 13h6M9 17h6"/>',
    "about": '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.01"/>',
    "ai": '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/>'
          '<path d="M19 15l.7 2.3L22 18l-2.3.7L19 21l-.7-2.3L16 18l2.3-.7z"/>',
    "download": '<path d="M12 4v14M6 12l6 6 6-6"/>',
    "upload": '<path d="M12 20V6M6 12l6-6 6 6"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/>',
    "dev_pc": '<rect x="3" y="4" width="18" height="12" rx="1.5"/><path d="M8 20h8M12 16v4"/>',
    "dev_computer": '<rect x="3" y="4" width="18" height="12" rx="1.5"/><path d="M8 20h8M12 16v4"/>',
    "dev_laptop": '<rect x="4" y="5" width="16" height="11" rx="1.5"/><path d="M2 19h20"/>',
    "dev_router": '<rect x="3" y="13" width="18" height="7" rx="1.5"/><path d="M7 16.5h.01M11 16.5h.01M12 13V9'
                  'M8.5 7a5 5 0 0 1 7 0M6 4.5a8.5 8.5 0 0 1 12 0"/>',
    "dev_phone": '<rect x="7" y="2" width="10" height="20" rx="2"/><path d="M11 18h2"/>',
    "dev_tv": '<rect x="3" y="4" width="18" height="13" rx="1.5"/><path d="M8 21h8"/>',
    "dev_generic": '<rect x="5" y="5" width="14" height="14" rx="2"/><rect x="9" y="9" width="6" height="6"/>',
    "devices": '<rect x="3" y="4" width="18" height="12" rx="1.5"/><path d="M8 20h8M12 16v4"/>',
}
_SVG_CACHE = {}


def _svg_pixmap(name, size, color, dpr=1.0):
    key = (name, size, color, dpr)
    if key not in _SVG_CACHE:
        from PyQt6.QtCore import QByteArray
        from PyQt6.QtGui import QPainter
        from PyQt6.QtSvg import QSvgRenderer
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
               f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{_SVG[name]}</svg>')
        px = round(size * dpr)
        pm = QPixmap(px, px)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        QSvgRenderer(QByteArray(svg.encode())).render(p)
        p.end()
        pm.setDevicePixelRatio(dpr)
        _SVG_CACHE[key] = pm
    return _SVG_CACHE[key]


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
        "capture": "mdi.shark-fin",
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
        "ai": "fa6s.wand-magic-sparkles",
        "gamepad": "fa6s.gamepad",
        "expand": "fa6s.expand",
        "compress": "fa6s.compress",
        "video": "fa6s.video",
        "film": "fa6s.film",
        "cloud_up": "fa6s.cloud-arrow-up",
        "chevron_down": "fa6s.chevron-down",
        "send": "fa6s.paper-plane",
        "clear_chat": "fa6s.broom",
        "arrow_right": "fa6s.arrow-right",
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
        "dev_tv": "fa6s.tv",
        "dev_nas": "fa6s.hard-drive",
        "dev_server": "fa6s.server",
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
        if name in _SVG:
            icon = QIcon()
            for size in (14, 16, 18, 20, 24, 32, 48):
                icon.addPixmap(_svg_pixmap(name, size, color or Theme.TEXT_SECONDARY, 2.0))
            return icon
        fa_name = cls._MAP.get(name, "fa6s.circle")
        return qta.icon(fa_name, color=color or Theme.TEXT_SECONDARY)

    @classmethod
    def pixmap(cls, name: str, size: int = 16, color: str = None) -> QPixmap:
        """QPixmap at the given size (for QLabel icons inside cards)."""
        if name in _SVG:
            from PyQt6.QtWidgets import QApplication
            app = QApplication.instance()
            dpr = app.devicePixelRatio() if app else 1.0
            return _svg_pixmap(name, size, color or Theme.TEXT_SECONDARY, dpr)
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
