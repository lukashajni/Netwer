"""Netwer AI chat panel."""
import html
import re

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.resources import Icons
from app.store import store
from app.theme import Theme
from app.traffic_history import traffic_history
from core import netwer_ai
from core.discovery import get_discovery_service
from ui.widgets.network_map import device_display_name, guess_device_icon

WIDTH = 420
BUBBLE_MAX = 318          # widest AI answer bubble
SEVERITY_COLOUR = {"critical": "DANGER", "warning": "WARNING", "info": "ACCENT", "good": "SUCCESS"}


def _rich(s: str) -> str:
    # escape, then **bold**
    s = html.escape(s)
    s = re.sub(r"\*\*(.+?)\*\*", rf"<b style='color:{Theme.TEXT_PRIMARY};'>\1</b>", s)
    return f"<div style='line-height:145%;'>{s}</div>"


def _label(text: str, color: str, size: float = 13, rich: bool = False, bold: bool = False) -> QLabel:
    lab = QLabel(_rich(text) if rich else text)
    if rich:
        lab.setTextFormat(Qt.TextFormat.RichText)
    lab.setWordWrap(True)
    lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    lab.setStyleSheet(f"color: {color}; font-size: {size}px; background: transparent; border: none;"
                      f"{'font-weight: 600;' if bold else ''}")
    return lab


def _icon_button(icon: str, tip: str, size: int = 30) -> QPushButton:
    b = QPushButton()
    b.setIcon(Icons.get(icon, Theme.TEXT_SECONDARY))
    b.setToolTip(tip)
    b.setFixedSize(size, size)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setStyleSheet(f"QPushButton {{ background: transparent; border: none; border-radius: {size // 2}px; }}"
                    f"QPushButton:hover {{ background: {Theme.BG_CARD_HOVER}; }}")
    return b


class _Avatar(QLabel):
    def __init__(self, size: int):
        super().__init__()
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setPixmap(Icons.pixmap("ai", int(size * 0.5), "#ffffff"))
        self.setStyleSheet(f"background: {Theme.GRAD_ACCENT}; border-radius: {size // 2}px;")


class _Typing(QFrame):
    # animated dots while thinking

    def __init__(self):
        super().__init__()
        self.setObjectName("Typing")
        self.setStyleSheet(
            f"#Typing {{ background: {Theme.GLASS_INPUT}; border: 1px solid {Theme.GLASS_BORDER};"
            f"border-radius: 14px; border-bottom-left-radius: 4px; }}")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 9, 14, 9)
        self._lab = QLabel("\u25CF")
        self._lab.setStyleSheet(f"color: {Theme.ACCENT}; font-size: 11px; background: transparent;")
        lay.addWidget(self._lab)
        self._n = 1
        self._timer = QTimer(self)
        self._timer.setInterval(300)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _tick(self):
        self._n = self._n % 3 + 1
        self._lab.setText("  ".join(["\u25CF"] * self._n))


class _AIBubble(QFrame):
    # one answer, blocks stacked in a bubble

    def __init__(self, on_action):
        super().__init__()
        self._on_action = on_action
        self.setObjectName("AIBubble")
        self.setFixedWidth(BUBBLE_MAX)
        self.setStyleSheet(
            f"#AIBubble {{ background: {Theme.GLASS_INPUT}; border: 1px solid {Theme.GLASS_BORDER};"
            f"border-radius: 14px; border-bottom-left-radius: 4px; }}")
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(14, 11, 14, 12)
        self._lay.setSpacing(9)

    def add_block(self, b: dict):
        kind = b["type"]
        if kind == "text":
            w = _label(b["text"], Theme.TEXT_BODY, 13, rich=True)
        elif kind == "steps":
            w = self._steps(b["items"])
        elif kind == "bullets":
            w = self._bullets(b["items"])
        elif kind == "finding":
            w = self._finding(b)
        elif kind == "actions":
            w = self._actions(b["items"])
        else:
            return
        self._lay.addWidget(w)

    def _steps(self, items):
        box = QWidget()
        box.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        for i, item in enumerate(items, 1):
            row = QHBoxLayout()
            row.setSpacing(10)
            badge = QLabel(str(i))
            badge.setFixedSize(22, 22)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setStyleSheet(f"color: {Theme.ACCENT}; background: transparent; font-size: 11px;"
                                f"font-weight: 700; border: 1px solid {Theme.ACCENT}; border-radius: 11px;")
            row.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
            row.addWidget(_label(item, Theme.TEXT_BODY, 12.5, rich=True), 1)
            lay.addLayout(row)
        return box

    def _bullets(self, items):
        box = QWidget()
        box.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        for item in items:
            row = QHBoxLayout()
            row.setSpacing(9)
            dot = QLabel("\u2022")
            dot.setFixedWidth(10)
            dot.setStyleSheet(f"color: {Theme.ACCENT}; background: transparent; font-size: 14px;")
            row.addWidget(dot, 0, Qt.AlignmentFlag.AlignTop)
            row.addWidget(_label(item, Theme.TEXT_BODY, 12.5, rich=True), 1)
            lay.addLayout(row)
        return box

    def _finding(self, b):
        colour = getattr(Theme, SEVERITY_COLOUR.get(b["severity"], "ACCENT"))
        card = QFrame()
        card.setObjectName("Fnd")
        card.setStyleSheet(f"#Fnd {{ background: rgba(7, 10, 20, 120); border: none;"
                           f"border-left: 3px solid {colour}; border-radius: 8px; }}")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(11, 8, 10, 9)
        lay.setSpacing(3)
        lay.addWidget(_label(b["title"], Theme.TEXT_PRIMARY, 12.5, bold=True))
        if b.get("detail"):
            lay.addWidget(_label(b["detail"], Theme.TEXT_SECONDARY, 12))
        if b.get("action"):
            lay.addWidget(_label("\u2192 " + b["action"], colour, 12))
        return card

    def _actions(self, items):
        box = QWidget()
        box.setStyleSheet("background: transparent;")
        grid = QGridLayout(box)
        grid.setContentsMargins(0, 2, 0, 0)
        grid.setSpacing(6)
        for i, it in enumerate(items):
            btn = QPushButton(it["label"] + "  \u203A")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {Theme.ACCENT}; text-align: left;"
                f"border: 1px solid {Theme.GLASS_BORDER_HI}; border-radius: 9px; padding: 7px 11px;"
                f"font-size: 12px; font-weight: 600; }}"
                f"QPushButton:hover {{ background: {Theme.BG_ELEVATED}; border-color: {Theme.ACCENT}; }}")
            btn.clicked.connect(lambda _=False, t=it["target"]: self._on_action(t))
            grid.addWidget(btn, i // 2, i % 2)
        return box


class AIChatPanel(QWidget):
    navigate = pyqtSignal(str)       # page key, "health_run" or "scan:<ip>"
    toggled = pyqtSignal(bool)       # open / closed

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ai = netwer_ai.NetwerAI()
        self._report = None
        self._open = False
        self._busy = False
        self._typing = None
        self._typing_row = None
        self._chips = None
        self._queue = []
        self._current = None
        self._suggestions = []
        self._token = 0              # invalidates a pending answer after "clear"
        self.setMaximumWidth(0)
        self.setMinimumWidth(0)
        self._anim = QPropertyAnimation(self, b"maximumWidth", self)
        self._anim.setDuration(240)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.finished.connect(self._after_anim)

        shell = QHBoxLayout(self)
        shell.setContentsMargins(Theme.GAP, 0, 0, 0)
        shell.setSpacing(0)
        card = QFrame()
        card.setObjectName("AIPanel")
        card.setFixedWidth(WIDTH)
        card.setStyleSheet(f"#AIPanel {{ background: {Theme.GLASS_CARD}; border: 1px solid {Theme.GLASS_BORDER};"
                           f"border-radius: {Theme.RADIUS_CARD}px; }}")
        shell.addWidget(card)

        outer = QVBoxLayout(card)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_header())
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background: {Theme.GLASS_BORDER};")
        outer.addWidget(line)
        outer.addWidget(self._build_chat(), 1)
        outer.addWidget(self._build_input())

    # -- construction --
    def _build_header(self):
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(16, 14, 12, 12)
        lay.setSpacing(11)
        lay.addWidget(_Avatar(38))
        col = QVBoxLayout()
        col.setSpacing(1)
        col.addWidget(_label("Netwer AI", Theme.TEXT_PRIMARY, 15, bold=True))
        sub = QLabel(f"<span style='color:{Theme.SUCCESS};'>\u25CF</span>&nbsp; Runs on your PC, nothing is sent out")
        sub.setTextFormat(Qt.TextFormat.RichText)
        sub.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: 11px; background: transparent;")
        col.addWidget(sub)
        lay.addLayout(col, 1)
        self.btn_clear = _icon_button("clear_chat", "Clear conversation")
        self.btn_clear.clicked.connect(self.clear)
        btn_close = _icon_button("close", "Close")
        btn_close.clicked.connect(self.close_panel)
        lay.addWidget(self.btn_clear)
        lay.addWidget(btn_close)
        return w

    def _build_chat(self):
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }"
                                   "QScrollBar:vertical { width: 6px; background: transparent; }"
                                   f"QScrollBar::handle:vertical {{ background: {Theme.BORDER_STRONG}; border-radius: 3px; }}"
                                   "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }")
        host = QWidget()
        host.setStyleSheet("background: transparent;")
        self._chat = QVBoxLayout(host)
        self._chat.setContentsMargins(16, 16, 16, 12)
        self._chat.setSpacing(12)
        self._welcome = self._build_welcome()
        self._chat.addWidget(self._welcome)
        self._chat.addStretch(1)
        self._scroll.setWidget(host)
        return self._scroll

    def _build_welcome(self):
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 2, 0, 0)
        lay.setSpacing(8)
        av = _Avatar(48)
        lay.addWidget(av, 0, Qt.AlignmentFlag.AlignHCenter)
        title = _label("Hi, I'm Netwer AI", Theme.TEXT_PRIMARY, 18, bold=True)
        title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(title)
        sub = _label("Ask me about your network. I read your latest diagnosis, devices and traffic and "
                     "explain them in plain language.", Theme.TEXT_MUTED, 12.5)
        sub.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(sub)
        lay.addSpacing(4)
        for q in self._ai.welcome_suggestions():
            lay.addWidget(self._suggestion_button(q))
        return w

    def _suggestion_button(self, q: str, compact: bool = False) -> QPushButton:
        b = QPushButton(q)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        pad = "6px 12px" if compact else "8px 14px"
        radius = 14 if compact else 11
        b.setStyleSheet(
            f"QPushButton {{ background: {Theme.GLASS_INPUT}; color: {Theme.TEXT_BODY}; text-align: left;"
            f"border: 1px solid {Theme.GLASS_BORDER}; border-radius: {radius}px; padding: {pad};"
            f"font-size: {12 if compact else 12.5}px; }}"
            f"QPushButton:hover {{ border-color: {Theme.ACCENT}; background: {Theme.BG_ELEVATED}; }}")
        b.clicked.connect(lambda _=False, t=q: self.ask(t))
        return b

    def _build_input(self):
        wrap = QWidget()
        wrap.setStyleSheet("background: transparent;")
        outer = QVBoxLayout(wrap)
        outer.setContentsMargins(14, 4, 14, 10)
        outer.setSpacing(6)
        bar = QFrame()
        bar.setObjectName("InputBar")
        bar.setStyleSheet(f"#InputBar {{ background: {Theme.GLASS_INPUT}; border: 1px solid {Theme.GLASS_BORDER};"
                          f"border-radius: 18px; }}")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(14, 5, 5, 5)
        lay.setSpacing(6)
        self.input = QLineEdit()
        self.input.setPlaceholderText("Ask about your network\u2026")
        self.input.setStyleSheet(f"QLineEdit {{ background: transparent; border: none; color: {Theme.TEXT_BODY};"
                                 f"font-size: 13px; padding: 6px 0; }}")
        self.input.returnPressed.connect(self._submit)
        lay.addWidget(self.input, 1)
        self.btn_send = QPushButton()
        self.btn_send.setIcon(Icons.get("send", "#ffffff"))
        self.btn_send.setFixedSize(34, 34)
        self.btn_send.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_send.setStyleSheet(f"QPushButton {{ background: {Theme.GRAD_ACCENT}; border: none; border-radius: 17px; }}"
                                    f"QPushButton:disabled {{ background: {Theme.BG_ELEVATED}; }}")
        self.btn_send.clicked.connect(self._submit)
        lay.addWidget(self.btn_send)
        outer.addWidget(bar)
        note = QLabel("Answers come from your own measurements, so run a diagnosis first.")
        note.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        note.setStyleSheet(f"color: {Theme.TEXT_FAINT}; font-size: 10px; background: transparent;")
        outer.addWidget(note)
        return wrap

    # -- open / close --
    @property
    def is_open(self) -> bool:
        return self._open

    def open(self):
        if self._open:
            return
        self._open = True
        self._animate(WIDTH + Theme.GAP)
        self.toggled.emit(True)

    def close_panel(self):
        if not self._open:
            return
        self._open = False
        self._animate(0)
        self.toggled.emit(False)

    def toggle(self):
        self.close_panel() if self._open else self.open()

    def _animate(self, target: int):
        self._anim.stop()
        self._anim.setStartValue(self.maximumWidth())
        self._anim.setEndValue(target)
        self._anim.start()

    def _after_anim(self):
        if self._open:
            self.input.setFocus()

    # -- conversation --
    def set_report(self, report):
        self._report = report

    def clear(self):
        self._token += 1
        self._queue.clear()
        self._current = None
        self._busy = False
        self._typing = None
        self._chips = None
        self._ai.reset()
        while self._chat.count():
            item = self._chat.takeAt(0)
            if item.widget() is not None:
                item.widget().setParent(None)
            elif item.layout() is not None:
                self._drop_layout(item.layout())
        self._welcome = self._build_welcome()
        self._chat.addWidget(self._welcome)
        self._chat.addStretch(1)
        self.input.setEnabled(True)
        self.btn_send.setEnabled(True)

    def _drop_layout(self, layout):
        while layout.count():
            it = layout.takeAt(0)
            if it.widget() is not None:
                it.widget().setParent(None)
            elif it.layout() is not None:
                self._drop_layout(it.layout())

    def ask(self, question: str, finding: dict = None):
        # finding: set when asking about one card
        question = (question or "").strip()
        if not question or self._busy:
            return
        self.open()
        self._welcome.hide()
        self._remove_chips()
        self._add_user(question)
        ctx = self._collect_context()
        answer = (self._ai.explain_finding(finding, ctx) if finding
                  else self._ai.answer(question, ctx))
        self._busy = True
        self.input.setEnabled(False)
        self.btn_send.setEnabled(False)
        self._typing = _Typing()
        self._add_ai_row(self._typing)
        token = self._token
        QTimer.singleShot(650, lambda: self._begin_answer(answer, token))

    def ask_about(self, finding: dict):
        self.ask(f"Explain: {finding.get('title', 'this finding')}", finding=finding)

    def _submit(self):
        text = self.input.text()
        self.input.clear()
        self.ask(text)

    def _collect_context(self) -> dict:
        devices = []
        try:
            for d in get_discovery_service().snapshot().get("devices", []):
                devices.append({"ip": d.get("ip", ""), "name": device_display_name(d),
                                "kind": guess_device_icon(d).replace("dev_", ""),
                                "is_gateway": bool(d.get("is_gateway"))})
        except Exception:
            pass
        port_scan = None
        try:
            port_scan = (store.get_last_scan("port_scanner") or {}).get("payload")
        except Exception:
            pass
        traffic = netwer_ai.traffic_summary(traffic_history.bandwidth(300),
                                            traffic_history.connectivity(300), traffic_history.adapter)
        return netwer_ai.build_context(self._report, devices, port_scan, traffic)

    # -- rendering --
    def _begin_answer(self, answer: dict, token: int):
        if token != self._token or self._typing is None:      # cleared while thinking
            return
        row = self._typing_row
        self._chat.removeItem(row)
        self._drop_layout(row)
        bubble = _AIBubble(self._on_action)
        self._add_ai_row(bubble)
        self._queue = list(answer["blocks"])
        self._suggestions = answer.get("suggestions", [])
        self._current = bubble
        self._reveal()

    def _reveal(self):
        if self._current is None:
            return
        if self._queue:
            self._current.add_block(self._queue.pop(0))
            self._scroll_down()
            token = self._token
            QTimer.singleShot(170, lambda: token == self._token and self._reveal())
            return
        if self._suggestions:
            self._add_chips(self._suggestions)
        self._current = None
        self._typing = None
        self._busy = False
        self.input.setEnabled(True)
        self.btn_send.setEnabled(True)
        self.input.setFocus()
        self._scroll_down()

    def _add_user(self, text: str):
        bubble = QFrame()
        bubble.setObjectName("UserBubble")
        bubble.setStyleSheet(
            f"#UserBubble {{ background: {Theme.GRAD_ACCENT}; border: none; border-radius: 14px;"
            f"border-bottom-right-radius: 4px; }}")
        lay = QVBoxLayout(bubble)
        lay.setContentsMargins(14, 9, 14, 10)
        label = _label(text, "#ffffff", 13)
        # Size the bubble to its text, wrapping only past 250 px.
        probe = QLabel(text)
        probe.setStyleSheet("font-size: 13px;")
        probe.ensurePolished()
        label.setFixedWidth(min(250, probe.sizeHint().width() + 2))
        lay.addWidget(label)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(bubble)
        self._insert(row)

    def _add_ai_row(self, content: QWidget):
        row = QHBoxLayout()
        row.setSpacing(9)
        row.addWidget(_Avatar(28), 0, Qt.AlignmentFlag.AlignTop)
        row.addWidget(content, 0, Qt.AlignmentFlag.AlignTop)
        row.addStretch(1)
        if isinstance(content, _Typing):
            self._typing_row = row
        self._insert(row)

    def _add_chips(self, suggestions):
        col = QVBoxLayout()
        col.setContentsMargins(37, 0, 0, 0)
        col.setSpacing(6)
        for s in suggestions:
            b = self._suggestion_button(s, compact=True)
            wrap = QHBoxLayout()
            wrap.addWidget(b)
            wrap.addStretch(1)
            col.addLayout(wrap)
        self._chips = col
        self._insert(col)

    def _remove_chips(self):
        if self._chips is not None:
            self._chat.removeItem(self._chips)
            self._drop_layout(self._chips)
            self._chips = None

    def _insert(self, layout):
        self._chat.insertLayout(self._chat.count() - 1, layout)
        self._scroll_down()

    def _scroll_down(self):
        bar = self._scroll.verticalScrollBar()
        for ms in (0, 80):
            QTimer.singleShot(ms, lambda: bar.setValue(bar.maximum()))

    def _on_action(self, target: str):
        self.navigate.emit(target)
