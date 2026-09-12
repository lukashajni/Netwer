"""
NETWER — Reverse DNS page.

Find the hostname behind an IP address (PTR lookup). Enter an IP, hit
Lookup, and see the resolved hostname plus any aliases the resolver returns.

Runs in a OneshotWorker around netwer_core.reverse_dns, which returns
{"ip": str, "hostname": str, "aliases": [...]} or {"error": ...}.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QFrame,
    QApplication
)

from app.theme import Theme
from app.resources import Icons
from app.activity import activity
from ui.pages.base_page import BasePage
from ui.widgets.card import Card
from workers import OneshotWorker


class ReverseDnsPage(BasePage):
    PAGE_TITLE = "Reverse DNS"
    PAGE_SUBTITLE = "Find the hostname behind an IP address"

    def __init__(self, core, parent=None, embedded=False):
        super().__init__(core, parent, embedded=embedded)
        self._worker = None
        self._build_toolbar()
        self._build_stats()
        self._build_results()
        self.body_layout.addStretch(1)

    # ── UI ─────────────────────────────────────────────────────
    def _build_toolbar(self):
        row = QHBoxLayout()
        row.setSpacing(8)

        self.input = QLineEdit()
        self.input.setPlaceholderText("IP address (e.g. 8.8.8.8)")
        self.input.setStyleSheet(
            f"QLineEdit {{ background: {Theme.GLASS_INPUT}; color: {Theme.TEXT_BODY};"
            f"border: 1px solid {Theme.BORDER_STRONG}; border-radius: 8px;"
            f"padding: 9px 12px; font-family: {Theme.FONT_MONO};"
            f"font-size: {Theme.FONT_SIZE_BODY}px; }}"
            f"QLineEdit:focus {{ border-color: {Theme.GLASS_BORDER_HI}; }}")
        self.input.returnPressed.connect(self._lookup)
        row.addWidget(self.input, 1)

        self.btn = QPushButton("  Lookup")
        self.btn.setIcon(Icons.get("reverse_dns", "#ffffff"))
        self.btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn.setMinimumWidth(120)
        self.btn.setStyleSheet(
            f"QPushButton {{ background: {Theme.GRAD_ACCENT}; color: white; border: none;"
            f"border-radius: 8px; padding: 9px 20px;"
            f"font-size: {Theme.FONT_SIZE_BODY}px; font-weight: 600; }}"
            f"QPushButton:hover {{ background: {Theme.ACCENT_PURPLE}; }}"
            f"QPushButton:disabled {{ background: {Theme.BORDER_STRONG}; }}")
        self.btn.clicked.connect(self._lookup)
        row.addWidget(self.btn)

        self.body_layout.addLayout(row)

    def _build_stats(self):
        row = QHBoxLayout()
        row.setSpacing(Theme.GAP)
        self.stat_ip = self._stat("IP address", Theme.TEXT_BODY)
        self.stat_host = self._stat("Hostname", Theme.SUCCESS)
        for s in (self.stat_ip, self.stat_host):
            row.addWidget(s["card"], 1)
        self.body_layout.addLayout(row)

    def _stat(self, label, color):
        card = Card("", "")
        card.setFixedHeight(72)
        lbl = QLabel(label)
        lbl.setStyleSheet(
            f"color: {Theme.TEXT_SECONDARY}; font-size: {Theme.FONT_SIZE_TINY}px;"
            f"background: transparent;")
        card.content_layout.addWidget(lbl)
        value = QLabel("\u2014")
        value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        value.setStyleSheet(
            f"color: {color}; font-family: {Theme.FONT_DATA};"
            f"font-size: 18px; font-weight: 600; background: transparent;")
        card.content_layout.addWidget(value)
        card.content_layout.addStretch()
        return {"card": card, "value": value}

    def _build_results(self):
        self.results_card = Card("Aliases", "summary")
        self.results_card.setMinimumHeight(180)
        self._rows = QVBoxLayout()
        self._rows.setSpacing(0)
        self.results_card.content_layout.addLayout(self._rows)
        self.results_card.content_layout.addStretch()
        self._set_message("Enter an IP address and press Lookup.")
        self.body_layout.addWidget(self.results_card)

    def _set_message(self, text, color=None):
        self._clear_rows()
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color: {color or Theme.TEXT_MUTED}; font-size: {Theme.FONT_SIZE_SMALL}px;"
            f"background: transparent; padding: 12px 2px;")
        self._rows.addWidget(lbl)

    def _alias_row(self, value):
        row = QFrame()
        row.setStyleSheet(
            f"background: transparent; border-bottom: 1px solid {Theme.BORDER};")
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 7, 0, 7)
        tag = QLabel("PTR")
        tag.setFixedWidth(60)
        tag.setStyleSheet(
            f"color: {Theme.ACCENT}; font-size: 11px; font-weight: 600; background: transparent;")
        rl.addWidget(tag)
        val = QLabel(value)
        val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        val.setStyleSheet(
            f"color: {Theme.TEXT_BODY}; font-family: {Theme.FONT_MONO};"
            f"font-size: 12px; background: transparent;")
        rl.addWidget(val, 1)
        copy = QPushButton()
        copy.setIcon(Icons.get("copy", Theme.TEXT_FAINT))
        copy.setCursor(Qt.CursorShape.PointingHandCursor)
        copy.setFixedSize(24, 24)
        copy.setStyleSheet(
            "QPushButton { background: transparent; border: none; }"
            f"QPushButton:hover {{ background: {Theme.BG_CARD_HOVER}; border-radius: 4px; }}")
        copy.clicked.connect(lambda: QApplication.clipboard().setText(value))
        rl.addWidget(copy)
        return row

    def _clear_rows(self):
        while self._rows.count():
            item = self._rows.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    # ── Lifecycle ──────────────────────────────────────────────
    def on_leave(self):
        if self._worker is not None:
            self._worker.stop()
        super().on_leave()

    # ── Lookup ─────────────────────────────────────────────────
    def _lookup(self):
        ip = self.input.text().strip()
        if not ip:
            return
        self.btn.setEnabled(False)
        self.btn.setText("  Looking up…")

        w = OneshotWorker(self.core.reverse_dns, ip)
        w.result.connect(self._on_result)
        w.error.connect(self._on_error)
        w.done.connect(self._on_done)
        self.register_worker(w)
        self._worker = w
        w.start()

    def _on_result(self, d: dict):
        ip = d.get("ip", "") or "\u2014"
        hostname = d.get("hostname", "") or "\u2014"
        aliases = d.get("aliases", []) or []

        self.stat_ip["value"].setText(ip)
        self.stat_host["value"].setText(hostname)

        self._clear_rows()
        # The primary hostname always shows as the first PTR row.
        self._rows.addWidget(self._alias_row(hostname))
        for a in aliases:
            if a and a != hostname:
                self._rows.addWidget(self._alias_row(a))
        extra = [a for a in aliases if a and a != hostname]
        if not extra:
            note = QLabel("No additional aliases returned.")
            note.setStyleSheet(
                f"color: {Theme.TEXT_MUTED}; font-size: {Theme.FONT_SIZE_TINY}px;"
                f"background: transparent; padding: 8px 2px;")
            self._rows.addWidget(note)

        activity.add("Reverse DNS", f"{ip} \u2192 {hostname}", kind="success")

    def _on_error(self, msg: str):
        self.stat_ip["value"].setText(self.input.text().strip() or "\u2014")
        self.stat_host["value"].setText("\u2014")
        self._set_message(f"No PTR record found ({msg}).", Theme.DANGER)

    def _on_done(self):
        self._worker = None
        self.btn.setEnabled(True)
        self.btn.setText("  Lookup")
