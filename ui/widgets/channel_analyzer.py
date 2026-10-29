import html

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from app.resources import Icons
from app.theme import Theme
from core import channel_analysis as ca
from ui.widgets.card import Card

OTHERS = ["#a78bfa", "#fbbf24", "#2dd4bf", "#f87171", "#94a3b8", "#fb923c", "#60a5fa", "#f472b6"]
LEVEL_COLOR = {"Low": "SUCCESS", "Medium": "WARNING", "High": "DANGER"}
DBM_LINES = (-30, -50, -70, -90)
BOTTOM = 62


def _level_color(level: str) -> QColor:
    return QColor(getattr(Theme, LEVEL_COLOR[level]))


class _Chart(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(330)
        self.setMouseTracking(True)
        self.band, self.aps, self.own, self.analysis = "2.4 GHz", [], "", None
        self._hits = []
        self._text = "Press Rescan to look for nearby networks"

    def set_data(self, band, aps, own, analysis, text=""):
        self.band, self.aps, self.own, self.analysis = band, aps, own, analysis
        if text:
            self._text = text
        self.update()

    # -- geometry --
    def _plot(self):
        return QRectF(62, 14, self.width() - 74, self.height() - 14 - BOTTOM)

    def _y(self, rssi, plot):
        f = min(max((rssi + 95) / 65.0, 0.03), 1.0)
        return plot.bottom() - f * plot.height() * 0.92

    def _slots(self):
        return ca.channel_list(self.band)

    def _x_slot(self, ch, plot):
        slots = self._slots()
        return plot.left() + (slots.index(ch) + 0.5) * plot.width() / len(slots) if ch in slots else None

    def _x_mhz(self, mhz, plot):
        lo, hi = 2399.5, 2484.5
        return plot.left() + (mhz - lo) / (hi - lo) * plot.width()

    def _span_x(self, lo_mhz, hi_mhz, plot):
        return self._x_mhz(lo_mhz, plot), self._x_mhz(hi_mhz, plot)

    def _block_x(self, chans, plot):
        slots = self._slots()
        idx = [slots.index(c) for c in chans if c in slots]
        if not idx:
            return None
        w = plot.width() / len(slots)
        return plot.left() + min(idx) * w + 1, plot.left() + (max(idx) + 1) * w - 1

    def _ap_x(self, ap, plot):
        if self.band == "2.4 GHz":
            lo, hi = ca.ap_span(ap)
            return self._span_x(lo, hi, plot)
        w = ap.get("width", 20)
        group = next((g for g in ca.groups(self.band, w) if ap["channel"] in g), [ap["channel"]])
        return self._block_x(group, plot)

    # -- painting --
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        plot = self._plot()
        small = QFont(Theme.FONT_FAMILY_PRIMARY, 8)
        p.setFont(small)
        self._hits = []

        for dbm in DBM_LINES:
            y = self._y(dbm, plot)
            p.setPen(QPen(QColor(Theme.BORDER), 1))
            p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            p.setPen(QColor(Theme.TEXT_MUTED))
            p.drawText(QRectF(0, y - 8, plot.left() - 6, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, str(dbm))
        p.drawText(QRectF(0, plot.bottom() + 2, plot.left() - 6, 14), Qt.AlignmentFlag.AlignRight, "dBm")

        aps = sorted(self.aps, key=lambda a: a["rssi"])
        if not aps:
            p.setPen(QColor(Theme.TEXT_MUTED))
            p.setFont(QFont(Theme.FONT_FAMILY_PRIMARY, 10))
            p.drawText(plot, Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self._text)
            p.end()
            return

        # best-channel highlight sits behind the networks
        if self.analysis:
            self._draw_best(p, plot)

        colors, label_rects = {}, []
        for i, ap in enumerate(sorted(aps, key=lambda a: -a["rssi"])):
            colors[ap["bssid"]] = QColor(OTHERS[i % len(OTHERS)])
        for ap in aps:
            xs = self._ap_x(ap, plot)
            if xs is None:
                continue
            own = ap["bssid"] == self.own
            col = QColor(Theme.ACCENT) if own else colors[ap["bssid"]]
            top = self._y(ap["rssi"], plot)
            fill = QColor(col)
            fill.setAlpha(80 if own else 38)
            p.setPen(QPen(col, 2.4 if own else 1.3))
            p.setBrush(fill)
            path = QPainterPath()
            if self.band == "2.4 GHz":
                path.moveTo(xs[0], plot.bottom())
                path.quadTo((xs[0] + xs[1]) / 2, plot.bottom() - 2 * (plot.bottom() - top), xs[1], plot.bottom())
                path.closeSubpath()
            else:
                path.addRoundedRect(QRectF(xs[0], top, xs[1] - xs[0], plot.bottom() - top + 8), 6, 6)
            p.drawPath(path)
            self._hits.append((ap, xs, top, plot.bottom()))
        # labels for your network and the strongest others
        shown = [a for a in sorted(aps, key=lambda a: -a["rssi"]) if a["bssid"] != self.own][:4]
        own_ap = next((a for a in aps if a["bssid"] == self.own), None)
        p.setFont(QFont(Theme.FONT_FAMILY_PRIMARY, 8, QFont.Weight.DemiBold))
        for ap in ([own_ap] if own_ap else []) + shown:
            xs = self._ap_x(ap, plot)
            if xs is None:
                continue
            text = "You" if ap is own_ap else ap["ssid"][:16]
            tw = p.fontMetrics().horizontalAdvance(text) + 8
            rect = QRectF((xs[0] + xs[1]) / 2 - tw / 2, self._y(ap["rssi"], plot) - 18, tw, 15)
            if rect.left() < plot.left() or rect.right() > plot.right() + 8 or any(rect.intersects(r) for r in label_rects):
                continue
            label_rects.append(rect)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(Theme.BG_CARD))
            p.drawRoundedRect(rect, 4, 4)
            p.setPen(QColor(Theme.ACCENT) if ap is own_ap else colors[ap["bssid"]])
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

        self._draw_axis(p, plot, small)
        p.end()

    def _draw_best(self, p, plot):
        best = self.analysis["best"]
        if self.band == "2.4 GHz":
            xs = self._span_x(*ca.group_span(self.band, best["chans"]), plot)
        else:
            xs = self._block_x(best["chans"], plot)
        if not xs:
            return
        green = QColor(Theme.SUCCESS)
        fill = QColor(green)
        fill.setAlpha(34)
        p.setPen(QPen(green, 1, Qt.PenStyle.DashLine))
        p.setBrush(fill)
        p.drawRoundedRect(QRectF(xs[0], plot.top(), xs[1] - xs[0], plot.height()), 6, 6)
        p.setPen(green)
        p.setFont(QFont(Theme.FONT_FAMILY_PRIMARY, 8, QFont.Weight.Bold))
        p.drawText(QRectF(xs[0], plot.top() + 3, xs[1] - xs[0], 14), Qt.AlignmentFlag.AlignCenter, "Best")

    def _draw_axis(self, p, plot, small):
        p.setFont(small)
        slots = self._slots()
        step = 1 if len(slots) <= 26 else 4
        strip = (self.analysis or {}).get("strip", {})
        for i, ch in enumerate(slots):
            x = self._x_mhz(2407 + 5 * ch, plot) if self.band == "2.4 GHz" else plot.left() + (i + 0.5) * plot.width() / len(slots)
            if i % step == 0:
                p.setPen(QColor(Theme.TEXT_SECONDARY))
                p.drawText(QRectF(x - 16, plot.bottom() + 10, 32, 14), Qt.AlignmentFlag.AlignCenter, str(ch))
            if ch in strip:
                w = plot.width() / (17 if self.band == "2.4 GHz" else len(slots)) * 0.84
                col = _level_color(ca.level(strip[ch]))
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(col)
                p.drawRoundedRect(QRectF(x - w / 2, plot.bottom() + 30, w, 7), 3, 3)
        p.setPen(QColor(Theme.TEXT_MUTED))
        p.drawText(QRectF(0, plot.bottom() + 27, plot.left() - 6, 14), Qt.AlignmentFlag.AlignRight, "Crowding")
        if self.band == "5 GHz":
            dfs = [i for i, c in enumerate(slots) if 52 <= c <= 144]
            if dfs:
                w = plot.width() / len(slots)
                p.setPen(QColor(Theme.WARNING))
                p.drawText(QRectF(plot.left() + dfs[0] * w, plot.bottom() + 44, (dfs[-1] - dfs[0] + 1) * w, 14),
                           Qt.AlignmentFlag.AlignCenter, "DFS channels (radar checks)")

    # -- hover --
    def mouseMoveEvent(self, e):
        pos = e.position()
        found = []
        for ap, xs, top, base in self._hits:
            if not xs[0] <= pos.x() <= xs[1]:
                continue
            if self.band == "2.4 GHz":
                half = (xs[1] - xs[0]) / 2
                k = 1 - ((pos.x() - (xs[0] + half)) / half) ** 2
                inside = base - pos.y() <= (base - top) * k and pos.y() <= base
            else:
                inside = top <= pos.y() <= base
            if inside:
                found.append(ap)
        if not found:
            QToolTip.hideText()
            return
        ap = max(found, key=lambda a: a["rssi"])
        auth = f" &middot; {html.escape(ap['auth'])}" if ap.get("auth") else ""
        QToolTip.showText(e.globalPosition().toPoint(),
                          f"<b>{html.escape(ap['ssid'])}</b>{auth}<br>BSSID {ap['bssid']}<br>Channel {ap['channel']} "
                          f"&middot; about {ap.get('width', 20)} MHz<br>Signal {ap['rssi']} dBm", self)


class ChannelAnalyzer(Card):
    rescan_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("Channel Analyzer", "wifi", parent)
        self._aps, self._own, self._own_channel, self._conn_band = [], "", None, ""
        self._band = "2.4 GHz"
        self._tabs = {}

        self._status = QLabel("")
        self._status.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: {Theme.FONT_SIZE_TINY}px; background: transparent;")
        self.header_layout.addWidget(self._status)
        for band in ca.BANDS:
            b = QPushButton(band)
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(
                f"QPushButton {{ background: {Theme.BG_ELEVATED}; color: {Theme.TEXT_SECONDARY}; border: 1px solid {Theme.BORDER_STRONG};"
                f"border-radius: 6px; padding: 4px 12px; font-size: {Theme.FONT_SIZE_TINY}px; font-weight: 600; }}"
                f"QPushButton:checked {{ background: {Theme.ACCENT}; color: white; border-color: transparent; }}")
            b.clicked.connect(lambda _=False, x=band: self._select(x))
            self._tabs[band] = b
            self.header_layout.addWidget(b)
        self.btn_rescan = QPushButton("  Rescan")
        self.btn_rescan.setIcon(Icons.get("refresh", "#ffffff"))
        self.btn_rescan.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_rescan.setStyleSheet(
            f"QPushButton {{ background: {Theme.ACCENT}; color: white; border: none; border-radius: 6px; padding: 4px 12px;"
            f"font-size: {Theme.FONT_SIZE_TINY}px; font-weight: 600; }}"
            f"QPushButton:hover {{ background: {Theme.ACCENT_HOVER}; }}"
            f"QPushButton:disabled {{ background: {Theme.BG_ELEVATED}; color: {Theme.TEXT_FAINT}; }}")
        self.btn_rescan.clicked.connect(self.rescan_requested)
        self.header_layout.addWidget(self.btn_rescan)

        body = QHBoxLayout()
        body.setSpacing(Theme.GAP)
        left = QVBoxLayout()
        self._hint = QLabel("")
        self._hint.setWordWrap(True)
        self._hint.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: {Theme.FONT_SIZE_TINY}px; background: transparent;")
        left.addWidget(self._hint)
        self.chart = _Chart()
        left.addWidget(self.chart, 1)
        body.addLayout(left, 3)
        body.addWidget(self._build_reco(), 1)
        self.content_layout.addLayout(body)
        self._select("2.4 GHz")

    def _build_reco(self):
        f = QFrame()
        f.setObjectName("Reco")
        f.setMinimumWidth(270)
        f.setMaximumWidth(330)
        f.setStyleSheet(f"#Reco {{ background: {Theme.GLASS_INPUT}; border: 1px solid {Theme.GLASS_BORDER}; border-radius: 12px; }}"
                        f"#Reco QLabel {{ background: transparent; border: none; }}")
        lay = QVBoxLayout(f)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)
        cap = QLabel("Recommended channel")
        cap.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: {Theme.FONT_SIZE_TINY}px;")
        self._reco_title = QLabel("\u2014")
        self._reco_title.setStyleSheet(f"color: {Theme.SUCCESS}; font-size: 26px; font-weight: 700;")
        self._reco_text = QLabel("")
        self._reco_text.setWordWrap(True)
        self._reco_text.setStyleSheet(f"color: {Theme.TEXT_BODY}; font-size: {Theme.FONT_SIZE_SMALL}px;")
        self._cur_row = QLabel("")
        self._cur_row.setTextFormat(Qt.TextFormat.RichText)
        self._cur_row.setWordWrap(True)
        self._cur_row.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-size: {Theme.FONT_SIZE_SMALL}px;")
        self._steps = QLabel("")
        self._steps.setWordWrap(True)
        self._steps.setTextFormat(Qt.TextFormat.RichText)
        self._steps.setStyleSheet(f"color: {Theme.TEXT_BODY}; font-size: {Theme.FONT_SIZE_SMALL}px;")
        note = QLabel("Based on signal strength and overlap of the networks in this scan. Width is estimated.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {Theme.TEXT_FAINT}; font-size: 10px;")
        for w in (cap, self._reco_title, self._reco_text, self._cur_row, self._steps):
            lay.addWidget(w)
        lay.addStretch(1)
        lay.addWidget(note)
        return f

    # -- public --
    def set_scanning(self, scanning: bool):
        self.btn_rescan.setEnabled(not scanning)
        self._status.setText("Scanning\u2026" if scanning else self._status.text())

    def set_connection(self, bssid: str, channel, band: str):
        self._own = (bssid or "").upper()
        try:
            self._own_channel = int(channel)
        except (TypeError, ValueError):
            self._own_channel = None
        self._conn_band = band if band in ca.BANDS else ""
        if self._aps:
            self._refresh()

    def set_scan(self, aps: list):
        import time
        self._aps = aps or []
        self._status.setText("Scanned just now" if self._aps else "")
        self._scan_time = time.time()
        have = {a["band"] for a in self._aps}
        self._tabs["6 GHz"].setVisible("6 GHz" in have)
        if self._band not in have:
            pick = self._conn_band if self._conn_band in have else next((b for b in ca.BANDS if b in have), self._band)
            self._band = pick
        self._select(self._band)

    # -- internals --
    def _select(self, band):
        self._band = band
        for b, btn in self._tabs.items():
            btn.setChecked(b == band)
        self._refresh()

    def _refresh(self):
        own_ap = next((a for a in self._aps if a["bssid"] == self._own), None)
        own_here = own_ap and own_ap["band"] == self._band
        channel = own_ap["channel"] if own_here else (self._own_channel if self._conn_band == self._band else None)
        width = own_ap.get("width", 20) if own_here else 80
        analysis = ca.analyze(self._aps, self._band, self._own, channel, width) if self._aps else None
        aps = [a for a in self._aps if a["band"] == self._band]
        self.chart.set_data(self._band, aps, self._own, analysis,
                            "" if self._aps else "Press Rescan to look for nearby networks")
        self._hint.setText("Taller means stronger. Where shapes overlap, the networks slow each other down." if self._band == "2.4 GHz"
                           else "Each block is one network; its width is the spectrum it uses (20, 40 or 80 MHz).")
        self._fill_reco(analysis, bool(aps))

    def _fill_reco(self, a, has_aps):
        if not a:
            self._reco_title.setText("\u2014")
            self._reco_text.setText("Scan to see nearby networks." if not self._aps else f"No networks seen on {self._band}.")
            self._cur_row.setText("")
            self._steps.setText("")
            return
        best, cur = a["best"], a["current"]
        # change the channel only when it clearly helps, otherwise show the one in use
        self._reco_title.setText(best["label"] if a["change"] or not cur else cur["label"])
        dfs = " These are DFS channels, so the router may pause briefly if it detects radar." if best["dfs"] else ""
        if cur and a["change"]:
            self._reco_text.setText(f"Less crowded than your channel. {best['overlap']} network{'s' if best['overlap'] != 1 else ''} overlap it, "
                                    f"against {cur['overlap']} on yours.{dfs}")
        elif cur and best["chans"] != cur["chans"]:
            self._reco_text.setText(f"You're on {cur['label']}, which is fine. {best['label']} is slightly less crowded.{dfs}")
        elif cur:
            self._reco_text.setText("Your channel is already a good choice.")
        else:
            self._reco_text.setText(f"Least crowded option on {self._band}. {best['overlap']} network{'s' if best['overlap'] != 1 else ''} overlap it.{dfs}")
        if cur:
            col = _level_color(cur["level"]).name()
            self._cur_row.setText(f"You: {html.escape(cur['label'])}<br><span style='color:{col};font-weight:600;'>{cur['level']} crowding</span>"
                                  f" &middot; {cur['overlap']} overlapping")
        else:
            self._cur_row.setText("You're not connected on this band.")
        n = sum(1 for x in self._aps if x["band"] == self._band)
        self._cur_row.setText(self._cur_row.text() + f"<br>{n} network{'s' if n != 1 else ''} seen on {self._band}")
        if a["change"]:
            self._steps.setText("<b>How to switch</b><br>1. Open your router's admin page<br>2. Go to Wi-Fi, then Channel<br>"
                                f"3. Choose {html.escape(best['label'])} and save<br><span style='color:{Theme.TEXT_MUTED};'>Router auto-channel often picks badly, so set it by hand.</span>")
        else:
            self._steps.setText("")
