"""
NETWER — StatCard widget.

Card for one key metric (Internet Status, Download, Upload, Packet Loss,
Uptime — the dashboard's top row). Real qtawesome icon, modern data font,
and an optional sparkline (mini trend chart) at the bottom like the mockup.
"""

from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QPainter, QColor, QBrush, QPen, QPainterPath
from PyQt6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel, QWidget

from app.theme import Theme
from app.resources import Icons
from ui.widgets.sparkline import Sparkline


class StatCard(QFrame):
    #: Tint presets for the little icon tile (solid bg, icon color).
    TILE_TINTS = {
        "internet": ("#123528", "#33d6a6"),
        "download": ("#152340", "#5b8cff"),
        "upload":   ("#231c40", "#8b6dff"),
        # The card is built with icon_name="packet_loss", so the key has to
        # match exactly — the old "packet" key never hit and the tile silently
        # fell back to the default blue.
        # Packet loss is GREEN while healthy; the dashboard recolours the tile
        # to amber/red only when loss actually rises.
        "packet_loss": ("#123528", "#33d6a6"),
        "packet":   ("#123528", "#33d6a6"),
        "uptime":   ("#332916", "#f5b545"),
        "devices":  ("#332916", "#f5b545"),
    }

    def __init__(self, icon_name: str, label: str, spark_color: str = None,
                 tint: str = None, parent=None):
        super().__init__(parent)
        self.setObjectName("StatCard")
        # We paint the card background ourselves in paintEvent (below) rather
        # than via a stylesheet. A stylesheet background on the frame doesn't
        # paint behind transparent child widgets (the sparkline), which left a
        # dark app-coloured band across the card. Painting it ourselves fills
        # the whole rounded rect under every child.
        self.setStyleSheet(
            "#StatCard QLabel { background: transparent; border: none; }"
        )

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 12)
        lay.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(9)
        # Colored icon tile (like the preview).
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
        # Trend badge (e.g. ↑12%). Kept in the layout at all times (empty +
        # transparent when unused) so it's always positioned correctly — a
        # hidden, never-laid-out label kept painting a stray box.
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

        # Sparkline at the bottom. Cards WITHOUT one still reserve the same
        # vertical space, so the header/value text lines up across every card
        # in the row (otherwise a no-sparkline card sits lower than the rest).
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
        """Show a small trend badge in the top-right (e.g. '↑ 12%')."""
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
        """Add a point to the sparkline (if this card has one)."""
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
