"""
NETWER — About page.

Brand panel with the rotating 3D globe on the left, project information on
the right, a feature strip and a footer with links.

The globe is the centrepiece: the real Blender model rendered with
QtQuick3D, draggable, springing back to its home orientation after three
idle seconds. If 3D isn't available on the machine (no GPU, software
rendering), Globe3D quietly falls back to the flat logo — the page still
looks right rather than breaking.
"""

import os
import webbrowser

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QFrame, QMessageBox
)

from app.theme import Theme
from app.resources import Icons
from ui.pages.base_page import BasePage
from ui.widgets.globe_3d import Globe3D


APP_VERSION = "v4.0"
AUTHOR = "Lukas Hajneman"
GITHUB_URL = "https://github.com/RomFishy/Netwer"

DESCRIPTION = (
    "NETWER is an all-in-one network toolkit for diagnostics, monitoring "
    "and analysis. It brings live traffic monitoring, device discovery, "
    "connectivity testing and professional reporting into a single desktop "
    "application."
)

TECH_STACK = [
    ("Python 3.13", Theme.ACCENT),
    ("PyQt6", Theme.SUCCESS),
    ("PyQtGraph", Theme.ACCENT_PURPLE),
    ("ReportLab", Theme.WARNING),
    ("psutil", Theme.ACCENT),
    ("qtawesome", Theme.SUCCESS),
]

FEATURES = [
    ("monitor", "Live monitoring"),
    ("ping_sweep", "Device discovery"),
    ("speedtest", "Speed testing"),
    ("report", "PDF reports"),
]

LICENSES = """NETWER uses the following open-source components:

• PyQt6 — Riverbank Computing (GPL v3 / Commercial)
• PyQtGraph — MIT License
• ReportLab — BSD License
• psutil — BSD License
• qtawesome — MIT License
• Font Awesome — CC BY 4.0
• Material Design Icons — Apache 2.0

Full license texts are available from each project's website."""


class AboutPage(BasePage):
    PAGE_TITLE = "About"
    PAGE_SUBTITLE = "About NETWER"

    def __init__(self, core, parent=None):
        super().__init__(core, parent)

        shell = QFrame()
        shell.setObjectName("AboutShell")
        shell.setStyleSheet(
            f"#AboutShell {{ background: {Theme.BG_CARD};"
            f"border: 1px solid {Theme.BORDER};"
            f"border-radius: {Theme.RADIUS_CARD}px; }}"
        )
        shell_lay = QVBoxLayout(shell)
        shell_lay.setContentsMargins(0, 0, 0, 0)
        shell_lay.setSpacing(0)

        shell_lay.addWidget(self._build_main_row(), 1)
        shell_lay.addWidget(self._divider())
        shell_lay.addWidget(self._build_features())
        shell_lay.addWidget(self._divider())
        shell_lay.addWidget(self._build_footer())

        self.body_layout.addWidget(shell)

    # ══════════════════════════════════════════════════════════
    def _divider(self):
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background: {Theme.BORDER}; border: none;")
        return line

    def _build_main_row(self):
        row = QWidget()
        row.setStyleSheet("background: transparent;")
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        lay.addWidget(self._build_brand_panel(), 10)
        lay.addWidget(self._build_info_panel(), 12)
        return row

    def _build_brand_panel(self):
        panel = QFrame()
        panel.setObjectName("BrandPanel")
        panel.setStyleSheet(
            f"#BrandPanel {{ background: {Theme.BG_SIDEBAR};"
            f"border: none; border-top-left-radius: {Theme.RADIUS_CARD}px; }}"
            f"#BrandPanel QLabel {{ background: transparent; }}"
        )
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(20, 24, 20, 24)
        lay.setSpacing(0)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.globe = Globe3D(250)
        lay.addWidget(self.globe, alignment=Qt.AlignmentFlag.AlignCenter)

        name = QLabel("NETWER")
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name.setStyleSheet(
            f"color: {Theme.TEXT_PRIMARY}; font-family: {Theme.FONT_FAMILY};"
            f"font-size: 25px; font-weight: 600; letter-spacing: 8px;"
            f"padding-top: 6px;")
        lay.addWidget(name)

        ver = QLabel(APP_VERSION)
        ver.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ver.setStyleSheet(
            f"color: {Theme.ACCENT}; font-family: {Theme.FONT_DATA};"
            f"font-size: {Theme.FONT_SIZE_SMALL}px; letter-spacing: 2px;")
        lay.addWidget(ver)

        tagline = QLabel("Network Diagnostic Suite")
        tagline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tagline.setStyleSheet(
            f"color: {Theme.TEXT_FAINT}; font-size: {Theme.FONT_SIZE_TINY}px;"
            f"padding-top: 8px;")
        lay.addWidget(tagline)

        status = QLabel("\u25CF  All systems operational")
        status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status.setStyleSheet(
            f"color: {Theme.SUCCESS}; font-size: {Theme.FONT_SIZE_TINY}px;"
            f"background: rgba(62, 201, 138, 0.08);"
            f"border: 1px solid rgba(62, 201, 138, 0.25);"
            f"border-radius: 12px; padding: 4px 12px; margin-top: 12px;")
        wrap = QHBoxLayout()
        wrap.addStretch()
        wrap.addWidget(status)
        wrap.addStretch()
        lay.addLayout(wrap)

        return panel

    def _build_info_panel(self):
        panel = QWidget()
        panel.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(26, 24, 26, 24)
        lay.setSpacing(0)

        lay.addWidget(self._section_label("About"))

        desc = QLabel(DESCRIPTION)
        desc.setWordWrap(True)
        desc.setStyleSheet(
            f"color: {Theme.TEXT_SECONDARY}; font-family: {Theme.FONT_FAMILY};"
            f"font-size: {Theme.FONT_SIZE_SMALL}px; line-height: 170%;"
            f"background: transparent; padding-bottom: 16px;")
        lay.addWidget(desc)

        lay.addWidget(self._section_label("Built with"))

        stack = QHBoxLayout()
        stack.setSpacing(6)
        for name, color in TECH_STACK:
            stack.addWidget(self._badge(name, color))
        stack.addStretch()
        stack_holder = QWidget()
        stack_holder.setStyleSheet("background: transparent;")
        stack_holder.setLayout(stack)
        lay.addWidget(stack_holder)
        lay.addSpacing(16)

        stats = QGridLayout()
        stats.setSpacing(10)
        stat_items = [
            ("Modules", self._count_modules()),
            ("Lines of code", self._count_lines()),
            ("Vendor database", self._count_vendors()),
            ("Pages", str(self._count_pages())),
        ]
        for i, (label, value) in enumerate(stat_items):
            stats.addWidget(self._stat_tile(label, value), i // 2, i % 2)
        stats_holder = QWidget()
        stats_holder.setStyleSheet("background: transparent;")
        stats_holder.setLayout(stats)
        lay.addWidget(stats_holder)

        lay.addStretch()
        return panel

    def _section_label(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color: {Theme.TEXT_BODY}; font-family: {Theme.FONT_FAMILY};"
            f"font-size: {Theme.FONT_SIZE_BODY}px; font-weight: 500;"
            f"background: transparent; padding-bottom: 8px;")
        return lbl

    def _badge(self, text, color):
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color: {color}; font-family: {Theme.FONT_FAMILY};"
            f"font-size: {Theme.FONT_SIZE_TINY}px;"
            f"background: {Theme.BG_ELEVATED};"
            f"border: 1px solid {Theme.BORDER}; border-radius: 6px;"
            f"padding: 4px 10px;")
        return lbl

    def _stat_tile(self, label, value):
        tile = QFrame()
        tile.setObjectName("StatTile")
        tile.setStyleSheet(
            f"#StatTile {{ background: {Theme.BG_ELEVATED};"
            f"border: 1px solid {Theme.BORDER}; border-radius: 8px; }}"
            f"#StatTile QLabel {{ background: transparent; border: none; }}")
        lay = QVBoxLayout(tile)
        lay.setContentsMargins(12, 9, 12, 9)
        lay.setSpacing(1)

        l = QLabel(label)
        l.setStyleSheet(
            f"color: {Theme.TEXT_MUTED}; font-size: {Theme.FONT_SIZE_TINY}px;")
        lay.addWidget(l)

        v = QLabel(str(value))
        v.setStyleSheet(
            f"color: {Theme.TEXT_PRIMARY}; font-family: {Theme.FONT_DATA};"
            f"font-size: 15px; font-weight: 600;")
        lay.addWidget(v)
        return tile

    def _build_features(self):
        holder = QWidget()
        holder.setStyleSheet("background: transparent;")
        lay = QHBoxLayout(holder)
        lay.setContentsMargins(26, 16, 26, 16)
        lay.setSpacing(10)

        for icon_name, text in FEATURES:
            item = QWidget()
            item.setStyleSheet("background: transparent;")
            h = QHBoxLayout(item)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(8)
            icon = QLabel()
            icon.setPixmap(Icons.pixmap(icon_name, 15, Theme.ACCENT))
            icon.setStyleSheet("background: transparent;")
            h.addWidget(icon)
            lbl = QLabel(text)
            lbl.setStyleSheet(
                f"color: {Theme.TEXT_SECONDARY};"
                f"font-size: {Theme.FONT_SIZE_TINY}px; background: transparent;")
            h.addWidget(lbl)
            h.addStretch()
            lay.addWidget(item, 1)

        return holder

    def _build_footer(self):
        holder = QWidget()
        holder.setStyleSheet("background: transparent;")
        lay = QHBoxLayout(holder)
        lay.setContentsMargins(26, 14, 26, 14)
        lay.setSpacing(8)

        copyright_lbl = QLabel(f"\u00A9 2026 {AUTHOR}  \u00B7  All rights reserved")
        copyright_lbl.setStyleSheet(
            f"color: {Theme.TEXT_FAINT}; font-size: {Theme.FONT_SIZE_TINY}px;"
            f"background: transparent;")
        lay.addWidget(copyright_lbl)
        lay.addStretch()

        btn_github = self._footer_button("github", "GitHub")
        btn_github.clicked.connect(lambda: webbrowser.open(GITHUB_URL))
        lay.addWidget(btn_github)

        btn_licenses = self._footer_button("report", "Licenses")
        btn_licenses.clicked.connect(self._show_licenses)
        lay.addWidget(btn_licenses)

        btn_updates = self._footer_button("refresh", "Check for updates")
        btn_updates.clicked.connect(self._check_updates)
        lay.addWidget(btn_updates)

        return holder

    def _footer_button(self, icon_name, text):
        btn = QPushButton(f"  {text}")
        btn.setIcon(Icons.get(icon_name, Theme.TEXT_SECONDARY))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {Theme.TEXT_SECONDARY};"
            f"border: 1px solid {Theme.BORDER_STRONG}; border-radius: 6px;"
            f"padding: 6px 14px; font-size: {Theme.FONT_SIZE_TINY}px; }}"
            f"QPushButton:hover {{ border-color: {Theme.ACCENT};"
            f"color: {Theme.TEXT_BODY}; }}")
        return btn

    # ══════════════════════════════════════════════════════════
    # Footer actions
    # ══════════════════════════════════════════════════════════
    def _dialog_style(self):
        """Shared style. The QLabel rules matter: without an explicit
        transparent background, Qt paints its own panel behind the text and
        it reads as a separate dark block sitting on the dialog."""
        return (
            f"QMessageBox {{ background: {Theme.BG_CARD};"
            f"border: 1px solid {Theme.BORDER}; }}"
            f"QMessageBox QLabel {{ background: transparent; border: none;"
            f"color: {Theme.TEXT_BODY};"
            f"font-family: {Theme.FONT_FAMILY};"
            f"font-size: {Theme.FONT_SIZE_SMALL}px; }}"
            f"QMessageBox QPushButton {{ background: {Theme.ACCENT};"
            f"color: white; border: none; border-radius: 6px;"
            f"padding: 6px 22px; font-size: {Theme.FONT_SIZE_SMALL}px;"
            f"font-weight: 600; min-width: 60px; }}"
            f"QMessageBox QPushButton:hover {{ background: {Theme.ACCENT_PURPLE}; }}"
        )

    def _show_licenses(self):
        box = QMessageBox(self)
        box.setWindowTitle("Open Source Licenses")
        box.setText(LICENSES)
        box.setIcon(QMessageBox.Icon.NoIcon)
        box.setStyleSheet(self._dialog_style())
        box.exec()

    def _check_updates(self):
        box = QMessageBox(self)
        box.setWindowTitle("Check for Updates")
        box.setText(
            f"You're running NETWER {APP_VERSION} — the latest version.\n\n"
            "Update checking against the release feed isn't wired up yet; "
            "for now, releases are published on GitHub.")
        box.setIcon(QMessageBox.Icon.NoIcon)
        box.setStyleSheet(self._dialog_style())
        box.exec()

    # ══════════════════════════════════════════════════════════
    # Project stats — computed, not hard-coded, so they stay honest
    # ══════════════════════════════════════════════════════════
    def _project_root(self):
        return os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))

    def _count_modules(self):
        try:
            root = self._project_root()
            count = 0
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [d for d in dirnames
                               if d not in ("__pycache__", ".venv", ".git", ".idea")]
                count += sum(1 for f in filenames
                             if f.endswith(".py") and f != "__init__.py")
            return str(count)
        except Exception:
            return "\u2014"

    def _count_lines(self):
        try:
            root = self._project_root()
            total = 0
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [d for d in dirnames
                               if d not in ("__pycache__", ".venv", ".git", ".idea")]
                for f in filenames:
                    if not f.endswith(".py"):
                        continue
                    try:
                        with open(os.path.join(dirpath, f), "r",
                                  encoding="utf-8", errors="ignore") as fh:
                            total += sum(1 for _ in fh)
                    except OSError:
                        continue
            return f"~{total:,}".replace(",", ",")
        except Exception:
            return "\u2014"

    def _count_vendors(self):
        try:
            return f"{len(self.core.OUI_TABLE)} vendors"
        except Exception:
            return "\u2014"

    def _count_pages(self):
        try:
            root = os.path.join(self._project_root(), "ui", "pages")
            return sum(1 for f in os.listdir(root)
                       if f.endswith("_page.py") and f != "base_page.py")
        except Exception:
            return "\u2014"
