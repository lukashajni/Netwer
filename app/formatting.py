
def format_speed(mbps: float):
    try:
        v = float(mbps)
    except (TypeError, ValueError):
        return "0", "Mbps"

    if v < 0:
        v = 0.0

    if v < 1.0:
        kbps = v * 1000.0
        if kbps < 100:
            return f"{kbps:.1f}", "Kbps"
        return f"{kbps:.0f}", "Kbps"

    if v < 1000.0:
        return f"{v:.1f}", "Mbps"

    return f"{v / 1000.0:.2f}", "Gbps"


def speed_label(mbps: float) -> str:
    value, unit = format_speed(mbps)
    return f"{value} {unit}"


def scale_for_axis(max_mbps: float):
    try:
        peak = float(max_mbps)
    except (TypeError, ValueError):
        peak = 0.0

    if peak < 1.0:
        return "Kbps", 0.001      # Mbps / 0.001 = Kbps
    if peak < 1000.0:
        return "Mbps", 1.0
    return "Gbps", 1000.0
