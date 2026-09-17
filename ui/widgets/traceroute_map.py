"""
NETWER — TracerouteMap widget.

Draws traceroute hops on a world map, natively with QPainter (no web engine
dependency). Each hop with a known location becomes a dot connected by the
packet path, the view starts zoomed on the origin and zooms out - city ->
regional -> world - as the path spans larger distances, so a route that ends
on another continent ends on a full world view.

Coordinates come from a bundled, simplified world-land dataset
(assets/world_land.json) projected with a Web-Mercator projection.
"""

import json
import math

from PyQt6.QtCore import Qt, QTimer, QPointF, QRectF
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QPolygonF, QFont
from PyQt6.QtWidgets import QWidget

from app.theme import Theme, is_dark
from app.resources import ASSETS_DIR
import os


# Major cities used as fixed reference points (shown when zoomed out enough).
REFERENCE_CITIES = [
    ("London", 51.51, -0.13), ("Paris", 48.86, 2.35), ("Berlin", 52.52, 13.40),
    ("Frankfurt", 50.11, 8.68), ("Amsterdam", 52.37, 4.90),
    ("Madrid", 40.42, -3.70), ("Rome", 41.90, 12.50), ("Zagreb", 45.81, 15.98),
    ("Moscow", 55.75, 37.62), ("Istanbul", 41.01, 28.98),
    ("New York", 40.71, -74.01), ("Chicago", 41.88, -87.63),
    ("Los Angeles", 34.05, -118.24), ("Dallas", 32.78, -96.80),
    ("Toronto", 43.65, -79.38), ("Miami", 25.76, -80.19),
    ("Tokyo", 35.68, 139.69), ("Singapore", 1.35, 103.82),
    ("Dubai", 25.20, 55.27), ("Mumbai", 19.08, 72.88),
    ("São Paulo", -23.55, -46.63), ("Sydney", -33.87, 151.21),
    ("Cairo", 30.04, 31.24), ("Beijing", 39.90, 116.40),
    ("Johannesburg", -26.20, 28.05), ("Mexico City", 19.43, -99.13),
]

_KIND_COLORS = {
    "local": "#3ec98a", "isp": "#4d9bff",
    "transit": "#b07cff", "dest": "#f0a830",
}


def _load_world():
    """Load country polygons (with borders). Falls back to the old land-only
    dataset if the country file isn't present."""
    for fname, key in (("world_countries.json", "countries"),
                       ("world_land.json", "polygons")):
        try:
            path = os.path.join(ASSETS_DIR, fname)
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)[key]
            if key == "countries":
                """ Flatten to a list of rings but remember they're separate
                countries so we can stroke each outline. """
                return data
            # Old format: list of rings -> wrap each as a one-ring "country".
            return [[ring] for ring in data]
        except Exception:
            continue
    return []


_WORLD = _load_world()   # list of countries, each country - list of rings


class TracerouteMap(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(320)
        self._hops = []
        self._visible = 0          # how many hops are currently drawn
        self._status = "Run a traceroute to plot the path on the map"
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

        # Current projection state (center lon/lat + span in degrees).
        self._c_lon = 0.0
        self._c_lat = 20.0
        self._span = 60.0
        self._world_mode = False

    # -- Public API --
    def set_status(self, text):
        # Show a message on the map (e.g. when geolocation is unavailable).
        self._status = text
        self.update()

    def set_hops(self, hops):
        # hops - list of dicts with lat/lon (optional), city, ms, kind, ip.
        self._hops = [h for h in hops]
        self._visible = len(self._hops)
        self._fit(self._visible)
        self.update()

    def clear(self):
        self._hops = []
        self._visible = 0
        self._timer.stop()
        self.update()

    def animate(self):
        # Replay the path build-up from the first hop.
        if not self._located_hops():
            self.update()
            return
        self._visible = 1
        self._fit(1)
        self.update()
        self._timer.start(850)

    # -- Animation --
    def _tick(self):
        self._visible += 1
        self._fit(self._visible)
        self.update()
        if self._visible >= len(self._hops):
            self._timer.stop()

    def _located_hops(self):
        return [h for h in self._hops
                if h.get("lat") is not None and h.get("lon") is not None]

    # -- Projection --
    def _fit(self, up_to):
        """Choose center + span (zoom) to frame the hops seen so far.

        Uses a minimum span so a tight cluster (e.g. several hops the offline
        estimate places at the same European point) doesn't zoom in so far
        that everything piles onto one pixel and the reference-city labels
        overlap into a mess.
        """
        pts = [h for h in self._hops[:max(up_to, 1)]
               if h.get("lat") is not None]
        if not pts:
            self._world_mode = True
            return
        lons = [h["lon"] for h in pts]
        lats = [h["lat"] for h in pts]
        min_lon, max_lon = min(lons), max(lons)
        min_lat, max_lat = min(lats), max(lats)
        self._c_lon = (min_lon + max_lon) / 2
        self._c_lat = (min_lat + max_lat) / 2
        # Real geographic spread of the path so far.
        spread = max(max_lon - min_lon, max_lat - min_lat)

        if spread > 60:
            # Path crosses continents -> full world view.
            self._world_mode = True
        elif spread > 18:
            # Multi-region (e.g. Europe → US east coast) -> continental.
            self._world_mode = False
            self._span = max(spread * 2.2, 55)
        else:
            """ Everything is clustered (one country / region, or coarse offline
            estimates all at one point). Keep a comfortable regional frame
            rather than zooming to street level - this is what was garbling. """
            self._world_mode = False
            self._span = 42

    def _project(self, lon, lat, w, h):
        # Web-Mercator projection to widget pixels for the current view.
        def merc_y(deg):
            deg = max(min(deg, 84), -84)
            return math.log(math.tan(math.pi / 4 + math.radians(deg) / 2))

        if self._world_mode:
            x = (lon + 180) / 360 * w
            y = (1 - (merc_y(lat) - merc_y(-84)) /
                 (merc_y(84) - merc_y(-84))) * h
            return QPointF(x, y)

        half = self._span / 2
        west = self._c_lon - half
        east = self._c_lon + half
        y_span = half * (h / w)
        north = self._c_lat + y_span
        south = self._c_lat - y_span
        x = (lon - west) / (east - west) * w
        y_top = merc_y(north)
        y_bot = merc_y(south)
        y = (y_top - merc_y(lat)) / (y_top - y_bot) * h
        return QPointF(x, y)

    # -- Paint --
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        # Background
        p.fillRect(self.rect(), QColor(Theme.BG_SIDEBAR))

        # Countries - filled land with visible borders between them.
        land_fill = QColor("#1b2949") if is_dark() else QColor("#d6deeb")
        border = QColor("#41547d") if is_dark() else QColor("#a9b6cc")
        p.setPen(QPen(border, 0.7))
        p.setBrush(QBrush(land_fill))
        for country in _WORLD:
            for ring in country:
                qpoly = QPolygonF()
                skip = False
                for lon, lat in ring:
                    pt = self._project(lon, lat, w, h)
                    if pt.x() < -2000 or pt.x() > w + 2000:
                        skip = True
                        break
                    qpoly.append(pt)
                if not skip and qpoly.count() >= 3:
                    p.drawPolygon(qpoly)

        located = [h for h in self._hops[:self._visible]
                   if h.get("lat") is not None]

        """ Reference cities (only when zoomed out enough to have room).
        Skip any label that would overlap one already drawn, so a tight
        European view doesn't turn into a pile of overlapping names. """
        if self._world_mode or self._span > 30:
            p.setFont(QFont(Theme.FONT_FAMILY_PRIMARY, 7))
            fm = p.fontMetrics()
            dot_col = QColor("#46536f")
            txt_col = QColor("#66738f")
            placed = []   # list of (x, y, w, h) label rects already drawn
            for name, lat, lon in REFERENCE_CITIES:
                pt = self._project(lon, lat, w, h)
                if not (6 < pt.x() < w - 6 and 6 < pt.y() < h - 6):
                    continue
                tw = fm.horizontalAdvance(name)
                lx, ly = pt.x() + 4, pt.y() + 3
                clash = False
                for (px, py, pw, ph) in placed:
                    if (lx < px + pw and lx + tw > px and
                            ly - 8 < py + ph and ly + 4 > py - 8):
                        clash = True
                        break
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(dot_col)
                p.drawEllipse(pt, 1.6, 1.6)
                if not clash:
                    p.setPen(txt_col)
                    p.drawText(QPointF(lx, ly), name)
                    placed.append((lx, ly - 8, tw, 12))

        # Packet path
        if len(located) > 1:
            pen = QPen(QColor(Theme.ACCENT), 1.6)
            pen.setStyle(Qt.PenStyle.DashLine)
            p.setPen(pen)
            for i in range(len(located) - 1):
                a = self._project(located[i]["lon"], located[i]["lat"], w, h)
                b = self._project(located[i + 1]["lon"],
                                  located[i + 1]["lat"], w, h)
                p.drawLine(a, b)

        # Hop dots first (so lines/labels sit cleanly on top).
        for hop in located:
            pt = self._project(hop["lon"], hop["lat"], w, h)
            col = QColor(_KIND_COLORS.get(hop.get("kind", "transit"), "#b07cff"))
            r = 5.5 if hop.get("kind") == "dest" else 4.0
            p.setPen(QPen(QColor(Theme.BG_SIDEBAR), 1.3))
            p.setBrush(col)
            p.drawEllipse(pt, r, r)

        """ Hop city labels - skip duplicates and any that would overlap a label
        already drawn (offline estimates can put several hops at one point). """
        p.setFont(QFont(Theme.FONT_FAMILY_PRIMARY, 8, QFont.Weight.Medium))
        fm = p.fontMetrics()
        seen_cities = set()
        label_rects = []
        for hop in located:
            city = hop.get("city", "")
            if not city or city in seen_cities:
                continue
            pt = self._project(hop["lon"], hop["lat"], w, h)
            tw = fm.horizontalAdvance(city) + 12
            bx, by = pt.x() + 8, pt.y() - 9
            clash = False
            for (rx, ry, rw, rh) in label_rects:
                if (bx < rx + rw and bx + tw > rx and
                        by < ry + rh and by + 16 > ry):
                    clash = True
                    break
            if clash:
                continue
            seen_cities.add(city)
            label_rects.append((bx, by, tw, 16))
            col = QColor(_KIND_COLORS.get(hop.get("kind", "transit"), "#b07cff"))
            box = QRectF(bx, by, tw, 16)
            p.setPen(QPen(col, 0.8))
            p.setBrush(QColor(Theme.BG_SIDEBAR))
            p.drawRoundedRect(box, 4, 4)
            p.setPen(QColor(Theme.TEXT_PRIMARY))
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, city)

        # Empty-state / status hint (supports multi-line messages)
        if not located and self._status:
            p.setPen(QColor(Theme.TEXT_MUTED))
            p.setFont(QFont(Theme.FONT_FAMILY_PRIMARY, 10))
            p.drawText(
                self.rect().adjusted(24, 0, -24, 0),
                Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                self._status)

        p.end()
