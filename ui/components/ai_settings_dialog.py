from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from app.theme import Theme
from core import ai_client
from workers import OneshotWorker


class AISettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI assistant")
        self.setMinimumWidth(480)
        self.setStyleSheet(
            f"QDialog {{ background: {Theme.BG_APP}; }}"
            f"QLabel {{ color: {Theme.TEXT_BODY}; font-size: {Theme.FONT_SIZE_SMALL}px; background: transparent; }}"
            f"QLineEdit, QComboBox {{ background: {Theme.GLASS_INPUT}; color: {Theme.TEXT_BODY};"
            f"border: 1px solid {Theme.GLASS_BORDER}; border-radius: 8px; padding: 8px 10px;"
            f"font-size: {Theme.FONT_SIZE_SMALL}px; }}"
            f"QLineEdit:focus {{ border-color: {Theme.ACCENT}; }}"
            f"QComboBox QAbstractItemView {{ background: {Theme.BG_ELEVATED}; color: {Theme.TEXT_BODY};"
            f"selection-background-color: {Theme.ACCENT}; border: 1px solid {Theme.BORDER_STRONG}; }}")
        cfg = ai_client.load_config()
        self._worker = None

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(12)
        title = QLabel("Connect an AI")
        title.setStyleSheet(f"color: {Theme.TEXT_PRIMARY}; font-size: 18px; font-weight: 600; background: transparent;")
        root.addWidget(title)
        intro = QLabel("The assistant reads data from Netwer (diagnosis, devices, port scan, traffic) "
                       "and answers with the AI you connect here.")
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-size: {Theme.FONT_SIZE_SMALL}px; background: transparent;")
        root.addWidget(intro)

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        self.provider = QComboBox()
        for key, label in ai_client.PROVIDERS.items():
            self.provider.addItem(label, key)
        self.provider.setCurrentIndex(max(self.provider.findData(cfg["provider"]), 0))
        self.url = QLineEdit(cfg["url"])
        self.model = QLineEdit(cfg["model"])
        self.key = QLineEdit(cfg["key"])
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText("Paste your API key")
        form.addRow("Provider", self.provider)
        form.addRow("Address", self.url)
        form.addRow("Model", self.model)
        form.addRow("API key", self.key)
        root.addLayout(form)
        reset = QPushButton("Reset address and model")
        reset.setCursor(Qt.CursorShape.PointingHandCursor)
        reset.setStyleSheet(f"QPushButton {{ background: transparent; color: {Theme.ACCENT}; border: none;"
                            f"text-align: left; padding: 0; font-size: {Theme.FONT_SIZE_SMALL}px; }}"
                            f"QPushButton:hover {{ color: {Theme.ACCENT_HOVER}; }}")
        reset.clicked.connect(self._reset_defaults)
        root.addWidget(reset, 0, Qt.AlignmentFlag.AlignLeft)
        self._last_defaults = ai_client.DEFAULTS[cfg["provider"]]
        self.provider.currentIndexChanged.connect(self._provider_changed)

        hint = QLabel("Claude: Anthropic. Gemini: Google Gemini (key from Google AI Studio). OpenAI, Ollama and most servers: OpenAI-compatible. "
                      "For Ollama use http://localhost:11434/v1 and any key.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: {Theme.FONT_SIZE_TINY}px; background: transparent;")
        root.addWidget(hint)
        note = QLabel("When you ask a question, a summary of your network data (no MAC addresses, public IP or "
                      "Wi-Fi name) is sent to this provider. The key is stored on this computer.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: {Theme.FONT_SIZE_TINY}px; background: transparent;")
        root.addWidget(note)

        self.result = QLabel("")
        self.result.setWordWrap(True)
        self.result.setStyleSheet("background: transparent;")
        root.addWidget(self.result)

        row = QHBoxLayout()
        self.btn_test = self._button("Test connection", primary=False)
        self.btn_test.clicked.connect(self._test)
        row.addWidget(self.btn_test)
        row.addStretch()
        cancel = self._button("Cancel", primary=False)
        cancel.clicked.connect(self.reject)
        save = self._button("Save")
        save.clicked.connect(self._save)
        row.addWidget(cancel)
        row.addWidget(save)
        root.addLayout(row)

    def _button(self, text, primary=True):
        b = QPushButton(text)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        if primary:
            b.setStyleSheet(f"QPushButton {{ background: {Theme.ACCENT}; color: white; border: none; border-radius: 8px;"
                            f"padding: 9px 20px; font-size: {Theme.FONT_SIZE_SMALL}px; font-weight: 600; }}"
                            f"QPushButton:hover {{ background: {Theme.ACCENT_HOVER}; }}")
        else:
            b.setStyleSheet(f"QPushButton {{ background: transparent; color: {Theme.TEXT_BODY};"
                            f"border: 1px solid {Theme.BORDER_STRONG}; border-radius: 8px; padding: 9px 18px;"
                            f"font-size: {Theme.FONT_SIZE_SMALL}px; font-weight: 600; }}"
                            f"QPushButton:hover {{ border-color: {Theme.ACCENT}; }}")
        return b

    def _provider_changed(self):
        # swap the defaults, but keep anything the user typed
        new = ai_client.DEFAULTS[self.provider.currentData()]
        if self.url.text().strip() in ("", self._last_defaults["url"]):
            self.url.setText(new["url"])
        if self.model.text().strip() in ("", self._last_defaults["model"]):
            self.model.setText(new["model"])
        self._last_defaults = new

    def _reset_defaults(self):
        d = ai_client.DEFAULTS[self.provider.currentData()]
        self.url.setText(d["url"])
        self.model.setText(d["model"])
        self._last_defaults = d
        self._show("Address and model reset to the defaults for this provider.", ok=None)

    def _address_problem(self, cfg):
        # common mix-up: the website instead of the API address
        host = cfg["url"].lower()
        if cfg["provider"] == "gemini" and "generativelanguage.googleapis.com" not in host:
            return ("For Gemini the address must be https://generativelanguage.googleapis.com/v1beta/openai "
                    "(gemini.google.com is the website). Press \u201cReset address and model\u201d.")
        if cfg["provider"] == "anthropic" and "anthropic" not in host and "claude.ai" in host:
            return "claude.ai is the website; the API address is https://api.anthropic.com."
        return ""

    def _current(self):
        return {"provider": self.provider.currentData(), "url": self.url.text().strip(),
                "model": self.model.text().strip(), "key": self.key.text().strip()}

    def _test(self):
        cfg = self._current()
        if not cfg["model"] or not cfg["url"]:
            self._show("Fill in the address and model first.", ok=False)
            return
        problem = self._address_problem(cfg)
        if problem:
            self._show(problem, ok=False)
            return
        self.btn_test.setEnabled(False)
        self._show("Testing\u2026", ok=None)
        self._worker = OneshotWorker(lambda: {"message": ai_client.test_connection(cfg)})
        self._worker.result.connect(lambda r: self._show("Connected." if not r["message"] else r["message"], ok=not r["message"]))
        self._worker.error.connect(lambda e: self._show(e, ok=False))
        self._worker.done.connect(lambda: self.btn_test.setEnabled(True))
        self._worker.start()

    def _show(self, text, ok):
        color = Theme.TEXT_MUTED if ok is None else Theme.SUCCESS if ok else Theme.DANGER
        self.result.setStyleSheet(f"color: {color}; font-size: {Theme.FONT_SIZE_SMALL}px; background: transparent;")
        self.result.setText(text)

    def _save(self):
        c = self._current()
        problem = self._address_problem(c)
        if problem:
            self._show(problem, ok=False)
            return
        ai_client.save_config(c["provider"], c["url"], c["model"], c["key"])
        self.accept()
