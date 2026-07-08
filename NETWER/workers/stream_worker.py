"""
NETWER — StreamWorker.

Za backend GENERATORE koji yield-aju rječnike jedan po jedan:
    ping_sweep_stream(), monitor_stream(adapter), speedtest_stream(),
    traceroute_stream(target), ping_stability_stream(target, count),
    ping_custom_stream(...), port_scan_quick_stream(ip)

Razlika od OneshotWorker-a: ovdje result signal se emitira VIŠE PUTA —
jednom za svaki yield iz generatora. Tako stranica dobiva podatke uživo
kako pristižu (npr. svaki pronađeni uređaj u ping sweepu odmah se pojavi
u tablici, ne čeka se kraj skeniranja).

Prekid je ovdje posebno važan: ping_sweep skenira 254 adrese i traje.
Provjeravamo is_cancelled u petlji da korisnik može prekinuti bez čekanja.

Primjer korištenja iz stranice:
    self.worker = StreamWorker(netwer_core.ping_sweep_stream)
    self.worker.result.connect(self._on_host)     # zove se za svaki host
    self.worker.done.connect(self._on_finished)   # zove se na kraju
    self.worker.start()
    ...
    # kad korisnik napusti stranicu:
    self.worker.stop()
"""

from workers.base_worker import BaseWorker


class StreamWorker(BaseWorker):
    def __init__(self, gen_func, *args, parent=None, **kwargs):
        """
        gen_func — backend generator-funkcija (poziv vraća generator)
        *args    — pozicijski argumenti
        **kwargs — imenovani argumenti
        """
        super().__init__(parent)
        self._gen_func = gen_func
        self._args = args
        self._kwargs = kwargs

    def run(self) -> None:
        generator = None
        try:
            generator = self._gen_func(*self._args, **self._kwargs)

            for update in generator:
                # Prekid PRIJE obrade sljedećeg rezultata — brz izlaz.
                if self._cancelled:
                    break

                if not isinstance(update, dict):
                    update = {"value": update}

                # Backend signalizira grešku kroz {"error": ...}
                if "error" in update:
                    self.error.emit(str(update["error"]))
                    continue

                self.result.emit(update)

                # Backend signalizira kraj kroz {"done": True}.
                # Prosljeđujemo taj dict (sadrži i sažetak), pa prekidamo.
                if update.get("done"):
                    break

        except Exception as e:
            if not self._cancelled:
                self.error.emit(str(e))
        finally:
            # Zatvori generator uredno — oslobađa resurse (socket, subprocess)
            # ako smo prekinuli usred streama.
            if generator is not None and hasattr(generator, "close"):
                try:
                    generator.close()
                except Exception:
                    pass
            self.done.emit()
