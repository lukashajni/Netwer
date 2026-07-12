"""
NETWER — LiveChart widget (live traffic graph).

PyQtGraph wrapper drawing a sliding download/upload traffic chart. Keeps a
sliding window of the last N samples and scrolls left-to-right as new data
arrives.

Units adapt to the traffic: the Y axis shows Kbps for light traffic, Mbps
for normal, Gbps for very fast links — so small traffic isn't a flat line
pinned to the bottom of a 100 Mbps axis.

Values are pushed in Mbps (what the backend yields); the widget converts
for display.

Usage:
    chart = LiveChart(max_points=60)
    chart.push(download_mbps, upload_mbps)
"""

from collections import deque

import pyqtgraph as pg
from PyQt6.QtWidgets import QWidget, QVBoxLayout

from app.theme import Theme
from app.formatting import scale_for_axis


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
        self._plot.setBackground(Theme.BG_CARD)
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
        self._rescale()

    def push(self, download: float, upload: float) -> None:
        """Add one sample (values in Mbps) and scroll the chart."""
        self._dl.append(float(download))
        self._ul.append(float(upload))
        self._rescale()

    def _rescale(self) -> None:
        """Pick the display unit from the current peak, convert, redraw."""
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
        # Headroom above the peak; keep a small floor so an idle chart still
        # has a sensible axis instead of collapsing to zero.
        y_max = peak_scaled * 1.25 if peak_scaled > 0 else 10.0
        self._plot.setYRange(0, y_max, padding=0)

    def reset(self) -> None:
        self._dl = deque([0.0] * self._max, maxlen=self._max)
        self._ul = deque([0.0] * self._max, maxlen=self._max)
        self._rescale()
