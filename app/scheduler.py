"""
NETWER background scan scheduler.

Runs a periodic ping sweep of the local network in the background, whatever
page happens to be open, and raises notifications when a device appears or
disappears. That's the basis of light-touch monitoring: leave NETWER running
and it tells you when something joins or leaves your network.

The scheduler is off by default; the user turns it on in Settings and picks
an interval. The sweep runs in a worker thread so the UI never blocks, the
result is diffed against the last known set of devices, and notifications go
out through the settings-aware helpers.
"""

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from app.store import store
from app.notifications import notifications
from app.activity import activity
from workers import StreamWorker


class ScanScheduler(QObject):
    #: emitted after each scheduled sweep with the list of device dicts
    scan_completed = pyqtSignal(list)
    #: emitted when the scheduler turns on/off (bool = running)
    state_changed = pyqtSignal(bool)

    def __init__(self, core, parent=None):
        super().__init__(parent)
        self.core = core
        self._worker = None
        self._devices = []          # devices from the in-progress sweep
        self._running = False

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._run_scan)

    # Control
    def start(self):
        """Begin periodic scanning at the interval from Settings."""
        if self._running:
            return
        self._running = True
        interval_min = int(store.get_setting("schedule_interval_min", 10))
        self._timer.start(max(1, interval_min) * 60 * 1000)
        self.state_changed.emit(True)
        activity.add("Scheduled scanning on",
                     f"every {interval_min} min", kind="info")
        # Kick off an immediate first scan so the user sees activity.
        self._run_scan()

    def stop(self):
        if not self._running:
            return
        self._running = False
        self._timer.stop()
        if self._worker is not None:
            self._worker.stop()
            self._worker = None
        self.state_changed.emit(False)
        activity.add("Scheduled scanning off", "", kind="info")

    def is_running(self):
        return self._running

    def set_interval(self, minutes):
        store.set_setting("schedule_interval_min", int(minutes))
        if self._running:
            self._timer.start(max(1, int(minutes)) * 60 * 1000)

    # Scan cycle
    def _run_scan(self):
        # Don't stack scans if a previous one is still going.
        if self._worker is not None and self._worker.isRunning():
            return
        self._devices = []
        w = StreamWorker(self.core.ping_sweep_stream,
                         int(store.get_setting("sweep_timeout_ms", 150)))
        w.result.connect(self._on_event)
        w.done.connect(self._on_done)
        self._worker = w
        w.start()

    def _on_event(self, d: dict):
        if d.get("online"):
            self._devices.append(d)

    def _on_done(self):
        self._diff_and_notify(self._devices)
        self.scan_completed.emit(list(self._devices))
        self._worker = None

    def _diff_and_notify(self, devices):
        """Compare against the last known device set and notify about
        devices that showed up or went away."""
        prev = set(store.get_setting("scheduler_known_macs", []) or [])
        prev_names = store.get_setting("scheduler_device_names", {}) or {}

        current = {}
        for d in devices:
            mac = (d.get("mac") or "").upper()
            if mac:
                current[mac] = self._name_for(d)

        cur_set = set(current.keys())

        # Only diff once we have a baseline (first run just records).
        if prev:
            for mac in cur_set - prev:
                notifications.notify_new_device(current[mac], "")
                activity.add("Device joined network", current[mac], kind="info")
            for mac in prev - cur_set:
                # A device leaving is reported under the "host down" toggle.
                if store.get_setting("notify_host_down", True):
                    notifications.push("Device left network",
                                       prev_names.get(mac, mac), kind="warning")
                    activity.add("Device left network",
                                 prev_names.get(mac, mac), kind="info")

        store.set_setting("scheduler_known_macs", sorted(cur_set))
        store.set_setting("scheduler_device_names", current)

    @staticmethod
    def _name_for(d):
        host = (d.get("hostname") or "").strip()
        if host and host.lower() not in ("unknown", "?", ""):
            return host
        vendor = (d.get("vendor") or "").strip()
        if vendor and vendor.lower() != "unknown":
            return vendor
        return d.get("ip", "") or "device"
