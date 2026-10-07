"""Interactive network topology graph shared by dashboard and detail views."""

import math

from PyQt6.QtCore import QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QFrame,
    QGraphicsEllipseItem,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsView,
)

from app.theme import Theme


def _device_name(device):
    try:
        from core import device_names

        custom = device_names.get(device)
        if custom:
            return custom
    except Exception:
        pass
    hostname = (device.get("hostname") or "").strip()
    if hostname and hostname.casefold() not in ("unknown", "?"):
        if hostname != device.get("ip", ""):
            return hostname
    vendor = (device.get("vendor") or "").strip()
    if vendor.casefold() not in ("", "unknown", "private", "private (randomized)"):
        return vendor.replace(" (private address)", "")
    return device.get("ip", "?")


class _DeviceItem(QGraphicsEllipseItem):
    def __init__(self, rect, device, callback):
        super().__init__(rect)
        self.device = device
        self._callback = callback
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            event.accept()
            self._callback(self.device)
            return
        super().mousePressEvent(event)


class TopologyGraphView(QGraphicsView):
    device_selected = pyqtSignal(dict)

    def __init__(self, compact=False, parent=None):
        super().__init__(parent)
        self.compact = compact
        self.scene_graph = QGraphicsScene(self)
        self.setScene(self.scene_graph)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.BoundingRectViewportUpdate)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setBackgroundBrush(QColor(Theme.BG_APP))
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setMinimumHeight(150 if compact else 260)
        self._nodes = {}
        self._labels = []
        self._segments = []
        self._devices = []
        self._selected_ip = ""
        self._filtered_ips = None
        self._first_layout = True

    def update_graph(self, segments, devices, visible_ips=None, selected_ip=""):
        next_segments = [dict(segment) for segment in (segments or [])]
        next_devices = [dict(device) for device in (devices or [])]
        next_visible = None if visible_ips is None else set(visible_ips)
        selected_ip = selected_ip or ""
        if (next_segments == self._segments and next_devices == self._devices
                and next_visible == self._filtered_ips
                and selected_ip == self._selected_ip):
            return
        self._segments = next_segments
        self._devices = next_devices
        self._filtered_ips = next_visible
        self._selected_ip = selected_ip
        self._draw_graph()

    def set_data(self, segments, devices):
        self.update_graph(segments, devices, self._filtered_ips, self._selected_ip)

    def set_selected(self, ip, center=False):
        ip = ip or ""
        if ip != self._selected_ip:
            self._selected_ip = ip
            self._draw_graph()
        if center:
            self.center_device(ip)

    def set_visible_devices(self, ips):
        visible = None if ips is None else set(ips)
        if visible != self._filtered_ips:
            self._filtered_ips = visible
            self._draw_graph()

    def _draw_graph(self):
        scene = self.scene_graph
        scene.clear()
        self._nodes = {}
        self._labels = []
        segments = self._enabled_segments()
        grouped = [(segment, self._segment_devices(segment, segments)) for segment in segments]
        layout = self._cluster_layout(grouped)

        self._box("Internet", "External network", 0, 0, Theme.SUCCESS, 82, 34)
        self._box("Router / gateway", self._gateway_label(), 0, 105, Theme.ACCENT, 106, 40)
        self._edge_path([(0, 34), (0, 65)], Theme.SUCCESS, 2.0)

        branch_y = 178
        if layout:
            left = layout[0][0]
            right = layout[-1][0]
            self._edge_path([(0, 145), (0, branch_y), (left, branch_y), (right, branch_y)],
                            Theme.GLASS_BORDER_HI, 1.5)
        for center_x, cluster_width, segment, devices, cols in layout:
            local = segment.get("kind") == "local"
            color = Theme.SUCCESS if local else Theme.ACCENT_PURPLE
            label = segment.get("label") or "Subnet"
            cidr = segment.get("cidr", "")
            self._edge_path([(center_x, branch_y), (center_x, 207)], color, 1.6)
            self._box(
                f"{label} · {cidr}".strip(" ·"),
                "LOCAL / L2" if local else "ROUTED / L3",
                center_x,
                243,
                color,
                min(max(cluster_width / 2 - 14, 116), 260),
                36,
            )
            self._draw_cluster(center_x, cluster_width, devices, cols, color)

        bounds = scene.itemsBoundingRect().adjusted(-60, -45, 60, 55)
        scene.setSceneRect(bounds)
        self._update_label_visibility(self.transform().m11())
        if self._first_layout:
            self._first_layout = False
            QTimer.singleShot(0, self.fit_graph)

    def _enabled_segments(self):
        segments = self._segments or [
            {"id": "default", "label": "Network", "cidr": "", "kind": "local"}
        ]
        return [segment for segment in segments if segment.get("enabled", True)] or segments

    def _segment_devices(self, segment, all_segments):
        segment_id = segment.get("id", segment.get("cidr", ""))
        devices = [
            device for device in self._devices
            if self._belongs(device, segment, segment_id, len(all_segments))
        ]
        if self._filtered_ips is not None:
            devices = [device for device in devices if device.get("ip") in self._filtered_ips]
        return sorted(devices, key=lambda device: self._ip_sort(device.get("ip", "")))

    def _cluster_layout(self, grouped):
        pitch_x = 108 if self.compact else 142
        gap = 56 if self.compact else 90
        layouts = []
        for segment, devices in grouped:
            cols = max(1, min(10 if self.compact else 12, math.ceil(math.sqrt(len(devices) or 1))))
            width = max(250, cols * pitch_x + 44)
            layouts.append([0.0, width, segment, devices, cols])
        total = sum(item[1] for item in layouts) + gap * max(0, len(layouts) - 1)
        cursor = -total / 2
        for item in layouts:
            item[0] = cursor + item[1] / 2
            cursor += item[1] + gap
        return layouts

    def _draw_cluster(self, center_x, width, devices, cols, color):
        pitch_x, pitch_y = (108, 78) if self.compact else (142, 92)
        rows = max(1, math.ceil(len(devices) / cols))
        top = 315
        height = rows * pitch_y + 54
        cluster = self.scene_graph.addRect(
            QRectF(center_x - width / 2, top - 32, width, height),
            QPen(QColor(Theme.GLASS_BORDER), 1, Qt.PenStyle.DashLine),
            QBrush(QColor(Theme.GLASS_CARD)),
        )
        cluster.setZValue(-1)
        if not devices:
            empty = self.scene_graph.addText("No discovered devices", QFont("Segoe UI", 9))
            empty.setDefaultTextColor(QColor(Theme.TEXT_MUTED))
            empty.setPos(center_x - empty.boundingRect().width() / 2, top + 4)
            return
        bus_y = top - 9
        first_x = center_x - (min(cols, len(devices)) - 1) * pitch_x / 2
        last_x = center_x + (min(cols, len(devices)) - 1) * pitch_x / 2
        self._edge_path([(center_x, 279), (center_x, bus_y), (first_x, bus_y), (last_x, bus_y)],
                        color, 1.3)
        for index, device in enumerate(devices):
            col, row = index % cols, index // cols
            row_count = min(cols, len(devices) - row * cols)
            x = center_x + (col - (row_count - 1) / 2) * pitch_x
            y = top + row * pitch_y + 33
            branch_top = bus_y if row == 0 else y - pitch_y / 2
            self._edge_path([(x, branch_top), (x, y - 27)], Theme.GLASS_BORDER_HI, 1.0)
            item = self._device_box(device, x, y)
            self._nodes.setdefault(device.get("ip", ""), []).append(item)

    def _box(self, title, subtitle, x, y, color, rx, ry):
        rect = QRectF(x - rx, y - ry, rx * 2, ry * 2)
        shape = self.scene_graph.addRect(rect, QPen(QColor(color), 1.6),
                                         QBrush(QColor(Theme.GLASS_CARD)))
        shape.setZValue(2)
        self._text(title, x, y - 16, Theme.TEXT_PRIMARY, 9, True)
        self._text(subtitle, x, y + 7, color, 7, False, mono=True)
        return shape

    def _device_box(self, device, x, y):
        rx, ry = (48, 25) if self.compact else (59, 29)
        rect = QRectF(x - rx, y - ry, rx * 2, ry * 2)
        color = self._device_color(device)
        selected = device.get("ip") == self._selected_ip
        item = _DeviceItem(rect, device, self.device_selected.emit)
        item.setPen(QPen(QColor(Theme.ACCENT if selected else color), 3 if selected else 1.6))
        item.setBrush(QBrush(QColor(Theme.GLASS_INPUT)))
        item.setZValue(3)
        self.scene_graph.addItem(item)
        title = self._text(_device_name(device), x, y - 13, Theme.TEXT_PRIMARY,
                           8 if self.compact else 9, True, device_label=True)
        subtitle = self._text(device.get("ip", ""), x, y + 7, Theme.TEXT_SECONDARY,
                              7, False, mono=True, device_label=True)
        title.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        subtitle.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        return item

    def _text(self, value, x, y, color, size, bold, mono=False, device_label=False):
        font = QFont("Consolas" if mono else "Segoe UI", size)
        if bold:
            font.setWeight(QFont.Weight.DemiBold)
        item = self.scene_graph.addText(str(value)[:28], font)
        item.setDefaultTextColor(QColor(color))
        item.setPos(x - item.boundingRect().width() / 2, y - item.boundingRect().height() / 2)
        item.setZValue(4)
        if device_label:
            self._labels.append(item)
        return item

    def _edge_path(self, points, color, width):
        if len(points) < 2:
            return
        path = QPainterPath()
        path.moveTo(*points[0])
        for point in points[1:]:
            path.lineTo(*point)
        edge = QGraphicsPathItem(path)
        edge.setPen(QPen(QColor(color), width))
        edge.setZValue(0)
        self.scene_graph.addItem(edge)

    def _gateway_label(self):
        gateway = next((device.get("ip") for device in self._devices
                        if device.get("is_gateway")), "")
        if gateway:
            return gateway
        return next((segment.get("gateway") for segment in self._segments
                     if segment.get("gateway")), "Gateway")

    @staticmethod
    def _belongs(device, segment, segment_id, segment_count):
        if device.get("segment_id"):
            return device.get("segment_id") == segment_id
        if device.get("cidr"):
            return device.get("cidr") == segment.get("cidr")
        return segment_count == 1

    @staticmethod
    def _ip_sort(ip):
        try:
            return tuple(int(part) for part in ip.split("."))
        except (ValueError, AttributeError):
            return (999, 999, 999, 999)

    @staticmethod
    def _device_color(device):
        if device.get("is_gateway"):
            return Theme.SUCCESS
        if device.get("reachability") == "reachable":
            return Theme.ACCENT
        if device.get("reachability") == "cached":
            return Theme.WARNING
        vendor = (device.get("vendor") or "").casefold()
        if vendor and vendor not in ("unknown", "private (randomized)"):
            return Theme.ACCENT_PURPLE
        return Theme.TEXT_MUTED

    def zoom_in(self):
        self._zoom(1.2)

    def zoom_out(self):
        self._zoom(1 / 1.2)

    def _zoom(self, factor):
        current = self.transform().m11()
        target = max(0.18, min(3.0, current * factor))
        self.scale(target / current, target / current)
        self._update_label_visibility(target)

    def wheelEvent(self, event):
        self._zoom(1.15 if event.angleDelta().y() > 0 else 1 / 1.15)
        event.accept()

    def fit_graph(self):
        if not self.sceneRect().isEmpty():
            self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
            self._update_label_visibility(self.transform().m11())

    def reset_zoom(self):
        self.resetTransform()
        self.centerOn(self.sceneRect().center())
        self._update_label_visibility(1.0)

    def _update_label_visibility(self, scale):
        for label in self._labels:
            label.setVisible(scale >= 0.52)

    def center_device(self, ip):
        items = self._nodes.get(ip, [])
        if items:
            self.centerOn(items[0])
