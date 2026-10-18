"""In-memory history of bandwidth and ping samples (GUI thread only)."""
import time
from collections import deque

RAW_SECONDS = 3600      # 1 s samples kept for the last hour
MINUTES = 43200         # per-minute buckets kept for 30 days
CONN_SAMPLES = 17280    # one ping/loss check every ~5 s for 24 hours


class TrafficHistory:
    def __init__(self):
        self.adapter = ""
        self._raw = deque(maxlen=RAW_SECONDS)     # (t, dl, ul) in Mbps
        self._minutes = deque(maxlen=MINUTES)     # (t, dl_avg, ul_avg, dl_max, ul_max, n)
        self._bucket = None                       # [minute, dl_sum, ul_sum, dl_max, ul_max, n]
        self._conn = deque(maxlen=CONN_SAMPLES)   # (t, ping_ms or None, loss_pct)

    # -- recording --
    def set_adapter(self, label: str) -> None:
        # new adapter, new record
        if label != self.adapter:
            self.adapter = label
            self._raw.clear()
            self._minutes.clear()
            self._bucket = None

    def add_bandwidth(self, dl: float, ul: float, t: float = None) -> None:
        t = t or time.time()
        dl, ul = float(dl), float(ul)
        self._raw.append((t, dl, ul))
        minute = int(t // 60) * 60
        b = self._bucket
        if b is None or b[0] != minute:
            self._flush()
            b = self._bucket = [minute, 0.0, 0.0, 0.0, 0.0, 0]
        b[1] += dl
        b[2] += ul
        b[3] = max(b[3], dl)
        b[4] = max(b[4], ul)
        b[5] += 1

    def add_connectivity(self, ping_ms, loss_pct: float, t: float = None) -> None:
        self._conn.append((t or time.time(),
                           None if ping_ms is None else float(ping_ms),
                           float(loss_pct)))

    def _flush(self) -> None:
        b = self._bucket
        if b and b[5]:
            n = b[5]
            self._minutes.append((b[0] + 30, b[1] / n, b[2] / n, b[3], b[4], n))

    # -- reading --
    def bandwidth(self, seconds: int) -> list:
        # rows: (t, dl, ul, dl_peak, ul_peak, seconds)
        start = time.time() - seconds
        if seconds <= RAW_SECONDS:
            return [(t, dl, ul, dl, ul, 1) for t, dl, ul in self._raw if t >= start]
        rows = [m for m in self._minutes if m[0] >= start]
        b = self._bucket
        if b and b[5] and b[0] >= start:
            n = b[5]
            rows.append((b[0] + 30, b[1] / n, b[2] / n, b[3], b[4], n))
        return rows

    def bandwidth_all(self):
        # (rows, coarse); short sessions stay per-second
        if len(self._minutes) < 60:
            return [(t, dl, ul, dl, ul, 1) for t, dl, ul in self._raw], False
        rows = list(self._minutes)
        b = self._bucket
        if b and b[5]:
            rows.append((b[0] + 30, b[1] / b[5], b[2] / b[5], b[3], b[4], b[5]))
        return rows, True

    def latest(self, max_age: float = 3.0):
        # newest sample, None if monitoring stopped
        if self._raw and time.time() - self._raw[-1][0] <= max_age:
            return self._raw[-1]
        return None

    def connectivity(self, seconds: int) -> list:
        start = time.time() - seconds
        return [c for c in self._conn if c[0] >= start]


traffic_history = TrafficHistory()
