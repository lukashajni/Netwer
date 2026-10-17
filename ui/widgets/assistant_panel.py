"""Chat panel for the Network Health page."""
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.store import store
from app.theme import Theme
from app.traffic_history import traffic_history
from core import assistant
from core.discovery import get_discovery_service
from ui.widgets.card import Card
from ui.widgets.network_map import device_display_name, guess_device_icon
from workers import StreamWorker

GREETING = ("Hi! Run \u201cDiagnose my network\u201d, then ask me about the results. "
            "I explain findings in plain language and walk you through fixes.")
SUGGESTIONS = ("Explain these results", "What should I fix first?", "Is my network secure?")


class _Bubble(QFrame):
    def __init__(self, text: str, role: str):
        super().__init__()
        user = role == "user"
        self.setObjectName("Bubble")
        bg = Theme.GRAD_ACCENT if user else Theme.GLASS_INPUT
        border = "none" if user else f"1px solid {Theme.GLASS_BORDER}"
        self.setStyleSheet(
            f"#Bubble {{ background: {bg}; border: {border}; border-radius: 12px; }}"
            f"#Bubble QLabel {{ background: transparent; border: none; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 9, 12, 9)
        self.label = QLabel()
        self.label.setWordWrap(True)
        self.label.setTextFormat(Qt.TextFormat.MarkdownText)
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.label.setStyleSheet(
            f"color: {'white' if user else Theme.TEXT_BODY}; font-size: {Theme.FONT_SIZE_SMALL + 0.5}px;")
        lay.addWidget(self.label)
        self.set_text(text)

    def set_text(self, text: str):
        self.label.setText(text)


class AssistantPanel(Card):
    def __init__(self, core, parent=None):
        super().__init__("AI assistant", "summary", parent)
        self.core = core
        self._report = None
        self._history = []
        self._worker = None
        self._bubble = None
        self._answer = ""
        self.setMinimumWidth(360)

        self.status = QLabel("")
        self.status.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: {Theme.FONT_SIZE_TINY}px;")
        self.header_layout.addWidget(self.status)
        self.btn_key = QPushButton("API key")
        self.btn_key.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_key.setStyleSheet(
            f"QPushButton {{ background: {Theme.BG_ELEVATED}; color: {Theme.TEXT_BODY};"
            f"border: 1px solid {Theme.BORDER_STRONG}; border-radius: 6px; padding: 3px 10px;"
            f"font-size: {Theme.FONT_SIZE_TINY}px; }}"
            f"QPushButton:hover {{ border-color: {Theme.ACCENT}; color: {Theme.ACCENT}; }}")
        self.btn_key.clicked.connect(self._ask_for_key)
        self.header_layout.addWidget(self.btn_key)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        host = QWidget()
        host.setStyleSheet("background: transparent;")
        self._chat = QVBoxLayout(host)
        self._chat.setContentsMargins(0, 0, 6, 0)
        self._chat.setSpacing(8)
        self._chat.addStretch()
        self._scroll.setWidget(host)
        self.content_layout.addWidget(self._scroll, 1)

        self._chips = QWidget()
        self._chips.setStyleSheet("background: transparent;")
        chips = QHBoxLayout(self._chips)
        chips.setContentsMargins(0, 0, 0, 0)
        chips.setSpacing(6)
        for text in SUGGESTIONS:
            b = QPushButton(text)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(
                f"QPushButton {{ background: {Theme.GLASS_INPUT}; color: {Theme.TEXT_SECONDARY};"
                f"border: 1px solid {Theme.GLASS_BORDER}; border-radius: 12px; padding: 5px 10px;"
                f"font-size: {Theme.FONT_SIZE_TINY}px; }}"
                f"QPushButton:hover {{ border-color: {Theme.ACCENT}; color: {Theme.TEXT_PRIMARY}; }}")
            b.clicked.connect(lambda _=False, t=text: self.ask(t))
            chips.addWidget(b)
        chips.addStretch()
        self.content_layout.addWidget(self._chips)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.input = QLineEdit()
        self.input.setPlaceholderText("Ask about your network\u2026")
        self.input.setStyleSheet(
            f"QLineEdit {{ background: {Theme.GLASS_INPUT}; color: {Theme.TEXT_BODY};"
            f"border: 1px solid {Theme.GLASS_BORDER}; border-radius: 10px; padding: 9px 12px;"
            f"font-size: {Theme.FONT_SIZE_SMALL}px; }}"
            f"QLineEdit:focus {{ border-color: {Theme.GLASS_BORDER_HI}; }}")
        self.input.returnPressed.connect(self._submit)
        row.addWidget(self.input, 1)
        self.btn_send = QPushButton("Send")
        self.btn_send.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_send.setStyleSheet(
            f"QPushButton {{ background: {Theme.GRAD_ACCENT}; color: white; border: none;"
            f"border-radius: 10px; padding: 9px 18px; font-size: {Theme.FONT_SIZE_SMALL}px;"
            f"font-weight: 600; }}")
        self.btn_send.clicked.connect(self._on_send_clicked)
        row.addWidget(self.btn_send)
        self.content_layout.addLayout(row)

        self.privacy = QLabel(
            "Questions and a summary of your diagnosis (no MAC addresses, public IP or Wi-Fi name) "
            "are sent to Anthropic.")
        self.privacy.setWordWrap(True)
        self.privacy.setStyleSheet(f"color: {Theme.TEXT_FAINT}; font-size: 10px;")
        self.content_layout.addWidget(self.privacy)

        self._add_bubble(GREETING, "assistant")
        self._refresh_status()

    def set_report(self, report):
        self._report = report

    def ask(self, question: str):
        question = (question or "").strip()
        if not question or self._worker is not None:
            return
        key = assistant.get_api_key()
        if not key:
            self._add_bubble("To chat I need an Anthropic API key. Press \u201cAPI key\u201d and paste "
                             "yours (it stays on this computer). The diagnosis itself works without it.",
                             "assistant")
            return
        self._chips.hide()
        self._add_bubble(question, "user")
        messages = assistant.build_messages(self._history, question, self._collect_context())
        self._history.append({"role": "user", "content": question})

        self._answer = ""
        self._bubble = self._add_bubble("\u2026", "assistant")
        self._set_busy(True)
        self._worker = StreamWorker(assistant.stream_answer, messages, key, assistant.get_model())
        self._worker.result.connect(self._on_chunk)
        self._worker.error.connect(self._on_error)
        self._worker.done.connect(self._on_done)
        self._worker.start()

    def stop(self):
        if self._worker is not None:
            self._worker.stop()

    def _collect_context(self) -> dict:
        devices = []
        try:
            for d in get_discovery_service().snapshot().get("devices", []):
                devices.append({"ip": d.get("ip", ""), "name": device_display_name(d),
                                "vendor": d.get("vendor", ""),
                                "kind": guess_device_icon(d).replace("dev_", ""),
                                "is_gateway": bool(d.get("is_gateway"))})
        except Exception:
            pass
        port_scan = None
        try:
            last = store.get_last_scan("port_scanner")
            port_scan = (last or {}).get("payload")
        except Exception:
            pass
        traffic = assistant.traffic_summary(
            traffic_history.bandwidth(300), traffic_history.connectivity(300),
            traffic_history.adapter)
        return assistant.build_context(self._report, devices, port_scan, traffic)

    def _submit(self):
        text = self.input.text()
        self.input.clear()
        self.ask(text)

    def _on_send_clicked(self):
        if self._worker is not None:
            self.stop()
        else:
            self._submit()

    def _on_chunk(self, ev: dict):
        if "text" in ev and self._bubble is not None:
            self._answer += ev["text"]
            self._bubble.set_text(self._answer)
            self._scroll_down()

    def _on_error(self, message: str):
        if self._bubble is not None:
            shown = (self._answer + "\n\n" if self._answer else "") + f"\u26A0 {message}"
            self._bubble.set_text(shown)

    def _on_done(self):
        if self._answer:
            self._history.append({"role": "assistant", "content": self._answer})
        elif self._history and self._history[-1]["role"] == "user":
            self._history.pop()
        self._worker = None
        self._bubble = None
        self._set_busy(False)

    def _set_busy(self, busy: bool):
        self.btn_send.setText("Stop" if busy else "Send")
        self.input.setEnabled(not busy)
        if not busy:
            self.input.setFocus()

    def _add_bubble(self, text: str, role: str) -> _Bubble:
        bubble = _Bubble(text, role)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        if role == "user":
            row.addStretch(1)
            row.addWidget(bubble, 5)
        else:
            row.addWidget(bubble, 5)
            row.addStretch(1)
        self._chat.insertLayout(self._chat.count() - 1, row)
        self._scroll_down()
        return bubble

    def _scroll_down(self):
        bar = self._scroll.verticalScrollBar()
        QTimer.singleShot(0, lambda: bar.setValue(bar.maximum()))

    def _refresh_status(self):
        ok = bool(assistant.get_api_key())
        self.status.setText("Ready" if ok else "No API key")
        self.status.setStyleSheet(
            f"color: {Theme.SUCCESS if ok else Theme.WARNING}; font-size: {Theme.FONT_SIZE_TINY}px;")

    def _ask_for_key(self):
        text, ok = QInputDialog.getText(
            self, "Anthropic API key",
            "Paste your API key (console.anthropic.com).\nIt is stored on this computer only.",
            QLineEdit.EchoMode.Password, "")
        if ok:
            store.set_setting("anthropic_api_key", text.strip())
            self._refresh_status()