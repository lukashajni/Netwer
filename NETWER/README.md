# NETWER — Network Diagnostic Suite (PyQt6)

## Pokretanje
```
pip install -r requirements.txt
python main.py
```

## Struktura
- core/      — backend (netwer_core.py) — čista logika, bez UI ovisnosti
- app/       — tema (boje), postavke, aplikacijska jezgra
- workers/   — threading sloj (OneshotWorker, StreamWorker)
- ui/        — prozor, stranice, widgeti, komponente
- reports/   — PDF generacija (dolazi kasnije)
- assets/    — ikone, logo, fontovi

## Status
Temelji gotovi i testirani: tema, threading sloj, lifecycle stranica,
glavni prozor sa sidebar navigacijom i animiranim prijelazima.
Dashboard je zasad placeholder — puna verzija je sljedeći korak.
