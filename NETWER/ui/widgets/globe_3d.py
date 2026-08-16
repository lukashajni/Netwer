"""
NETWER — Globe3D widget.

Displays the NETWER logo model on the About page: slow idle spin, drag to
rotate, eases back to its starting orientation after three idle seconds.

The model is the project's own .glb, recoloured to the theme palette. It's
shown as-is — no added geometry, no decoration.

Falls back to the flat 2D logo if 3D can't run (no GPU / software
rendering), so the page still looks right rather than showing an empty box.
"""

import os
import tempfile

from PyQt6.QtCore import QUrl, Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel

from app.theme import Theme
from app.resources import ASSETS_DIR, logo_pixmap


MODEL_PATH = os.path.join(ASSETS_DIR, "models", "netwer_globe.glb")

# The model is authored at ~1 unit radius; QtQuick3D's scene units are far
# larger, so scale up to fill the viewport.
MODEL_SCALE = 120


def _build_qml(model_url: str) -> str:
    return f"""
import QtQuick
import QtQuick3D
import QtQuick3D.AssetUtils

Item {{
    id: root

    property real rotX: 0
    property real rotY: 0
    property real velX: 0
    property real velY: idleSpin

    readonly property real idleSpin: 0.24
    property bool touched: false
    property real idleMs: 0

    View3D {{
        anchors.fill: parent
        renderMode: View3D.Offscreen

        environment: SceneEnvironment {{
            clearColor: "transparent"
            backgroundMode: SceneEnvironment.Transparent
            antialiasingMode: SceneEnvironment.MSAA
            antialiasingQuality: SceneEnvironment.High
        }}

        PerspectiveCamera {{
            z: 400
            fieldOfView: 45
        }}

        DirectionalLight {{
            eulerRotation.x: -25
            eulerRotation.y: -30
            brightness: 1.5
        }}
        DirectionalLight {{
            eulerRotation.x: 20
            eulerRotation.y: 150
            brightness: 0.7
        }}

        Node {{
            eulerRotation.x: root.rotX
            eulerRotation.y: root.rotY

            RuntimeLoader {{
                source: "{model_url}"
                scale: Qt.vector3d({MODEL_SCALE}, {MODEL_SCALE}, {MODEL_SCALE})
            }}
        }}
    }}

    MouseArea {{
        id: mouse
        anchors.fill: parent
        cursorShape: pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor
        property real lastX: 0
        property real lastY: 0

        onPressed: (e) => {{
            root.touched = true;
            root.velX = 0;
            root.velY = 0;
            lastX = e.x;
            lastY = e.y;
        }}
        onPositionChanged: (e) => {{
            if (!pressed) return;
            root.velY = (e.x - lastX) * 0.30;
            root.velX = (e.y - lastY) * 0.30;
            root.rotY += root.velY;
            root.rotX += root.velX;
            lastX = e.x;
            lastY = e.y;
        }}
        onReleased: root.idleMs = 0
    }}

    Timer {{
        interval: 16
        running: true
        repeat: true
        onTriggered: {{
            if (mouse.pressed)
                return;

            if (!root.touched) {{
                root.rotY += root.idleSpin;
                return;
            }}

            root.idleMs += 16;

            if (root.idleMs < 3000) {{
                // Coast on inertia for the first three seconds
                root.rotY += root.velY;
                root.rotX += root.velX;
                root.velX *= 0.96;
                root.velY *= 0.96;
            }} else {{
                // Ease back home, then resume the idle spin
                root.rotX += (0 - root.rotX) * 0.05;

                var target = Math.round(root.rotY / 360) * 360;
                var dy = target - root.rotY;
                root.rotY += dy * 0.05;

                if (Math.abs(root.rotX) < 0.3 && Math.abs(dy) < 0.5) {{
                    root.rotX = 0;
                    root.rotY = 0;
                    root.velX = 0;
                    root.velY = root.idleSpin;
                    root.touched = false;
                    root.idleMs = 0;
                }}
            }}
        }}
    }}
}}
"""


class Globe3D(QWidget):
    """The logo in 3D, or a static logo if 3D isn't available."""

    def __init__(self, size: int = 260, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setStyleSheet("background: transparent;")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        widget = self._build_3d()
        if widget is None:
            widget = self._build_fallback(size)
        lay.addWidget(widget)

    def _build_3d(self):
        if not os.path.exists(MODEL_PATH):
            return None
        try:
            from PyQt6.QtQuickWidgets import QQuickWidget

            model_url = QUrl.fromLocalFile(MODEL_PATH).toString()
            tmp = tempfile.NamedTemporaryFile(
                "w", suffix=".qml", delete=False, encoding="utf-8")
            tmp.write(_build_qml(model_url))
            tmp.close()
            self._qml_path = tmp.name

            view = QQuickWidget()
            view.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
            # Clear to the surrounding card colour (not transparent): a
            # translucent 3D viewport renders as a black box on some drivers,
            # and this way the globe always sits flush on the panel.
            from PyQt6.QtGui import QColor
            view.setClearColor(QColor(Theme.BG_CARD))
            view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            view.setAttribute(Qt.WidgetAttribute.WA_AlwaysStackOnTop)
            view.setStyleSheet("background: transparent;")
            view.setSource(QUrl.fromLocalFile(self._qml_path))

            if view.status() != QQuickWidget.Status.Ready:
                return None

            # `Ready` only means the QML parsed. Qt Quick 3D additionally needs
            # an RHI-based scene graph (a real 3D graphics API). On software
            # rendering — old GPUs, some VMs, remote desktop — View3D silently
            # draws nothing, which left an empty box instead of the logo. So
            # check the actual graphics API and fall back if it can't do 3D.
            if not self._scene_graph_supports_3d(view):
                return None
            return view
        except Exception:
            return None

    @staticmethod
    def _scene_graph_supports_3d(view) -> bool:
        """True only when the scene graph is backed by a real 3D API."""
        try:
            from PyQt6.QtQuick import QSGRendererInterface
            win = view.quickWindow()
            if win is None:
                return False
            rif = win.rendererInterface()
            if rif is None:
                return False
            api = rif.graphicsApi()
            unsupported = {
                QSGRendererInterface.GraphicsApi.Software,
                QSGRendererInterface.GraphicsApi.Unknown,
            }
            return api not in unsupported
        except Exception:
            # If we can't tell, prefer the safe 2D logo over an empty box.
            return False

    def _build_fallback(self, size):
        lbl = QLabel()
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setPixmap(logo_pixmap(int(size * 0.62)))
        lbl.setStyleSheet("background: transparent;")
        return lbl
