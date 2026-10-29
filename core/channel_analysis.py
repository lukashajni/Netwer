"""Channel crowding analysis for the Wi-Fi Channel Analyzer."""

BANDS = ("2.4 GHz", "5 GHz", "6 GHz")
CH_5 = [36, 40, 44, 48, 52, 56, 60, 64, 100, 104, 108, 112, 116, 120, 124, 128, 132, 136, 140, 144, 149, 153, 157, 161, 165]
CH_6 = list(range(1, 234, 4))
GROUPS_5 = {20: [[c] for c in CH_5],
            40: [[36, 40], [44, 48], [52, 56], [60, 64], [100, 104], [108, 112], [116, 120], [124, 128],
                 [132, 136], [140, 144], [149, 153], [157, 161]],
            80: [[36, 40, 44, 48], [52, 56, 60, 64], [100, 104, 108, 112], [116, 120, 124, 128],
                 [132, 136, 140, 144], [149, 153, 157, 161]],
            160: [[36, 40, 44, 48, 52, 56, 60, 64], [100, 104, 108, 112, 116, 120, 124, 128]]}


def groups_6(width):
    n = max(width // 20, 1)
    return [CH_6[i:i + n] for i in range(0, len(CH_6) - n + 1, n)]


def base_mhz(band):
    return {"2.4 GHz": 2407, "5 GHz": 5000, "6 GHz": 5950}[band]


def channel_list(band):
    return list(range(1, 14)) if band == "2.4 GHz" else CH_5 if band == "5 GHz" else CH_6


def groups(band, width):
    if band == "5 GHz":
        return GROUPS_5.get(width, GROUPS_5[20])
    if band == "6 GHz":
        return groups_6(width)
    return [[c] for c in range(1, 14)]


def ap_span(ap):
    # (low MHz, high MHz) taken by an access point
    band, ch, w = ap["band"], ap["channel"], ap.get("width", 20)
    if band == "2.4 GHz":
        centre = 2484 if ch == 14 else 2407 + 5 * ch
        return centre - w / 2, centre + w / 2
    for g in groups(band, w):
        if ch in g:
            return base_mhz(band) + 5 * g[0] - 10, base_mhz(band) + 5 * g[-1] + 10
    centre = base_mhz(band) + 5 * ch
    return centre - w / 2, centre + w / 2


def group_span(band, chans):
    if band == "2.4 GHz":
        c = 2407 + 5 * chans[0]
        return c - 10, c + 10
    return base_mhz(band) + 5 * chans[0] - 10, base_mhz(band) + 5 * chans[-1] + 10


def _weight(rssi):
    # a neighbour at -50 dBm hurts much more than one at -85 dBm
    return min(max((rssi + 95) / 45.0, 0.05), 1.0)


def crowding(span, aps, own_bssid=""):
    """(score, number of overlapping networks) for a frequency span."""
    lo, hi = span
    score, count = 0.0, 0
    for ap in aps:
        if own_bssid and ap["bssid"] == own_bssid:
            continue
        a_lo, a_hi = ap_span(ap)
        overlap = max(0.0, min(hi, a_hi) - max(lo, a_lo)) / (hi - lo)
        if overlap > 0:
            score += overlap * _weight(ap["rssi"])
            if ap["rssi"] > -85:
                count += 1
    return score, count


def level(score):
    return "Low" if score < 0.35 else "Medium" if score < 1.2 else "High"


def is_dfs(chans):
    return any(52 <= c <= 144 for c in chans)


def label(band, chans, width):
    if band == "2.4 GHz":
        return f"Channel {chans[0]}"
    return f"{chans[0]}" if len(chans) == 1 else f"{chans[0]} to {chans[-1]}"


def analyze(aps, band, own_bssid="", own_channel=None, own_width=20):
    aps = [a for a in aps if a["band"] == band]
    if not aps and not own_channel:
        return None
    # one score per 20 MHz channel for the crowding strip
    strip = {c: crowding(group_span(band, [c]), aps, own_bssid)[0] for c in channel_list(band)}
    width = 20 if band == "2.4 GHz" else (own_width if own_width in (20, 40, 80, 160) else 80)
    candidates = [[c] for c in (1, 6, 11)] if band == "2.4 GHz" else groups(band, width)
    scored = []
    for g in candidates:
        s, n = crowding(group_span(band, g), aps, own_bssid)
        scored.append({"chans": g, "label": label(band, g, width), "score": s, "overlap": n,
                       "dfs": is_dfs(g), "level": level(s)})
    # prefer channels without radar checks when the scores are close
    best = min(scored, key=lambda c: (round(c["score"] / 0.15), c["dfs"], c["score"]))
    current = None
    if own_channel:
        g = next((x for x in groups(band, width) if own_channel in x), [own_channel])
        if band == "2.4 GHz":
            g = [own_channel]
        s, n = crowding(group_span(band, g), aps, own_bssid)
        current = {"chans": g, "label": label(band, g, width), "score": s, "overlap": n, "dfs": is_dfs(g), "level": level(s)}
    change = bool(current) and best["chans"] != current["chans"] and current["level"] != "Low" \
        and best["score"] < current["score"] * 0.7
    return {"band": band, "strip": strip, "best": best, "current": current, "change": change,
            "candidates": scored, "width": width}
