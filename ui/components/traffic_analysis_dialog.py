"""Detailed traffic analysis dialog."""
import time

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.formatting import format_speed, scale_for_axis
from app.theme import Theme, card_bg
from app.traffic_history import traffic_history

ALL = 0   # "Continuous": no window, everything recorded so far
RANGES = (("Continuous", ALL), ("5 min", 300), ("1 hour", 3600), ("24 hours", 86400))


def _clock(t: float, long_range: bool) -> str:
    return time.strftime("%d.%m. %H:%M" if long_range else "%H:%M:%S",
                         time.localtime(t))


def _speed(mbps: float) -> str:
    value, unit = format_speed(mbps)
    return f"{value} {unit}"


def _data_size(mib: float) -> str:
    return f"{mib / 1024:.2f} GB" if mib >= 1024 else f"{mib:.1f} MB"


def _gapped(ts, series, gap):
    # NaN rows mark gaps in the data
    out_t, out = [], [[] for _ in series]
    prev = None
    for i, t in enumerate(ts):
        if prev is not None and t - prev > gap:
            out_t.append(prev + gap / 2.0)
            for o in out:
                o.append(float("nan"))
        out_t.append(t)
        for o, s in zip(out, series):
            o.append(s[i])
        prev = t
    return np.array(out_t, dtype=float), [np.array(o, dtype=float) for o in out]


class _Tile(QFrame):
    # small stat card

    def __init__(self, caption: str, accent: str = None):
        super().__init__()
        self.setObjectName("Tile")
        self.setStyleSheet(
            f"#Tile {{ background: {Theme.GLASS_CARD}; border: 1px solid {accent or Theme.GLASS_BORDER};"
            f"border-radius: 12px; }} #Tile QLabel {{ background: transparent; border: none; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(2)
        cap = QLabel(caption)
        cap.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-size: {Theme.FONT_SIZE_TINY}px;")
        self.value = QLabel("\u2014")
        self.value.setStyleSheet(
            f"color: {Theme.TEXT_PRIMARY}; font-size: 18px; font-weight: 600;"
            f"font-family: {Theme.FONT_MONO};")
        self.detail = QLabel("")
        self.detail.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: {Theme.FONT_SIZE_TINY}px;")
        for w in (cap, self.value, self.detail):
            lay.addWidget(w)

    def set(self, value: str, detail: str = "", color: str = None):
        self.value.setText(value)
        self.detail.setText(detail)
        self.value.setStyleSheet(
            f"color: {color or Theme.TEXT_PRIMARY}; font-size: 18px; font-weight: 600;"
            f"font-family: {Theme.FONT_MONO};")


class _NowTile(_Tile):
    # live value, same as the Dashboard cards

    def __init__(self):
        super().__init__("Now \u00b7 live", accent=Theme.ACCENT)
        self.detail.setStyleSheet(
            f"color: {Theme.CHART_UPLOAD}; font-size: 18px; font-weight: 600;"
            f"font-family: {Theme.FONT_MONO};")

    def set_now(self, sample):
        if sample is None:
            self.set("\u2014", "no live data", Theme.TEXT_MUTED)
            self.detail.setStyleSheet(
                f"color: {Theme.TEXT_MUTED}; font-size: {Theme.FONT_SIZE_TINY}px;")
            return
        self.set(f"\u2193 {_speed(sample[1])}", f"\u2191 {_speed(sample[2])}",
                 Theme.CHART_DOWNLOAD)
        self.detail.setStyleSheet(
            f"color: {Theme.CHART_UPLOAD}; font-size: 18px; font-weight: 600;"
            f"font-family: {Theme.FONT_MONO};")


class TrafficAnalysisDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Network Analysis")
        self.setMinimumSize(1000, 760)
        self.setStyleSheet(f"QDialog {{ background: {Theme.BG_APP}; }}")
        self._range = ALL
        self._long = False
        self._span = 300
        self._follow = True
        self._rows, self._conn, self._conn_view = [], [], []
        self._view_timer = QTimer(self)           # recompute stats after zoom or pan
        self._view_timer.setSingleShot(True)
        self._view_timer.setInterval(60)
        self._view_timer.timeout.connect(self._apply_view)
        self._bw_ts = np.array([])
        self._bw_dl = np.array([])
        self._bw_ul = np.array([])
        self._conn = []
        self._divisor, self._unit = 1.0, "Mbps"

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(12)
        root.addLayout(self._build_header())
        root.addLayout(self._build_tiles())
        root.addWidget(self._build_plots(), 1)
        root.addWidget(self._build_highlights())

        foot = QHBoxLayout()
        note = QLabel("Recorded in the background while Netwer runs. Cleared when you close it.")
        note.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: {Theme.FONT_SIZE_TINY}px;")
        foot.addWidget(note)
        foot.addStretch()
        close = QPushButton("Close")
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setStyleSheet(
            f"QPushButton {{ background: {Theme.GRAD_ACCENT}; color: white; border: none;"
            f"border-radius: 6px; padding: 8px 20px; font-size: {Theme.FONT_SIZE_SMALL}px;"
            f"font-weight: 600; }}")
        close.clicked.connect(self.accept)
        foot.addWidget(close)
        root.addLayout(foot)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        self.refresh()

    def done(self, result):
        self._timer.stop()
        super().done(result)

    # -- construction --
    def _build_header(self):
        row = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(2)
        title = QLabel("Network Analysis")
        title.setStyleSheet(
            f"color: {Theme.TEXT_PRIMARY}; font-family: {Theme.FONT_FAMILY};"
            f"font-size: 20px; font-weight: 600; background: transparent;")
        self._subtitle = QLabel("")
        self._subtitle.setStyleSheet(
            f"color: {Theme.TEXT_MUTED}; font-size: {Theme.FONT_SIZE_SMALL}px;"
            f"background: transparent;")
        col.addWidget(title)
        col.addWidget(self._subtitle)
        row.addLayout(col)
        row.addStretch()

        group = QButtonGroup(self)
        group.setExclusive(True)
        for i, (label, seconds) in enumerate(RANGES):
            b = QPushButton(label)
            b.setCheckable(True)
            b.setChecked(i == 0)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(
                f"QPushButton {{ background: {Theme.BG_ELEVATED}; color: {Theme.TEXT_SECONDARY};"
                f"border: 1px solid {Theme.BORDER_STRONG}; border-radius: 8px; padding: 6px 14px;"
                f"font-size: {Theme.FONT_SIZE_SMALL}px; font-weight: 600; }}"
                f"QPushButton:checked {{ background: {Theme.GRAD_ACCENT}; color: white;"
                f"border-color: transparent; }}")
            b.clicked.connect(lambda _=False, s=seconds: self._set_range(s))
            group.addButton(b)
            row.addWidget(b)
        self._btn_follow = QPushButton("Follow live")
        self._btn_follow.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_follow.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {Theme.ACCENT}; border: 1px solid {Theme.ACCENT};"
            f"border-radius: 8px; padding: 6px 14px; font-size: {Theme.FONT_SIZE_SMALL}px; font-weight: 600; }}"
            f"QPushButton:hover {{ background: {Theme.BG_ELEVATED}; }}")
        self._btn_follow.clicked.connect(self._reset_zoom)
        self._btn_follow.hide()
        row.insertWidget(row.count() - len(RANGES), self._btn_follow)
        return row

    def _build_tiles(self):
        row = QHBoxLayout()
        row.setSpacing(10)
        self._t_now = _NowTile()
        self._t_dl = _Tile("Receive \u00b7 avg")
        self._t_ul = _Tile("Send \u00b7 avg")
        self._t_data = _Tile("Data transferred")
        self._t_loss = _Tile("Packet loss \u00b7 avg")
        self._t_lat = _Tile("Latency \u00b7 avg")
        for t in (self._t_now, self._t_dl, self._t_ul, self._t_data, self._t_loss, self._t_lat):
            row.addWidget(t, 1)
        return row

    def _make_plot(self, ylabel: str, show_time: bool):
        plot = pg.PlotWidget(axisItems={"bottom": pg.DateAxisItem()})
        plot.setBackground(card_bg())
        plot.showGrid(x=False, y=True, alpha=0.15)
        plot.setMouseEnabled(x=True, y=False)
        plot.hideButtons()
        plot.getViewBox().setMenuEnabled(False)
        plot.setLabel("left", ylabel, **{"color": Theme.TEXT_FAINT, "font-size": "9pt"})
        for name in ("left", "bottom"):
            ax = plot.getAxis(name)
            ax.setPen(pg.mkPen(color=Theme.CHART_GRID))
            ax.setTextPen(pg.mkColor(Theme.TEXT_FAINT))
        plot.getAxis("left").setWidth(64)
        plot.getAxis("bottom").setStyle(showValues=show_time)
        vline = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen(
            Theme.TEXT_FAINT, width=1, style=Qt.PenStyle.DashLine))
        vline.setVisible(False)
        plot.addItem(vline, ignoreBounds=True)
        plot.scene().sigMouseMoved.connect(lambda pos, p=plot: self._hover(p, pos))
        plot.scene().sigMouseClicked.connect(lambda ev: ev.double() and self._reset_zoom())
        vb = plot.getViewBox()
        vb.setLimits(minXRange=3)
        vb.sigRangeChangedManually.connect(self._user_zoomed)
        vb.sigXRangeChanged.connect(lambda *_: self._view_timer.start())
        return plot, vline

    def _build_plots(self):
        frame = QFrame()
        frame.setObjectName("Plots")
        frame.setStyleSheet(
            f"#Plots {{ background: {Theme.BG_CARD}; border: 1px solid {Theme.BORDER};"
            f"border-radius: {Theme.RADIUS_CARD}px; }}")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(4)

        legend = QHBoxLayout()
        for text, color in (("Receive", Theme.CHART_DOWNLOAD), ("Send", Theme.CHART_UPLOAD),
                            ("Latency", Theme.WARNING), ("Packet loss", Theme.DANGER)):
            dot = QLabel(f"<span style='color:{color};'>\u25CF</span> {text}")
            dot.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-size: {Theme.FONT_SIZE_TINY}px;"
                              f"background: transparent;")
            legend.addWidget(dot)
            legend.addSpacing(10)
        legend.addStretch()
        hint = QLabel("Scroll to zoom \u00b7 drag to move \u00b7 double-click to reset")
        hint.setStyleSheet(f"color: {Theme.TEXT_FAINT}; font-size: {Theme.FONT_SIZE_TINY}px; background: transparent;")
        legend.addWidget(hint)
        lay.addLayout(legend)

        self._p_bw, v1 = self._make_plot("Mbps", False)
        self._p_lat, v2 = self._make_plot("ms", False)
        self._p_loss, v3 = self._make_plot("%", True)
        self._vlines = (v1, v2, v3)
        self._p_lat.setXLink(self._p_bw)
        self._p_loss.setXLink(self._p_bw)

        self._dl_curve = self._p_bw.plot(
            pen=pg.mkPen(Theme.CHART_DOWNLOAD, width=2), connect="finite",
            fillLevel=0, brush=pg.mkBrush(*Theme.CHART_FILL_DL))
        self._ul_curve = self._p_bw.plot(
            pen=pg.mkPen(Theme.CHART_UPLOAD, width=2), connect="finite",
            fillLevel=0, brush=pg.mkBrush(*Theme.CHART_FILL_UL))
        self._peaks = pg.ScatterPlotItem(size=9, pen=pg.mkPen(Theme.BG_APP, width=1))
        self._p_bw.addItem(self._peaks)
        self._readout = pg.TextItem(anchor=(0, 1), color=Theme.TEXT_BODY)
        self._readout.setVisible(False)
        self._p_bw.addItem(self._readout, ignoreBounds=True)

        self._lat_curve = self._p_lat.plot(
            pen=pg.mkPen(Theme.WARNING, width=2), connect="finite")
        self._loss_bars = pg.BarGraphItem(x=[], height=[], width=1,
                                          brush=pg.mkBrush(Theme.DANGER),
                                          pen=pg.mkPen(None))
        self._p_loss.addItem(self._loss_bars)

        lay.addWidget(self._p_bw, 5)
        lay.addWidget(self._p_lat, 2)
        lay.addWidget(self._p_loss, 2)
        return frame

    def _build_highlights(self):
        frame = QFrame()
        frame.setObjectName("Highlights")
        frame.setStyleSheet(
            f"#Highlights {{ background: {Theme.BG_CARD}; border: 1px solid {Theme.BORDER};"
            f"border-radius: {Theme.RADIUS_CARD}px; }}"
            f"#Highlights QLabel {{ background: transparent; border: none; }}")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(4)
        head = QLabel("Highlights")
        head.setStyleSheet(f"color: {Theme.TEXT_BODY}; font-size: {Theme.FONT_SIZE_BODY}px;"
                           f"font-weight: 500;")
        lay.addWidget(head)
        self._highlights = QLabel("")
        self._highlights.setTextFormat(Qt.TextFormat.RichText)
        self._highlights.setWordWrap(True)
        self._highlights.setStyleSheet(
            f"color: {Theme.TEXT_SECONDARY}; font-size: {Theme.FONT_SIZE_SMALL}px;")
        lay.addWidget(self._highlights)
        return frame

    # -- interaction --
    def _set_range(self, seconds: int):
        self._range = seconds
        self._reset_zoom()

    def _user_zoomed(self, *_):
        self._follow = False
        self._btn_follow.show()

    def _reset_zoom(self):
        self._follow = True
        self._btn_follow.hide()
        self.refresh()

    def _hover(self, plot, pos):
        if not plot.sceneBoundingRect().contains(pos) or not len(self._bw_ts):
            for v in self._vlines:
                v.setVisible(False)
            self._readout.setVisible(False)
            return
        x = plot.getViewBox().mapSceneToView(pos).x()
        i = int(np.clip(np.searchsorted(self._bw_ts, x), 0, len(self._bw_ts) - 1))
        if i > 0 and abs(self._bw_ts[i - 1] - x) < abs(self._bw_ts[i] - x):
            i -= 1
        t = float(self._bw_ts[i])
        for v in self._vlines:
            v.setPos(t)
            v.setVisible(True)

        dl, ul = self._bw_dl[i], self._bw_ul[i]
        near = [c for c in self._conn if abs(c[0] - t) <= 10]
        extra = ""
        if near:
            c = min(near, key=lambda c: abs(c[0] - t))
            ping = "timeout" if c[1] is None else f"{c[1]:.0f} ms"
            extra = (f"<br><span style='color:{Theme.WARNING};'>ping {ping}</span>"
                     f" &nbsp;<span style='color:{Theme.DANGER};'>loss {c[2]:.0f}%</span>")
        self._readout.setHtml(
            f"<div style='background:{Theme.BG_ELEVATED}; padding:3px 6px; font-size:9pt;'>"
            f"<span style='color:{Theme.TEXT_MUTED};'>{_clock(t, self._long)}</span><br>"
            f"<span style='color:{Theme.CHART_DOWNLOAD};'>\u2193 {_speed(0 if np.isnan(dl) else dl)}</span>"
            f" &nbsp;<span style='color:{Theme.CHART_UPLOAD};'>\u2191 {_speed(0 if np.isnan(ul) else ul)}</span>"
            f"{extra}</div>")
        right_half = x > (self._p_bw.viewRange()[0][0] + self._p_bw.viewRange()[0][1]) / 2
        self._readout.setAnchor((1, 1) if right_half else (0, 1))
        top = np.nanmax([dl, ul, 0.0]) / self._divisor
        self._readout.setPos(t, top)
        self._readout.setVisible(True)

    # -- data --
    def refresh(self):
        now = time.time()
        coarse = self._range >= 86400
        if self._range == ALL:
            bw, coarse = traffic_history.bandwidth_all()
            self._conn = traffic_history.connectivity(10 ** 9)
            start = bw[0][0] if bw else now - 300
        else:
            bw = traffic_history.bandwidth(self._range)
            self._conn = traffic_history.connectivity(self._range)
            start = now - self._range
        self._span = max(now - start, 60)
        long_range = self._span >= 6 * 3600
        self._long = long_range
        adapter = traffic_history.adapter or "detecting\u2026"
        label = next(l for l, s in RANGES if s == self._range)
        period = "all recorded data" if self._range == ALL else f"last {label}"
        self._subtitle.setText(f"Monitoring: {adapter}  \u00b7  {period}")

        gap = 150.0 if coarse else 3.0
        if bw:
            ts, (dl, ul, dlp, ulp) = _gapped(
                [r[0] for r in bw],
                ([r[1] for r in bw], [r[2] for r in bw], [r[3] for r in bw], [r[4] for r in bw]),
                gap)
        else:
            ts = dl = ul = dlp = ulp = np.array([])
        self._bw_ts, self._bw_dl, self._bw_ul = ts, dl, ul
        self._bw_dlp, self._bw_ulp = dlp, ulp
        self._rows = bw

        if self._conn:
            cts, (ping, loss) = _gapped(
                [c[0] for c in self._conn],
                ([float("nan") if c[1] is None else c[1] for c in self._conn],
                 [c[2] for c in self._conn]), 12.0)
        else:
            cts = ping = loss = np.array([])
        self._cts, self._ping, self._loss = cts, ping, np.nan_to_num(loss)
        self._lat_curve.setData(cts, ping)
        self._loss_bars.setOpts(x=cts, height=self._loss, width=max(5.0, self._span / 150.0))

        if self._follow:
            self._p_bw.setXRange(start, now, padding=0)
        self._t_now.set_now(traffic_history.latest())
        self._apply_view()

    def _apply_view(self):
        # Everything that depends on the visible time window: axes, stats, highlights
        ts = self._bw_ts
        x0, x1 = self._p_bw.viewRange()[0]
        zoomed = not self._follow
        if len(ts):
            vis = (ts >= x0) & (ts <= x1)
            pk = np.concatenate([self._bw_dlp[vis], self._bw_ulp[vis], [0.0]])
            peak = float(np.nanmax(pk)) if len(pk) else 0.0
        else:
            vis, peak = np.array([], dtype=bool), 0.0
        self._unit, self._divisor = scale_for_axis(peak)
        self._p_bw.setLabel("left", self._unit, **{"color": Theme.TEXT_FAINT, "font-size": "9pt"})
        self._dl_curve.setData(ts, self._bw_dl / self._divisor)
        self._ul_curve.setData(ts, self._bw_ul / self._divisor)
        self._p_bw.setYRange(0, (peak / self._divisor) * 1.25 if peak > 0 else 10.0, padding=0)

        marks = []
        if len(ts) and vis.any():
            for series, color in ((self._bw_dlp, Theme.CHART_DOWNLOAD), (self._bw_ulp, Theme.CHART_UPLOAD)):
                part = np.where(vis, series, np.nan)
                if not np.all(np.isnan(part)):
                    i = int(np.nanargmax(part))
                    if series[i] > 0:
                        marks.append({"pos": (ts[i], series[i] / self._divisor), "brush": pg.mkBrush(color)})
        self._peaks.setData(marks)

        if len(self._cts):
            cv = (self._cts >= x0) & (self._cts <= x1)
            pv = self._ping[cv]
            self._p_lat.setYRange(0, float(np.nanmax(pv)) * 1.25 if len(pv) and not np.all(np.isnan(pv)) else 50, padding=0)
            lv = self._loss[cv]
            self._p_loss.setYRange(0, max(5.0, float(lv.max()) * 1.25) if len(lv) else 5.0, padding=0)
        rows = [r for r in self._rows if x0 <= r[0] <= x1] if zoomed else self._rows
        self._conn_view = [c for c in self._conn if x0 <= c[0] <= x1] if zoomed else self._conn
        if zoomed:
            adapter_name = traffic_history.adapter or "detecting\u2026"
            long_sel = (x1 - x0) >= 6 * 3600
            self._subtitle.setText(f"Monitoring: {adapter_name}  \u00b7  "
                                   f"selection {_clock(x0, long_sel)} to {_clock(x1, long_sel)}")
        self._update_tiles(rows)
        self._update_highlights(rows, self._long)

    def _update_tiles(self, bw):
        if bw:
            n = sum(r[5] for r in bw)
            dl_avg = sum(r[1] * r[5] for r in bw) / n
            ul_avg = sum(r[2] * r[5] for r in bw) / n
            self._t_dl.set(_speed(dl_avg), f"peak {_speed(max(r[3] for r in bw))}",
                           Theme.CHART_DOWNLOAD)
            self._t_ul.set(_speed(ul_avg), f"peak {_speed(max(r[4] for r in bw))}",
                           Theme.CHART_UPLOAD)
            dl_mib = sum(r[1] * r[5] for r in bw) / 8
            ul_mib = sum(r[2] * r[5] for r in bw) / 8
            self._t_data.set(f"\u2193 {_data_size(dl_mib)}", f"\u2191 {_data_size(ul_mib)}")
        else:
            for t in (self._t_dl, self._t_ul, self._t_data):
                t.set("\u2014", "waiting for data")

        pings = [c[1] for c in self._conn_view if c[1] is not None]
        losses = [c[2] for c in self._conn_view]
        if losses:
            avg_loss = sum(losses) / len(losses)
            color = (Theme.SUCCESS if avg_loss < 1 else Theme.WARNING if avg_loss < 5
                     else Theme.DANGER)
            self._t_loss.set(f"{avg_loss:.1f}%", f"worst {max(losses):.0f}%", color)
        else:
            self._t_loss.set("\u2014", "waiting for data")
        if pings:
            jitter = float(np.std(pings))
            self._t_lat.set(f"{sum(pings) / len(pings):.0f} ms",
                            f"jitter {jitter:.0f} ms \u00b7 max {max(pings):.0f} ms",
                            Theme.WARNING)
        else:
            self._t_lat.set("\u2014", "waiting for data")

    def _update_highlights(self, bw, long_range: bool):
        lines = []

        def add(color, text):
            lines.append(f"<span style='color:{color};'>\u25CF</span>&nbsp; {text}")

        if bw:
            peak_dl = max(bw, key=lambda r: r[3])
            if peak_dl[3] > 0:
                add(Theme.CHART_DOWNLOAD,
                    f"Highest receive speed {_speed(peak_dl[3])} at {_clock(peak_dl[0], long_range)}.")
            n = sum(r[5] for r in bw)
            ul_avg = sum(r[2] * r[5] for r in bw) / n
            peak_ul = max(bw, key=lambda r: r[4])
            if peak_ul[4] > 0.5 and peak_ul[4] > 4 * max(ul_avg, 0.01):
                add(Theme.CHART_UPLOAD,
                    f"Send spike to {_speed(peak_ul[4])} at {_clock(peak_ul[0], long_range)} "
                    f"(average is {_speed(ul_avg)}). A backup, sync or large upload is likely.")
        if self._conn_view:
            lossy = [c for c in self._conn_view if c[2] > 0]
            drops = [c for c in self._conn_view if c[2] >= 100]
            if drops:
                add(Theme.DANGER, f"Connection dropped {len(drops)} time(s); last at "
                                  f"{_clock(drops[-1][0], long_range)}.")
            elif lossy:
                worst = max(lossy, key=lambda c: c[2])
                add(Theme.WARNING, f"Packet loss in {len(lossy)} of {len(self._conn_view)} checks, "
                                   f"worst {worst[2]:.0f}% at {_clock(worst[0], long_range)}.")
            else:
                add(Theme.SUCCESS, "No packet loss detected in this period.")
            pings = [c for c in self._conn_view if c[1] is not None]
            if pings:
                avg = sum(c[1] for c in pings) / len(pings)
                worst = max(pings, key=lambda c: c[1])
                if worst[1] > 2.5 * avg and worst[1] - avg > 30:
                    add(Theme.WARNING, f"Latency spiked to {worst[1]:.0f} ms at "
                                       f"{_clock(worst[0], long_range)} (average {avg:.0f} ms).")
        if not lines:
            add(Theme.TEXT_MUTED, "Collecting data\u2026 highlights appear after a few seconds.")
        self._highlights.setText("<br>".join(lines[:5]))
