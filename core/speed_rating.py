"""What a measured connection is good for, in the spirit of Ookla's result page."""

LEVELS = ("Poor", "Fair", "Good", "Great")


def _clamp(level):
    return max(0, min(3, level))


def fmt_duration(seconds: float) -> str:
    if seconds < 90:
        return f"{max(round(seconds), 1)} s"
    if seconds < 5400:
        return f"{round(seconds / 60)} min"
    return f"{int(seconds // 3600)} h {round(seconds % 3600 / 60)} min"


def _transfer(gb, mbps):
    return fmt_duration(gb * 8 * 1024 / max(mbps, 0.01))


def rate(dl, ul, ping, jitter=None, loss=None):
    """Return a list of {key, title, level, rating, detail} for the common activities."""
    jitter = 0.0 if jitter is None else jitter
    loss = 0.0 if loss is None else loss
    out = []

    web = 3 if dl >= 25 else 2 if dl >= 10 else 1 if dl >= 3 else 0
    if ping > 150:
        web -= 1
    out.append(("web", "Web browsing", web,
                f"Pages open quickly at {dl:g} Mbps" if web >= 2 else "Pages may load slowly"))

    if dl >= 25:
        stream, label = 3, "4K Ultra HD"
    elif dl >= 8:
        stream, label = 2, "Full HD"
    elif dl >= 3:
        stream, label = 1, "HD (720p)"
    else:
        stream, label = 0, "Standard definition at best"
    out.append(("stream", "Video streaming", stream, label))

    if ul >= 8 and dl >= 8 and ping < 80 and jitter < 30:
        calls = 3
    elif ul >= 3 and dl >= 3 and ping < 120:
        calls = 2
    elif ul >= 1:
        calls = 1
    else:
        calls = 0
    if jitter > 50:
        calls -= 1
    detail = ("Group video calls in HD" if calls == 3 else "One-to-one HD calls" if calls == 2
              else "Calls may stutter" if calls == 1 else "Upload is too slow for calls")
    out.append(("calls", "Video calls", calls, detail))

    if ping < 25 and jitter < 10 and loss < 0.5:
        game = 3
    elif ping < 50 and jitter < 20 and loss < 1:
        game = 2
    elif ping < 100 and loss < 3:
        game = 1
    else:
        game = 0
    if dl < 3:
        game -= 1
    out.append(("gaming", "Online gaming", game,
                f"Ping {ping:g} ms" + (f", jitter {jitter:g} ms" if jitter else "")
                + (", fast and steady" if game == 3 else ", fine for most games" if game == 2
                   else ", competitive games will lag" if game <= 1 else "")))

    big = 3 if dl >= 100 else 2 if dl >= 50 else 1 if dl >= 15 else 0
    out.append(("download", "Large downloads", big, f"A 10 GB game takes about {_transfer(10, dl)}"))

    cloud = 3 if ul >= 50 else 2 if ul >= 15 else 1 if ul >= 5 else 0
    out.append(("cloud", "Cloud backup", cloud, f"1 GB uploads in about {_transfer(1, ul)}"))

    return [{"key": k, "title": t, "level": _clamp(lv), "rating": LEVELS[_clamp(lv)], "detail": d}
            for k, t, lv, d in out]


def summary(items):
    poor = [i["title"].lower() for i in items if i["level"] == 0]
    fair = [i["title"].lower() for i in items if i["level"] == 1]
    if poor:
        return "Weak spots: " + ", ".join(poor) + "."
    if fair:
        return "Good for everyday use. Could be better for " + ", ".join(fair) + "."
    return "Your connection is great for everything we tested."
