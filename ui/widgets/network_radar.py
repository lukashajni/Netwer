"""Live network radar — an animated, "breathing" view of the local network.

The router sits at the centre, discovered devices orbit around it. Active
devices pulse, links glow and carry little packet dots when there's traffic, a
radar beam sweeps around, and hovering a node shows its details. It's the same
data as the static NetworkMap (gateway + device dicts), just rendered live.

Rendering is pure QPainter on a QTimer - no GPU, no extra deps - so it behaves
the same on every machine. When the widget isn't visible the timer stops, so it
costs nothing on other pages.
"""
from __future__ import annotations

import math
import random

from PyQt6.QtCore import Qt, QTimer, QRectF, QPointF, pyqtSignal
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QRadialGradient, QConicalGradient, QFont,
    QPainterPath,
)
from PyQt6.QtWidgets import QWidget, QToolTip, QSizePolicy

from app.theme import Theme
from app.resources import Icons

try:
    # Reuse the map's naming + icon logic so labels match the rest of the app.
    from ui.widgets.network_map import device_display_name, guess_device_icon
except Exception:                                   # pragma: no cover
    def device_display_name(dev):                   # minimal fallback
        return dev.get("hostname") or dev.get("ip", "?")

    def guess_device_icon(dev):
        return "devices"


""" A single glyph per device kind - drawn in the node with the icon font would
be ideal, but a compact unicode glyph keeps the radar crisp at small sizes. """
class _Node:
    """One device on the radar."""
    __slots__ = ("dev", "angle", "dist", "radius", "kind", "is_router",
                 "is_self", "is_unknown", "active", "traffic", "phase")

    def __init__(self, dev, angle, dist, radius, kind, is_router=False,
                 is_self=False, is_unknown=False, active=True, traffic=0.3):
        self.dev = dev
        self.angle = angle
        self.dist = dist
        self.radius = radius
        self.kind = kind
        self.is_router = is_router
        self.is_self = is_self
        self.is_unknown = is_unknown
        self.active = active
        self.traffic = traffic
        self.phase = random.uniform(0, math.tau)   # de-sync the pulses


class _Packet:
    __slots__ = ("node", "p", "speed")

    def __init__(self, node, p, speed):
        self.node = node
        self.p = p
        self.speed = speed


class NetworkRadar(QWidget):
    # Animated radar view. Feed it data via set_topology(), it renders live.

    # Emitted with the device dict when a node is clicked.
    node_clicked = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        """ Keep the minimum low so the widget never overflows a short card (the
        bottom of the circle used to get clipped), but let it expand to use
        whatever height the card actually offers. """
        self.setMinimumHeight(170)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        self._nodes: list[_Node] = []
        self._packets: list[_Packet] = []
        self._gateway = ""
        self._online = True
        self._t = 0.0            # global animation clock (seconds-ish)
        self._sweep = 0.0        # radar beam angle
        self._hover: _Node | None = None
        self._detailed = False   # big view: bigger nodes + per-device labels

        # ~60 fps timer, but only while visible.
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

    def set_detailed(self, on: bool) -> None:
        # Big-screen mode - larger nodes and a name under every device.
        self._detailed = bool(on)
        self.update()

    def _node_scale(self) -> float:
        """Nodes only scale up in the big Expand view. The dashboard card keeps
        the original fixed node sizes, which is the look we had before."""
        if not self._detailed:
            return 1.0
        _, _, radius = self._center_and_scale()
        return max(0.85, min(2.0, radius / 120.0))

    def _radius_of(self, node) -> float:
        return node.radius * self._node_scale()

    # -- Data --
    def set_topology(self, gateway, devices, router_vendor="", online=True):
        """Same signature as NetworkMap. "devices" is a list of dicts with
        ip / hostname / vendor / rtt_ms (and optionally is_self)."""
        self._gateway = gateway or ""
        self._online = online

        others = [d for d in (devices or []) if d.get("ip") != gateway]
        # Keep the radar readable - cap the number of orbiting nodes.
        others = others[:12]

        nodes: list[_Node] = []
        # Router at the centre.
        router_dev = {"ip": gateway, "hostname": "", "vendor": router_vendor,
                      "rtt_ms": 0}
        nodes.append(_Node(router_dev, 0, 0, 17, "dev_router",
                           is_router=True, active=online, traffic=0.7))

        n = max(1, len(others))
        for i, dev in enumerate(others):
            angle = -math.pi / 2 + i * (math.tau / n)   # start at top, go round
            """ Orbit radius as a fraction of the outer ring. Keep nodes well
            inside the outer ring (0.60–0.72) so their halos never reach the
            card edge and the whole radar reads as one clean circle. """
            rtt = dev.get("rtt_ms")
            base = 0.78 if self._detailed else 0.66
            if isinstance(rtt, (int, float)) and rtt > 0:
                lo, hi = (0.72, 0.86) if self._detailed else (0.60, 0.72)
                base = max(lo, min(hi, lo + rtt / 600.0))
            vendor = (dev.get("vendor") or "").lower()
            """ "Apple (private address)" means we did identify it - it just uses
            a randomized MAC - so it shouldn't be flagged as unidentified. """
            identified = bool(dev.get("kind")) or "(private address)" in vendor
            is_unknown = (not identified
                          and ("private" in vendor or "unknown" in vendor
                               or not vendor))
            # A tiny bit of deterministic variety in traffic so it feels alive.
            traffic = 0.15 + (hash(dev.get("ip", "")) % 70) / 100.0
            nodes.append(_Node(
                dev, angle, base, 11, guess_device_icon(dev),
                is_self=bool(dev.get("is_self")),
                is_unknown=is_unknown, active=True, traffic=traffic))

        self._nodes = nodes
        self._packets = []
        for nd in nodes:
            if not nd.is_router and nd.active and nd.traffic > 0.25:
                self._packets.append(_Packet(nd, random.random(), nd.traffic))
        self.update()

    def clear(self):
        self._nodes = []
        self._packets = []
        self.update()

    # -- Lifecycle: only animate while shown --
    def showEvent(self, e):
        super().showEvent(e)
        if not self._timer.isActive():
            self._timer.start()

    def hideEvent(self, e):
        super().hideEvent(e)
        self._timer.stop()

    def _tick(self):
        self._t += 0.016
        self._sweep = (self._sweep + 0.012) % math.tau
        for pk in self._packets:
            pk.p += 0.006 + pk.speed * 0.010
            if pk.p > 1.0:
                pk.p = 0.0
        self.update()

    # -- Geometry helpers --
    def _center_and_scale(self):
        w, h = self.width(), self.height()
        """ Reserve room at the bottom for the "Router" label, and a uniform
        margin so the outer ring + node halos never touch (or get clipped by)
        the card edges. The radar is a circle, so the radius is limited by
        whichever of width/height is smaller. """
        label_room = 38 if self._detailed else 18   # name (+IP) under nodes
        margin = 52 if self._detailed else 26       # halo + label allowance
        avail_w = w - margin * 2
        avail_h = h - margin * 2 - label_room
        radius = max(60, min(avail_w, avail_h) / 2)
        cx = w / 2
        """ Centre the circle in the space that's left, instead of pinning it to
        the top - otherwise a wide-but-short view leaves a big empty band
        under the radar. Clamped so the ring and its labels always fit. """
        lo = margin + radius
        hi = h - radius - label_room
        if self._detailed:
            # Big view: centre the circle in the space that's left.
            cy = (lo + hi) / 2 if hi > lo else lo
        else:
            # Dashboard card: original placement.
            cy = lo
        return cx, cy, radius

    def _node_pos(self, node) -> QPointF:
        cx, cy, scale = self._center_and_scale()
        if node.is_router:
            return QPointF(cx, cy)
        return QPointF(cx + math.cos(node.angle) * node.dist * scale,
                       cy + math.sin(node.angle) * node.dist * scale)

    def _node_color(self, node) -> QColor:
        if node.is_router or node.is_self:
            return QColor(Theme.SUCCESS)
        if not node.active:
            return QColor(Theme.TEXT_MUTED)
        if node.is_unknown:
            return QColor(Theme.DANGER)
        return QColor(Theme.ACCENT)

    # -- Painting --
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy, scale = self._center_and_scale()
        center = QPointF(cx, cy)

        if not self._nodes:
            p.setPen(QColor(Theme.TEXT_MUTED))
            p.setFont(QFont(Theme.FONT_FAMILY_PRIMARY, 11))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "Scanning the network…")
            p.end()
            return

        """ Concentric radar rings (drawn a touch inside `scale` so the outer
        ring sits comfortably within the card, never flush to the edge). """
        ring_max = scale * 0.94
        for i in range(1, 4):
            rr = ring_max * i / 3.0
            p.setPen(QPen(QColor(91, 140, 255, max(8, 26 - i * 6)), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(center, rr, rr)

        """Sweeping beam - a soft rotating wedge that fades out both around the
        arc and toward the edge."""
        p.save()
        p.setClipRect(self.rect())
        beam = QConicalGradient(center, -math.degrees(self._sweep))
        c0 = QColor(Theme.SUCCESS); c0.setAlpha(34)
        cq = QColor(Theme.SUCCESS); cq.setAlpha(20)
        cmid = QColor(Theme.SUCCESS); cmid.setAlpha(8)
        c1 = QColor(Theme.SUCCESS); c1.setAlpha(0)
        """A long, gradual tail - bright at the leading edge, fading out over a
        wide arc so there's no hard "pie slice" edge anywhere. """
        beam.setColorAt(0.0, c0)
        beam.setColorAt(0.05, cq)
        beam.setColorAt(0.14, cmid)
        beam.setColorAt(0.30, c1)
        beam.setColorAt(1.0, c1)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(beam))
        """ Paint the wedge in concentric bands with falling opacity, so it also
        fades toward the rim - a soft radar glow instead of a hard disc. """
        bands = 6
        for i in range(bands):
            r_out = ring_max * (i + 1) / bands
            r_in = ring_max * i / bands
            band = QPainterPath()
            band.addEllipse(center, r_out, r_out)
            if r_in > 0:
                inner = QPainterPath()
                inner.addEllipse(center, r_in, r_in)
                band = band.subtracted(inner)
            p.save()
            p.setClipPath(band)
            p.setOpacity(1.0 - (i / bands) * 0.75)
            p.drawEllipse(center, r_out, r_out)
            p.restore()
        p.setOpacity(1.0)
        p.restore()

        # Links + packets.
        for node in self._nodes:
            if node.is_router:
                continue
            np = self._node_pos(node)
            lit = node.active and node.traffic > 0
            if lit:
                a = 0.22 + 0.4 * abs(math.sin(self._t * 2 + node.angle)) * node.traffic
                pen = QPen(QColor(139, 109, 255, int(a * 255)), 1.6)
            else:
                pen = QPen(QColor(120, 140, 200, 26), 1)
            p.setPen(pen)
            p.drawLine(center, np)

        for pk in self._packets:
            np = self._node_pos(pk.node)
            x = cx + (np.x() - cx) * pk.p
            y = cy + (np.y() - cy) * pk.p
            p.setPen(Qt.PenStyle.NoPen)
            col = QColor(Theme.ACCENT_PURPLE); col.setAlpha(230)
            p.setBrush(col)
            p.drawEllipse(QPointF(x, y), 2.4, 2.4)

        # Nodes (halo + core + glyph).
        ns = self._node_scale()
        for node in self._nodes:
            np = self._node_pos(node)
            base = self._node_color(node)
            r = node.radius * ns

            if node.active:
                pulse = 1.0 + 0.16 * math.sin(self._t * 2.4 + node.phase)
                for ring, alpha in ((7 * ns, 26), (2 * ns, 46)):
                    halo = QColor(base); halo.setAlpha(alpha)
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(halo)
                    p.drawEllipse(np, r * pulse + ring, r * pulse + ring)

            # Core.
            core = QColor(base)
            if not node.active:
                core.setAlpha(140)
            p.setBrush(core)
            p.setPen(QPen(QColor(7, 10, 20, 200), 2))
            p.drawEllipse(np, r, r)

            # Highlight ring on hover.
            if node is self._hover:
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(QColor(Theme.TEXT_PRIMARY), 2))
                p.drawEllipse(np, r + 4, r + 4)

            """ A small bright centre dot instead of a glyph - the unicode
            squares/rectangles read as boxes at this size and looked broken.
            Clean dots keep the radar tidy, the label under each node says
            what the device actually is. """
            p.setPen(Qt.PenStyle.NoPen)
            inner = QColor("#ffffff")
            inner.setAlpha(235 if node.active else 150)
            p.setBrush(inner)
            p.drawEllipse(np, max(2.0, r * 0.30), max(2.0, r * 0.30))

            # Labels: the router always, every device in the big view.
            label = None
            if node.is_router:
                label = "Router"
            elif self._detailed:
                label = device_display_name(node.dev)
                if len(label) > 14:
                    label = label[:13] + "\u2026"
            if label:
                p.setPen(QColor(Theme.TEXT_PRIMARY if node.is_router
                                else Theme.TEXT_SECONDARY))
                p.setFont(QFont(Theme.FONT_FAMILY_PRIMARY,
                                10 if self._detailed else 9,
                                QFont.Weight.DemiBold))
                p.drawText(QRectF(np.x() - 80, np.y() + r + 4, 160, 16),
                           Qt.AlignmentFlag.AlignHCenter, label)
                if self._detailed and not node.is_router:
                    p.setPen(QColor(Theme.TEXT_MUTED))
                    p.setFont(QFont(Theme.FONT_MONO, 8))
                    p.drawText(QRectF(np.x() - 80, np.y() + r + 19, 160, 14),
                               Qt.AlignmentFlag.AlignHCenter,
                               node.dev.get("ip", ""))

        p.end()

    # -- Hover tooltip --
    def _node_at(self, pos) -> _Node | None:
        for node in self._nodes:
            np = self._node_pos(node)
            if math.hypot(pos.x() - np.x(), pos.y() - np.y()) <= self._radius_of(node) + 4:
                return node
        return None

    def mouseMoveEvent(self, event):
        hit = self._node_at(event.position())
        if hit is not self._hover:
            self._hover = hit
            self.setCursor(Qt.CursorShape.PointingHandCursor if hit
                           else Qt.CursorShape.ArrowCursor)
            self.update()
        if hit:
            dev = hit.dev
            name = "Router" if hit.is_router else device_display_name(dev)
            ip = dev.get("ip", "")
            vendor = dev.get("vendor") or ""
            rtt = dev.get("rtt_ms")
            lines = [f"<b>{name}</b>"]
            sub = ip
            if vendor and vendor.lower() not in ("unknown", ""):
                sub += f" · {vendor}"
            lines.append(sub)
            if isinstance(rtt, (int, float)) and rtt > 0:
                lines.append(f"{round(rtt)} ms")
            QToolTip.showText(event.globalPosition().toPoint(),
                              "<br>".join(lines), self)
        else:
            QToolTip.hideText()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            hit = self._node_at(event.position())
            if hit is not None:
                self.node_clicked.emit(hit.dev)

    def leaveEvent(self, event):
        self._hover = None
        QToolTip.hideText()
        self.update()
