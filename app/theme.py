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
    BG_APP = "#070a14"        # najtamnija — pozadina cijelog prozora
    BG_SIDEBAR = "#0b0f1c"    # sidebar navigacija
    BG_TOPBAR = "#0b0f1c"     # gornja traka (top bar)
    BG_CARD = "#141a2e"       # kartice / paneli (glass baza)
    BG_CARD_HOVER = "#1a2138"  # kartica kad je miš iznad nje
    BG_ELEVATED = "#1e2740"   # aktivni element navigacije, istaknuto

    # ── Obrubi ─────────────────────────────────────────────────
    # Suptilniji od pozadine kartice — sprječava tvrdi "selektirani" rub.
    BORDER = "#212a44"         # standardni tanki obrub
    BORDER_STRONG = "#2e3a5c"  # naglašeni obrub (hover)

    # ── Tekst (od najsvjetlijeg prema prigušenom) ──────────────
    TEXT_PRIMARY = "#eaf0ff"    # naslovi, glavne vrijednosti
    TEXT_BODY = "#dbe3f7"       # standardni tekst u karticama
    TEXT_SECONDARY = "#9aa6c8"  # oznake, sekundarni tekst
    TEXT_MUTED = "#67718f"      # natpisi, jedinice, prigušeno
    TEXT_FAINT = "#525c78"      # najprigušenije (verzija, footer)

    # ── Akcentne boje (semantičke) ─────────────────────────────
    ACCENT = "#5b8cff"          # primarni plavi akcent (download, linkovi)
    ACCENT_PURPLE = "#8b6dff"   # ljubičasti (upload, brand)
    ACCENT_GLOW = "#8b6dff"     # logo, istaknuti brand

    # ── Statusne boje ──────────────────────────────────────────
    SUCCESS = "#33d6a6"   # zeleno — connected, online, excellent
    WARNING = "#f5b545"   # žuto — upozorenje, uptime
    DANGER = "#ff6b8a"    # crveno/rose — greška, offline, timeout
    DANGER_HOVER = "#e85578"  # tamnija varijanta za hover na crvenom gumbu
    INFO = "#5b8cff"      # info (isto kao accent)

    # ── Grafovi (PyQtGraph) ────────────────────────────────────
    CHART_DOWNLOAD = "#5b8cff"
    CHART_UPLOAD = "#8b6dff"
    CHART_GRID = "#1a2338"
    CHART_FILL_DL = (91, 140, 255, 55)    # RGBA — poluprozirno punjenje
    CHART_FILL_UL = (139, 109, 255, 40)

    # ── Tipografija ────────────────────────────────────────────
    # Font STACKOVI s fallbackovima. Windows 11 ima "Segoe UI Variable",
    # Windows 10 "Segoe UI", a drugi OS-ovi padnu na sans-serif — tako
    # tekst ostaje čitak svugdje, ne samo na Win11. Qt stylesheet i QFont
    # oba razumiju zarezom odvojenu listu obitelji.
    FONT_FAMILY = ('"Inter", "Segoe UI Variable Display", "Segoe UI", '
                   '"Helvetica Neue", Arial, sans-serif')
    FONT_MONO = ('"JetBrains Mono", "Cascadia Code", "Cascadia Mono", '
                 'Consolas, "DejaVu Sans Mono", monospace')
    # Za vrijednosti podataka: čišći, deblji sans.
    FONT_DATA = ('"Inter", "Segoe UI Semibold", "Segoe UI", Arial, sans-serif')

    #: Prva stvarna obitelj iz svakog stacka — za QFont(...) pozive koji
    #: žele jedno ime (Qt svejedno primijeni substituciju, ali ovo je čišće).
    FONT_FAMILY_PRIMARY = "Inter"
    FONT_MONO_PRIMARY = "JetBrains Mono"

    FONT_SIZE_TITLE = 24
    FONT_SIZE_HEADING = 15
    FONT_SIZE_BODY = 13
    FONT_SIZE_SMALL = 12
    FONT_SIZE_TINY = 11

    # ── Geometrija ─────────────────────────────────────────────
    RADIUS_CARD = 16          # zaobljeniji "glass" izgled
    RADIUS_CONTROL = 11
    PAD = 16
    GAP = 14

    # ── UI density / rezolucija ────────────────────────────────
    #: Trenutni profil gustoće sučelja ("compact" / "standard" / "large"),
    #: biran u Settings prema rezoluciji ekrana. Mijenja veličinu sidebara,
    #: topbara, razmaka i fontova — vidi apply_ui_scale().
    UI_SCALE = "standard"
    SIDEBAR_WIDTH = 230
    TOPBAR_HEIGHT = 60

    # ── Glass / gradijent tokeni ───────────────────────────────
    # Qt kompozitira poluprozirne (rgba) stylesheet pozadine preko VLASTITE
    # neprozirne podloge widgeta (tamna), pa prave rgba kartice ispadnu kao
    # tamni okviri s "podcrtanim" tekstom. Zato koristimo SOLID boje koje samo
    # izgledaju glassy (malo svjetlije od pozadine) — čisto se crta, bez
    # artefakata. Korisnik u Settings može uključiti/isključiti glass izgled;
    # kad je isključen, kartice su ravne (BG_CARD), kad je uključen, malo
    # svjetlije s naglašenim rubom.
    GLASS_CARD = "#161d33"          # glassy površina (solid, svjetlija)
    GLASS_CARD_HOVER = "#1b2440"    # glassy na hover
    GLASS_INPUT = "#0e1424"         # unos / pill u glassu
    GLASS_BORDER = "#293355"        # glass rub (vidljiviji od običnog)
    GLASS_BORDER_HI = "#3a4a72"     # naglašeni glass rub
    #: Gradijent za aktivnu nav stavku i primarne gumbe (Qt linearni grad).
    GRAD_ACCENT = ("qlineargradient(x1:0, y1:0, x2:1, y2:1, "
                   "stop:0 #5b8cff, stop:1 #8b6dff)")
    GRAD_ACCENT_SOFT = ("qlineargradient(x1:0, y1:0, x2:1, y2:1, "
                        "stop:0 #26325a, stop:1 #2b2f5a)")
    #: Je li glass izgled uključen (Settings toggle). Kad je False, kartice
    #: koriste ravni BG_CARD i obični BORDER.
    GLASS_ENABLED = True

    # ── Trajanja animacija (ms) ────────────────────────────────
    ANIM_FAST = 150
    ANIM_NORMAL = 200
    ANIM_SLOW = 250


# ── Teme (cijele palete) koje korisnik bira u Settings ─────────
# Svaka tema definira KOMPLETAN set boja. apply_theme() ih upiše u Theme.*
# na runtime, pa se cijela aplikacija prilagodi kad se ponovno iscrta.
#
# "mode" govori je li tema tamna ili svijetla (koristi se za neke odluke,
# npr. boju checkmarka). Svaka tema ima i svoj akcent, ali korisnik ga može
# dodatno promijeniti preko ACCENT_PRESETS.

THEMES = {
    "Dark Blue": {
        "mode": "dark",
        "BG_APP": "#070a14", "BG_SIDEBAR": "#0b0f1c", "BG_TOPBAR": "#0b0f1c",
        "BG_CARD": "#141a2e", "BG_CARD_HOVER": "#1a2138", "BG_ELEVATED": "#1e2740",
        "BORDER": "#212a44", "BORDER_STRONG": "#2e3a5c",
        "TEXT_PRIMARY": "#eaf0ff", "TEXT_BODY": "#dbe3f7", "TEXT_SECONDARY": "#9aa6c8",
        "TEXT_MUTED": "#67718f", "TEXT_FAINT": "#525c78",
        "ACCENT": "#5b8cff", "ACCENT_PURPLE": "#8b6dff", "ACCENT_GLOW": "#8b6dff",
        "SUCCESS": "#33d6a6", "WARNING": "#f5b545", "DANGER": "#ff6b8a",
        "DANGER_HOVER": "#e85578",
        "CHART_GRID": "#1a2338",
        "GLASS_CARD": "#161d33", "GLASS_CARD_HOVER": "#1b2440",
        "GLASS_INPUT": "#0e1424", "GLASS_BORDER": "#293355",
        "GLASS_BORDER_HI": "#3a4a72",
        "GRAD_ACCENT": ("qlineargradient(x1:0, y1:0, x2:1, y2:1, "
                        "stop:0 #5b8cff, stop:1 #8b6dff)"),
        "GRAD_ACCENT_SOFT": ("qlineargradient(x1:0, y1:0, x2:1, y2:1, "
                             "stop:0 #26325a, stop:1 #2b2f5a)"),
    },
    "Midnight Purple": {
        "mode": "dark",
        "BG_APP": "#0a0716", "BG_SIDEBAR": "#0f0a1e", "BG_TOPBAR": "#0f0a1e",
        "BG_CARD": "#181230", "BG_CARD_HOVER": "#201840", "BG_ELEVATED": "#241a48",
        "BORDER": "#241a42", "BORDER_STRONG": "#382a5a",
        "TEXT_PRIMARY": "#efeaf7", "TEXT_BODY": "#e2daf2", "TEXT_SECONDARY": "#9a8fc0",
        "TEXT_MUTED": "#7566a0", "TEXT_FAINT": "#5f5080",
        "ACCENT": "#8b6dff", "ACCENT_PURPLE": "#b07cff", "ACCENT_GLOW": "#a78aff",
        "SUCCESS": "#33d6a6", "WARNING": "#f5b545", "DANGER": "#ff6b8a",
        "DANGER_HOVER": "#e85578",
        "CHART_GRID": "#241a42",
        "GLASS_CARD": "#1f1840", "GLASS_CARD_HOVER": "#261e4e",
        "GLASS_INPUT": "#130e28", "GLASS_BORDER": "#352a5e",
        "GLASS_BORDER_HI": "#4a3c7a",
        "GRAD_ACCENT": ("qlineargradient(x1:0, y1:0, x2:1, y2:1, "
                        "stop:0 #8b6dff, stop:1 #b07cff)"),
        "GRAD_ACCENT_SOFT": ("qlineargradient(x1:0, y1:0, x2:1, y2:1, "
                             "stop:0 #322858, stop:1 #382a5e)"),
    },
    "Slate": {
        "mode": "dark",
        "BG_APP": "#0c0f13", "BG_SIDEBAR": "#101419", "BG_TOPBAR": "#101419",
        "BG_CARD": "#181d24", "BG_CARD_HOVER": "#1f2630", "BG_ELEVATED": "#222a35",
        "BORDER": "#222831", "BORDER_STRONG": "#333c48",
        "TEXT_PRIMARY": "#eef1f4", "TEXT_BODY": "#dde2e8", "TEXT_SECONDARY": "#8c96a3",
        "TEXT_MUTED": "#697280", "TEXT_FAINT": "#565f6b",
        "ACCENT": "#33d6a6", "ACCENT_PURPLE": "#5b8cff", "ACCENT_GLOW": "#4fd0b0",
        "SUCCESS": "#33d6a6", "WARNING": "#f5b545", "DANGER": "#ff6b8a",
        "DANGER_HOVER": "#e85578",
        "CHART_GRID": "#222831",
        "GLASS_CARD": "#1d232d", "GLASS_CARD_HOVER": "#232a35",
        "GLASS_INPUT": "#12161c", "GLASS_BORDER": "#2c3540",
        "GLASS_BORDER_HI": "#3c4756",
        "GRAD_ACCENT": ("qlineargradient(x1:0, y1:0, x2:1, y2:1, "
                        "stop:0 #33d6a6, stop:1 #5b8cff)"),
        "GRAD_ACCENT_SOFT": ("qlineargradient(x1:0, y1:0, x2:1, y2:1, "
                             "stop:0 #24333a, stop:1 #263442)"),
    },
    "Light": {
        "mode": "light",
        "BG_APP": "#eef1f7", "BG_SIDEBAR": "#ffffff", "BG_TOPBAR": "#ffffff",
        "BG_CARD": "#ffffff", "BG_CARD_HOVER": "#f4f7fc", "BG_ELEVATED": "#e8edf6",
        "BORDER": "#dce1ec", "BORDER_STRONG": "#c2cad9",
        "TEXT_PRIMARY": "#1a2035", "TEXT_BODY": "#2b3450", "TEXT_SECONDARY": "#5c6788",
        "TEXT_MUTED": "#8791a8", "TEXT_FAINT": "#a3abbf",
        "ACCENT": "#2f7fe0", "ACCENT_PURPLE": "#8a5cf0", "ACCENT_GLOW": "#6f5ce0",
        "SUCCESS": "#1e9e6a", "WARNING": "#d98a1a", "DANGER": "#d64339",
        "DANGER_HOVER": "#bd3a31",
        "CHART_GRID": "#dce1ec",
        "GLASS_CARD": "#ffffff", "GLASS_CARD_HOVER": "#f4f7fc",
        "GLASS_INPUT": "#f0f4fa", "GLASS_BORDER": "#d8dfea",
        "GLASS_BORDER_HI": "#b9c6dc",
        "GRAD_ACCENT": ("qlineargradient(x1:0, y1:0, x2:1, y2:1, "
                        "stop:0 #2f7fe0, stop:1 #8a5cf0)"),
        "GRAD_ACCENT_SOFT": ("qlineargradient(x1:0, y1:0, x2:1, y2:1, "
                             "stop:0 #dbe7fb, stop:1 #e6def8)"),
    },
    "Light Warm": {
        "mode": "light",
        "BG_APP": "#f5f1ea", "BG_SIDEBAR": "#fffdf9", "BG_TOPBAR": "#fffdf9",
        "BG_CARD": "#fffdf9", "BG_CARD_HOVER": "#f7f2e9", "BG_ELEVATED": "#efe8db",
        "BORDER": "#e5ddce", "BORDER_STRONG": "#d0c6b2",
        "TEXT_PRIMARY": "#2a2418", "TEXT_BODY": "#3d3628", "TEXT_SECONDARY": "#6d6350",
        "TEXT_MUTED": "#948872", "TEXT_FAINT": "#b0a68f",
        "ACCENT": "#c77d2a", "ACCENT_PURPLE": "#b0672a", "ACCENT_GLOW": "#d68f3f",
        "SUCCESS": "#4a9c3e", "WARNING": "#d98a1a", "DANGER": "#cc4436",
        "DANGER_HOVER": "#b33b2f",
        "CHART_GRID": "#e5ddce",
        "GLASS_CARD": "#fffdf9", "GLASS_CARD_HOVER": "#f7f2e9",
        "GLASS_INPUT": "#f7f2e9", "GLASS_BORDER": "#e5ddce",
        "GLASS_BORDER_HI": "#d0c6b2",
        "GRAD_ACCENT": ("qlineargradient(x1:0, y1:0, x2:1, y2:1, "
                        "stop:0 #c77d2a, stop:1 #d68f3f)"),
        "GRAD_ACCENT_SOFT": ("qlineargradient(x1:0, y1:0, x2:1, y2:1, "
                             "stop:0 #f3e6d3, stop:1 #f5ede0)"),
    },
}

# Akcent override — mijenja SAMO akcentne boje povrh odabrane teme.
ACCENT_PRESETS = {
    "Default":   None,   # koristi akcent iz same teme
    "Blue":      {"accent": "#4d9bff", "purple": "#b07cff"},
    "Purple":    {"accent": "#8a7cff", "purple": "#b07cff"},
    "Teal":      {"accent": "#1baf7a", "purple": "#3ec98a"},
    "Amber":     {"accent": "#f0a830", "purple": "#ff9d5c"},
    "Rose":      {"accent": "#f0567c", "purple": "#ff7ca0"},
}

_current_theme = "Dark Blue"
_current_accent = "Default"


def current_theme_name():
    return _current_theme


def current_accent_name():
    return _current_accent


def is_dark():
    return THEMES.get(_current_theme, {}).get("mode", "dark") == "dark"


# ══════════════════════════════════════════
# UI DENSITY / RESOLUTION PROFILES
# ══════════════════════════════════════════
#: Sidebar width, top bar height, spacing, corner radii and font sizes for
#: each density. "standard" matches the original hand-tuned defaults, so
#: switching back to it is always exact, never a drift from repeated scaling.
UI_SCALE_PROFILES = {
    "compact": {
        "SIDEBAR_WIDTH": 200, "TOPBAR_HEIGHT": 54,
        "GAP": 11, "PAD": 13, "RADIUS_CARD": 13, "RADIUS_CONTROL": 9,
        "FONT_SIZE_TITLE": 21, "FONT_SIZE_HEADING": 14,
        "FONT_SIZE_BODY": 12, "FONT_SIZE_SMALL": 11, "FONT_SIZE_TINY": 10,
    },
    "standard": {
        "SIDEBAR_WIDTH": 230, "TOPBAR_HEIGHT": 60,
        "GAP": 14, "PAD": 16, "RADIUS_CARD": 16, "RADIUS_CONTROL": 11,
        "FONT_SIZE_TITLE": 24, "FONT_SIZE_HEADING": 15,
        "FONT_SIZE_BODY": 13, "FONT_SIZE_SMALL": 12, "FONT_SIZE_TINY": 11,
    },
    "large": {
        "SIDEBAR_WIDTH": 254, "TOPBAR_HEIGHT": 66,
        "GAP": 16, "PAD": 18, "RADIUS_CARD": 18, "RADIUS_CONTROL": 12,
        "FONT_SIZE_TITLE": 27, "FONT_SIZE_HEADING": 17,
        "FONT_SIZE_BODY": 14, "FONT_SIZE_SMALL": 13, "FONT_SIZE_TINY": 12,
    },
}


def apply_ui_scale(profile: str) -> None:
    """Switch the sidebar/topbar size, spacing and font sizes to a density
    profile. Like apply_theme(), this only mutates Theme.* — the caller (main
    window) still has to rebuild the UI (_reskin_all) for widgets built
    earlier to pick the new values up."""
    values = UI_SCALE_PROFILES.get(profile, UI_SCALE_PROFILES["standard"])
    Theme.UI_SCALE = profile if profile in UI_SCALE_PROFILES else "standard"
    for key, value in values.items():
        setattr(Theme, key, value)


def card_bg():
    """Trenutna boja pozadine kartice — glass kad je efekt uključen, inače
    ravni BG_CARD. Koristi se u paintEvent karticama, sidebaru i topbaru."""
    return Theme.GLASS_CARD if getattr(Theme, "GLASS_ENABLED", True) else Theme.BG_CARD


def card_border():
    return Theme.GLASS_BORDER if getattr(Theme, "GLASS_ENABLED", True) else Theme.BORDER


def input_bg():
    return Theme.GLASS_INPUT if getattr(Theme, "GLASS_ENABLED", True) else Theme.BG_ELEVATED


def apply_theme(theme_name: str, accent_name: str = None) -> None:
    """Upiši cijelu paletu u Theme.* na runtime. Nakon poziva treba
    ponovno primijeniti globalni stylesheet (main_window to radi)."""
    global _current_theme, _current_accent
    palette = THEMES.get(theme_name)
    if not palette:
        return
    _current_theme = theme_name
    for key, value in palette.items():
        if key == "mode":
            continue
        setattr(Theme, key, value)
    # INFO prati ACCENT
    Theme.INFO = Theme.ACCENT
    # RGBA punjenja grafa iz nove akcentne boje
    Theme.CHART_DOWNLOAD = Theme.ACCENT
    Theme.CHART_UPLOAD = Theme.ACCENT_PURPLE
    Theme.CHART_FILL_DL = _hex_to_rgba(Theme.ACCENT, 45)
    Theme.CHART_FILL_UL = _hex_to_rgba(Theme.ACCENT_PURPLE, 35)
    if accent_name is not None:
        apply_accent(accent_name)


def apply_accent(preset_name: str) -> None:
    """Override akcentnih boja povrh trenutne teme. 'Default' vraća akcent
    na onaj definiran u samoj temi (bez ovoga se izbor akcenta ne može
    poništiti — graf ostane zaglavljen na zadnjoj boji)."""
    global _current_accent
    _current_accent = preset_name
    preset = ACCENT_PRESETS.get(preset_name)
    if preset is None:
        # "Default" — vrati akcent iz same teme.
        palette = THEMES.get(_current_theme, {})
        Theme.ACCENT = palette.get("ACCENT", Theme.ACCENT)
        Theme.ACCENT_PURPLE = palette.get("ACCENT_PURPLE", Theme.ACCENT_PURPLE)
    else:
        Theme.ACCENT = preset["accent"]
        Theme.ACCENT_PURPLE = preset["purple"]
    Theme.INFO = Theme.ACCENT
    Theme.CHART_DOWNLOAD = Theme.ACCENT
    Theme.CHART_UPLOAD = Theme.ACCENT_PURPLE
    Theme.CHART_FILL_DL = _hex_to_rgba(Theme.ACCENT, 45)
    Theme.CHART_FILL_UL = _hex_to_rgba(Theme.ACCENT_PURPLE, 35)


def _hex_to_rgba(hex_color: str, alpha: int):
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (r, g, b, alpha)
