import json
import math
import os
import time

import numpy as np
import pyqtgraph as pg

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
    QRadialGradient,
)
from PyQt6.QtWidgets import QToolTip, QWidget

from app.resources import ASSETS_DIR
from app.theme import Theme, is_dark

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

_KIND_COLORS = {"local": "#3ec98a", "isp": "#4d9bff", "transit": "#b07cff", "dest": "#f0a830"}
_KIND_NAMES = {"local": "Local", "isp": "ISP", "transit": "Transit", "dest": "Destination"}
EARTH_KM = 6371.0
MIN_SPAN, MAX_SPAN = 2.0, 360.0


def _load_world():
    for fname, key in (("world_countries.json", "countries"), ("world_land.json", "polygons")):
        try:
            with open(os.path.join(ASSETS_DIR, fname), "r", encoding="utf-8") as f:
                data = json.load(f)[key]
            rings = [r for c in data for r in c] if key == "countries" else data
            return [_prepare(r) for r in rings if len(r) >= 3]
        except Exception:
            continue
    return []


def _prepare(ring):
    arr = np.asarray(ring, dtype=np.float64)
    lat = np.clip(arr[:, 1], -85.0, 85.0)
    my = np.log(np.tan(np.pi / 4 + np.radians(lat) / 2))
    lon = arr[:, 0].copy()
    lo, hi = float(lon.min()), float(lon.max())
    # centre and half-width for cheap culling; rings touching the date line are always tested
    half = (hi - lo) / 2
    return lon, my, (lo + hi) / 2, half if half < 170 else 360.0, float(my.min()), float(my.max())


_WORLD = _load_world()


def _merc(lat):
    lat = max(min(lat, 85.0), -85.0)
    return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def _unmerc(m):
    return math.degrees(2 * math.atan(math.exp(m)) - math.pi / 2)


def _arc(a, b):
    """Points along the great circle from a to b, each (lat, lon)."""
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (math.sin((la2 - la1) / 2) ** 2
         + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2)
    d = 2 * math.asin(min(1.0, math.sqrt(h)))
    if d < 1e-5:
        return [a, b], 0.0
    n = max(6, min(90, int(math.degrees(d) * 1.2)))
    pts = []
    for i in range(n + 1):
        f = i / n
        k1, k2 = math.sin((1 - f) * d) / math.sin(d), math.sin(f * d) / math.sin(d)
        x = k1 * math.cos(la1) * math.cos(lo1) + k2 * math.cos(la2) * math.cos(lo2)
        y = k1 * math.cos(la1) * math.sin(lo1) + k2 * math.cos(la2) * math.sin(lo2)
        z = k1 * math.sin(la1) + k2 * math.sin(la2)
        pts.append((math.degrees(math.atan2(z, math.hypot(x, y))), math.degrees(math.atan2(y, x))))
    return pts, d * EARTH_KM


def _thin(x, y):
    # far away, most points land on the same pixel: keep a sensible number
    extent = max(float(x.max() - x.min()), float(y.max() - y.min()))
    keep = max(24, int(extent * 1.5))
    if len(x) > keep * 2:
        step = len(x) // keep
        return x[::step], y[::step]
    return x, y


def _smooth(x, y):
    # Chaikin corner cutting; more rounds the longer the on-screen segments are
    seg = float(np.hypot(np.diff(x), np.diff(y)).mean()) if len(x) > 1 else 0.0
    rounds = 0 if seg < 3 else 1 if seg < 8 else 2 if seg < 20 else 3
    while rounds and len(x) * 2 ** rounds > 300000:
        rounds -= 1
    for _ in range(rounds):
        xn, yn = np.roll(x, -1), np.roll(y, -1)
        nx, ny = np.empty(len(x) * 2), np.empty(len(y) * 2)
        nx[0::2], nx[1::2] = 0.75 * x + 0.25 * xn, 0.25 * x + 0.75 * xn
        ny[0::2], ny[1::2] = 0.75 * y + 0.25 * yn, 0.25 * y + 0.75 * yn
        x, y = nx, ny
    return x, y


def _ms_color(ms):
    if ms < 40:
        return QColor(Theme.SUCCESS)
    return QColor(Theme.WARNING) if ms < 120 else QColor(Theme.DANGER)


class TracerouteMap(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMinimumHeight(320)
        self.setMouseTracking(True)
        self._hops = []
        self._visible = 0
        self._status = "Run a traceroute to plot the path on the map"
        self._view = [0.0, 20.0, 160.0]       # centre lon, centre lat, span in degrees of longitude
        self._target = list(self._view)
        self._manual = False
        self._drag = None
        self._phase = 0.0
        self._land = None                     # (key, pixmap, view it was drawn for)
        self._land_t = 0.0
        self._last = None
        self._moving = False
        self._had_located = False
        self._settle = QTimer(self)           # redraw crisp once the view stops moving
        self._settle.setSingleShot(True)
        self._settle.timeout.connect(self._settled)
        self._clusters = []

        self._reveal = QTimer(self)
        self._reveal.timeout.connect(self._tick)
        self._frame = QTimer(self)            # view easing and the moving packet
        self._frame.setInterval(16)
        self._frame.timeout.connect(self._step)

    # -- public --
    def set_status(self, text):
        self._status = text
        self.update()

    def set_hops(self, hops):
        self._hops = list(hops)
        self._visible = len(self._hops)
        self._manual = False
        self._fit()
        if not self._had_located and self._located():
            self._view = list(self._target)      # first fix: go straight there
            self._had_located = True
        self._frame.start()
        self.update()

    def clear(self):
        self._hops = []
        self._visible = 0
        self._had_located = False
        self._target = [0.0, 20.0, 160.0]
        self._reveal.stop()
        self._frame.stop()
        self.update()

    def animate(self):
        if not self._located():
            self.update()
            return
        self._visible = 1
        self._manual = False
        self._fit()
        self._frame.start()
        self._reveal.start(850)
        self.update()

    # -- state --
    def _tick(self):
        self._visible += 1
        if not self._manual:
            self._fit()
        if self._visible >= len(self._hops):
            self._reveal.stop()
        self.update()

    def _located(self, limit=None):
        hops = self._hops if limit is None else self._hops[:limit]
        return [h for h in hops if h.get("lat") is not None and h.get("lon") is not None]

    def _step(self):
        now = time.monotonic()
        dt = min(now - (self._last or now), 0.1)
        self._last = now
        f = 1 - math.exp(-dt * 7)
        v, t = self._view, self._target
        dlon = (t[0] - v[0] + 180) % 360 - 180
        dlat = t[1] - v[1]
        dspan = math.log(t[2]) - math.log(v[2])
        tol = 0.002 * v[2]
        moved = False
        if abs(dlon) > tol or abs(dlat) > tol or abs(dspan) > 0.002:
            v[0] += dlon * f
            v[1] += dlat * f
            v[2] = math.exp(math.log(v[2]) + dspan * f)
            moved = True
            self._moving = True
            self._settle.start(140)
        elif dlon or dlat or dspan:
            v[:] = t                                  # snap the last bit
            self._moving = True
            self._settle.start(140)
            moved = True
        if len(self._located(self._visible)) > 1:
            self._phase = (self._phase + 0.006) % 1.0
        elif not moved:
            return
        self.update()

    def _settled(self):
        self._moving = False
        self.update()

    def _view_changed(self):
        self._moving = True
        self._settle.start(140)

    def hideEvent(self, e):
        self._frame.stop()
        super().hideEvent(e)

    def showEvent(self, e):
        if self._hops:
            self._frame.start()
        super().showEvent(e)

    # -- view --
    def _fit(self):
        pts = self._located(self._visible)
        if not pts:
            return
        w, h = max(self.width(), 1), max(self.height(), 1)
        lons = sorted(((p["lon"] + 180) % 360) for p in pts)
        # Smallest longitude window: split the circle at its biggest gap
        gaps = [(lons[(i + 1) % len(lons)] - lons[i]) % 360 for i in range(len(lons))]
        i = max(range(len(lons)), key=lambda j: gaps[j]) if len(lons) > 1 else 0
        lon_range = 360 - gaps[i] if len(lons) > 1 else 0.0
        start = lons[(i + 1) % len(lons)] if len(lons) > 1 else lons[0]
        c_lon = (start + lon_range / 2) % 360 - 180
        ms = [_merc(p["lat"]) for p in pts]
        m_range = max(ms) - min(ms)
        c_lat = _unmerc((max(ms) + min(ms)) / 2)
        span = max(lon_range / 0.7, math.degrees(m_range) * (w / h) / 0.6, 1.5)
        self._target = [c_lon, c_lat, min(span, MAX_SPAN)]
        if span >= MAX_SPAN:
            self._target[0] = 0.0

    def resizeEvent(self, e):
        if self._hops and not self._manual:
            self._fit()
        super().resizeEvent(e)

    def _project_delta(self, dlon, lat):
        # dlon is the longitude offset from the view centre, not wrapped
        c_lat, span = self._view[1], self._view[2]
        k = max(self.width(), 1) / span
        return QPointF(self.width() / 2 + dlon * k,
                       self.height() / 2 - (_merc(lat) - _merc(c_lat)) * k * 180 / math.pi)

    def _project(self, lon, lat):
        return self._project_delta((lon - self._view[0] + 180) % 360 - 180, lat)

    def _unproject(self, x, y):
        c_lon, c_lat, span = self._view
        k = self.width() / span
        lon = c_lon + (x - self.width() / 2) / k
        lat = _unmerc(_merc(c_lat) - (y - self.height() / 2) / (k * 180 / math.pi))
        return lon, lat

    def _project_run(self, pts):
        """Project a (lat, lon) run keeping it continuous across the date line."""
        out, prev = [], None
        c_lon = self._view[0]
        for lat, lon in pts:
            d = (lon - c_lon + 180) % 360 - 180
            if prev is not None:
                while d - prev > 180:
                    d -= 360
                while d - prev < -180:
                    d += 360
            prev = d
            out.append(self._project_delta(d, lat))
        return out

    # -- mouse --
    def wheelEvent(self, event):
        pos = event.position()
        lon, lat = self._unproject(pos.x(), pos.y())
        factor = 0.82 if event.angleDelta().y() > 0 else 1 / 0.82
        span = min(max(self._view[2] * factor, MIN_SPAN), MAX_SPAN)
        self._manual = True
        self._view[2] = self._target[2] = span
        self._view_changed()
        # Keep the point under the cursor where it was
        k = self.width() / span
        self._view[0] = self._target[0] = lon - (pos.x() - self.width() / 2) / k
        self._view[1] = self._target[1] = _unmerc(
            _merc(lat) + (pos.y() - self.height() / 2) / (k * 180 / math.pi))
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag = (event.position(), list(self._view))
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseReleaseEvent(self, event):
        self._drag = None
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def mouseDoubleClickEvent(self, event):
        self._manual = False
        self._fit()
        self.update()

    def mouseMoveEvent(self, event):
        pos = event.position()
        if self._drag is not None:
            start, view = self._drag
            k = self.width() / view[2]
            self._manual = True
            self._view[0] = self._target[0] = view[0] - (pos.x() - start.x()) / k
            self._view[1] = self._target[1] = _unmerc(
                _merc(view[1]) + (pos.y() - start.y()) / (k * 180 / math.pi))
            self._view_changed()
            self.update()
            return
        for c in self._clusters:
            if math.hypot(c["pt"].x() - pos.x(), c["pt"].y() - pos.y()) < 12:
                QToolTip.showText(event.globalPosition().toPoint(), self._tip(c), self)
                return
        QToolTip.hideText()

    def _tip(self, c):
        rows = []
        for h in c["hops"]:
            ms = f"{h['ms']:.0f} ms" if h.get("ms") else "no reply time"
            rows.append(f"<b>Hop {h['n']}</b> &nbsp;{h.get('ip', '')} &nbsp;{ms}")
        where = c["city"] or "approximate location"
        return f"<b>{where}</b><br>" + "<br>".join(rows)

    # -- drawing --
    def _land_layer(self, w, h, dpr):
        key = (round(self._view[0], 3), round(self._view[1], 3), round(self._view[2], 3),
               w, h, dpr, is_dark())
        if self._land and self._land[0] == key:
            return self._land[1], None
        if self._moving and self._land and self._reusable(self._land[2], w):
            return self._land[1], self._land[2]
        pm = QPixmap(int(w * dpr), int(h * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(QColor(Theme.BG_SIDEBAR))
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        span = self._view[2]

        # Graticule
        step = 30 if span > 120 else 10 if span > 40 else 5 if span > 12 else 1
        p.setPen(QPen(QColor(255, 255, 255, 14) if is_dark() else QColor(0, 0, 0, 20), 0.6))
        lon0 = math.floor((self._view[0] - span) / step) * step
        for i in range(int(2 * span / step) + 2):
            x = self._project(lon0 + i * step, 0).x()
            p.drawLine(QPointF(x, 0), QPointF(x, h))
        for lat in range(-80, 81, step):
            y = self._project(self._view[0], lat).y()
            if 0 <= y <= h:
                p.drawLine(QPointF(0, y), QPointF(w, y))

        land = QColor("#1b2949") if is_dark() else QColor("#d6deeb")
        edge = QColor("#41547d") if is_dark() else QColor("#a9b6cc")
        paths = self._land_paths(w, h)
        # fill first with a same-colour stroke so hairline gaps between countries close up
        p.setPen(QPen(land, 1.6))
        p.setBrush(QBrush(land))
        for path in paths:
            p.drawPath(path)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(edge, 0.7))
        for path in paths:
            p.drawPath(path)

        if span > 14:
            p.setFont(QFont(Theme.FONT_FAMILY_PRIMARY, 7))
            fm = p.fontMetrics()
            placed = []
            for name, lat, lon in REFERENCE_CITIES:
                pt = self._project(lon, lat)
                if not (6 < pt.x() < w - 6 and 6 < pt.y() < h - 6):
                    continue
                tw = fm.horizontalAdvance(name)
                lx, ly = pt.x() + 4, pt.y() + 3
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor("#46536f"))
                p.drawEllipse(pt, 1.6, 1.6)
                if not any(lx < px + pw and lx + tw > px and ly - 8 < py + 12 and ly + 4 > py
                           for px, py, pw in placed):
                    p.setPen(QColor("#66738f"))
                    p.drawText(QPointF(lx, ly), name)
                    placed.append((lx, ly - 8, tw))
        p.end()
        self._land = (key, pm, list(self._view))
        self._land_t = time.monotonic()
        return pm, None

    def _reusable(self, old, w):
        # the last render stays usable until the view drifts too far from it
        s = old[2] / self._view[2]
        shift = abs((old[0] - self._view[0] + 180) % 360 - 180) * w / self._view[2]
        return 0.6 < s < 1.7 and shift < w * 0.45

    def _land_paths(self, w, h):
        c_lon, c_lat, span = self._view
        k = w / span
        ky = k * 180 / math.pi
        cm = _merc(c_lat)
        shifts = (-360, 0, 360) if span > 110 else (0,)
        paths = []
        half_w = span / 2 + 1
        half_h = h / 2 / ky
        for lon, my, lc, hw, my_lo, my_hi in _WORLD:
            if my_lo > cm + half_h or my_hi < cm - half_h:
                continue
            if abs((lc - c_lon + 180) % 360 - 180) - hw > half_w:
                continue
            if (my_hi - my_lo) * ky < 0.8 and hw * 2 * k < 0.8:
                continue
            d = (lon - c_lon + 180) % 360 - 180
            d = np.degrees(np.unwrap(np.radians(d)))
            y = h / 2 - (my - cm) * ky
            if y.max() < 0 or y.min() > h:
                continue
            for shift in shifts:
                x = w / 2 + (d + shift) * k
                if x.max() < 0 or x.min() > w:
                    continue
                if x.max() - x.min() < 0.8 and y.max() - y.min() < 0.8:
                    continue
                px, py = _smooth(*_thin(x, y))
                path = pg.functions.arrayToQPath(px, py, connect="all")
                path.closeSubpath()
                paths.append(path)
        return paths

    def _build_clusters(self, located):
        groups = []
        for hop in located:
            for g in groups:
                if (abs(g["lat"] - hop["lat"]) < 0.4 and
                        abs((g["lon"] - hop["lon"] + 180) % 360 - 180) < 0.4):
                    g["hops"].append(hop)
                    break
            else:
                groups.append({"lat": hop["lat"], "lon": hop["lon"], "hops": [hop]})
        for g in groups:
            g["city"] = next((h.get("city") for h in g["hops"] if h.get("city")), "")
            g["kind"] = "dest" if any(h.get("kind") == "dest" for h in g["hops"]) else g["hops"][-1].get("kind", "transit")
            g["approx"] = all(h.get("approx") for h in g["hops"])
            g["pt"] = self._project(g["lon"], g["lat"])
        return groups

    def paintEvent(self, event):
        w, h = self.width(), self.height()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pm, old = self._land_layer(w, h, self.devicePixelRatioF())
        if old is None:
            p.drawPixmap(0, 0, pm)
        else:
            # same Mercator map, just scaled and shifted, so reuse the last render
            p.fillRect(self.rect(), QColor(Theme.BG_SIDEBAR))
            s = old[2] / self._view[2]
            k_new = w / self._view[2]
            dlon = (old[0] - self._view[0] + 180) % 360 - 180
            dm = _merc(old[1]) - _merc(self._view[1])
            p.save()
            p.translate(w / 2 * (1 - s) + dlon * k_new, h / 2 * (1 - s) - dm * k_new * 180 / math.pi)
            p.scale(s, s)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            p.drawPixmap(0, 0, pm)
            p.restore()

        located = self._located(self._visible)
        self._clusters = self._build_clusters(located)
        if not located:
            if self._status:
                p.setPen(QColor(Theme.TEXT_MUTED))
                p.setFont(QFont(Theme.FONT_FAMILY_PRIMARY, 10))
                p.drawText(self.rect().adjusted(24, 0, -24, 0),
                           Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self._status)
            p.end()
            return

        # Legs along the great circle, coloured by the latency of the hop they lead to
        total_km, screen_path = 0.0, []
        for a, b in zip(located, located[1:]):
            pts, km = _arc((a["lat"], a["lon"]), (b["lat"], b["lon"]))
            total_km += km
            if km == 0:
                continue
            run = self._project_run(pts)
            screen_path.extend(run)
            col = _ms_color(b.get("ms") or 0)
            glow = QColor(col)
            glow.setAlpha(50)
            path = QPainterPath(run[0])
            for q in run[1:]:
                path.lineTo(q)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(glow, 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawPath(path)
            p.setPen(QPen(col, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawPath(path)

        # Packet travelling along the path
        if len(screen_path) > 1 and self._visible >= len(self._hops):
            lengths = [math.hypot(b.x() - a.x(), b.y() - a.y()) for a, b in zip(screen_path, screen_path[1:])]
            goal, acc = sum(lengths) * self._phase, 0.0
            for (a, b), seg in zip(zip(screen_path, screen_path[1:]), lengths):
                if acc + seg >= goal and seg > 0:
                    t = (goal - acc) / seg
                    pos = QPointF(a.x() + (b.x() - a.x()) * t, a.y() + (b.y() - a.y()) * t)
                    grad = QRadialGradient(pos, 9)
                    grad.setColorAt(0, QColor(255, 255, 255, 230))
                    grad.setColorAt(0.4, QColor(Theme.ACCENT))
                    grad.setColorAt(1, QColor(0, 0, 0, 0))
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(QBrush(grad))
                    p.drawEllipse(pos, 9, 9)
                    break
                acc += seg

        # Hop markers: numbered, hollow when the location is only approximate
        p.setFont(QFont(Theme.FONT_FAMILY_PRIMARY, 7, QFont.Weight.Bold))
        fm = p.fontMetrics()
        for c in self._clusters:
            col = QColor(_KIND_COLORS.get(c["kind"], "#b07cff"))
            nums = [x["n"] for x in c["hops"]]
            label = str(nums[0]) if len(nums) == 1 else f"{nums[0]}-{nums[-1]}"
            tw = fm.horizontalAdvance(label)
            rect = QRectF(c["pt"].x() - max(tw / 2 + 4, 8), c["pt"].y() - 8, max(tw + 8, 16), 16)
            if c["approx"]:
                ring = QColor(col)
                ring.setAlpha(45)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(ring)
                p.drawEllipse(c["pt"], 22, 22)
                p.setBrush(QColor(Theme.BG_SIDEBAR))
                pen = QPen(col, 1.4, Qt.PenStyle.DashLine)
            else:
                p.setBrush(col)
                pen = QPen(QColor(Theme.BG_SIDEBAR), 1.5)
            p.setPen(pen)
            p.drawRoundedRect(rect, 8, 8)
            p.setPen(col if c["approx"] else QColor("#0b1020"))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)

        # Labels, kept clear of each other; the ends of the path go first
        p.setFont(QFont(Theme.FONT_FAMILY_PRIMARY, 8, QFont.Weight.Medium))
        fm = p.fontMetrics()
        order = sorted(self._clusters, key=lambda c: (c is not self._clusters[-1], c is not self._clusters[0]))
        taken = [QRectF(c["pt"].x() - 10, c["pt"].y() - 10, 20, 20) for c in self._clusters]
        for c in order:
            ms = next((x["ms"] for x in reversed(c["hops"]) if x.get("ms")), 0)
            name = c["city"] or ("You" if c is self._clusters[0] else "")
            text = f"{name} \u00b7 {ms:.0f} ms" if name and ms else name
            if not text:
                continue
            tw = fm.horizontalAdvance(text) + 14
            for dx, dy in ((12, -26), (12, 10), (-12 - tw, -26), (-12 - tw, 10)):
                box = QRectF(c["pt"].x() + dx, c["pt"].y() + dy, tw, 16)
                if box.left() < 2 or box.right() > w - 2 or box.top() < 2 or box.bottom() > h - 2:
                    continue
                if any(box.intersects(t) for t in taken[len(self._clusters):]):
                    continue
                taken.append(box)
                col = QColor(_KIND_COLORS.get(c["kind"], "#b07cff"))
                p.setPen(QPen(col, 0.8))
                p.setBrush(QColor(Theme.BG_SIDEBAR))
                p.drawRoundedRect(box, 5, 5)
                p.setPen(QColor(Theme.TEXT_PRIMARY))
                p.drawText(box, Qt.AlignmentFlag.AlignCenter, text)
                break

        # Summary chip and legend
        last_ms = next((x["ms"] for x in reversed(located) if x.get("ms")), 0)
        p.setFont(QFont(Theme.FONT_FAMILY_PRIMARY, 8))
        info = f"{len(self._hops)} hops  \u00b7  {total_km:,.0f} km  \u00b7  {last_ms:.0f} ms"
        iw = p.fontMetrics().horizontalAdvance(info) + 18
        p.setPen(QPen(QColor(Theme.GLASS_BORDER), 1))
        p.setBrush(QColor(Theme.BG_SIDEBAR))
        p.drawRoundedRect(QRectF(10, 10, iw, 22), 8, 8)
        p.setPen(QColor(Theme.TEXT_BODY))
        p.drawText(QRectF(10, 10, iw, 22), Qt.AlignmentFlag.AlignCenter, info)

        x = 12
        used = {c["kind"] for c in self._clusters}
        for kind in ("local", "isp", "transit", "dest"):
            if kind not in used:
                continue
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(_KIND_COLORS[kind]))
            p.drawEllipse(QPointF(x + 4, h - 16), 4, 4)
            p.setPen(QColor(Theme.TEXT_MUTED))
            p.drawText(QPointF(x + 13, h - 12.5), _KIND_NAMES[kind])
            x += 22 + p.fontMetrics().horizontalAdvance(_KIND_NAMES[kind])
        if any(c["approx"] for c in self._clusters):
            p.setPen(QColor(Theme.TEXT_MUTED))
            p.drawText(QPointF(x + 6, h - 12.5), "dashed = approximate location")
        hint = "Scroll to zoom \u00b7 drag to move \u00b7 double-click to fit"
        p.setPen(QColor(Theme.TEXT_FAINT))
        p.drawText(QPointF(w - p.fontMetrics().horizontalAdvance(hint) - 12, h - 12.5), hint)
        p.end()
