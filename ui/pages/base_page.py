"""
NETWER — BasePage.

Zajednička osnova SVIH 17 stranica. Svaka stranica (Dashboard, Ping,
Port Scanner...) nasljeđuje ovo i time automatski dobiva:

  1. Jedinstven lifecycle: on_enter() / on_leave()
     - on_enter() se zove kad korisnik OTVORI stranicu → tu pokrećeš
       učitavanje podataka, tajmere, live workere.
     - on_leave() se zove kad korisnik NAPUSTI stranicu → tu se AUTOMATSKI
       zaustave svi workeri i tajmeri. Ovo sprječava curenje niti i
       nepotrebno trošenje resursa (npr. da monitor nastavi vrtjeti u
       pozadini kad ga ne gledaš).

  2. Upravljanje workerima: register_worker()
     - Kad stranica pokrene worker, registrira ga ovdje. on_leave() ga
       onda zna zaustaviti bez da svaka stranica to ručno pamti.

  3. Naslov + podnaslov u jedinstvenom stilu (header).

Zašto je ovo ključno za skalabilnost: dodavanje 18. stranice ne dira
nijednu postojeću. Sve stranice se ponašaju isto jer dijele ovu osnovu.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel

from app.theme import Theme


class BasePage(QWidget):
    #: Podklase postave ovo — koristi se za naslov i navigaciju.
    PAGE_TITLE = "Page"
    PAGE_SUBTITLE = ""

    def __init__(self, core, parent=None, embedded=False):
        """
        core — modul netwer_core (backend). Stranica NIKAD ne zove backend
               izravno u glavnoj niti; koristi ga samo da workeru preda
               referencu na funkciju.
        embedded — kad je True, stranica ne crta vlastiti naslov/podnaslov
               (koristi se kad je ugniježđena u kontejner poput DNS Tools
               koji ima svoj zajednički header + tabove).
        """
        super().__init__(parent)
        self.core = core
        self._embedded = embedded
        self._workers = []  # aktivni workeri ove stranice
        self._window = None  # referenca na MainWindow (za loading koordinaciju)

        self.setStyleSheet(f"background: {Theme.BG_APP};")

        # Vanjski layout — podklase dodaju sadržaj u self.body_layout
        self._root = QVBoxLayout(self)
        margins = (0, 0, 0, 0) if embedded else (24, 20, 24, 20)
        self._root.setContentsMargins(*margins)
        self._root.setSpacing(16)

        if not embedded:
            self._build_header()

        # Ovamo podklase slažu svoj sadržaj.
        self.body_layout = QVBoxLayout()
        self.body_layout.setSpacing(Theme.GAP)
        self._root.addLayout(self.body_layout)

    # ── Header ─────────────────────────────────────────────────
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

    # ── Upravljanje workerima ──────────────────────────────────
    def set_window(self, window) -> None:
        """MainWindow se registrira ovdje da stranica moze javljati
        napredak ucitavanja (za fullscreen loading screen)."""
        self._window = window

    def register_worker(self, worker) -> None:
        """Registriraj worker da ga on_leave() može automatski zaustaviti.
        Također ga čisti iz liste kad prirodno završi."""
        self._workers.append(worker)
        worker.done.connect(lambda: self._unregister_worker(worker))

    def _unregister_worker(self, worker) -> None:
        if worker in self._workers:
            self._workers.remove(worker)

    def stop_workers(self) -> None:
        """Zaustavi i uredno ugasi sve aktivne workere ove stranice."""
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
                worker.wait(2000)  # čekaj do 2s da nit izađe čisto
        self._workers.clear()

    # ── Lifecycle (podklase nadjačavaju po potrebi) ────────────
    def preload(self) -> None:
        """Pokreni jednokratno učitavanje podataka U POZADINI pri pokretanju
        aplikacije, PRIJE nego korisnik uđe na stranicu. Tako podaci već
        stoje spremni kad se klikne na stranicu — ne vrti se učitavanje tek
        na prvi ulazak. Default: ništa (podklase koje imaju spori jednokratni
        load nadjačaju ovo). Mora biti sigurno pozvati dok stranica nije
        vidljiva i idempotentno (dvostruki poziv ne smije duplati posao).
        """
        pass

    def on_enter(self) -> None:
        """Zove se kad korisnik uđe na stranicu. Podklase pokreću
        učitavanje podataka ovdje. Default: ništa."""
        pass

    def on_leave(self) -> None:
        """Zove se kad korisnik napusti stranicu. Uvijek gasi workere.
        Podklase koje nadjačaju MORAJU pozvati super().on_leave()."""
        self.stop_workers()
