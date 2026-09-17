"""
NETWER — LiveChart widget (live traffic graph).

PyQtGraph wrapper drawing a sliding download/upload traffic chart. Keeps a
sliding window of the last N samples and scrolls left-to-right as new data
arrives.

Units adapt to the traffic: the Y axis shows Kbps for light traffic, Mbps
for normal, Gbps for very fast links - so small traffic isn't a flat line
pinned to the bottom of a 100 Mbps axis.

Values are pushed in Mbps (what the backend yields), the widget converts
for display.

Usage:
    chart = LiveChart(max_points=60)
    chart.push(download_mbps, upload_mbps)
"""

from collections import deque

import pyqtgraph as pg
from PyQt6.QtWidgets import QWidget, QVBoxLayout

from app.theme import Theme, card_bg
from app.formatting import scale_for_axis, format_speed as _fmt


class LiveChart(QWidget):
    def __init__(self, max_points: int = 60, parent=None):
        super().__init__(parent)
        self._max = max_points
        # Stored in Mbps
        self._dl = deque([0.0] * max_points, maxlen=max_points)
        self._ul = deque([0.0] * max_points, maxlen=max_points)
        self._x = list(range(max_points))
        self._unit = "Kbps"
        self._divisor = 0.001

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        pg.setConfigOptions(antialias=True)
        self._plot = pg.PlotWidget()
        """ Match the card exactly (glass or flat) so the plot doesn't
        show up as a slightly different rectangle inside the card. """
        self._plot.setBackground(card_bg())
        self._plot.showGrid(x=False, y=True, alpha=0.15)
        self._plot.setMouseEnabled(x=False, y=False)
        self._plot.hideButtons()
        self._plot.getAxis("bottom").setStyle(showValues=False)
        self._plot.setLabel("left", "Kbps",
                            **{"color": Theme.TEXT_FAINT, "font-size": "9pt"})

        axis_pen = pg.mkPen(color=Theme.CHART_GRID)
        text_pen = pg.mkColor(Theme.TEXT_FAINT)
        for ax in ("left", "bottom"):
            self._plot.getAxis(ax).setPen(axis_pen)
            self._plot.getAxis(ax).setTextPen(text_pen)

        self._dl_curve = self._plot.plot(
            self._x, [0.0] * max_points,
            pen=pg.mkPen(Theme.CHART_DOWNLOAD, width=2),
            fillLevel=0, brush=pg.mkBrush(*Theme.CHART_FILL_DL),
        )
        self._ul_curve = self._plot.plot(
            self._x, [0.0] * max_points,
            pen=pg.mkPen(Theme.CHART_UPLOAD, width=2),
            fillLevel=0, brush=pg.mkBrush(*Theme.CHART_FILL_UL),
        )
        lay.addWidget(self._plot)

        """ Hover crosshair - a vertical line that follows the cursor plus a
        small label showing the download/upload value at that sample. """
        self._vline = pg.InfiniteLine(
            angle=90, movable=False,
            pen=pg.mkPen(Theme.TEXT_FAINT, width=1,
                         style=pg.QtCore.Qt.PenStyle.DashLine))
        self._vline.setVisible(False)
        self._plot.addItem(self._vline, ignoreBounds=True)
        self._hover_label = pg.TextItem(anchor=(0, 1), color=Theme.TEXT_BODY)
        self._hover_label.setVisible(False)
        self._plot.addItem(self._hover_label, ignoreBounds=True)
        self._plot.scene().sigMouseMoved.connect(self._on_mouse_moved)
        self._plot.getViewBox().setMenuEnabled(False)

        self._rescale()

    def _on_mouse_moved(self, pos):
        # Show a crosshair + value readout at the hovered sample.
        vb = self._plot.getViewBox()
        if not self._plot.sceneBoundingRect().contains(pos):
            self._vline.setVisible(False)
            self._hover_label.setVisible(False)
            return
        mouse_pt = vb.mapSceneToView(pos)
        idx = int(round(mouse_pt.x()))
        idx = max(0, min(self._max - 1, idx))
        dl = list(self._dl)[idx]
        ul = list(self._ul)[idx]
        self._vline.setPos(idx)
        self._vline.setVisible(True)
        dl_s, dl_u = _fmt(dl)
        ul_s, ul_u = _fmt(ul)
        self._hover_label.setHtml(
            f"<div style='background:{Theme.BG_ELEVATED}; padding:3px 6px;"
            f"border-radius:4px; font-size:9pt;'>"
            f"<span style='color:{Theme.CHART_DOWNLOAD};'>\u2193 {dl_s} {dl_u}</span><br>"
            f"<span style='color:{Theme.CHART_UPLOAD};'>\u2191 {ul_s} {ul_u}</span></div>")
        self._hover_label.setPos(idx, max(dl, ul) / self._divisor)
        self._hover_label.setVisible(True)

    def stats(self):
        """Return live min/max/avg (in Mbps) for download and upload, over
        the non-zero portion of the buffer (so startup zeros don't skew it)."""
        def _s(seq):
            vals = [v for v in seq]
            nonzero = [v for v in vals if v > 0]
            if not nonzero:
                return {"min": 0.0, "max": 0.0, "avg": 0.0, "cur": vals[-1]}
            return {"min": min(nonzero), "max": max(nonzero),
                    "avg": sum(nonzero) / len(nonzero), "cur": vals[-1]}
        return {"download": _s(self._dl), "upload": _s(self._ul)}

    def push(self, download: float, upload: float) -> None:
        # Add one sample (values in Mbps) and scroll the chart.
        self._dl.append(float(download))
        self._ul.append(float(upload))
        self._rescale()

    def _rescale(self) -> None:
        # Pick the display unit from the current peak, convert, redraw.
        peak_mbps = max(max(self._dl), max(self._ul), 0.0)
        unit, divisor = scale_for_axis(peak_mbps)

        if unit != self._unit:
            self._unit = unit
            self._divisor = divisor
            self._plot.setLabel("left", unit,
                                **{"color": Theme.TEXT_FAINT, "font-size": "9pt"})

        dl_scaled = [v / self._divisor for v in self._dl]
        ul_scaled = [v / self._divisor for v in self._ul]
        self._dl_curve.setData(self._x, dl_scaled)
        self._ul_curve.setData(self._x, ul_scaled)

        peak_scaled = max(max(dl_scaled), max(ul_scaled), 0.0)
        # Headroom above the peak, keep a small floor so an idle chart still
        # has a sensible axis instead of collapsing to zero.
        y_max = peak_scaled * 1.25 if peak_scaled > 0 else 10.0
        self._plot.setYRange(0, y_max, padding=0)

    def reset(self) -> None:
        self._dl = deque([0.0] * self._max, maxlen=self._max)
        self._ul = deque([0.0] * self._max, maxlen=self._max)
        self._rescale()
