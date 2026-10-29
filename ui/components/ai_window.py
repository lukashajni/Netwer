from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QVBoxLayout

from app.theme import Theme
from ui.widgets.ai_chat_panel import AIChatPanel


class AIWindow(QDialog):
    """Separate Netwer AI window, used by pages that should not jump to Network Health."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Netwer AI")
        self.setModal(False)
        self.setStyleSheet(f"QDialog {{ background: {Theme.BG_APP}; }}")
        self.resize(480, 700)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        self.panel = AIChatPanel(window_mode=True)
        self.panel.toggled.connect(lambda on: None if on else self.hide())
        lay.addWidget(self.panel)

    def ask(self, question: str):
        self.show()
        self.raise_()
        self.activateWindow()
        self.panel.ask(question)

    def closeEvent(self, event):
        # keep the conversation, only hide
        event.ignore()
        self.hide()
