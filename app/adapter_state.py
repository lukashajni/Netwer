from PyQt6.QtCore import QObject, pyqtSignal

from app.store import store
from core import network


class AdapterState(QObject):
    # One adapter for the whole app; "" means automatic
    changed = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        network.set_selected_adapter(store.get_setting("selected_adapter", ""))

    def get(self) -> str:
        return network.get_selected_adapter()

    def set(self, name: str) -> None:
        name = name or ""
        if name == self.get():
            return
        store.set_setting("selected_adapter", name)
        network.set_selected_adapter(name)
        self.changed.emit(name)


adapter_state = AdapterState()
