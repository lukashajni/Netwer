"""
NETWER — Traceroute page.

Traces the network path to a host and plots it on a world map.

Layout: the map sits on the left and the hop list on the right, both visible
at once (stacking them vertically pushed the map below the window, where
there was no way to scroll to it).

Flow:
  1. netwer_core.traceroute_stream streams one event per hop → rows appear live
  2. when the trace finishes, the public hops are geolocated in ONE background
     call (never inline, or a slow provider would stall the trace)
  3. the located hops are handed to TracerouteMap, which animates the path
"""

import html

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QComboBox, QFrame, QScrollArea
)

from app.theme import Theme
from app.resources import Icons
from app.activity import activity
from ui.pages.base_page import BasePage
from ui.widgets.card import Card
from ui.widgets.traceroute_map import TracerouteMap
from workers import StreamWorker, OneshotWorker


HOP_OPTIONS = [("Auto", 0), ("Max hops: 15", 15), ("Max hops: 30", 30),
               ("Max hops: 64", 64)]

# Colour per hop kind, matching the map.
KIND_COLORS = {
    "local": "SUCCESS", "isp": "ACCENT",
    "transit": "ACCENT_PURPLE", "dest": "WARNING",
}


class TraceroutePage(BasePage):
    def __init__(self, core, parent=None, embedded=False):
        super().__init__(core, parent, embedded=embedded)
        self.core = core
        self._worker = None
        self._running = False
        self._resolved = None
        self._reached = False
        self._hop_count = 0
        self._hops = []          # every hop, with lat/lon once geolocated
        self._home = None        # our own {lat, lon, city}, if known

        self._build_toolbar()
        self._build_status()
        self._build_split()

    # ══════════════════════════════════════════════════════════
    # Build
    # ══════════════════════════════════════════════════════════
    def _build_toolbar(self):
        row = QHBoxLayout()
        row.setSpacing(8)

        self.input = QLineEdit()
        self.input.setPlaceholderText("Domain or IP (e.g. google.com)")
        self.input.setStyleSheet(
            f"QLineEdit {{ background: {Theme.GLASS_INPUT}; color: {Theme.TEXT_BODY};"
            f"border: 1px solid {Theme.GLASS_BORDER}; border-radius: {Theme.RADIUS_CONTROL}px;"
            f"padding: 9px 13px; font-family: {Theme.FONT_MONO};"
            f"font-size: {Theme.FONT_SIZE_BODY}px; }}"
            f"QLineEdit:focus {{ border-color: {Theme.GLASS_BORDER_HI}; }}")
        self.input.returnPressed.connect(self._toggle)
        row.addWidget(self.input, 1)

        self.hops_combo = QComboBox()
        for label, value in HOP_OPTIONS:
            self.hops_combo.addItem(label, value)
        self.hops_combo.setCurrentIndex(0)   # default: Auto
        self.hops_combo.setStyleSheet(
            f"QComboBox {{ background: {Theme.GLASS_INPUT}; color: {Theme.TEXT_BODY};"
            f"border: 1px solid {Theme.GLASS_BORDER}; border-radius: {Theme.RADIUS_CONTROL}px;"
            f"padding: 9px 13px; font-size: {Theme.FONT_SIZE_SMALL}px; }}"
            f"QComboBox::drop-down {{ border: none; }}")
        row.addWidget(self.hops_combo)

        self.btn = QPushButton("  Trace")
        self.btn.setIcon(Icons.get("route", "#ffffff"))
        self.btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn.clicked.connect(self._toggle)
        self._style_button(running=False)
        row.addWidget(self.btn)

        self.body_layout.addLayout(row)

    def _style_button(self, running):
        bg = Theme.DANGER if running else Theme.GRAD_ACCENT
        self.btn.setStyleSheet(
            f"QPushButton {{ background: {bg}; color: white; border: none;"
            f"border-radius: {Theme.RADIUS_CONTROL}px; padding: 10px 22px;"
            f"font-weight: 600; font-size: {Theme.FONT_SIZE_SMALL}px; }}"
            f"QPushButton:hover {{ background: {bg}; }}")

    def _build_status(self):
        card = Card("")
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        self.status_left = QLabel("Ready to trace")
        self.status_left.setStyleSheet(
            f"color: {Theme.TEXT_SECONDARY};"
            f"font-size: {Theme.FONT_SIZE_BODY}px; background: transparent;")
        row.addWidget(self.status_left)
        row.addStretch()
        self.status_right = QLabel("")
        self.status_right.setStyleSheet(
            f"color: {Theme.SUCCESS};"
            f"font-size: {Theme.FONT_SIZE_SMALL}px; background: transparent;")
        row.addWidget(self.status_right)
        card.content_layout.addLayout(row)
        self.body_layout.addWidget(card)

    def _build_split(self):
        """Map left, hop list right — both on screen at the same time."""
        # ── Map ────────────────────────────────────────────────
        map_card = Card("Path on map", "route")
        self.map = TracerouteMap()
        map_card.content_layout.addWidget(self.map, 1)

        # ── Hops ───────────────────────────────────────────────
        hops_card = Card("Hops", "list")
        header = QHBoxLayout()
        header.setContentsMargins(10, 0, 10, 6)
        for text, stretch, width in (("Hop", 0, 38), ("Address", 1, 0),
                                     ("RTT", 0, 0)):
            lbl = QLabel(text)
            lbl.setAlignment((Qt.AlignmentFlag.AlignRight if text == "RTT"
                              else Qt.AlignmentFlag.AlignLeft)
                             | Qt.AlignmentFlag.AlignVCenter)
            lbl.setStyleSheet(
                f"color: {Theme.TEXT_FAINT}; font-size: 11px; font-weight: 600;"
                f"letter-spacing: 0.5px; background: transparent;")
            if width:
                lbl.setFixedWidth(width)
            header.addWidget(lbl, stretch)
        head_wrap = QFrame()
        head_wrap.setObjectName("TrHead")
        head_wrap.setStyleSheet(
            f"#TrHead {{ border-bottom: 1px solid {Theme.BORDER}; }}")
        head_wrap.setLayout(header)
        hops_card.content_layout.addWidget(head_wrap)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent;")
        self._rows_host = QWidget()
        self._rows_host.setStyleSheet("background: transparent;")
        self._rows_layout = QVBoxLayout(self._rows_host)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(0)
        self._rows_layout.addStretch(1)
        scroll.setWidget(self._rows_host)
        hops_card.content_layout.addWidget(scroll, 1)
        self._empty = None
        self._show_empty("Enter a destination and press Trace.")

        split = QHBoxLayout()
        split.setSpacing(12)
        split.addWidget(map_card, 3)
        split.addWidget(hops_card, 2)
        self.body_layout.addLayout(split, 1)

    # ══════════════════════════════════════════════════════════
    # Rows
    # ══════════════════════════════════════════════════════════
    def _show_empty(self, text):
        self._clear_rows()
        self._empty = QLabel(text)
        self._empty.setStyleSheet(
            f"color: {Theme.TEXT_MUTED}; font-size: {Theme.FONT_SIZE_SMALL}px;"
            f"padding: 18px 12px; background: transparent;")
        self._rows_layout.insertWidget(0, self._empty)

    def _clear_rows(self):
        while self._rows_layout.count() > 1:
            item = self._rows_layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        self._empty = None

    def _add_row(self, ttl, ip, hostname, avg, timeout=False,
                 dest=False, kind="transit", city="", city_approx=False):
        row = QFrame()
        row.setStyleSheet(
            f"QFrame {{ background: transparent;"
            f"border-bottom: 1px solid {Theme.BORDER}; }}"
            f"QFrame:hover {{ background: {Theme.BG_CARD_HOVER}; }}")
        rl = QHBoxLayout(row)
        rl.setContentsMargins(10, 7, 10, 7)
        rl.setSpacing(8)

        dot_color = (Theme.DANGER if timeout
                     else getattr(Theme, KIND_COLORS.get(kind, "ACCENT_PURPLE")))
        dot = QLabel("\u25CF")
        dot.setFixedWidth(12)
        dot.setStyleSheet(
            f"color: {dot_color}; font-size: 9px; background: transparent;")
        rl.addWidget(dot)

        n = QLabel(str(ttl))
        n.setFixedWidth(20)
        n.setStyleSheet(
            f"color: {Theme.TEXT_MUTED}; font-family: {Theme.FONT_MONO};"
            f"font-size: 11px; background: transparent;")
        rl.addWidget(n)

        sub_parts = []
        if hostname and hostname != ip:
            sub_parts.append(hostname)
        elif city and not city_approx:
            # Only show a real, known city (from the live lookup) — never the
            # coarse offline "Europe/United States" placeholders.
            sub_parts.append(city)
        if dest:
            sub_parts.append("destination")
        sub = " \u00b7 ".join(sub_parts)

        ip_color = Theme.DANGER if timeout else Theme.TEXT_BODY
        text = (f"<span style='color:{ip_color};"
                f"font-family:{Theme.FONT_MONO}; font-size:11px;'>"
                f"{html.escape(ip)}</span>")
        if sub:
            text += (f"<br><span style='color:{Theme.TEXT_MUTED};"
                     f"font-size:11px;'>{html.escape(sub)}</span>")
        info = QLabel(text)
        info.setStyleSheet("background: transparent;")
        rl.addWidget(info, 1)

        if timeout:
            rtt_color, rtt_text = Theme.DANGER, "\u2014"
        else:
            rtt_text = f"{avg} ms" if avg is not None else "\u2014"
            rtt_color = (Theme.SUCCESS if (avg or 0) < 20 else
                         Theme.WARNING if (avg or 0) < 50 else Theme.DANGER)
        rtt = QLabel(rtt_text)
        rtt.setAlignment(Qt.AlignmentFlag.AlignRight
                         | Qt.AlignmentFlag.AlignVCenter)
        rtt.setStyleSheet(
            f"color: {rtt_color}; font-family: {Theme.FONT_MONO};"
            f"font-size: 11px; background: transparent;")
        rl.addWidget(rtt)

        self._rows_layout.insertWidget(self._rows_layout.count() - 1, row)

    # ══════════════════════════════════════════════════════════
    # Run
    # ══════════════════════════════════════════════════════════
    def _toggle(self):
        self._stop() if self._running else self._start()

    def _start(self):
        target = self.input.text().strip()
        if not target:
            self.status_left.setText("Enter a destination first.")
            return

        self._ensure_home()
        self._running = True
        self._resolved = None
        self._reached = False
        self._hop_count = 0
        self._hops = []
        # Bump the trace id so any still-running geolocation worker from a
        # previous trace is ignored when it finishes (that stale result was
        # mixing old hops — Zagreb/Osijek/Mountain View — into a new trace).
        self._trace_id = getattr(self, "_trace_id", 0) + 1

        self.btn.setText("  Stop")
        self.btn.setIcon(Icons.get("stop", "#ffffff"))
        self._style_button(running=True)
        self.input.setEnabled(False)
        self.hops_combo.setEnabled(False)

        self._clear_rows()
        self.map.clear()
        self.map.set_status("Tracing\u2026")
        self.status_left.setText(f"Tracing {target}\u2026")
        self.status_right.setText("")

        max_hops = self.hops_combo.currentData()
        auto = (max_hops == 0)
        if auto:
            max_hops = 30   # ceiling; the trace stops early at the destination
        w = StreamWorker(self.core.traceroute_stream, target, max_hops, auto)
        w.result.connect(self._on_event)
        w.error.connect(self._on_error)
        w.done.connect(self._on_finished)
        self.register_worker(w)
        self._worker = w
        w.start()

    def _stop(self):
        if self._worker is not None:
            self._worker.stop()
        self._running = False
        self.btn.setText("  Trace")
        self.btn.setIcon(Icons.get("route", "#ffffff"))
        self._style_button(running=False)
        self.input.setEnabled(True)
        self.hops_combo.setEnabled(True)

    def _locate_hop(self, hop):
        """Locate one hop in the background and redraw the path. Keeps the
        map filling in live as the trace progresses, using real ip-api.com
        city data (offline estimate only as a last resort)."""
        tid = getattr(self, "_trace_id", 0)
        if hop["local"]:
            # Pin to our own location if known; else defer to the anchor pass.
            if self._home and self._home.get("lat") is not None:
                hop["lat"] = self._home["lat"]
                hop["lon"] = self._home["lon"]
                hop["city"] = self._home.get("city") or "Local network"
                self._redraw()
            return
        try:
            w = OneshotWorker(self.core.geolocate_ip, hop["ip"])
            w.result.connect(
                lambda g, h=hop, t=tid: self._on_hop_located(h, g, t))
            w.error.connect(lambda e: None)
            self.register_worker(w)
            w.start()
        except Exception:
            pass

    def _on_hop_located(self, hop, geo, tid):
        if tid != getattr(self, "_trace_id", 0):
            return   # from a previous trace
        if isinstance(geo, dict) and geo.get("lat") is not None:
            hop["lat"] = geo["lat"]
            hop["lon"] = geo["lon"]
            hop["approx"] = geo.get("approx", False)
            hop["city"] = "" if hop["approx"] else geo.get("city", "")
            self._redraw()

    def _redraw(self):
        """Anchor any not-yet-located local hops to the first known point,
        then draw the current path (called as hops are located)."""
        anchor = None
        if self._home and self._home.get("lat") is not None:
            anchor = (self._home["lat"], self._home["lon"],
                      self._home.get("city") or "Local network")
        else:
            first = next((h for h in self._hops
                          if not h["local"] and h["lat"] is not None), None)
            if first:
                anchor = (first["lat"], first["lon"], "Local network")
        if anchor:
            for h in self._hops:
                if h["local"] and h["lat"] is None:
                    h["lat"], h["lon"], h["city"] = anchor
                    h["approx"] = False
        if any(h["lat"] is not None for h in self._hops):
            self.map.set_status(None)
            self.map.set_hops(self._hops)

    def _on_error(self, msg):
        self.status_left.setText(str(msg))
        self.map.set_status(str(msg))
        self._stop()

    def _on_event(self, d):
        if d.get("error"):
            self._on_error(d["error"])
            return
        if d.get("resolved"):
            self._resolved = d["resolved"]
            self.status_left.setText(
                f"Resolved {d.get('target','')} \u2192 {d['resolved']}")
            return
        if d.get("done"):
            return

        ttl = d.get("ttl")
        if ttl is None:
            return
        self._hop_count = max(self._hop_count, ttl)

        if d.get("timeout"):
            self._add_row(ttl, "\u2014", "Request timed out", None,
                          timeout=True)
            return

        ip = d.get("ip", "")
        hostname = d.get("hostname", ip) or ip
        avg = d.get("avg")
        is_dest = self._resolved is not None and ip == self._resolved
        local = self._is_local(ip)
        kind = ("dest" if is_dest else
                "local" if (local and ttl <= 1) else
                "isp" if local else "transit")
        if is_dest:
            self._reached = True

        self._add_row(ttl, ip, hostname, avg, dest=is_dest, kind=kind)
        hop = {"n": ttl, "ip": ip, "ms": avg or 0, "kind": kind,
               "local": local, "city": "", "lat": None, "lon": None,
               "approx": False}
        self._hops.append(hop)
        # Geolocate this hop in the background and plot the path as hops come
        # in. Local hops are pinned to our own location; public hops get a
        # real city from ip-api.com. Cheap and non-blocking, one lookup/hop.
        self._locate_hop(hop)

    def _on_finished(self):
        if self._running:
            if self._reached:
                self.status_right.setText(
                    f"\u2713 Reached in {self._hop_count} hops")
            else:
                self.status_right.setText(
                    f"Stopped after {self._hop_count} hops")
            if self._hop_count == 0:
                self._show_empty("No hops returned.")
            activity.add("Traceroute",
                         f"{self.input.text().strip()} \u00b7 "
                         f"{self._hop_count} hops", kind="success")
            self._finalize_map()
        self._worker = None
        self._stop()

    # ══════════════════════════════════════════════════════════
    # Map
    # ══════════════════════════════════════════════════════════
    def _is_local(self, ip):
        try:
            return self.core._is_private_ip(ip)
        except Exception:
            return False

    def _ensure_home(self):
        """Fetch our own approximate location once, in the background."""
        if self._home is not None or getattr(self, "_home_pending", False):
            return
        self._home_pending = True
        try:
            w = OneshotWorker(self.core.geolocate_me)
            w.result.connect(self._on_home)
            self.register_worker(w)
            w.start()
        except Exception:
            pass

    def _on_home(self, geo):
        if isinstance(geo, dict) and geo.get("lat") is not None:
            self._home = geo

    def _finalize_map(self):
        """Called when the trace ends. Fill in any hop the live per-hop
        lookup didn't manage to locate (offline region estimate, plain dot),
        anchor local hops, and draw the final path once."""
        # Offline fill for any public hop still without a location.
        for h in self._hops:
            if not h["local"] and h["lat"] is None:
                try:
                    g = self.core._offline_geolocate(h["ip"])
                except Exception:
                    g = None
                if g:
                    h["lat"], h["lon"] = g["lat"], g["lon"]
                    h["approx"] = True
                    h["city"] = ""
        # Anchor local hops.
        anchor = None
        if self._home and self._home.get("lat") is not None:
            anchor = (self._home["lat"], self._home["lon"],
                      self._home.get("city") or "Local network")
        else:
            first = next((h for h in self._hops
                          if not h["local"] and h["lat"] is not None), None)
            if first:
                anchor = (first["lat"], first["lon"], "Local network")
        if anchor:
            for h in self._hops:
                if h["local"] and h["lat"] is None:
                    h["lat"], h["lon"], h["city"] = anchor
                    h["approx"] = False

        located = [h for h in self._hops if h["lat"] is not None]
        if not located:
            self.map.set_status("Couldn't place any hops on the map.")
            return
        self.map.set_status(None)
        self.map.set_hops(self._hops)

    # ══════════════════════════════════════════════════════════
    # Lifecycle
    # ══════════════════════════════════════════════════════════
    def on_enter(self):
        self._ensure_home()

    def preload(self):
        self._ensure_home()

    def on_leave(self):
        self._stop()
        super().on_leave()
