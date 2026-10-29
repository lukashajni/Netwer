"""Shared base class for pages, including headers and worker lifecycle."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.theme import Theme


class BasePage(QWidget):
    # Subclasses set this - used for title and navigation.
    PAGE_TITLE = "Page"
    PAGE_SUBTITLE = ""
    AI_QUESTION = ""   # header "Ask Netwer AI" button asks this

    def __init__(self, core, parent=None, embedded=False):
        """Initialize a page, optionally without its own header."""
        super().__init__(parent)
        self.core = core
        self._embedded = embedded
        self._workers = []  # Active workers for this page 
        self._window = None  # MainWindow reference for loading coordination.

        self.setStyleSheet("background: transparent;")

        # Subclasses add page content to this layout.
        self._root = QVBoxLayout(self)
        margins = (0, 0, 0, 0) if embedded else (24, 20, 24, 20)
        self._root.setContentsMargins(*margins)
        self._root.setSpacing(16)

        if not embedded:
            self._build_header()

        # Subclasses arrange their content here.
        self.body_layout = QVBoxLayout()
        self.body_layout.setSpacing(Theme.GAP)
        self._root.addLayout(self.body_layout)

    # -- Header --
    def _build_header(self) -> None:
        row = QHBoxLayout()
        row.setSpacing(10)
        text = QVBoxLayout()
        text.setSpacing(2)
        title = QLabel(self.PAGE_TITLE)
        title.setStyleSheet(
            f"color: {Theme.TEXT_PRIMARY}; font-family: {Theme.FONT_FAMILY};"
            f"font-size: {Theme.FONT_SIZE_TITLE}px; font-weight: 600;"
            f"background: transparent;"
        )
        text.addWidget(title)

        if self.PAGE_SUBTITLE:
            sub = QLabel(self.PAGE_SUBTITLE)
            sub.setStyleSheet(
                f"color: {Theme.TEXT_MUTED}; font-family: {Theme.FONT_FAMILY};"
                f"font-size: {Theme.FONT_SIZE_SMALL}px;"
                f"background: transparent;"
            )
            text.addWidget(sub)
        row.addLayout(text, 1)

        # pages put their own buttons here, next to the AI button
        self.header_actions = QHBoxLayout()
        self.header_actions.setSpacing(8)
        row.addLayout(self.header_actions)
        if self.AI_QUESTION:
            from ui.widgets.ui_kit import button
            self.btn_page_ai = button("Ask Netwer AI", "ai", "ai")
            self.btn_page_ai.clicked.connect(lambda: self.ask_ai(self.AI_QUESTION))
            row.addWidget(self.btn_page_ai, 0, Qt.AlignmentFlag.AlignVCenter)
        self._root.addLayout(row)

    # -- Netwer AI --
    def ai_context(self) -> dict:
        """What the assistant may read about this page's latest results."""
        return {}

    def ask_ai(self, question: str) -> None:
        win = self._window or self.window()
        if hasattr(win, "ask_ai"):
            win.ask_ai(question)

    # -- Worker management --
    def set_window(self, window) -> None:
        """Set the window used to report loading progress."""
        self._window = window

    def register_worker(self, worker) -> None:
        """Track a worker until it finishes or the page is left."""
        self._workers.append(worker)
        worker.done.connect(lambda: self._unregister_worker(worker))

    def _unregister_worker(self, worker) -> None:
        if worker in self._workers:
            self._workers.remove(worker)

    def stop_workers(self) -> None:
        """Stop and shut down this page's active workers."""
        for worker in list(self._workers):
            # Prevent queued payloads from reaching widgets during teardown.
            # Keep `done` connected so pages can reset their worker state.
            for sig in ("result", "error"):
                s = getattr(worker, sig, None)
                if s is not None:
                    try:
                        s.disconnect()
                    except Exception:
                        pass
            worker.stop()
            if worker.isRunning():
                worker.wait(2000)  # Wait for 2 seconds so that the thread can exit cleanly
        self._workers.clear()

    # -- Lifecycle (Subclasses override as needed.) --
    def preload(self) -> None:
        """Start any one-time background loading required by the page."""
        pass

    def on_enter(self) -> None:
        """Load or refresh page data when the page is opened."""
        pass

    def on_leave(self) -> None:
        """Stop page workers when leaving; overrides should call this method."""
        self.stop_workers()
