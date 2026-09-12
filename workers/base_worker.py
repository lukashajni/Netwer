"""
NETWER — Bazni worker (threading temelj).

PROBLEM koji ovo rješava:
Mrežne operacije (ping, skeniranje, speed test) traju. Ako ih pokreneš
izravno u glavnoj niti, cijela aplikacija se ZAMRZNE dok čekaju — prozor
se ne može pomaknuti, gumbi ne reagiraju. To izgleda kao da se aplikacija
srušila.

RJEŠENJE:
Svaka operacija se izvršava u zasebnoj pozadinskoj niti (QThread). Rezultati
se vraćaju u glavnu nit preko SIGNALA. Qt jamči da se slot spojen na signal
izvrši sigurno u glavnoj niti — pa smijemo dirati UI iz slota, ali NIKAD
izravno iz worker niti.

Dva su tipa workera (u odvojenim datotekama):
- OneshotWorker  → za funkcije koje vrate JEDAN dict (get_ethernet_info...)
- StreamWorker   → za generatore koji YIELD-aju dictove (ping_sweep_stream...)

Oba nasljeđuju BaseWorker koji donosi zajedničku logiku: signale i
kooperativni prekid (stop()).
"""

from PyQt6.QtCore import QThread, pyqtSignal


class BaseWorker(QThread):
    """Zajednička osnova za sve NETWER workere.

    Signali:
        result(dict)  — emitira se za svaki rezultat (jednom ili više puta)
        error(str)    — emitira se ako operacija vrati {"error": ...} ili baci
        done()        — emitira se točno jednom, na kraju, uvijek

    Prekid:
        stop()  — postavlja zastavicu; petlje u podklasama je provjeravaju
                  i izlaze čisto. NIKAD ne koristimo terminate() jer ostavlja
                  resurse u nedefiniranom stanju.
    """

    result = pyqtSignal(dict)
    error = pyqtSignal(str)
    done = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cancelled = False

    def stop(self) -> None:
        """Zatraži prekid. Sigurno za pozvati iz glavne niti u bilo kojem
        trenutku (npr. kad korisnik napusti stranicu ili klikne Cancel)."""
        self._cancelled = True

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    def run(self) -> None:
        """Podklase implementiraju ovo. Ovdje samo definiramo ugovor."""
        raise NotImplementedError(
            "Podklase BaseWorker-a moraju implementirati run()"
        )
