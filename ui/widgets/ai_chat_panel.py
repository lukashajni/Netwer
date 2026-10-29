"""Chat panel for the AI assistant."""
import html
import os
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

from app.adapter_state import adapter_state
from app.notifications import notifications
from app.resources import Icons
from app.store import store
from app.theme import Theme
from app.traffic_history import traffic_history
from core import ai_client, ai_knowledge, ai_session, ai_tools, network
from core.discovery import get_discovery_service
from ui.widgets.network_map import device_display_name, guess_device_icon
from workers import StreamWorker

WIDTH = 420
BUBBLE_MAX = 318
BUBBLE_WIDE = 720      # answer width in full screen
CHAT_WIDE = 860        # width of the centred conversation in full screen
SUGGESTIONS = ("Explain these results", "What should I fix first?", "How can I improve my network?",
               "Is my network secure?", "Who is on my network?")


def _rich(s: str) -> str:
    s = html.escape(s)
    s = re.sub(r"\*\*(.+?)\*\*", rf"<b style='color:{Theme.TEXT_PRIMARY};'>\1</b>", s)
    s = re.sub(r"`([^`]+)`", rf"<span style='font-family:{Theme.FONT_MONO}; color:{Theme.TEXT_PRIMARY};'>\1</span>", s)
    return f"<div style='line-height:145%;'>{s}</div>"


def markdown_blocks(src: str) -> list:
    # paragraphs, numbered lists, bullet lists and headings are enough for chat answers
    blocks, para, items, kind = [], [], [], None

    def flush_para():
        if para:
            blocks.append({"type": "text", "text": " ".join(para)})
            para.clear()

    def flush_list():
        nonlocal items, kind
        if items:
            blocks.append({"type": "steps" if kind == "num" else "bullets", "items": items})
        items, kind = [], None

    for line in src.split("\n"):
        s = line.strip()
        num, bul = re.match(r"^\d+[.)]\s+(.*)", s), re.match(r"^[-*\u2022]\s+(.*)", s)
        if not s:
            flush_para()
            flush_list()
        elif num or bul:
            flush_para()
            want = "num" if num else "bul"
            if kind != want:
                flush_list()
                kind = want
            items.append((num or bul).group(1))
        elif s.startswith("#"):
            flush_para()
            flush_list()
            blocks.append({"type": "text", "text": f"**{s.lstrip('# ').strip()}**"})
        elif items and line.startswith((" ", "\t")):
            items[-1] += " " + s
        else:
            flush_list()
            para.append(s)
    flush_para()
    flush_list()
    return blocks


def _label(text: str, color: str, size: int = 13, rich: bool = False, bold: bool = False) -> QLabel:
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
        self.setStyleSheet(f"background: {Theme.ACCENT}; border-radius: {size // 2}px;")


class _Typing(QFrame):
    # animated dots with an optional status line
    def __init__(self):
        super().__init__()
        self.setObjectName("Typing")
        self.setStyleSheet(
            f"#Typing {{ background: {Theme.GLASS_INPUT}; border: 1px solid {Theme.GLASS_BORDER};"
            f"border-radius: 14px; border-bottom-left-radius: 4px; }}")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 9, 14, 9)
        lay.setSpacing(8)
        self._dots = QLabel("\u25CF")
        self._dots.setStyleSheet(f"color: {Theme.ACCENT}; font-size: 11px; background: transparent;")
        self._status = QLabel("")
        self._status.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: 12px; background: transparent;")
        lay.addWidget(self._dots)
        lay.addWidget(self._status)
        self._n = 1
        self._timer = QTimer(self)
        self._timer.setInterval(300)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def set_status(self, text: str):
        self._status.setText(text)

    def _tick(self):
        self._n = self._n % 3 + 1
        self._dots.setText("  ".join(["\u25CF"] * self._n))


class _AIBubble(QFrame):
    def __init__(self, on_action, width=BUBBLE_MAX):
        super().__init__()
        self._on_action = on_action
        self.setObjectName("AIBubble")
        self.setFixedWidth(width)
        self.setStyleSheet(
            f"#AIBubble {{ background: {Theme.GLASS_INPUT}; border: 1px solid {Theme.GLASS_BORDER};"
            f"border-radius: 14px; border-bottom-left-radius: 4px; }}")
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(14, 11, 14, 12)
        self._lay.setSpacing(9)

    def set_blocks(self, blocks):
        while self._lay.count():
            w = self._lay.takeAt(0).widget()
            if w is not None:
                w.setParent(None)
        for b in blocks:
            kind = b["type"]
            if kind == "text":
                w = _label(b["text"], Theme.TEXT_BODY, 13, rich=True)
            elif kind == "steps":
                w = self._list(b["items"], numbered=True)
            elif kind == "bullets":
                w = self._list(b["items"], numbered=False)
            elif kind == "actions":
                w = self._actions(b["items"])
            else:
                continue
            self._lay.addWidget(w)

    def _list(self, items, numbered):
        box = QWidget()
        box.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8 if numbered else 6)
        for i, item in enumerate(items, 1):
            row = QHBoxLayout()
            row.setSpacing(10)
            if numbered:
                mark = QLabel(str(i))
                mark.setFixedSize(22, 22)
                mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
                mark.setStyleSheet(f"color: {Theme.ACCENT}; background: transparent; font-size: 11px; font-weight: 700;"
                                   f"border: 1px solid {Theme.ACCENT}; border-radius: 11px;")
            else:
                mark = QLabel("\u2022")
                mark.setFixedWidth(10)
                mark.setStyleSheet(f"color: {Theme.ACCENT}; background: transparent; font-size: 14px;")
            row.addWidget(mark, 0, Qt.AlignmentFlag.AlignTop)
            row.addWidget(_label(item, Theme.TEXT_BODY, 13, rich=True), 1)
            lay.addLayout(row)
        return box

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
    toggled = pyqtSignal(bool)
    expanded = pyqtSignal(bool)      # full screen on / off

    def __init__(self, parent=None, window_mode=False):
        super().__init__(parent)
        # window mode: lives in its own window, no sliding and no full screen button
        self._window_mode = window_mode
        self._report = None
        self._open = window_mode
        self._busy = False
        self._worker = None
        self._history = []
        self._seen_version = ai_session.version
        self._typing = self._typing_row = self._bubble = self._chips = None
        self._answer = ""
        self._actions = []
        self._expanded = False
        if not window_mode:
            self.setMaximumWidth(0)
            self.setMinimumWidth(0)
        self._anim = QPropertyAnimation(self, b"maximumWidth", self)
        self._anim.setDuration(240)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.finished.connect(lambda: self._open and self.input.setFocus())
        self._render_timer = QTimer(self)             # redraw the streaming answer a few times a second
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(70)
        self._render_timer.timeout.connect(self._render)

        shell = QHBoxLayout(self)
        shell.setContentsMargins(0 if window_mode else Theme.GAP, 0, 0, 0)
        shell.setSpacing(0)
        card = QFrame()
        card.setObjectName("AIPanel")
        self._card = card
        if window_mode:
            card.setMinimumWidth(WIDTH)
        else:
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
        self._refresh_status()
        ai_client.add_listener(self._refresh_status)
        if window_mode:
            self.btn_expand.hide()

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
        self._status = QLabel("")
        self._status.setTextFormat(Qt.TextFormat.RichText)
        self._status.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: 11px; background: transparent;")
        col.addWidget(self._status)
        lay.addLayout(col, 1)
        btn_clear = _icon_button("clear_chat", "Clear conversation")
        btn_clear.clicked.connect(self.clear)
        self.btn_expand = _icon_button("expand", "Full screen")
        self.btn_expand.clicked.connect(lambda: self.set_expanded(not self._expanded))
        btn_close = _icon_button("close", "Close")
        btn_close.clicked.connect(self.close_panel)
        for b in (btn_clear, self.btn_expand, btn_close):
            lay.addWidget(b)
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
        lay.addWidget(_Avatar(48), 0, Qt.AlignmentFlag.AlignHCenter)
        title = _label("Hi, I'm Netwer AI", Theme.TEXT_PRIMARY, 18, bold=True)
        title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(title)
        sub = _label("I can read your diagnosis, devices, port scan and traffic from Netwer and explain them "
                     "in plain language.", Theme.TEXT_MUTED, 13)
        sub.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(sub)
        lay.addSpacing(2)
        for q in SUGGESTIONS:
            lay.addWidget(self._suggestion_button(q))
        return w

    def _suggestion_button(self, q: str, compact: bool = False) -> QPushButton:
        b = QPushButton(q)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setStyleSheet(
            f"QPushButton {{ background: {Theme.GLASS_INPUT}; color: {Theme.TEXT_BODY}; text-align: left;"
            f"border: 1px solid {Theme.GLASS_BORDER}; border-radius: {14 if compact else 11}px;"
            f"padding: {'6px 12px' if compact else '8px 14px'}; font-size: {12 if compact else 13}px; }}"
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
        self.btn_send.setFixedSize(34, 34)
        self.btn_send.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_send.setStyleSheet(f"QPushButton {{ background: {Theme.ACCENT}; border: none; border-radius: 17px; }}"
                                    f"QPushButton:hover {{ background: {Theme.ACCENT_HOVER}; }}")
        self.btn_send.clicked.connect(self._on_send_clicked)
        lay.addWidget(self.btn_send)
        outer.addWidget(bar)
        note = QLabel("A summary of your network data (no MAC addresses, public IP or Wi-Fi name) goes to your AI provider.")
        note.setWordWrap(True)
        note.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        note.setStyleSheet(f"color: {Theme.TEXT_FAINT}; font-size: 10px; background: transparent;")
        outer.addWidget(note)
        self._set_busy(False)
        return wrap

    # -- open / close --
    @property
    def is_open(self) -> bool:
        return self._open

    def open(self):
        if self._window_mode:
            return
        if not self._open:
            self._open = True
            self._animate(WIDTH + Theme.GAP)
            self.toggled.emit(True)

    def close_panel(self):
        if self._window_mode:
            self.toggled.emit(False)
            return
        if self._expanded:
            self.set_expanded(False)
        if self._open:
            self._open = False
            self._animate(0)
            self.toggled.emit(False)

    def set_expanded(self, on: bool):
        if on == self._expanded:
            return
        self._expanded = on
        if on:
            self.open()
            self._anim.stop()
            self.setMaximumWidth(16777215)
            self._card.setMinimumWidth(WIDTH)
            self._card.setMaximumWidth(16777215)
        else:
            self._card.setFixedWidth(WIDTH)
            self.setMaximumWidth(WIDTH + Theme.GAP if self._open else 0)
        self.btn_expand.setIcon(Icons.get("compress" if on else "expand", Theme.TEXT_SECONDARY))
        self.btn_expand.setToolTip("Exit full screen (Esc)" if on else "Full screen")
        width = BUBBLE_WIDE if on else BUBBLE_MAX
        for b in self._scroll.widget().findChildren(_AIBubble):
            b.setFixedWidth(width)
        self._center_chat()
        self.expanded.emit(on)
        self._scroll_down()

    def _center_chat(self):
        # keep the conversation readable on a wide window
        side = 16
        if self._expanded:
            side = max(16, (self._scroll.viewport().width() - CHAT_WIDE) // 2)
        self._chat.setContentsMargins(side, 16, side, 12)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._expanded:
            self._center_chat()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and self._expanded:
            self.set_expanded(False)
            return
        super().keyPressEvent(event)

    def toggle(self):
        self.close_panel() if self._open else self.open()

    def _animate(self, target: int):
        self._anim.stop()
        self._anim.setStartValue(self.maximumWidth())
        self._anim.setEndValue(target)
        self._anim.start()

    # -- setup --
    def _refresh_status(self):
        ok = ai_client.is_configured()
        self._status.setText(
            f"<span style='color:{Theme.SUCCESS if ok else Theme.WARNING};'>\u25CF</span>&nbsp; "
            + ("Connected" if ok else "Not connected"))

    # -- conversation --
    def set_report(self, report):
        self._report = report

    def clear(self):
        # the clear button wipes the shared conversation for every panel
        ai_session.clear()
        self._reset_ui()
        self._seen_version = ai_session.version

    def showEvent(self, event):
        super().showEvent(event)
        self._sync()

    def _sync(self):
        # pick up messages written in another panel
        if self._busy or self._seen_version == ai_session.version:
            return
        self._reset_ui()
        if ai_session.entries:
            self._welcome.hide()
        for e in ai_session.entries:
            self._add_user(e["q"])
            bubble = _AIBubble(self._on_action, BUBBLE_WIDE if self._expanded else BUBBLE_MAX)
            blocks = markdown_blocks(e["a"])
            if e["actions"]:
                blocks.append({"type": "actions", "items": e["actions"]})
            bubble.set_blocks(blocks)
            self._add_ai_row(bubble)
        self._history = ai_session.history()
        self._seen_version = ai_session.version

    def _reset_ui(self):
        self.stop()
        self._history.clear()
        self._typing = self._typing_row = self._bubble = self._chips = None
        self._answer, self._actions = "", []
        while self._chat.count():
            item = self._chat.takeAt(0)
            if item.widget() is not None:
                item.widget().setParent(None)
            elif item.layout() is not None:
                self._drop_layout(item.layout())
        self._welcome = self._build_welcome()
        self._chat.addWidget(self._welcome)
        self._chat.addStretch(1)
        self._set_busy(False)

    def stop(self):
        if self._worker is not None:
            self._worker.stop()

    def ask_about(self, finding: dict):
        self.ask(f"Explain this finding and how to fix it: {finding.get('title', '')}. {finding.get('detail', '')}")

    def ask(self, question: str):
        question = (question or "").strip()
        if not question or self._busy:
            return
        self._sync()
        self.open()
        self._welcome.hide()
        self._remove_chips()
        self._add_user(question)
        tools = ai_tools.AppTools(self._snapshot())
        self._answer, self._actions, self._bubble = "", [], None
        self._typing = _Typing()
        self._add_ai_row(self._typing)
        self._set_busy(True)
        self._question = question
        w = StreamWorker(ai_client.chat, list(self._history), question, ai_knowledge.build_system_prompt(),
                         ai_tools.TOOLS, tools, ai_client.load_config())
        w.result.connect(self._on_event)
        w.error.connect(self._on_error)
        w.done.connect(self._on_done)
        self._worker = w
        w.start()

    def _submit(self):
        text = self.input.text()
        self.input.clear()
        self.ask(text)

    def _on_send_clicked(self):
        self.stop() if self._busy else self._submit()

    # -- data the assistant can read --
    def _snapshot(self) -> dict:
        snap = {"selected_adapter": adapter_state.get()}
        r = self._report
        if r:
            m = dict(r.get("measurements") or {})
            for k in ("ssid", "mac", "public_ip"):
                m.pop(k, None)
            snap["diagnosis"] = {"headline": r.get("headline"), "summary": r.get("summary"),
                                 "severity": r.get("severity"), "measurements": m,
                                 "findings": [{k: f.get(k) for k in ("severity", "title", "detail", "action")}
                                              for f in r.get("findings", [])]}
        try:
            cfg = network.get_network_config()
            snap["network"] = {k: cfg.get(k) for k in ("adapter", "ip", "gateway", "dns", "error") if cfg.get(k)}
        except Exception:
            pass
        devices = []
        try:
            for d in get_discovery_service().snapshot().get("devices", [])[:25]:
                devices.append({"ip": d.get("ip", ""), "name": device_display_name(d), "vendor": d.get("vendor", ""),
                                "kind": guess_device_icon(d).replace("dev_", ""), "is_gateway": bool(d.get("is_gateway"))})
        except Exception:
            pass
        snap["devices"] = devices
        try:
            ps = (store.get_last_scan("port_scanner") or {}).get("payload") or {}
            if ps.get("target"):
                snap["port_scan"] = {"target": ps["target"], "target_name": ps.get("target_name", ""),
                                     "device_type": ps.get("device_type", ""),
                                     "open_ports": [{"port": x.get("port"), "service": x.get("service"),
                                                     "banner": (x.get("banner") or "")[:60]} for x in ps.get("results", [])]}
        except Exception:
            pass
        snap["traffic"] = ai_tools.traffic_snapshot(traffic_history.bandwidth(3600), traffic_history.connectivity(3600),
                                                    traffic_history.adapter)
        try:
            from core import wifi
            w = wifi.get_wifi_info() or {}
            if w and "error" not in w:
                snap["wifi"] = {k: v for k, v in w.items() if k not in ("ssid", "bssid", "networks", "nearby")}
        except Exception:
            pass
        try:
            import psutil
            snap["system"] = {"cpu_percent": psutil.cpu_percent(None), "memory_percent": psutil.virtual_memory().percent,
                              "disk_percent": psutil.disk_usage(os.path.abspath(os.sep)).percent}
        except Exception:
            pass
        snap["activity"] = [{"title": n.title, "detail": n.detail, "kind": n.kind} for n in notifications.items()[:10]]
        try:
            from core.capture import get_capture_service
            cap = get_capture_service()
            if cap.count():
                snap["capture"] = cap.summary()
        except Exception:
            pass
        win = self.window()
        if hasattr(win, "current_page_context"):
            try:
                snap["current_page"] = win.current_page_context()
            except Exception:
                pass
        return snap

    # -- streaming --
    def _on_event(self, ev: dict):
        if "tool" in ev and self._typing is not None:
            self._typing.set_status(f"Reading {ev['tool']}\u2026")
        elif "text" in ev:
            if self._bubble is None:
                self._start_bubble()
            self._answer += ev["text"]
            if not self._render_timer.isActive():
                self._render_timer.start()
        elif "action" in ev:
            self._actions.append(ev["action"])

    def _on_error(self, message: str):
        self._answer += ("\n\n" if self._answer else "") + f"\u26A0 {message}"
        if self._bubble is None:
            self._start_bubble()
        self._failed = True
        self._render()

    def _on_done(self):
        self._render_timer.stop()
        if self._bubble is None and self._typing is not None:
            self._start_bubble()
        self._render(final=True)
        if self._answer and not getattr(self, "_failed", False):
            self._history += [{"role": "user", "content": self._question},
                              {"role": "assistant", "content": self._answer}]
            ai_session.add(self._question, self._answer, self._actions)
            self._seen_version = ai_session.version
        self._failed = False
        self._worker = None
        self._typing = None
        self._set_busy(False)
        self._scroll_down()

    def _start_bubble(self):
        if self._typing_row is not None:
            self._chat.removeItem(self._typing_row)
            self._drop_layout(self._typing_row)
            self._typing_row = None
        self._typing = None
        self._bubble = _AIBubble(self._on_action, BUBBLE_WIDE if self._expanded else BUBBLE_MAX)
        self._add_ai_row(self._bubble)

    def _render(self, final: bool = False):
        if self._bubble is None:
            return
        blocks = markdown_blocks(self._answer)
        if final and self._actions:
            blocks.append({"type": "actions", "items": self._actions})
        self._bubble.set_blocks(blocks)
        self._scroll_down()

    # -- layout helpers --
    def _set_busy(self, busy: bool):
        self._busy = busy
        self.btn_send.setIcon(Icons.get("close" if busy else "send", "#ffffff"))
        self.btn_send.setToolTip("Stop" if busy else "Send")
        self.input.setEnabled(not busy)
        if not busy and self._open:
            self.input.setFocus()

    def _drop_layout(self, layout):
        while layout.count():
            it = layout.takeAt(0)
            if it.widget() is not None:
                it.widget().setParent(None)
            elif it.layout() is not None:
                self._drop_layout(it.layout())

    def _add_user(self, text: str):
        bubble = QFrame()
        bubble.setObjectName("UserBubble")
        bubble.setStyleSheet(f"#UserBubble {{ background: {Theme.ACCENT}; border: none; border-radius: 14px;"
                             f"border-bottom-right-radius: 4px; }}")
        lay = QVBoxLayout(bubble)
        lay.setContentsMargins(14, 9, 14, 10)
        label = _label(text, "#ffffff", 13)
        probe = QLabel(text)
        probe.setStyleSheet("font-size: 13px;")
        probe.ensurePolished()
        label.setFixedWidth(min(560 if self._expanded else 250, probe.sizeHint().width() + 2))
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
