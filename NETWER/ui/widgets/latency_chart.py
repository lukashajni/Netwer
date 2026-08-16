"""
NETWER — LatencyChart widget.

A sliding latency plot for the ping pages. Unlike the dashboard's traffic
chart, a lost packet must read as a GAP rather than a zero — plotting a
timeout as 0 ms would draw a spike down to the axis and lie about the
result. Timeouts are pushed as NaN, which PyQtGraph renders as a break in
the line, and are additionally marked with a red tick on the axis.
"""

from collections import deque

import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import QWidget, QVBoxLayout

from app.theme import Theme, card_bg


class LatencyChart(QWidget):
    def __init__(self, max_points: int = 60, parent=None):
        super().__init__(parent)
        self._max = max_points
        self._data = deque(maxlen=max_points)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        pg.setConfigOptions(antialias=True)
        self._plot = pg.PlotWidget()
        # Match the card exactly (glass or flat) so the plot doesn't
        # show up as a slightly different rectangle inside the card.
        self._plot.setBackground(card_bg())
        self._plot.showGrid(x=False, y=True, alpha=0.15)
        self._plot.setMouseEnabled(x=False, y=False)
        self._plot.hideButtons()
        self._plot.getAxis("bottom").setStyle(showValues=False)
        self._plot.setLabel("left", "ms",
                            **{"color": Theme.TEXT_FAINT, "font-size": "9pt"})

        axis_pen = pg.mkPen(color=Theme.CHART_GRID)
        text_pen = pg.mkColor(Theme.TEXT_FAINT)
        for ax in ("left", "bottom"):
            self._plot.getAxis(ax).setPen(axis_pen)
            self._plot.getAxis(ax).setTextPen(text_pen)

        self._curve = self._plot.plot(
            pen=pg.mkPen(Theme.ACCENT, width=2),
            fillLevel=0, brush=pg.mkBrush(*Theme.CHART_FILL_DL),
            connect="finite",   # NaN breaks the line instead of spiking to 0
        )

        # Red markers where packets were lost
        self._losses = pg.ScatterPlotItem(
            size=6, brush=pg.mkBrush(Theme.DANGER), pen=None, symbol="x")
        self._plot.addItem(self._losses)

        lay.addWidget(self._plot)

    def push(self, ms) -> None:
        """Add a reply. Pass None for a timeout — it renders as a gap."""
        self._data.append(float("nan") if ms is None else float(ms))
        self._redraw()

    def _redraw(self) -> None:
        values = np.array(self._data, dtype=float)
        x = np.arange(len(values))
        self._curve.setData(x, values)

        # Mark timeouts on the baseline
        lost_idx = np.where(np.isnan(values))[0]
        if len(lost_idx):
            self._losses.setData(lost_idx, np.zeros(len(lost_idx)))
        else:
            self._losses.setData([], [])

        finite = values[~np.isnan(values)]
        if len(finite):
            lo, hi = float(finite.min()), float(finite.max())
            span = max(hi - lo, 4.0)
            self._plot.setYRange(max(0.0, lo - span * 0.25), hi + span * 0.25,
                                 padding=0)
        else:
            self._plot.setYRange(0, 50, padding=0)

    def reset(self) -> None:
        self._data.clear()
        self._curve.setData([], [])
        self._losses.setData([], [])
        self._plot.setYRange(0, 50, padding=0)
