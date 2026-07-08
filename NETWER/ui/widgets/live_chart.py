"""
NETWER — LiveChart widget (živi graf prometa).

Omotač oko PyQtGraph koji crta klizni graf download/upload prometa
(glavni graf na dashboardu + Network Monitor stranica). Drži klizni
prozor zadnjih N točaka i pomiče graf slijeva nadesno kako stižu novi
podaci.

PyQtGraph je izabran jer podnosi česta ažuriranja bez zastajkivanja —
za razliku od matplotliba. Ovo je "gluma" widget: prima brojeve i crta
ih, ne zna odakle dolaze. Dashboard mu dostavlja podatke iz
monitor_stream() workera.

Korištenje:
    chart = LiveChart(max_points=60)
    chart.push(download_mbps, upload_mbps)   # svaki novi uzorak
"""

from collections import deque

import pyqtgraph as pg
from PyQt6.QtWidgets import QWidget, QVBoxLayout

from app.theme import Theme


class LiveChart(QWidget):
    def __init__(self, max_points: int = 60, y_max: float = 100.0, parent=None):
        super().__init__(parent)
        self._max = max_points
        self._dl = deque([0.0] * max_points, maxlen=max_points)
        self._ul = deque([0.0] * max_points, maxlen=max_points)
        self._x = list(range(max_points))

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        pg.setConfigOptions(antialias=True)
        self._plot = pg.PlotWidget()
        self._plot.setBackground(Theme.BG_CARD)
        self._plot.showGrid(x=False, y=True, alpha=0.15)
        self._plot.setYRange(0, y_max, padding=0)
        self._plot.setMouseEnabled(x=False, y=False)
        self._plot.hideButtons()
        self._plot.getAxis("bottom").setStyle(showValues=False)

        # Stil osi
        axis_pen = pg.mkPen(color=Theme.CHART_GRID)
        text_pen = pg.mkColor(Theme.TEXT_FAINT)
        for ax in ("left", "bottom"):
            self._plot.getAxis(ax).setPen(axis_pen)
            self._plot.getAxis(ax).setTextPen(text_pen)

        # Krivulje s poluprozirnim punjenjem ispod
        self._dl_curve = self._plot.plot(
            self._x, list(self._dl),
            pen=pg.mkPen(Theme.CHART_DOWNLOAD, width=2),
            fillLevel=0, brush=pg.mkBrush(*Theme.CHART_FILL_DL),
        )
        self._ul_curve = self._plot.plot(
            self._x, list(self._ul),
            pen=pg.mkPen(Theme.CHART_UPLOAD, width=2),
            fillLevel=0, brush=pg.mkBrush(*Theme.CHART_FILL_UL),
        )
        lay.addWidget(self._plot)

    def push(self, download: float, upload: float) -> None:
        """Dodaj jedan novi uzorak i pomakni graf."""
        self._dl.append(float(download))
        self._ul.append(float(upload))
        self._dl_curve.setData(self._x, list(self._dl))
        self._ul_curve.setData(self._x, list(self._ul))

        # Auto-skaliranje Y ako promet premaši trenutni raspon
        peak = max(max(self._dl), max(self._ul), 10.0)
        self._plot.setYRange(0, peak * 1.15, padding=0)

    def reset(self) -> None:
        self._dl = deque([0.0] * self._max, maxlen=self._max)
        self._ul = deque([0.0] * self._max, maxlen=self._max)
        self._dl_curve.setData(self._x, list(self._dl))
        self._ul_curve.setData(self._x, list(self._ul))
