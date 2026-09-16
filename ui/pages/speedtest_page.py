"""
NETWER — Speed Test page.

Measure download, upload and latency using Ookla's speedtest CLI. Hit Start
and watch the three big readouts fill in live, with a phase indicator and
elapsed timer.

Runs in a StreamWorker around netwer_core.speedtest_stream, which yields:
    {"type": "start", "isp", "server"}
    {"type": "ping", "ms"}
    {"type": "download", "mbps"}   (repeated, live)
    {"type": "upload", "mbps"}     (repeated, live)
    {"type": "result", "ping", "dl", "ul"}
or {"error": ...} when speedtest.exe isn't found.
"""

import time

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame
)

from app.theme import Theme
from app.resources import Icons
from app.activity import activity
from ui.pages.base_page import BasePage
from ui.widgets.progress_bar import ProgressBar
from ui.widgets.sparkline import Sparkline
from workers import StreamWorker


class SpeedTestPage(BasePage):
    PAGE_TITLE = "Speed Test"
    PAGE_SUBTITLE = "Measure your download, upload and latency"

    def __init__(self, core, parent=None):
        super().__init__(core, parent)
        self._worker = None
        self._running = False
        self._start_time = 0
        self._phase = ""

        self._timer = QTimer(self)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._tick)

        self._build_toolbar()
        self._build_readouts()
        self._build_progress()
        self.body_layout.addStretch(1)

    # -- UI --
    def _build_toolbar(self):
        row = QHBoxLayout()
        row.setSpacing(8)

        self.server_label = QLabel("Server \u2014  \u00b7  ISP \u2014")
        self.server_label.setStyleSheet(
            f"color: {Theme.TEXT_SECONDARY}; font-size: {Theme.FONT_SIZE_BODY}px;"
            f"background: transparent;")
        row.addWidget(self.server_label, 1)

        self.btn = QPushButton("  Start test")
        self.btn.setIcon(Icons.get("play", "#ffffff"))
        self.btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn.setMinimumWidth(130)
        self._style_button(running=False)
        self.btn.clicked.connect(self._toggle)
        row.addWidget(self.btn)

        self.body_layout.addLayout(row)

    def _style_button(self, running: bool):
        color = Theme.DANGER if running else Theme.ACCENT
        hover = Theme.DANGER_HOVER if running else Theme.ACCENT_PURPLE
        self.btn.setStyleSheet(
            f"QPushButton {{ background: {color}; color: white; border: none;"
            f"border-radius: 8px; padding: 9px 20px;"
            f"font-size: {Theme.FONT_SIZE_BODY}px; font-weight: 600; }}"
            f"QPushButton:hover {{ background: {hover}; }}")

    def _build_readouts(self):
        row = QHBoxLayout()
        row.setSpacing(Theme.GAP)
        self.card_dl = self._big_readout("download", "Download", Theme.ACCENT, "Mbps")
        self.card_ul = self._big_readout("upload", "Upload", Theme.ACCENT_PURPLE, "Mbps")
        self.card_ping = self._big_readout("packet_loss", "Ping", Theme.SUCCESS, "ms")
        for c in (self.card_dl, self.card_ul, self.card_ping):
            row.addWidget(c["frame"], 1)
        self.body_layout.addLayout(row)

    def _big_readout(self, icon, label, color, unit):
        frame = QFrame()
        frame.setObjectName("Readout")
        frame.setStyleSheet(
            f"#Readout {{ background: {Theme.BG_CARD}; border: 1px solid {Theme.BORDER};"
            f"border-radius: {Theme.RADIUS_CARD}px; }}"
            f"#Readout QLabel {{ background: transparent; border: none; }}")
        frame.setFixedHeight(168)
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(16, 14, 16, 12)
        lay.setSpacing(2)

        # Header: icon + label
        head = QHBoxLayout()
        head.setSpacing(7)
        icon_lbl = QLabel()
        icon_lbl.setPixmap(Icons.pixmap(icon, 15, color))
        head.addWidget(icon_lbl)
        label_lbl = QLabel(label)
        label_lbl.setStyleSheet(
            f"color: {Theme.TEXT_SECONDARY}; font-size: {Theme.FONT_SIZE_SMALL}px;"
            f"font-weight: 500; background: transparent;")
        head.addWidget(label_lbl)
        head.addStretch()
        lay.addLayout(head)

        lay.addStretch()

        # Big value + unit
        val_row = QHBoxLayout()
        val_row.setSpacing(4)
        val_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        value = QLabel("\u2014")
        value.setStyleSheet(
            f"color: {color}; font-family: {Theme.FONT_DATA};"
            f"font-size: 38px; font-weight: 600; background: transparent;")
        val_row.addWidget(value)
        unit_lbl = QLabel(unit)
        unit_lbl.setAlignment(Qt.AlignmentFlag.AlignBottom)
        unit_lbl.setStyleSheet(
            f"color: {Theme.TEXT_MUTED}; font-size: 13px; background: transparent;"
            f"padding-bottom: 8px;")
        val_row.addWidget(unit_lbl)
        lay.addLayout(val_row)

        lay.addStretch()

        # Live sparkline trace (fills during that phase)
        spark = Sparkline(color, max_points=50)
        lay.addWidget(spark)

        return {"frame": frame, "value": value, "color": color,
                "spark": spark, "label": label_lbl}

    def _set_card_active(self, card, active):
        # Highlight the card whose phase is currently running.
        color = card["color"]
        if active:
            card["frame"].setStyleSheet(
                f"#Readout {{ background: {Theme.BG_CARD};"
                f"border: 2px solid {color};"
                f"border-radius: {Theme.RADIUS_CARD}px; }}"
                f"#Readout QLabel {{ background: transparent; border: none; }}")
        else:
            card["frame"].setStyleSheet(
                f"#Readout {{ background: {Theme.BG_CARD};"
                f"border: 1px solid {Theme.BORDER};"
                f"border-radius: {Theme.RADIUS_CARD}px; }}"
                f"#Readout QLabel {{ background: transparent; border: none; }}")

    def _build_progress(self):
        card = QFrame()
        card.setObjectName("SpeedProgress")
        card.setStyleSheet(
            f"#SpeedProgress {{ background: {Theme.BG_CARD};"
            f"border: 1px solid {Theme.BORDER}; border-radius: {Theme.RADIUS_CARD}px; }}"
            f"#SpeedProgress QLabel {{ background: transparent; border: none; }}")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)

        top = QHBoxLayout()
        self.phase_label = QLabel("Idle")
        self.phase_label.setStyleSheet(
            f"color: {Theme.TEXT_SECONDARY}; font-size: {Theme.FONT_SIZE_BODY}px;")
        top.addWidget(self.phase_label)
        top.addStretch()
        self.elapsed_label = QLabel("")
        self.elapsed_label.setStyleSheet(
            f"color: {Theme.TEXT_MUTED}; font-size: {Theme.FONT_SIZE_BODY}px;")
        top.addWidget(self.elapsed_label)
        lay.addLayout(top)

        self.progress = ProgressBar(height=8)
        lay.addWidget(self.progress)

        self.body_layout.addWidget(card)

    # --Lifecycle --
    def on_leave(self):
        self._stop()
        super().on_leave()

    # --Run / stop --
    def _toggle(self):
        if self._running:
            self._stop()
        else:
            self._start()

    def _start(self):
        self._running = True
        self._start_time = time.time()
        self._phase = "Connecting"
        self.btn.setText("  Stop")
        self.btn.setIcon(Icons.get("stop", "#ffffff"))
        self._style_button(running=True)

        for c in (self.card_dl, self.card_ul, self.card_ping):
            c["value"].setText("\u2014")
            c["spark"].reset()
            self._set_card_active(c, False)
        self.server_label.setText("Server \u2014  \u00b7  ISP \u2014")
        self.phase_label.setStyleSheet(
            f"color: {Theme.TEXT_SECONDARY}; font-size: {Theme.FONT_SIZE_BODY}px;")
        self.phase_label.setText("Connecting to server…")
        self.progress.set_color(Theme.ACCENT)
        self.progress.set_fraction(0.05)
        self._timer.start()

        w = StreamWorker(self.core.speedtest_stream)
        w.result.connect(self._on_event)
        w.error.connect(self._on_error)
        w.done.connect(self._on_finished)
        self.register_worker(w)
        self._worker = w
        w.start()

    def _stop(self):
        if self._worker is not None:
            self._worker.stop()
        self._timer.stop()
        self._running = False
        self.btn.setText("  Start test")
        self.btn.setIcon(Icons.get("play", "#ffffff"))
        self._style_button(running=False)

    def _tick(self):
        if self._running:
            elapsed = time.time() - self._start_time
            self.elapsed_label.setText(f"{elapsed:.1f}s elapsed")

    def _on_event(self, d: dict):
        etype = d.get("type", "")

        if etype == "start":
            isp = d.get("isp", "") or "\u2014"
            server = d.get("server", "") or "\u2014"
            self.server_label.setText(f"Server {server}  \u00b7  ISP {isp}")
            self._set_phase("Ping", 0.15, Theme.SUCCESS)
            self._set_card_active(self.card_ping, True)

        elif etype == "ping":
            ms = d.get("ms", 0)
            self.card_ping["value"].setText(f"{ms:g}")
            self.card_ping["spark"].push(ms)

        elif etype == "download":
            self._set_phase("Download", 0.55, Theme.ACCENT)
            self._set_card_active(self.card_ping, False)
            self._set_card_active(self.card_dl, True)
            mbps = d.get("mbps", 0)
            self.card_dl["value"].setText(f"{mbps:g}")
            self.card_dl["spark"].push(mbps)

        elif etype == "upload":
            self._set_phase("Upload", 0.9, Theme.ACCENT_PURPLE)
            self._set_card_active(self.card_dl, False)
            self._set_card_active(self.card_ul, True)
            mbps = d.get("mbps", 0)
            self.card_ul["value"].setText(f"{mbps:g}")
            self.card_ul["spark"].push(mbps)

        elif etype == "result":
            self.card_ping["value"].setText(f"{d.get('ping', 0):g}")
            self.card_dl["value"].setText(f"{d.get('dl', 0):g}")
            self.card_ul["value"].setText(f"{d.get('ul', 0):g}")
            self.progress.set_color(Theme.SUCCESS)
            self.progress.set_fraction(1.0)
            for c in (self.card_dl, self.card_ul, self.card_ping):
                self._set_card_active(c, False)
            self.phase_label.setText(
                f"<span style='color:{Theme.SUCCESS};'>\u2713 Test complete</span>")
            activity.add("Speed test",
                         f"\u2193 {d.get('dl', 0):g} / \u2191 {d.get('ul', 0):g} Mbps",
                         kind="success")

    def _set_phase(self, name, fraction, color):
        self._phase = name
        self.phase_label.setText(
            f"<span style='color:{Theme.TEXT_SECONDARY};'>Phase: </span>"
            f"<span style='color:{color};'>{name}</span>")
        self.progress.set_fraction(fraction)

    def _on_error(self, msg: str):
        self._timer.stop()
        if "not found" in str(msg).lower():
            self.phase_label.setText(
                "speedtest.exe not found \u2014 place Ookla's CLI on your "
                "Desktop or in Downloads.")
        else:
            self.phase_label.setText(f"Speed test failed: {msg}")
        self.phase_label.setStyleSheet(
            f"color: {Theme.DANGER}; font-size: {Theme.FONT_SIZE_SMALL}px;")

    def _on_finished(self):
        self._timer.stop()
        self._worker = None
        self._stop()
