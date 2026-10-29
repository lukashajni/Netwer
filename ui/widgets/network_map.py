"""NETWER — NetworkMap widget"""

import math
import random
import time

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from app.theme import Theme
from app.resources import Icons


def guess_device_icon(dev: dict) -> str:
    """Pick an icon name for a device."""
    kind = (dev.get("kind") or "").strip()
    if kind.startswith("dev_"):
        return kind
    try:
        from core import device_fingerprint
        return device_fingerprint.classify_kind(dev)
    except Exception:
        return "dev_generic"


def device_display_name(dev: dict) -> str:
    """Best available name, in order: a name the user gave the device, its real
    hostname, a real manufacturer, else what kind of device it is."""
    try:
        from core import device_names
        custom = device_names.get(dev)
        if custom:
            return custom
    except Exception:
        pass
    hostname = (dev.get("hostname") or "").strip()
    if hostname and hostname.lower() not in ("unknown", "?", ""):
        # A hostname that's just the IP repeated isn't a real name.
        if hostname != dev.get("ip", ""):
            return hostname
    vendor = (dev.get("vendor") or "").strip()
    generic = ("unknown", "private (randomized)", "private", "randomized", "")
    if vendor and vendor.lower() not in generic:
        # "Apple (private address)" is useful detail, but as a "name" the
        # manufacturer alone reads better under an icon.
        return vendor.replace(" (private address)", "")
    try:
        from core.device_fingerprint import KIND_LABELS
        label = KIND_LABELS.get(guess_device_icon(dev))
    except Exception:
        label = None
    return label or "Unknown device"


class NetworkMap(QWidget):
    """Internet, router and devices drawn as one picture, with traffic dots on the links."""
    # Emitted with the device dict when a device node is clicked.
    node_clicked = pyqtSignal(dict)

    R = 22

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(220)
        self.setMouseTracking(True)
        self._online = True
        self._gateway = ""
        self._router_vendor = ""
        self._gw_dev = None
        self._devices = []
        self._new_ips = set()
        self._wan = ""
        self._link_label = ""
        self._hover = None
        self._dots = []
        self._pulse = 0.0
        self._anim = QTimer(self)
        self._anim.setInterval(30)
        self._anim.timeout.connect(self._step)
        self._anim.start()

    # -- data --
    def set_topology(self, gateway, devices, router_vendor="", online=True):
        self._gateway = gateway or ""
        self._router_vendor = router_vendor
        self._online = online
        gw = next((d for d in devices if d.get("ip") == gateway), None)
        self._gw_dev = dict(gw or {"ip": gateway, "hostname": "", "vendor": router_vendor})
        self._gw_dev["is_gateway"] = True
        others = [d for d in devices if d.get("ip") != gateway]
        others.sort(key=lambda d: (not d.get("is_self"), d.get("ip", "")))
        self._devices = others[:6]
        self.update()

    def set_wan(self, text):
        self._wan = text
        self.update()

    def set_link_label(self, text):
        # label on the link from the router to this computer, e.g. "Ethernet 4 · 1 Gbps"
        self._link_label = text
        self.update()

    def set_new(self, ips):
        self._new_ips = set(ips)
        self.update()

    def node_titles(self):
        return [(t, s) for _k, _c, t, s, _d in self._nodes()]

    # -- geometry --
    def _nodes(self):
        w, h = self.width(), self.height()
        cx = w / 2
        rv = (self._router_vendor or "").strip()
        if not rv or rv.lower() in ("unknown", "private (randomized)"):
            rv = "Router"
        top, bottom = 30, h - 64
        nodes = [("net", QPointF(cx, top), "Internet", "via ISP · public IP hidden", None),
                 ("gw", QPointF(cx, (top + bottom) / 2), rv, f"{self._gateway or '—'} · gateway", self._gw_dev)]
        n = len(self._devices)
        for i, d in enumerate(self._devices):
            x = w * (i + 1) / (n + 1)
            if n == 2:
                x = cx + (-1 if i == 0 else 1) * min(w * 0.22, 120)
            name = device_display_name(d)
            if d.get("is_self"):
                name = "PC (you)" if guess_device_icon(d) in ("dev_pc", "dev_computer", "dev_generic") else f"{name} (you)"
            nodes.append((f"d{i}", QPointF(x, bottom), name[:18], d.get("ip", ""), d))
        return nodes

    def _route(self, to_key):
        pts = {k: c for k, c, _t, _s, _d in self._nodes()}
        return [pts["net"], pts["gw"]] + ([pts[to_key]] if to_key in pts else [])

    # -- traffic --
    def set_traffic(self, dl_mbps, ul_mbps, lan_ips=()):
        """Spawn dots for one second of traffic: blue in, purple out, grey for LAN multicast."""
        if not self._online or not self.isVisible():
            return
        me = next((f"d{i}" for i, d in enumerate(self._devices) if d.get("is_self")), None)
        now = time.monotonic()
        for mbps, down in ((dl_mbps, True), (ul_mbps, False)):
            kbps = max(0.0, mbps) * 1000
            n = min(8, int(round(math.log2(1 + kbps / 20)))) if kbps > 1 else 0
            for _ in range(n):
                self._dots.append({"t0": now + random.random(), "dur": 1.1 + random.random() * 0.3,
                                   "key": me, "down": down, "color": Theme.ACCENT if down else Theme.ACCENT_PURPLE})
        for i, d in enumerate(self._devices):
            if d.get("ip") in lan_ips and not d.get("is_self"):
                self._dots.append({"t0": now + random.random(), "dur": 1.0, "key": f"d{i}", "down": False,
                                   "lan": True, "color": "#7d86a0"})

    def _step(self):
        now = time.monotonic()
        self._dots = [d for d in self._dots if now < d["t0"] + d["dur"]]
        self._pulse = (self._pulse + 0.012) % 1.0
        if self.isVisible():
            self.update()

    # -- input --
    def _hit(self, pos):
        for key, c, _t, _s, dev in self._nodes():
            if (pos.x() - c.x()) ** 2 + (pos.y() - c.y()) ** 2 <= (self.R + 4) ** 2:
                return key, dev
        return None, None

    def mouseMoveEvent(self, e):
        key, dev = self._hit(e.position())
        self._hover = key if dev else None
        self.setCursor(Qt.CursorShape.PointingHandCursor if dev else Qt.CursorShape.ArrowCursor)

    def mousePressEvent(self, e):
        _key, dev = self._hit(e.position())
        if dev:
            self.node_clicked.emit(dev)

    # -- drawing --
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        nodes = self._nodes()
        pts = {k: c for k, c, _t, _s, _d in nodes}
        link = QColor(Theme.BORDER_STRONG)
        mono = QFont(Theme.FONT_MONO_PRIMARY)
        mono.setPixelSize(11)

        # links
        p.setPen(QPen(link, 2))
        p.drawLine(pts["net"], pts["gw"])
        for i, d in enumerate(self._devices):
            pen = QPen(link, 2)
            if not d.get("is_self"):
                pen.setStyle(Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.drawLine(pts["gw"], pts[f"d{i}"])

        # link labels
        p.setFont(mono)
        p.setPen(QColor(Theme.TEXT_MUTED))
        if self._wan:
            mid = (pts["net"] + pts["gw"]) / 2
            p.drawText(QRectF(mid.x() + 8, mid.y() - 8, 160, 16), Qt.AlignmentFlag.AlignVCenter, f"WAN · {self._wan}")
        for i, d in enumerate(self._devices):
            if d.get("is_self") and self._link_label:
                a, b = pts["gw"], pts[f"d{i}"]
                mid = (a + b) / 2
                right = b.x() > a.x()
                r = QRectF(mid.x() + 10, mid.y() - 18, 170, 16) if right else QRectF(mid.x() - 180, mid.y() - 18, 170, 16)
                p.drawText(r, (Qt.AlignmentFlag.AlignLeft if right else Qt.AlignmentFlag.AlignRight)
                           | Qt.AlignmentFlag.AlignVCenter, self._link_label)

        # traffic dots
        now = time.monotonic()
        p.setPen(Qt.PenStyle.NoPen)
        for d in self._dots:
            f = (now - d["t0"]) / d["dur"]
            if not 0 <= f <= 1:
                continue
            route = [pts[d["key"]], pts["gw"]] if d.get("lan") else self._route(d["key"])
            if len(route) < 2:
                continue
            pt = _along(route if d["down"] else route[::-1], f)
            c = QColor(d["color"])
            c.setAlphaF(min(1.0, f * 6, (1 - f) * 6))
            p.setBrush(c)
            p.drawEllipse(pt, 3.2, 3.2)

        # router pulse
        gwp = pts["gw"]
        halo = QColor(Theme.SUCCESS if self._online else Theme.TEXT_MUTED)
        halo.setAlphaF(0.55 * (1 - self._pulse))
        p.setPen(QPen(halo, 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        rr = self.R + 2 + 10 * self._pulse
        p.drawEllipse(gwp, rr, rr)

        title = QFont(Theme.FONT_FAMILY_PRIMARY)
        title.setPixelSize(12)
        title.setBold(True)
        for key, c, t, sub, dev in nodes:
            is_new = dev is not None and dev.get("ip") in self._new_ips
            stroke = QColor(Theme.ACCENT if (dev and dev.get("is_self")) or key == self._hover
                            else Theme.ACCENT_GLOW if is_new else Theme.BORDER_STRONG)
            pen = QPen(stroke, 1.5)
            if is_new:
                pen.setStyle(Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.setBrush(QColor(Theme.BG_ELEVATED))
            p.drawEllipse(c, self.R, self.R)
            if key == "net":
                icon, color = "globe", Theme.SUCCESS if self._online else Theme.TEXT_MUTED
            elif key == "gw":
                icon, color = "dev_router", Theme.TEXT_SECONDARY
            else:
                icon = guess_device_icon(dev)
                color = Theme.ACCENT_HOVER if dev.get("is_self") else "#c9bdff" if is_new else Theme.TEXT_SECONDARY
            pm = Icons.pixmap(icon if icon.startswith("dev_") or icon == "globe" else "dev_generic", 20, color)
            p.drawPixmap(QPointF(c.x() - 10, c.y() - 10), pm)

            if key in ("net", "gw"):
                p.setFont(title)
                p.setPen(QColor(Theme.TEXT_PRIMARY))
                p.drawText(QPointF(c.x() + self.R + 10, c.y() - 2), t)
                p.setFont(mono)
                p.setPen(QColor(Theme.TEXT_MUTED))
                p.drawText(QPointF(c.x() + self.R + 10, c.y() + 13), sub)
            else:
                p.setFont(title)
                p.setPen(QColor(Theme.TEXT_PRIMARY))
                label = t + ("  NEW" if is_new else "")
                p.drawText(QRectF(c.x() - 90, c.y() + self.R + 6, 180, 16), Qt.AlignmentFlag.AlignCenter, label)
                p.setFont(mono)
                p.setPen(QColor(Theme.TEXT_MUTED))
                p.drawText(QRectF(c.x() - 90, c.y() + self.R + 22, 180, 16), Qt.AlignmentFlag.AlignCenter, sub)
        p.end()


def _along(route, f):
    segs = [(route[i], route[i + 1]) for i in range(len(route) - 1)]
    lens = [math.hypot(b.x() - a.x(), b.y() - a.y()) for a, b in segs]
    x = f * (sum(lens) or 1)
    for i, ((a, b), ln) in enumerate(zip(segs, lens)):
        if x <= ln or i == len(segs) - 1:
            k = x / ln if ln else 0
            return QPointF(a.x() + (b.x() - a.x()) * k, a.y() + (b.y() - a.y()) * k)
        x -= ln
    return route[-1]
