"""NETWER core paket.

Pri importu prosirujemo ugradjenu OUI tablicu dodatnim proizvodjacima
(core/oui_extended.py) tako da uredjaji na mrezi prepoznaju pravog
proizvodjaca umjesto "Unknown". Ne diramo netwer_core.py — samo mu
napunimo tablicu.
"""
from core import netwer_core
from core.oui_extended import EXTENDED_OUI

# Prosiri postojecu tablicu (postojeci unosi imaju prednost se ne gaze
# ako vec postoje; novi se dodaju).
for prefix, vendor in EXTENDED_OUI.items():
    netwer_core.OUI_TABLE.setdefault(prefix, vendor)

# "Zagrij" psutil CPU mjerenje. Prvi poziv cpu_percent() uvijek vrati 0.0
# jer nema prethodne referentne tocke — pozovemo ga jednom pri startu tako
# da sva kasnija mjerenja (gaugevi) odmah budu tocna.
try:
    import psutil
    psutil.cpu_percent(interval=None)  # uspostavi referentnu tocku
except Exception:
    pass
