"""
NETWER — DNS Lookup page.

Resolve a domain name to its IP addresses. Enter a hostname, hit Resolve,
and see the canonical name plus every A (IPv4) and AAAA (IPv6) record the
resolver returns, each copyable to the clipboard.

The lookup runs in a OneshotWorker around netwer_core.dns_lookup, which
returns {"ipv4": [...], "ipv6": [...], "canonical": str, "total": int}.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QFrame, QApplication
)

from app.theme import Theme
from app.resources import Icons
from app.activity import activity
from ui.pages.base_page import BasePage
from ui.widgets.card import Card
from workers import OneshotWorker


class DnsLookupPage(BasePage):
    PAGE_TITLE = "DNS Lookup"
    PAGE_SUBTITLE = "Resolve a domain name to its IP addresses"

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
        self.input.setPlaceholderText("Domain name (e.g. cloudflare.com)")
        self.input.setStyleSheet(
            f"QLineEdit {{ background: {Theme.BG_CARD}; color: {Theme.TEXT_BODY};"
            f"border: 1px solid {Theme.BORDER_STRONG}; border-radius: 8px;"
            f"padding: 9px 12px; font-family: {Theme.FONT_MONO};"
            f"font-size: {Theme.FONT_SIZE_BODY}px; }}"
            f"QLineEdit:focus {{ border-color: {Theme.ACCENT}; }}")
        self.input.returnPressed.connect(self._resolve)
        row.addWidget(self.input, 1)

        self.btn = QPushButton("  Resolve")
        self.btn.setIcon(Icons.get("dns", "#ffffff"))
        self.btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn.setMinimumWidth(120)
        self.btn.setStyleSheet(
            f"QPushButton {{ background: {Theme.ACCENT}; color: white; border: none;"
            f"border-radius: 8px; padding: 9px 20px;"
            f"font-size: {Theme.FONT_SIZE_BODY}px; font-weight: 600; }}"
            f"QPushButton:hover {{ background: {Theme.ACCENT_PURPLE}; }}"
            f"QPushButton:disabled {{ background: {Theme.BORDER_STRONG}; }}")
        self.btn.clicked.connect(self._resolve)
        row.addWidget(self.btn)

        self.body_layout.addLayout(row)

    def _build_stats(self):
        row = QHBoxLayout()
        row.setSpacing(Theme.GAP)
        self.stat_canonical = self._stat("Canonical name", Theme.TEXT_BODY)
        self.stat_v4 = self._stat("IPv4 records", Theme.SUCCESS)
        self.stat_v6 = self._stat("IPv6 records", Theme.ACCENT_PURPLE)
        for s in (self.stat_canonical, self.stat_v4, self.stat_v6):
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
        value.setStyleSheet(
            f"color: {color}; font-family: {Theme.FONT_DATA};"
            f"font-size: 18px; font-weight: 600; background: transparent;")
        card.content_layout.addWidget(value)
        card.content_layout.addStretch()
        return {"card": card, "value": value}

    def _build_results(self):
        self.results_card = Card("Resolved addresses", "summary")
        self.results_card.setMinimumHeight(220)
        self._rows = QVBoxLayout()
        self._rows.setSpacing(0)
        self.results_card.content_layout.addLayout(self._rows)
        self.results_card.content_layout.addStretch()
        self._placeholder = QLabel("Enter a domain and press Resolve.")
        self._placeholder.setStyleSheet(
            f"color: {Theme.TEXT_MUTED}; font-size: {Theme.FONT_SIZE_SMALL}px;"
            f"background: transparent; padding: 12px 2px;")
        self._rows.addWidget(self._placeholder)
        self.body_layout.addWidget(self.results_card)

    def _record_row(self, rtype, value, color):
        row = QFrame()
        row.setStyleSheet(
            f"background: transparent; border-bottom: 1px solid {Theme.BORDER};")
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 7, 0, 7)

        tag = QLabel(rtype)
        tag.setFixedWidth(60)
        tag.setStyleSheet(
            f"color: {color}; font-size: 11px; font-weight: 600; background: transparent;")
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
            f"QPushButton:hover {{ background: {Theme.BG_CARD_HOVER};"
            f"border-radius: 4px; }}")
        copy.clicked.connect(lambda: QApplication.clipboard().setText(value))
        rl.addWidget(copy)
        return row

    def _clear_rows(self):
        while self._rows.count():
            item = self._rows.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._placeholder = None

    # ── Lifecycle ──────────────────────────────────────────────
    def on_leave(self):
        if self._worker is not None:
            self._worker.stop()
        super().on_leave()

    # ── Resolve ────────────────────────────────────────────────
    def _resolve(self):
        domain = self.input.text().strip()
        if not domain:
            return
        self.btn.setEnabled(False)
        self.btn.setText("  Resolving…")
        self._clear_rows()

        w = OneshotWorker(self.core.dns_lookup, domain)
        w.result.connect(self._on_result)
        w.error.connect(self._on_error)
        w.done.connect(self._on_done)
        self.register_worker(w)
        self._worker = w
        w.start()

    def _on_result(self, d: dict):
        canonical = d.get("canonical", "") or "\u2014"
        ipv4 = d.get("ipv4", []) or []
        ipv6 = d.get("ipv6", []) or []

        self.stat_canonical["value"].setText(canonical)
        self.stat_v4["value"].setText(str(len(ipv4)))
        self.stat_v6["value"].setText(str(len(ipv6)))

        self._clear_rows()
        for ip in ipv4:
            self._rows.addWidget(self._record_row("A", ip, Theme.ACCENT))
        for ip in ipv6:
            self._rows.addWidget(self._record_row("AAAA", ip, Theme.ACCENT_PURPLE))
        if not ipv4 and not ipv6:
            empty = QLabel("No records returned.")
            empty.setStyleSheet(
                f"color: {Theme.TEXT_MUTED}; font-size: {Theme.FONT_SIZE_SMALL}px;"
                f"background: transparent; padding: 12px 2px;")
            self._rows.addWidget(empty)

        activity.add("DNS lookup", f"{self.input.text().strip()} \u00b7 "
                     f"{len(ipv4) + len(ipv6)} records", kind="success")

    def _on_error(self, msg: str):
        self.stat_canonical["value"].setText("\u2014")
        self.stat_v4["value"].setText("0")
        self.stat_v6["value"].setText("0")
        self._clear_rows()
        err = QLabel(f"Could not resolve: {msg}")
        err.setStyleSheet(
            f"color: {Theme.DANGER}; font-size: {Theme.FONT_SIZE_SMALL}px;"
            f"background: transparent; padding: 12px 2px;")
        self._rows.addWidget(err)

    def _on_done(self):
        self._worker = None
        self.btn.setEnabled(True)
        self.btn.setText("  Resolve")
