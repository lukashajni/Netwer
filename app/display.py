"""Screen-resolution profiles.

Lets NETWER either auto-detect the current screen or be pinned to a specific
resolution, handy when prepping a demo for a projector or a particular
monitor size ahead of time. Picking a resolution selects a UI density profile
(compact / standard / large, see app.theme.UI_SCALE_PROFILES) and a sensible
window size, so a cramped 1366x768 laptop and a 4K monitor both get a
comfortable layout instead of one fixed size stretched or squeezed to fit.
"""
from __future__ import annotations

#: key -> label shown in Settings. "auto" always sits first.
RESOLUTIONS = {
    "auto": "Auto (detect this screen)",
    "1280x720": "1280 × 720",
    "1366x768": "1366 × 768 (laptop)",
    "1600x900": "1600 × 900",
    "1920x1080": "1920 × 1080 (Full HD)",
    "2560x1440": "2560 × 1440 (2K)",
    "3840x2160": "3840 × 2160 (4K)",
}

#: (width, height) for every key except "auto", which uses the real screen.
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
    """Turn a resolution key into the (width, height) to plan a layout for.

    'auto' (or anything unrecognised) uses the screen NETWER is actually
    running on; a preset key uses that fixed size regardless of the real
    screen, which is useful for testing a specific target display."""
    return _SIZES.get(key, (screen_width, screen_height))


def window_geometry(width: int, height: int) -> tuple[int, int, int, int]:
    """A sensible (window_w, window_h, min_w, min_h) for a screen this size.

    The window is about 82% of the screen (never edge-to-edge, and never
    overflowing it even when the preset is bigger than the real display it's
    previewed on), with a minimum size scaled down for small screens so the
    app still fits rather than clipping off the edge."""
    win_w = max(1000, min(int(width * 0.82), width - 60))
    win_h = max(650, min(int(height * 0.82), height - 100))
    min_w = min(1000, int(width * 0.74))
    min_h = min(620, int(height * 0.74))
    return win_w, win_h, min_w, min_h
