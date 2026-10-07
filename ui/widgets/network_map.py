from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from ui.widgets.topology_map import TopologyGraphView


def guess_device_icon(dev: dict) -> str:
    """Pick an icon name from device metadata."""
    kind = (dev.get("kind") or "").strip()
    if kind.startswith("dev_"):
        return kind

    text = f"{dev.get('hostname','')} {dev.get('vendor','')}".lower()

    def has(*words):
        return any(w in text for w in words)

    if has("router", "mikrotik", "gateway", "ubiquiti", "tp-link", "netgear",
           "asus", "fritz", "openwrt", "d-link", "zyxel", "cisco", "unifi"):
        return "dev_router"
    if has("tv", "television", "bravia", "roku", "chromecast", "firetv",
           "shield", "appletv", "vizio", "samsung tv", "lg tv"):
        return "dev_tv"
    if has("watch", "band"):
        return "dev_watch"
    if has("ipad", "tablet", "tab-"):
        return "dev_tablet"
    if has("phone", "iphone", "android", "galaxy", "pixel", "xiaomi",
           "redmi", "oneplus", "huawei", "oppo", "vivo", "mobile"):
        return "dev_phone"
    if has("laptop", "notebook", "macbook", "thinkpad", "ideapad"):
        return "dev_laptop"
    if has("nas", "synology", "qnap", "storage", "server", "truenas",
           "western digital", "seagate"):
        return "dev_nas"
    if has("printer", "print", "canon", "epson", "brother", "laserjet",
           "officejet"):
        return "dev_printer"
    if has("playstation", "ps4", "ps5", "xbox", "nintendo", "switch"):
        return "dev_console"
    if has("camera", "cam", "hikvision", "dahua", "axis", "cctv", "ring"):
        return "dev_camera"
    if has("echo", "alexa", "sonos", "speaker", "homepod"):
        return "dev_speaker"
    if has("esp", "espressif", "tuya", "sonoff", "shelly", "bulb", "lifx",
           "nest", "hue", "smart", "iot", "wemo"):
        return "dev_iot"
    if has("desktop", "pc-", "-pc", "windows", "asrock", "msi", "gigabyte"):
        return "dev_pc"
    return "dev_generic"


def device_display_name(dev: dict) -> str:
    """Return the best available display name for a device."""
    try:
        from core import device_names
        custom = device_names.get(dev)
        if custom:
            return custom
    except Exception:
        pass
    hostname = (dev.get("hostname") or "").strip()
    if hostname and hostname.lower() not in ("unknown", "?", ""):
        # A hostname that's just the IP repeated isn't a real name.
        if hostname != dev.get("ip", ""):
            return hostname
    vendor = (dev.get("vendor") or "").strip()
    generic = ("unknown", "private (randomized)", "private", "randomized", "")
    if vendor and vendor.lower() not in generic:
        # "Apple (private address)" is useful detail, but as a "name" the
        # manufacturer alone reads better under an icon.
        return vendor.replace(" (private address)", "")
    return dev.get("ip", "?")


class NetworkMap(QWidget):
    # Emitted with the device dict when a device node is clicked.
    node_clicked = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        self.setMinimumHeight(220)
        self.graph = TopologyGraphView(compact=True)
        self.graph.device_selected.connect(self.node_clicked.emit)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.graph)

    def set_topology(self, gateway, devices, router_vendor="", online=True):
        preview = []
        for device in devices[:5]:
            item = dict(device)
            item["segment_id"] = "preview"
            item["cidr"] = ""
            preview.append(item)
        self.graph.update_graph(
            [{"id": "preview", "label": router_vendor or "LAN", "cidr": "",
              "kind": "local", "gateway": gateway}],
            preview,
        )
