"""Ping a host and display live connectivity and latency results."""

import re
from collections import deque

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
)

from app.activity import activity
from app.notifications import notifications
from app.resources import Icons
from app.theme import Theme
from ui.pages.base_page import BasePage
from ui.widgets.card import Card
from ui.widgets.ui_kit import InsightRow, empty_state
from ui.widgets.host_input import HostInput
from ui.widgets.latency_chart import LatencyChart
from ui.widgets.terminal_output import TerminalOutput
from workers import StreamWorker

COUNT_OPTIONS = [
    ("4 packets", 4),
    ("10 packets", 10),
    ("25 packets", 25),
    ("50 packets", 50),
    ("Continuous", 0),
]


class PingPage(BasePage):
    PAGE_TITLE = "Ping"
    PAGE_SUBTITLE = "Test connectivity and latency to any host"
    AI_QUESTION = "Explain my ping results. Is this connection good?"

    def __init__(self, core, parent=None):
        super().__init__(core, parent)
        self._recent = deque(maxlen=40)

        self._worker = None
        self._running = False

        self._build_toolbar()
        self._build_stats()
        self.findings = InsightRow(self.ask_ai)
        self.body_layout.addWidget(self.findings)
        self._build_results()
        self.body_layout.addStretch(1)

    # -- UI --
    def _build_toolbar(self):
        row = QHBoxLayout()
        row.setSpacing(8)

        self.target_input = HostInput(
            kind="ping", placeholder="IP address or hostname (e.g. 8.8.8.8)")
        self.target_input.submitted.connect(self._toggle)
        row.addWidget(self.target_input, 1)

        self.count_combo = QComboBox()
        for label, value in COUNT_OPTIONS:
            self.count_combo.addItem(label, value)
        self.count_combo.setCurrentIndex(1)   # default: 10 packets
        self.count_combo.setStyleSheet(
            f"QComboBox {{ background: {Theme.GLASS_INPUT}; color: {Theme.TEXT_BODY};"
            f"border: 1px solid {Theme.BORDER}; border-radius: 8px;"
            f"padding: 9px 12px; font-size: {Theme.FONT_SIZE_SMALL}px; }}"
            f"QComboBox::drop-down {{ border: none; width: 20px; }}"
            f"QComboBox QAbstractItemView {{ background: {Theme.BG_ELEVATED};"
            f"color: {Theme.TEXT_BODY}; selection-background-color: {Theme.ACCENT};"
            f"border: 1px solid {Theme.BORDER_STRONG}; outline: none; }}")
        row.addWidget(self.count_combo)

        self.btn_run = QPushButton("  Start")
        self.btn_run.setIcon(Icons.get("play", "#ffffff"))
        self.btn_run.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_run.setMinimumWidth(120)
        self._style_run_button(running=False)
        self.btn_run.clicked.connect(self._toggle)
        row.addWidget(self.btn_run)

        self.body_layout.addLayout(row)

    def _style_run_button(self, running: bool):
        color = Theme.DANGER if running else Theme.ACCENT
        hover = Theme.DANGER_HOVER if running else Theme.ACCENT_HOVER
        self.btn_run.setStyleSheet(
            f"QPushButton {{ background: {color}; color: white; border: none;"
            f"border-radius: 8px; padding: 9px 20px;"
            f"font-size: {Theme.FONT_SIZE_BODY}px; font-weight: 600; }}"
            f"QPushButton:hover {{ background: {hover}; }}")

    def _build_stats(self):
        row = QHBoxLayout()
        row.setSpacing(Theme.GAP)

        self.stat_current = self._stat("Current", Theme.TEXT_MUTED)
        self.stat_avg = self._stat("Average", Theme.ACCENT)
        self.stat_jitter = self._stat("Jitter", Theme.ACCENT_PURPLE)
        self.stat_loss = self._stat("Packet loss", Theme.SUCCESS)

        for s in (self.stat_current, self.stat_avg, self.stat_jitter, self.stat_loss):
            row.addWidget(s["card"])
        self.body_layout.addLayout(row)

    def _stat(self, label, color):
        card = Card("", "")
        card.setFixedHeight(76)

        lbl = QLabel(label)
        lbl.setStyleSheet(
            f"color: {Theme.TEXT_SECONDARY}; font-size: {Theme.FONT_SIZE_TINY}px;"
            f"background: transparent;")
        card.content_layout.addWidget(lbl)

        value = QLabel("\u2014")
        value.setStyleSheet(
            f"color: {color}; font-family: {Theme.FONT_DATA};"
            f"font-size: 20px; font-weight: 600; background: transparent;")
        card.content_layout.addWidget(value)
        card.content_layout.addStretch()

        return {"card": card, "value": value, "color": color}

    def _build_results(self):
        row = QHBoxLayout()
        row.setSpacing(Theme.GAP)
        H = 300

        chart_card = Card("Latency over time", "monitor")
        chart_card.setFixedHeight(H)
        self.chart = LatencyChart(max_points=60)
        chart_card.content_layout.addWidget(self.chart)
        row.addWidget(chart_card, 14)

        out_card = Card("Replies", "terminal")
        out_card.setFixedHeight(H)

        self.sent_label = QLabel("")
        self.sent_label.setStyleSheet(
            f"color: {Theme.TEXT_FAINT}; font-size: {Theme.FONT_SIZE_TINY}px;"
            f"background: transparent;")
        out_card.header_layout.addWidget(self.sent_label)

        self.terminal = TerminalOutput()
        self.terminal.hide()
        self._replies_empty = empty_state("ping", "No replies yet",
                                          "Enter a host and press Start to see every reply here.")
        out_card.content_layout.addWidget(self._replies_empty)
        out_card.content_layout.addWidget(self.terminal)
        row.addWidget(out_card, 10)

        self.body_layout.addLayout(row)

    # -- Lifecycle --
    def on_leave(self):
        self._stop()
        super().on_leave()

    # -- Run / stop -- 
    def _toggle(self):
        if self._running:
            self._stop()
        else:
            self._start()

    def _start(self):
        target = self.target_input.text().strip()
        self._replies_empty.hide()
        self.terminal.show()
        self.findings.set_items([])
        if not target:
            self.terminal.append("Enter a target first", kind="error")
            return

        self._running = True
        self.btn_run.setText("  Stop")
        self.btn_run.setIcon(Icons.get("stop", "#ffffff"))
        self._style_run_button(running=True)
        self.target_input.setEnabled(False)
        self.count_combo.setEnabled(False)

        self.chart.reset()
        self.terminal.clear()
        self._reset_stats()
        self._link_up = None   # reset watch-mode transition tracking

        count = self.count_combo.currentData()
        self.terminal.append(f"Pinging {target}…", kind="info")

        from app.store import store
        ping_to = store.get_setting("ping_timeout_ms", 1000)
        w = StreamWorker(self.core.ping_custom_stream, target, count, ping_to)
        w.result.connect(self._on_reply)
        w.error.connect(
            lambda e: self.terminal.append(
                self.core.friendly_error(e), kind="error"))
        w.done.connect(self._on_finished)
        self.register_worker(w)
        self._worker = w
        w.start()

    def _stop(self):
        if self._worker is not None:
            self._worker.stop()
        self._running = False
        self.btn_run.setText("  Start")
        self.btn_run.setIcon(Icons.get("play", "#ffffff"))
        self._style_run_button(running=False)
        self.target_input.setEnabled(True)
        self.count_combo.setEnabled(True)

    def _on_finished(self):
        if self._running:
            self.terminal.append("Ping complete", kind="info")
            target = self.target_input.text().strip()
            avg = self.stat_avg["value"].text()
            activity.add("Ping completed", f"{target} · avg {avg}",
                         kind="success")
            self.target_input.remember()
        self._worker = None
        self._stop()

    # -- Results --
    def _on_reply(self, d: dict):
        if d.get("done"):
            return

        target = self.target_input.text().strip()
        ms = d.get("ms")
        is_up = d.get("status") == "ok"
        self._recent.append(ms if is_up else None)

        # Notify only when watch mode detects a connectivity transition.
        prev = getattr(self, "_link_up", None)
        if prev is not None and prev != is_up:
            if is_up:
                self.terminal.append(
                    f"\u2714 {target} is back UP", f"{ms} ms", kind="ok")
                activity.add("Host recovered", f"{target} is reachable again",
                             kind="success")
            else:
                self.terminal.append(
                    f"\u26a0 {target} went DOWN", "no reply", kind="error")
                activity.add("Host unreachable",
                             f"{target} stopped responding", kind="error")
            # Bell notification (respects the "host down" toggle in Settings).
            notifications.notify_host_down(target, is_up)
        self._link_up = is_up

        if is_up:
            self.chart.push(ms)
            self.terminal.append(f"Reply from {target}", f"{ms} ms", kind="ok")
            self._set_stat(self.stat_current, f"{ms}", "ms",
                           self._latency_color(ms))
        else:
            self.chart.push(None)
            self.terminal.append("Request timed out", "\u2014", kind="error")
            self._set_stat(self.stat_current, "\u2014", "", Theme.DANGER)

        if d.get("avg") is not None:
            self._set_stat(self.stat_avg, f"{d['avg']}", "ms", Theme.ACCENT)
        self._set_stat(self.stat_jitter, f"{d.get('jitter', 0)}", "ms",
                       Theme.ACCENT_PURPLE)

        loss = d.get("loss", 0)
        loss_color = (Theme.SUCCESS if loss < 1 else
                      Theme.WARNING if loss < 10 else Theme.DANGER)
        self._set_stat(self.stat_loss, f"{loss}", "%", loss_color)

        self.sent_label.setText(f"{d.get('sent', 0)} packets sent")
        self._update_findings(target, d)

    def _update_findings(self, target, d):
        got = [x for x in self._recent if x is not None]
        if len(self._recent) < 3:
            return
        items = []
        if not got:
            items.append({"severity": "danger", "text": "Host not responding", "detail": target,
                          "question": f"Why does {target} not answer my ping?"})
            self.findings.set_items(items)
            return
        avg, jitter, loss = d.get("avg") or 0, d.get("jitter", 0) or 0, d.get("loss", 0) or 0
        if avg < 30:
            sev, text = "success", "Latency excellent"
        elif avg < 80:
            sev, text = "info", "Latency good"
        elif avg < 150:
            sev, text = "warning", "Latency high"
        else:
            sev, text = "danger", "Very high latency"
        items.append({"severity": sev, "text": text, "detail": f"{avg} ms avg",
                      "question": f"My ping to {target} averages {avg} ms. Is that good, and what affects it?"})
        if jitter > 30:
            items.append({"severity": "warning", "text": "Unstable latency", "detail": f"jitter {jitter} ms",
                          "question": f"My ping to {target} has {jitter} ms jitter. What causes that and how do I fix it?"})
        else:
            items.append({"severity": "success", "text": "Stable", "detail": f"jitter {jitter} ms",
                          "question": "What is jitter and why does it matter for calls and games?"})
        if loss > 0:
            items.append({"severity": "danger" if loss >= 5 else "warning", "text": "Packet loss", "detail": f"{loss}%",
                          "question": f"I lose {loss}% of packets when pinging {target}. Where could they be lost?"})
        else:
            items.append({"severity": "success", "text": "No packet loss", "detail": "",
                          "question": "Explain my ping results. Is this connection good?"})
        self.findings.set_items(items)

    @staticmethod
    def _latency_color(ms):
        if ms is None:
            return Theme.DANGER
        if ms < 30:
            return Theme.SUCCESS
        if ms < 100:
            return Theme.WARNING
        return Theme.DANGER

    def _set_stat(self, stat, value, unit, color):
        if unit:
            stat["value"].setText(
                f"<span style='color:{color}; font-family:{Theme.FONT_DATA};"
                f"font-size:20px; font-weight:600;'>{value}</span>"
                f" <span style='color:{Theme.TEXT_MUTED}; font-size:12px;'>{unit}</span>")
        else:
            stat["value"].setText(
                f"<span style='color:{color}; font-size:20px;"
                f"font-weight:600;'>{value}</span>")

    def _reset_stats(self):
        for stat in (self.stat_current, self.stat_avg,
                     self.stat_jitter, self.stat_loss):
            stat["value"].setText("\u2014")
            stat["value"].setStyleSheet(
                f"color: {Theme.TEXT_MUTED}; font-family: {Theme.FONT_DATA};"
                f"font-size: 20px; font-weight: 600; background: transparent;")
        self.sent_label.setText("")

    def ai_context(self):
        def v(stat):
            return re.sub(r"<[^>]+>", "", stat["value"].text()).strip()
        return {"target": self.target_input.text().strip(), "running": self._running,
                "current_ms": v(self.stat_current), "avg_ms": v(self.stat_avg),
                "jitter_ms": v(self.stat_jitter), "loss_pct": v(self.stat_loss),
                "sent": self.sent_label.text(), "recent_ms": list(self._recent)}
