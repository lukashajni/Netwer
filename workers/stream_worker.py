
import inspect
from threading import Event

from workers.base_worker import BaseWorker


class StreamWorker(BaseWorker):

    def __init__(self, gen_func, *args, parent=None, **kwargs):
        super().__init__(parent)
        self._gen_func = gen_func
        self._args = args
        self._kwargs = kwargs
        self._cancel_event = Event()

    def stop(self) -> None:
        super().stop()
        self._cancel_event.set()

    def run(self) -> None:
        generator = None
        try:
            kwargs = dict(self._kwargs)
            try:
                signature = inspect.signature(self._gen_func)
                if "cancel_event" in signature.parameters:
                    bound = signature.bind_partial(*self._args, **kwargs)
                    if "cancel_event" not in bound.arguments:
                        kwargs["cancel_event"] = self._cancel_event
            except (TypeError, ValueError):
                pass
            generator = self._gen_func(*self._args, **kwargs)

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
            if generator is not None and hasattr(generator, "close"):
                try:
                    generator.close()
                except Exception:
                    pass
            self.done.emit()
