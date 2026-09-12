"""
NETWER — OneshotWorker.

Za backend funkcije koje se pozovu jednom i vrate JEDAN rječnik:
    get_ethernet_info(), get_wifi_info(), get_system_info(),
    get_system_resources(), dns_lookup(domain), reverse_dns(ip),
    port_scan_custom(ip, port), get_top_devices(), get_network_map()

Tok:
    1. Pokrene funkciju s proslijeđenim argumentima (u pozadinskoj niti).
    2. Ako rezultat sadrži "error" → emitira error(str).
    3. Inače → emitira result(dict).
    4. Uvijek na kraju → emitira done().

Primjer korištenja iz stranice:
    self.worker = OneshotWorker(netwer_core.get_ethernet_info)
    self.worker.result.connect(self._on_data)
    self.worker.error.connect(self._on_error)
    self.worker.done.connect(self._on_done)
    self.worker.start()
"""

from workers.base_worker import BaseWorker


class OneshotWorker(BaseWorker):
    def __init__(self, func, *args, parent=None, **kwargs):
        """
        func    — backend funkcija koju treba pozvati
        *args   — pozicijski argumenti za func
        **kwargs — imenovani argumenti za func
        """
        super().__init__(parent)
        self._func = func
        self._args = args
        self._kwargs = kwargs

    def run(self) -> None:
        try:
            result = self._func(*self._args, **self._kwargs)

            if self._cancelled:
                return  # korisnik je otišao — ne emitiraj ništa

            if isinstance(result, dict) and "error" in result:
                self.error.emit(str(result["error"]))
            elif isinstance(result, dict):
                self.result.emit(result)
            elif isinstance(result, list):
                # Neke funkcije (npr. ping_quick, list_adapters) vraćaju listu.
                # Umotamo je u dict da signal ostane tipiziran (dict).
                self.result.emit({"items": result})
            else:
                self.result.emit({"value": result})

        except Exception as e:
            if not self._cancelled:
                self.error.emit(str(e))
        finally:
            if not self._cancelled:
                self.done.emit()
