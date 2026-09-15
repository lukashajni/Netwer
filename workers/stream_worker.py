"""NETWER — Streaming worker for generator functions."""

from workers.base_worker import BaseWorker


class StreamWorker(BaseWorker):
    """Executes generator tasks and emits results incrementally as they arrive."""

    def __init__(self, gen_func, *args, parent=None, **kwargs):
        super().__init__(parent)
        self._gen_func = gen_func
        self._args = args
        self._kwargs = kwargs

    def run(self) -> None:
        generator = None
        try:
            generator = self._gen_func(*self._args, **self._kwargs)

            for update in generator:
                if self._cancelled:
                    break

                if not isinstance(update, dict):
                    update = {"value": update}

                if "error" in update:
                    self.error.emit(str(update["error"]))
                    continue

                self.result.emit(update)

                if update.get("done"):
                    break

        except Exception as e:
            if not self._cancelled:
                self.error.emit(str(e))
        finally:
            # Clean up generator resources (sockets, processes) on exit
            if generator is not None and hasattr(generator, "close"):
                try:
                    generator.close()
                except Exception:
                    pass
            self.done.emit()