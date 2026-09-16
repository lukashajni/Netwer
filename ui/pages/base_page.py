"""
NETWER — BasePage.

Common basis of all 17 pages. Each page (Dashboard, Ping,
Port Scanner...) inherits this and the time automatically gets:

  1. Unique life cycle: on_enter() / on_leave()
     - on_enter() is called when the user opens the page - you start it there
       loading data, timers, live workers.
     - on_leave() is called when the user leaves the page - there automatically
       all workers and timers stop. This separate thread leakage and
       unnecessary consumption of resources (e.g. for the monitor to continue rotating in
       background when you are not looking at it).

  2. Management of workers: register_worker()
     - When the site starts a worker, it registers it here. on_leave() him
       then it can stop without manually remembering each page.

  3. Title + subtitle in a unique style (header).

"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel

from app.theme import Theme


class BasePage(QWidget):
    # Subclasses set this - used for title and navigation.
    PAGE_TITLE = "Page"
    PAGE_SUBTITLE = ""

    def __init__(self, core, parent=None, embedded=False):
        """
        core — module netwer_core (backend). The page never calls the backend
               directly in the main thread, it only uses it to hand over to the worker
               a function reference.
        embedded — when True, the page does not draw its own title/subtitle
               (used when nested in a container like DNS Tools
               which has its own common header + tabs).
        """
        super().__init__(parent)
        self.core = core
        self._embedded = embedded
        self._workers = []  # Active workers for this page 
        self._window = None  # reference to MainWindow (for loading cordination)

        self.setStyleSheet(f"background: {Theme.BG_APP};")

        # Outer layout — sublcasses add content to self.body_layout
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
        title = QLabel(self.PAGE_TITLE)
        title.setStyleSheet(
            f"color: {Theme.TEXT_PRIMARY}; font-family: {Theme.FONT_FAMILY};"
            f"font-size: {Theme.FONT_SIZE_TITLE}px; font-weight: 600;"
            f"background: transparent;"
        )
        self._root.addWidget(title)

        if self.PAGE_SUBTITLE:
            sub = QLabel(self.PAGE_SUBTITLE)
            sub.setStyleSheet(
                f"color: {Theme.TEXT_MUTED}; font-family: {Theme.FONT_FAMILY};"
                f"font-size: {Theme.FONT_SIZE_SMALL}px;"
                f"background: transparent;"
            )
            self._root.addWidget(sub)

    # -- Upravljanje workerima --
    def set_window(self, window) -> None:
        """The MainWindow initializes itself here so that the page can report
        loading progress (for the fullscreen loading screen)."""
        self._window = window

    def register_worker(self, worker) -> None:
        """Register the worker so that on_leave() can automatically stop it.
        It also removes it from the list when it finishes normally."""
        self._workers.append(worker)
        worker.done.connect(lambda: self._unregister_worker(worker))

    def _unregister_worker(self, worker) -> None:
        if worker in self._workers:
            self._workers.remove(worker)

    def stop_workers(self) -> None:
        """Stop and neatly shut down all active workers for this site."""
        for worker in list(self._workers):
            # Disconnect signals FIRST so a result/error queued just before
            # stop() can't fire back into a widget we're about to delete
            # (that race segfaults on theme rebuild).
            for sig in ("result", "error", "done"):
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
        """Trigger a one-time data load in the background upon application startup, 
           before the user navigates to the page. This ensures the data is already 
           ready when the page is clicked, avoiding a loading spinner upon the 
           initial visit. Default: none (subclasses with a slow one-time load 
           override this). The method must be safe to call while the page is not 
           visible and must be idempotent (a second call must not duplicate the work).
        """
        pass

    def on_enter(self) -> None:
        """Called when the user opens the page. Subclasses initiate
        data loading here."""
        pass

    def on_leave(self) -> None:
        """Called when the user leaves the page. Always shuts down workers.
        Subclasses that override this must call super().on_leave()."""
        self.stop_workers()
