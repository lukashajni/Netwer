"""
NETWER formatting helpers.

Speed values are stored internally in Mbps (that's what the backend
yields), but showing "0.02 Mbps" is unhelpful. Real network tools switch
units to whatever fits: Kbps for slow traffic, Mbps for normal, Gbps for
very fast links. These helpers do that.
"""


def format_speed(mbps: float):
    """Return (value_string, unit_string) with a sensible unit.

    Under 1 Mbps comes back as Kbps (512 Kbps), under 1000 Mbps as Mbps
    (152.4 Mbps), and anything at or above 1000 Mbps as Gbps
    (1.20 Gbps).
    """
    try:
        v = float(mbps)
    except (TypeError, ValueError):
        return "0", "Mbps"

    if v < 0:
        v = 0.0

    if v < 1.0:
        kbps = v * 1000.0
        # Below 100 Kbps a decimal place is still worth showing
        if kbps < 100:
            return f"{kbps:.1f}", "Kbps"
        return f"{kbps:.0f}", "Kbps"

    if v < 1000.0:
        return f"{v:.1f}", "Mbps"

    return f"{v / 1000.0:.2f}", "Gbps"


def speed_label(mbps: float) -> str:
    """Single string, e.g. '512 Kbps' or '152.4 Mbps'."""
    value, unit = format_speed(mbps)
    return f"{value} {unit}"


def scale_for_axis(max_mbps: float):
    """Pick the display unit + divisor for a chart axis given the peak value.

    Returns (unit_name, divisor). Chart values (in Mbps) divided by the
    divisor give numbers in that unit, so the axis reads 'Kbps' when
    traffic is small instead of a flat line near zero on an Mbps axis.
    """
    try:
        peak = float(max_mbps)
    except (TypeError, ValueError):
        peak = 0.0

    if peak < 1.0:
        return "Kbps", 0.001      # Mbps / 0.001 = Kbps
    if peak < 1000.0:
        return "Mbps", 1.0
    return "Gbps", 1000.0
