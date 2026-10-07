"""Screen-resolution presets and window sizing helpers."""
from __future__ import annotations

RESOLUTIONS = {
    "auto": "Auto (detect this screen)",
    "1280x720": "1280 × 720",
    "1366x768": "1366 × 768 (laptop)",
    "1600x900": "1600 × 900",
    "1920x1080": "1920 × 1080 (Full HD)",
    "2560x1440": "2560 × 1440 (2K)",
    "3840x2160": "3840 × 2160 (4K)",
}

_SIZES = {
    "1280x720": (1280, 720),
    "1366x768": (1366, 768),
    "1600x900": (1600, 900),
    "1920x1080": (1920, 1080),
    "2560x1440": (2560, 1440),
    "3840x2160": (3840, 2160),
}


def profile_for(width: int) -> str:
    """compact / standard / large UI density for a screen this wide."""
    if width <= 1366:
        return "compact"
    if width >= 2560:
        return "large"
    return "standard"


def resolve(key: str, screen_width: int, screen_height: int) -> tuple[int, int]:
    """Resolve a preset key or use the current screen dimensions."""
    return _SIZES.get(key, (screen_width, screen_height))


def window_geometry(width: int, height: int) -> tuple[int, int, int, int]:
    """Return the window and minimum dimensions for a screen size."""
    win_w = max(1000, min(int(width * 0.82), width - 60))
    win_h = max(650, min(int(height * 0.82), height - 100))
    # Large typography and the fixed-width sidebar/settings panel need more
    # room than the compact layout; don't allow a 4K-scaled UI to be squeezed
    # into a narrow window where navigation labels overlap and cards clip.
    min_w = (min(win_w, max(1200, int(width * 0.60)))
             if width >= 1600 else min(1000, int(width * 0.74)))
    min_h = min(620, int(height * 0.74))
    return win_w, win_h, min_w, min_h
