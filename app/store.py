"""
NETWER persistent store.

A tiny JSON-backed key/value store living in the user's config folder, used
for things that should survive across sessions: app settings (default
timeouts, worker counts), recent hosts, favorites, and the last scan results
per feature. Everything is namespaced so one feature can't clobber another.

Location:
    Windows : %APPDATA%\\NETWER\\netwer_data.json
    Linux   : ~/.config/NETWER/netwer_data.json
    macOS   : ~/Library/Application Support/NETWER/netwer_data.json

The store is forgiving on purpose: a corrupt or missing file just resets to
defaults instead of crashing the app. Writes are atomic (write a temp file,
then replace) so a crash mid-write can't leave a broken file behind.
"""

import os
import sys
import json
import tempfile
from datetime import datetime


APP_NAME = "NETWER"
DATA_FILE = "netwer_data.json"

DEFAULT_SETTINGS = {
    "ping_timeout_ms": 1000,
    "sweep_timeout_ms": 150,
    "portscan_timeout_ms": 600,
    "portscan_workers": 100,
    "max_recent_hosts": 12,
    "monitor_interval_s": 5,
    "schedule_enabled": False,
    "schedule_interval_min": 10,
}


def _config_dir():
    """Per-OS config directory, created if missing."""
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        path = os.path.join(base, APP_NAME)
    elif sys.platform == "darwin":
        path = os.path.join(os.path.expanduser("~"),
                            "Library", "Application Support", APP_NAME)
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or \
            os.path.join(os.path.expanduser("~"), ".config")
        path = os.path.join(base, APP_NAME)
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        path = tempfile.gettempdir()
    return path


def _data_path():
    return os.path.join(_config_dir(), DATA_FILE)


class Store:
    """Singleton-ish JSON store. Import the module-level `store` instance."""

    def __init__(self):
        self._data = {
            "settings": dict(DEFAULT_SETTINGS),
            "recent_hosts": [],       # list of {"host", "kind", "ts"}
            "favorites": [],          # list of {"host", "label"}
            "last_scans": {},         # feature -> arbitrary result payload
        }
        self._loaded = False
        self.load()

    # Load / save
    def load(self):
        try:
            with open(_data_path(), "r", encoding="utf-8") as f:
                disk = json.load(f)
            if isinstance(disk, dict):
                # Merge so new default keys appear for old files.
                self._data["settings"] = {**DEFAULT_SETTINGS,
                                          **disk.get("settings", {})}
                self._data["recent_hosts"] = disk.get("recent_hosts", [])
                self._data["favorites"] = disk.get("favorites", [])
                self._data["last_scans"] = disk.get("last_scans", {})
        except Exception:
            pass  # missing or corrupt file, keep defaults
        self._loaded = True

    def save(self):
        try:
            path = _data_path()
            fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path),
                                       suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
            os.replace(tmp, path)   # atomic
        except Exception:
            pass

    # Settings
    def get_setting(self, key, default=None):
        return self._data["settings"].get(
            key, DEFAULT_SETTINGS.get(key, default))

    def set_setting(self, key, value):
        self._data["settings"][key] = value
        self.save()

    def all_settings(self):
        return dict(self._data["settings"])

    def reset_settings(self):
        self._data["settings"] = dict(DEFAULT_SETTINGS)
        self.save()

    # Recent hosts
    def add_recent_host(self, host, kind="ping"):
        host = (host or "").strip()
        if not host:
            return
        recents = self._data["recent_hosts"]
        # De-dup: drop existing entry for this host, then prepend.
        recents = [r for r in recents if r.get("host") != host]
        recents.insert(0, {"host": host, "kind": kind,
                           "ts": datetime.now().isoformat(timespec="seconds")})
        limit = int(self.get_setting("max_recent_hosts", 12))
        self._data["recent_hosts"] = recents[:limit]
        self.save()

    def recent_hosts(self, kind=None):
        rs = self._data["recent_hosts"]
        if kind:
            rs = [r for r in rs if r.get("kind") == kind]
        return list(rs)

    def clear_recent_hosts(self):
        self._data["recent_hosts"] = []
        self.save()

    # Favorites
    def add_favorite(self, host, label=""):
        host = (host or "").strip()
        if not host:
            return
        favs = self._data["favorites"]
        if any(f.get("host") == host for f in favs):
            return
        favs.append({"host": host, "label": label or host})
        self._data["favorites"] = favs
        self.save()

    def remove_favorite(self, host):
        self._data["favorites"] = [
            f for f in self._data["favorites"] if f.get("host") != host]
        self.save()

    def is_favorite(self, host):
        return any(f.get("host") == host for f in self._data["favorites"])

    def favorites(self):
        return list(self._data["favorites"])

    # Last scan cache
    def set_last_scan(self, feature, payload):
        self._data["last_scans"][feature] = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "payload": payload,
        }
        self.save()

    def get_last_scan(self, feature):
        return self._data["last_scans"].get(feature)

    # Utility
    def data_file_path(self):
        return _data_path()


# Module-level singleton used across the app.
store = Store()
