from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.resources import Icons
from app.theme import Theme
from ui.widgets.sparkline import Sparkline


class StatCard(QFrame):
    # Tint presets for the little icon tile (solid bg, icon color).
    TILE_TINTS = {
        "internet": ("#123528", "#33d6a6"),
        "download": ("#152340", "#5b8cff"),
        "upload":   ("#231c40", "#8b6dff"),
        "packet_loss": ("#123528", "#33d6a6"),
        "uptime":   ("#332916", "#f5b545"),
        "devices":  ("#332916", "#f5b545"),
    }

    def __init__(self, icon_name: str, label: str, spark_color: str = None,
                 tint: str = None, parent=None):
        super().__init__(parent)
        self.setObjectName("StatCard")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet(
            "#StatCard QLabel { background: transparent; border: none; }"
        )

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 12)
        lay.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(9)
        tile_bg, tile_fg = self.TILE_TINTS.get(
            tint or icon_name, (Theme.GLASS_INPUT, Theme.ACCENT))
        self._icon = QLabel()
        self._icon.setFixedSize(34, 34)
        self._icon.setObjectName("StatTile")
        self._icon.setStyleSheet(
            f"#StatTile {{ background: {tile_bg}; border-radius: 10px; }}")
        self._icon_name = icon_name
        self._icon.setPixmap(Icons.pixmap(icon_name, 17, tile_fg))
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top.addWidget(self._icon)
        top.addStretch()
        self._badge = QLabel("")
        self._badge.setStyleSheet("background: transparent; border: none;")
        top.addWidget(self._badge)
        lay.addLayout(top)

        self._value = QLabel("\u2014")
        self._value.setMinimumHeight(32)   # room for the 24px font (was clipped)
        self._value.setStyleSheet(
            f"color: {Theme.TEXT_PRIMARY}; font-size: 24px; font-weight: 700;"
            f"background: transparent; border: none;"
        )
        lay.addWidget(self._value)

        lbl = QLabel(label)
        lbl.setStyleSheet(
            f"color: {Theme.TEXT_SECONDARY}; font-size: {Theme.FONT_SIZE_SMALL}px;"
            f"background: transparent; border: none;"
        )
        lay.addWidget(lbl)

        self._sub = QLabel("")
        self._sub.setStyleSheet(
            f"color: {Theme.TEXT_FAINT}; font-size: {Theme.FONT_SIZE_TINY}px;"
            f"background: transparent; border: none;"
        )
        lay.addWidget(self._sub)

        self.spark = None
        if spark_color:
            self.spark = Sparkline(spark_color)
            lay.addWidget(self.spark)
        else:
            filler = QWidget()
            filler.setFixedHeight(Sparkline.HEIGHT)
            filler.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            filler.setStyleSheet("background: transparent;")
            lay.addWidget(filler)

    def set_badge(self, text: str, positive: bool = True) -> None:
        if not text:
            self._badge.setText("")
            self._badge.setStyleSheet("background: transparent; border: none;")
            return
        if positive:
            bg, fg = "#123528", Theme.SUCCESS
        else:
            bg, fg = "#331d24", Theme.DANGER
        self._badge.setText(f"  {text}  ")
        self._badge.setStyleSheet(
            f"color: {fg}; background: {bg}; border-radius: 7px;"
            f"font-size: 11px; font-weight: 600;")

    def set_tile_tint(self, bg: str, fg: str) -> None:
        """Recolour the icon tile at runtime (e.g. packet loss going from a
        healthy green to amber/red as it climbs)."""
        self._icon.setStyleSheet(
            f"#StatTile {{ background: {bg}; border-radius: 10px; }}")
        self._icon.setPixmap(Icons.pixmap(self._icon_name, 17, fg))

    def set_value(self, value: str, unit: str = "", color: str | None = None,
                  subtitle: str = "") -> None:
        col = color or Theme.TEXT_PRIMARY
        if unit:
            self._value.setText(
                f"<span style='color:{col}; font-family:{Theme.FONT_DATA}; font-size:24px; font-weight:700;'>{value}</span>"
                f" <span style='color:{Theme.TEXT_MUTED}; font-size:13px;'>{unit}</span>"
            )
        else:
            self._value.setText(
                f"<span style='color:{col}; font-family:{Theme.FONT_DATA}; font-size:24px; font-weight:700;'>{value}</span>"
            )
        self._sub.setText(subtitle)

    def push_spark(self, value: float) -> None:
        if self.spark is not None:
            self.spark.push(value)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = Theme.RADIUS_CARD
        path = QPainterPath()
        path.addRoundedRect(r, radius, radius)
        glass = getattr(Theme, "GLASS_ENABLED", True)
        fill = Theme.GLASS_CARD if glass else Theme.BG_CARD
        border = Theme.GLASS_BORDER if glass else Theme.BORDER
        p.fillPath(path, QBrush(QColor(fill)))
        p.setPen(QPen(QColor(border), 1))
        p.drawPath(path)
        p.end()
