"""Follow-stream and statistics dialogs for the Packet Capture page."""

import html

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
)

from app.theme import Theme, card_bg, card_border
from ui.widgets.ui_kit import button

MAX_SHOWN = 200_000


def _printable(data: bytes) -> str:
    return "".join(chr(b) if 32 <= b < 127 or b in (9, 10) else "." for b in data)


def _size(n):
    return f"{n / 1048576:.2f} MB" if n >= 1048576 else f"{n / 1024:.1f} KB" if n >= 1024 else f"{n} B"


class _Base(QDialog):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setStyleSheet(f"QDialog {{ background: {Theme.BG_SIDEBAR}; }}"
                           f"QLabel {{ background: transparent; color: {Theme.TEXT_BODY}; }}")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(20, 18, 20, 18)
        self.lay.setSpacing(12)
        head = QLabel(title)
        head.setStyleSheet(f"color: {Theme.TEXT_PRIMARY}; font-size: 17px; font-weight: 600;")
        self.lay.addWidget(head)

    def _ask(self, question):
        win = self.parentWidget().window() if self.parentWidget() else None
        self.accept()
        if hasattr(win, "ask_ai"):
            win.ask_ai(question)


class FollowStreamDialog(_Base):
    def __init__(self, svc, stream, on_filter, parent=None):
        info = svc.follow_stream(stream)
        kind = (info or {}).get("l4", "tcp").upper()
        super().__init__(f"Follow {kind} stream #{stream}", parent)
        self.resize(820, 620)
        if info is None:
            self.lay.addWidget(QLabel("This stream is no longer in the capture."))
            return
        sub = QLabel(f"<span style='color:{Theme.ACCENT}'>{info['client']}</span> → "
                     f"<span style='color:{Theme.ACCENT_PURPLE}'>{info['server']}</span>"
                     f" ({html.escape(info['server_name'])}) · {info['packets']} packets")
        sub.setTextFormat(Qt.TextFormat.RichText)
        sub.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-family: {Theme.FONT_MONO}; font-size: 12px;")
        self.lay.addWidget(sub)
        if info["encrypted"]:
            note = QLabel("This stream is encrypted. Only the handshake can be read; the rest is shown as raw bytes.")
            note.setStyleSheet(f"color: {Theme.WARNING}; font-size: {Theme.FONT_SIZE_SMALL}px;")
            self.lay.addWidget(note)

        text = QTextEdit()
        text.setReadOnly(True)
        text.setStyleSheet(f"QTextEdit {{ background: {card_bg()}; border: 1px solid {card_border()};"
                           f"border-radius: {Theme.RADIUS_CONTROL}px; padding: 8px; }}")
        parts, shown = [], 0
        for side, data in info["chunks"]:
            data = data[:MAX_SHOWN - shown]
            shown += len(data)
            color = Theme.ACCENT if side == "client" else Theme.ACCENT_PURPLE
            parts.append(f"<span style='color:{color}'>{html.escape(_printable(data))}</span>")
            if shown >= MAX_SHOWN:
                parts.append(f"<br><span style='color:{Theme.TEXT_MUTED}'>[cut at 200 KB]</span>")
                break
        if not parts:
            parts.append(f"<span style='color:{Theme.TEXT_MUTED}'>No payload in this stream, only handshakes and ACKs.</span>")
        text.setHtml(f"<pre style='font-family: Consolas, monospace; font-size: 12px; white-space: pre-wrap;'>"
                     f"{''.join(parts)}</pre>")
        self.lay.addWidget(text, 1)

        legend = QLabel(f"<span style='color:{Theme.ACCENT}'>■</span> sent by {info['client']}   "
                        f"<span style='color:{Theme.ACCENT_PURPLE}'>■</span> sent by {info['server']}")
        legend.setTextFormat(Qt.TextFormat.RichText)
        legend.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: {Theme.FONT_SIZE_TINY}px;")
        row = QHBoxLayout()
        row.addWidget(legend)
        row.addStretch()
        b_filter = button("Show only this stream", "list")
        b_filter.clicked.connect(lambda: (on_filter(f"{info['l4']}.stream == {stream}"), self.accept()))
        row.addWidget(b_filter)
        b_ai = button("Ask Netwer AI", "ai", "ai")
        b_ai.clicked.connect(lambda: self._ask(
            f"Explain {kind} stream #{stream} in my capture, between {info['client']} and {info['server']} "
            f"({info['server_name']}). What are they doing?"))
        row.addWidget(b_ai)
        close = button("Close", kind="primary")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        self.lay.addLayout(row)


class StatisticsDialog(_Base):
    def __init__(self, svc, on_filter, parent=None):
        super().__init__("Capture statistics", parent)
        self.resize(860, 560)
        self._svc, self._on_filter = svc, on_filter
        hint = QLabel("Double-click a row to show only its packets.")
        hint.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: {Theme.FONT_SIZE_SMALL}px;")
        self.lay.addWidget(hint)

        tabs = QTabWidget()
        tabs.setStyleSheet(
            f"QTabWidget::pane {{ border: 1px solid {card_border()}; border-radius: {Theme.RADIUS_CONTROL}px; }}"
            f"QTabBar::tab {{ background: transparent; color: {Theme.TEXT_SECONDARY}; padding: 7px 14px; }}"
            f"QTabBar::tab:selected {{ color: {Theme.TEXT_PRIMARY}; border-bottom: 2px solid {Theme.ACCENT}; }}")
        convs = svc.conversations()
        tabs.addTab(self._table(
            ["Address A", "Address B", "Packets", "Data", "Duration", "Main protocol"],
            [[svc.host(c["a"]), svc.host(c["b"]), c["packets"], _size(c["bytes"]), f"{c['end'] - c['start']:.1f} s",
              c["protos"].most_common(1)[0][0]] for c in convs],
            [f"ip.addr == {c['a']} && ip.addr == {c['b']}" for c in convs]), f"Conversations ({len(convs)})")
        eps = svc.endpoints()
        tabs.addTab(self._table(
            ["Address", "Name", "Packets", "Data", "Sent", "Received"],
            [[e["ip"], svc.host(e["ip"]) if svc.host(e["ip"]) != e["ip"] else "", e["packets"], _size(e["bytes"]),
              _size(e["sent"]), _size(e["received"])] for e in eps],
            [f"ip.addr == {e['ip']}" for e in eps]), f"Endpoints ({len(eps)})")
        self.lay.addWidget(tabs, 1)

        row = QHBoxLayout()
        row.addStretch()
        b_ai = button("Ask Netwer AI", "ai", "ai")
        b_ai.clicked.connect(lambda: self._ask(
            "Look at the conversations in my capture. Who does my computer talk to most, and is anything unusual?"))
        row.addWidget(b_ai)
        close = button("Close", kind="primary")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        self.lay.addLayout(row)

    def _table(self, headers, rows, filters):
        t = QTableWidget(len(rows), len(headers))
        t.setHorizontalHeaderLabels(headers)
        t.verticalHeader().hide()
        t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        t.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        t.setShowGrid(False)
        t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        t.setStyleSheet(
            f"QTableWidget {{ background: {card_bg()}; color: {Theme.TEXT_BODY}; border: none;"
            f"font-family: {Theme.FONT_MONO}; font-size: 12px; }}"
            f"QTableWidget::item:selected {{ background: {Theme.ACCENT}; color: #ffffff; }}"
            f"QHeaderView::section {{ background: {Theme.BG_ELEVATED}; color: {Theme.TEXT_MUTED}; border: none;"
            f"padding: 6px 8px; font-size: {Theme.FONT_SIZE_TINY}px; }}")
        for r, values in enumerate(rows):
            for c, v in enumerate(values):
                item = QTableWidgetItem(str(v))
                if isinstance(v, int):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                t.setItem(r, c, item)
        t.cellDoubleClicked.connect(lambda r, _c: (self._on_filter(filters[r]), self.accept()))
        return t
