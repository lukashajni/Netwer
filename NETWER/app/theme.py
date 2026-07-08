"""
NETWER — Centralna tema (dizajnerski tokeni).

SVE boje aplikacije žive ovdje. Nijedna druga datoteka ne smije sadržavati
hardkodirane hex vrijednosti — uvijek se referira na Theme.

Zašto ovako: kad želiš promijeniti akcentnu boju (npr. korisnik u Settings
odabere "Dark Blue" vs "Purple"), mijenjaš je na JEDNOM mjestu, a cijela
aplikacija se prilagodi. Ovo je razlika između održivog koda i lova na
boje po 17 datoteka.

Boje su preuzete izravno iz odobrenog dashboard mockupa.
"""


class Theme:
    # ── Pozadine (od najtamnije prema svjetlijoj) ──────────────
    BG_APP = "#0a0e1a"        # najtamnija — pozadina cijelog prozora
    BG_SIDEBAR = "#0c1120"    # sidebar navigacija
    BG_CARD = "#111830"       # kartice / paneli
    BG_CARD_HOVER = "#161f3d"  # kartica kad je miš iznad nje
    BG_ELEVATED = "#1a2440"   # aktivni element navigacije, istaknuto

    # ── Obrubi ─────────────────────────────────────────────────
    # Suptilniji od pozadine kartice — sprječava tvrdi "selektirani" rub.
    BORDER = "#1e2842"         # standardni tanki obrub
    BORDER_STRONG = "#2a3555"  # naglašeni obrub (hover)

    # ── Tekst (od najsvjetlijeg prema prigušenom) ──────────────
    TEXT_PRIMARY = "#e8ecf5"    # naslovi, glavne vrijednosti
    TEXT_BODY = "#dfe6f5"       # standardni tekst u karticama
    TEXT_SECONDARY = "#8a95b0"  # oznake, sekundarni tekst
    TEXT_MUTED = "#657095"      # natpisi, jedinice, prigušeno
    TEXT_FAINT = "#556080"      # najprigušenije (verzija, footer)

    # ── Akcentne boje (semantičke) ─────────────────────────────
    ACCENT = "#4d9bff"          # primarni plavi akcent (download, linkovi)
    ACCENT_PURPLE = "#b07cff"   # ljubičasti (upload, brand)
    ACCENT_GLOW = "#8a7cff"     # logo, istaknuti brand

    # ── Statusne boje ──────────────────────────────────────────
    SUCCESS = "#3ec98a"   # zeleno — connected, online, excellent
    WARNING = "#f0a830"   # žuto — upozorenje, uptime
    DANGER = "#e2504a"    # crveno — greška, offline, timeout
    INFO = "#4d9bff"      # info (isto kao accent)

    # ── Grafovi (PyQtGraph) ────────────────────────────────────
    CHART_DOWNLOAD = "#4d9bff"
    CHART_UPLOAD = "#b07cff"
    CHART_GRID = "#1c2740"
    CHART_FILL_DL = (77, 155, 255, 45)    # RGBA — poluprozirno punjenje
    CHART_FILL_UL = (176, 124, 255, 35)

    # ── Tipografija ────────────────────────────────────────────
    FONT_FAMILY = "Segoe UI Variable Display"  # Windows 11 sistemski font
    FONT_MONO = "Cascadia Code"       # moderni monospace (Win11); fallback Consolas
    FONT_SIZE_TITLE = 22
    FONT_SIZE_HEADING = 15
    FONT_SIZE_BODY = 13
    FONT_SIZE_SMALL = 12
    FONT_SIZE_TINY = 11

    # ── Geometrija ─────────────────────────────────────────────
    RADIUS_CARD = 12
    RADIUS_CONTROL = 8
    PAD = 14
    GAP = 12

    # ── Trajanja animacija (ms) ────────────────────────────────
    ANIM_FAST = 150
    ANIM_NORMAL = 200
    ANIM_SLOW = 250


# ── Akcentne palete koje korisnik može birati u Settings ───────
# Svaka mijenja samo ACCENT/ACCENT_PURPLE — ostatak teme ostaje isti.
ACCENT_PRESETS = {
    "Dark Blue": {"accent": "#4d9bff", "purple": "#b07cff"},
    "Purple":    {"accent": "#8a7cff", "purple": "#b07cff"},
    "Teal":      {"accent": "#1baf7a", "purple": "#3ec98a"},
    "Amber":     {"accent": "#f0a830", "purple": "#ff9d5c"},
}


def apply_accent(preset_name: str) -> None:
    """Promijeni akcentne boje na runtime. Pozovi iz Settings stranice.
    Stranice koje se nakon toga ponovno iscrtaju pokupit će nove boje."""
    preset = ACCENT_PRESETS.get(preset_name)
    if not preset:
        return
    Theme.ACCENT = preset["accent"]
    Theme.ACCENT_PURPLE = preset["purple"]
    Theme.CHART_DOWNLOAD = preset["accent"]
    Theme.CHART_UPLOAD = preset["purple"]
