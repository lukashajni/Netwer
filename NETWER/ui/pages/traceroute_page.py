"""
NETWER — Traceroute page.

Trace the network path to a destination. Enter a host, hit Trace, and watch
each hop appear live: hop number, IP, hostname and round-trip time. Timed-out
hops show in red; the final hop is tagged as the destination.

The trace runs in a StreamWorker around netwer_core.traceroute_stream, which
first yields {"resolved": ip, "target": host}, then one dict per hop
({"ttl", "ip", "hostname", "avg"} or {"ttl", "timeout": True}), and finally
{"done": True, "reached": bool}.
"""

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
from workers import StreamWorker


HOP_OPTIONS = [("Max hops: 15", 15), ("Max hops: 30", 30), ("Max hops: 64", 64)]


class TraceroutePage(BasePage):
    PAGE_TITLE = "Traceroute"
    PAGE_SUBTITLE = "Trace the network path to a destination"

    COL_HOP = 46
    COL_IP = 150
    COL_RTT = 78

    def __init__(self, core, parent=None, embedded=False):
        super().__init__(core, parent, embedded=embedded)
        self._worker = None
        self._running = False
        self._resolved = None
        self._hop_count = 0

        self._build_toolbar()
        self._build_status()
        self._build_table()
        self.body_layout.addStretch(1)

    # ── UI ─────────────────────────────────────────────────────
    def _build_toolbar(self):
        row = QHBoxLayout()
        row.setSpacing(8)

        self.input = QLineEdit()
        self.input.setPlaceholderText("Hostname or IP (e.g. google.com)")
        self.input.setStyleSheet(
            f"QLineEdit {{ background: {Theme.BG_CARD}; color: {Theme.TEXT_BODY};"
            f"border: 1px solid {Theme.BORDER_STRONG}; border-radius: 8px;"
            f"padding: 9px 12px; font-family: {Theme.FONT_MONO};"
            f"font-size: {Theme.FONT_SIZE_BODY}px; }}"
            f"QLineEdit:focus {{ border-color: {Theme.ACCENT}; }}")
        self.input.returnPressed.connect(self._toggle)
        row.addWidget(self.input, 1)

        self.hops_combo = QComboBox()
        for label, value in HOP_OPTIONS:
            self.hops_combo.addItem(label, value)
        self.hops_combo.setCurrentIndex(1)
        self.hops_combo.setStyleSheet(
            f"QComboBox {{ background: {Theme.BG_CARD}; color: {Theme.TEXT_SECONDARY};"
            f"border: 1px solid {Theme.BORDER}; border-radius: 8px;"
            f"padding: 9px 12px; font-size: {Theme.FONT_SIZE_SMALL}px; }}"
            f"QComboBox::drop-down {{ border: none; width: 20px; }}"
            f"QComboBox QAbstractItemView {{ background: {Theme.BG_ELEVATED};"
            f"color: {Theme.TEXT_BODY}; selection-background-color: {Theme.ACCENT};"
            f"border: 1px solid {Theme.BORDER_STRONG}; outline: none; }}")
        row.addWidget(self.hops_combo)

        self.btn = QPushButton("  Trace")
        self.btn.setIcon(Icons.get("traceroute", "#ffffff"))
        self.btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn.setMinimumWidth(120)
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

    def _build_status(self):
        card = QFrame()
        card.setObjectName("TraceStatus")
        card.setStyleSheet(
            f"#TraceStatus {{ background: {Theme.BG_CARD};"
            f"border: 1px solid {Theme.BORDER}; border-radius: {Theme.RADIUS_CARD}px; }}"
            f"#TraceStatus QLabel {{ background: transparent; border: none; }}")
        lay = QHBoxLayout(card)
        lay.setContentsMargins(14, 11, 14, 11)

        self.status_left = QLabel("Ready to trace")
        self.status_left.setStyleSheet(
            f"color: {Theme.TEXT_SECONDARY}; font-size: {Theme.FONT_SIZE_BODY}px;")
        lay.addWidget(self.status_left)
        lay.addStretch()
        self.status_right = QLabel("")
        self.status_right.setStyleSheet(
            f"color: {Theme.TEXT_SECONDARY}; font-size: {Theme.FONT_SIZE_BODY}px;")
        lay.addWidget(self.status_right)

        self.body_layout.addWidget(card)

    def _build_table(self):
        card = Card("Hops", "route")
        card.setMinimumHeight(280)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 6)
        for text, w in (("Hop", self.COL_HOP), ("IP", self.COL_IP),
                        ("Hostname", -1), ("RTT", self.COL_RTT)):
            lbl = QLabel(text)
            lbl.setAlignment((Qt.AlignmentFlag.AlignRight if text == "RTT"
                              else Qt.AlignmentFlag.AlignLeft)
                             | Qt.AlignmentFlag.AlignVCenter)
            lbl.setStyleSheet(
                f"color: {Theme.TEXT_FAINT}; font-size: 11px; font-weight: 600;"
                f"letter-spacing: 0.5px; background: transparent;")
            if w >= 0:
                lbl.setFixedWidth(w)
                header.addWidget(lbl)
            else:
                header.addWidget(lbl, 1)
        header_wrap = QFrame()
        header_wrap.setStyleSheet(
            f"border-bottom: 1px solid {Theme.BORDER}; background: transparent;")
        header_wrap.setLayout(header)
        card.content_layout.addWidget(header_wrap)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollBar:vertical { background: transparent; width: 8px; }"
            f"QScrollBar::handle:vertical {{ background: {Theme.BORDER_STRONG};"
            f"border-radius: 4px; min-height: 24px; }}"
            "QScrollBar::add-line, QScrollBar::sub-line { height: 0; }")

        self._rows_host = QWidget()
        self._rows_host.setStyleSheet("background: transparent;")
        self._rows_layout = QVBoxLayout(self._rows_host)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(0)
        self._rows_layout.addStretch(1)
        self._empty = None

        scroll.setWidget(self._rows_host)
        card.content_layout.addWidget(scroll, 1)
        self.body_layout.addWidget(card, 1)

        self._show_empty("Enter a destination and press Trace.")

    def _show_empty(self, text):
        if self._empty is not None:
            self._empty.setText(text)
            return
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color: {Theme.TEXT_MUTED}; font-size: {Theme.FONT_SIZE_SMALL}px;"
            f"background: transparent; padding: 16px 2px;")
        self._rows_layout.insertWidget(self._rows_layout.count() - 1, lbl)
        self._empty = lbl

    def _clear_rows(self):
        while self._rows_layout.count():
            item = self._rows_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._rows_layout.addStretch(1)
        self._empty = None

    def _hop_row(self, ttl, ip, hostname, rtt, timeout=False, dest=False):
        row = QFrame()
        row.setStyleSheet(
            f"QFrame {{ background: transparent;"
            f"border-bottom: 1px solid {Theme.BORDER}; }}"
            f"QFrame:hover {{ background: {Theme.BG_CARD_HOVER}; }}")
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 8, 0, 8)

        n = QLabel(str(ttl))
        n.setFixedWidth(self.COL_HOP)
        n.setStyleSheet(
            f"color: {Theme.TEXT_SECONDARY}; font-size: 13px; font-weight: 500;"
            f"background: transparent;")
        rl.addWidget(n)

        ip_lbl = QLabel(ip)
        ip_lbl.setFixedWidth(self.COL_IP)
        ip_lbl.setStyleSheet(
            f"color: {Theme.DANGER if timeout else Theme.TEXT_BODY};"
            f"font-family: {Theme.FONT_MONO}; font-size: 13px; background: transparent;")
        rl.addWidget(ip_lbl)

        if dest:
            host_html = (f"<span style='color:{Theme.ACCENT}; font-size:14px;'>{hostname}</span>"
                         f" <span style='color:{Theme.TEXT_MUTED}; font-size:11px;'>\u00b7 destination</span>")
        elif timeout:
            host_html = f"<span style='color:{Theme.DANGER}; font-size:14px;'>{hostname}</span>"
        else:
            host_html = f"<span style='color:{Theme.TEXT_BODY}; font-size:14px;'>{hostname}</span>"
        host = QLabel(host_html)
        host.setStyleSheet("background: transparent;")
        rl.addWidget(host, 1)

        rtt_lbl = QLabel(rtt)
        rtt_lbl.setFixedWidth(self.COL_RTT)
        rtt_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        rtt_lbl.setStyleSheet(
            f"color: {Theme.DANGER if timeout else Theme.SUCCESS};"
            f"font-family: {Theme.FONT_MONO}; font-size: 13px; background: transparent;")
        rl.addWidget(rtt_lbl)

        self._rows_layout.insertWidget(self._rows_layout.count() - 1, row)

    # ── Lifecycle ──────────────────────────────────────────────
    def on_leave(self):
        self._stop()
        super().on_leave()

    # ── Run / stop ─────────────────────────────────────────────
    def _toggle(self):
        if self._running:
            self._stop()
        else:
            self._start()

    def _start(self):
        target = self.input.text().strip()
        if not target:
            return
        self._running = True
        self._resolved = None
        self._hop_count = 0
        self.btn.setText("  Stop")
        self.btn.setIcon(Icons.get("stop", "#ffffff"))
        self._style_button(running=True)
        self.input.setEnabled(False)
        self.hops_combo.setEnabled(False)

        self._clear_rows()
        self.status_left.setText(f"Tracing {target}…")
        self.status_right.setText("")

        max_hops = self.hops_combo.currentData()
        w = StreamWorker(self.core.traceroute_stream, target, max_hops)
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
        self.btn.setIcon(Icons.get("traceroute", "#ffffff"))
        self._style_button(running=False)
        self.input.setEnabled(True)
        self.hops_combo.setEnabled(True)

    def _on_event(self, d: dict):
        if "resolved" in d:
            self._resolved = d["resolved"]
            target = d.get("target", "")
            self.status_left.setText(
                f"Resolved {target} \u2192 {d['resolved']}")
            return

        if d.get("done"):
            return  # handled in _on_finished (reached flag stored below)

        ttl = d.get("ttl")
        if ttl is None:
            return
        self._hop_count = max(self._hop_count, ttl)

        if d.get("timeout"):
            self._hop_row(ttl, "\u2014", "Request timed out", "\u2014",
                          timeout=True)
        else:
            ip = d.get("ip", "")
            hostname = d.get("hostname", ip) or ip
            avg = d.get("avg")
            is_dest = (self._resolved is not None and ip == self._resolved)
            self._hop_row(ttl, ip, hostname,
                          f"{avg} ms" if avg is not None else "\u2014",
                          dest=is_dest)
            if is_dest:
                self._reached = True

    def _on_error(self, msg: str):
        self.status_left.setText(str(msg))

    def _on_finished(self):
        if self._running:
            reached = getattr(self, "_reached", False)
            if reached:
                self.status_right.setText(
                    f"\u2713 Reached in {self._hop_count} hops")
                self.status_right.setStyleSheet(
                    f"color: {Theme.SUCCESS}; font-size: {Theme.FONT_SIZE_BODY}px; font-weight: 500;")
            else:
                self.status_right.setText("Destination not reached")
                self.status_right.setStyleSheet(
                    f"color: {Theme.WARNING}; font-size: {Theme.FONT_SIZE_BODY}px; font-weight: 500;")
            if self._hop_count == 0:
                self._show_empty("No hops returned.")
            activity.add("Traceroute", f"{self.input.text().strip()} \u00b7 "
                         f"{self._hop_count} hops", kind="success")
        self._reached = False
        self._worker = None
        self._stop()
