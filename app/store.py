import json
import os
import sys
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
    "offline_mode": True,
}


def _config_dir():
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

    def __init__(self):
        self._data = {
            "settings": dict(DEFAULT_SETTINGS),
            "recent_hosts": [],       # list of {"host", "kind", "ts"}
            "favorites": [],          # list of {"host", "label"}
            "last_scans": {},         # feature -> arbitrary result payload
            "discovery_subnets": None,  # initialized from eligible local adapters
        }
        self._loaded = False
        self.load()

    def load(self):
        try:
            with open(_data_path(), "r", encoding="utf-8") as f:
                disk = json.load(f)
            if isinstance(disk, dict):
                self._data["settings"] = {**DEFAULT_SETTINGS,
                                          **disk.get("settings", {})}
                self._data["recent_hosts"] = disk.get("recent_hosts", [])
                self._data["favorites"] = disk.get("favorites", [])
                self._data["last_scans"] = disk.get("last_scans", {})
                self._data["discovery_subnets"] = disk.get("discovery_subnets")
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

    def add_recent_host(self, host, kind="ping"):
        host = (host or "").strip()
        if not host:
            return
        recents = self._data["recent_hosts"]
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

    def set_last_scan(self, feature, payload):
        self._data["last_scans"][feature] = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "payload": payload,
        }
        self.save()

    def get_last_scan(self, feature):
        return self._data["last_scans"].get(feature)

    def get_discovery_subnets(self):
        """Return persisted discovery scopes, or None before first setup."""
        entries = self._data.get("discovery_subnets")
        return [dict(entry) for entry in entries] if isinstance(entries, list) else None

    def set_discovery_subnets(self, entries):
        """Persist configured local and routed IPv4 discovery scopes."""
        self._data["discovery_subnets"] = [dict(entry) for entry in entries]
        self.save()

    def data_file_path(self):
        return _data_path()


store = Store()
