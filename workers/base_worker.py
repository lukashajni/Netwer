"""NETWER — Base worker infrastructure for async execution."""

from PyQt6.QtCore import QThread, pyqtSignal


class BaseWorker(QThread):
    """Base thread worker providing standard signals and cooperative cancellation."""

    result = pyqtSignal(dict)
    error = pyqtSignal(str)
    done = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cancelled = False

    def stop(self) -> None:
        """Flag thread for safe cancellation."""
        self._cancelled = True

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    def run(self) -> None:
        """Must be implemented by subclasses."""
        raise NotImplementedError(
            "Subclasses of BaseWorker must implement run()"
        )