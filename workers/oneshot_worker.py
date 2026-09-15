"""NETWER — Single-execution worker for background tasks."""

from workers.base_worker import BaseWorker


class OneshotWorker(BaseWorker):
    """Executes a function once in a background thread and emits the result."""

    def __init__(self, func, *args, parent=None, **kwargs):
        super().__init__(parent)
        self._func = func
        self._args = args
        self._kwargs = kwargs

    def run(self) -> None:
        try:
            result = self._func(*self._args, **self._kwargs)

            if self._cancelled:
                return

            # Format raw response into a standard payload dictionary
            if isinstance(result, dict) and "error" in result:
                self.error.emit(str(result["error"]))
            elif isinstance(result, dict):
                self.result.emit(result)
            elif isinstance(result, list):
                self.result.emit({"items": result})
            else:
                self.result.emit({"value": result})

        except Exception as e:
            if not self._cancelled:
                self.error.emit(str(e))
        finally:
            if not self._cancelled:
                self.done.emit()