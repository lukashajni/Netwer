"""About page with project information and branding."""

import os
import webbrowser

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from app.resources import Icons
from app.theme import Theme, card_bg, card_border, input_bg
from ui.pages.base_page import BasePage

APP_VERSION = "v5.0"
AUTHOR = "Netwer Team"
TEAM = "Lukas Hajneman, Jan Sven Bukovski and Erik Celjak"
GITHUB_URL = "https://github.com/lukashajni/Netwer"

DESCRIPTION = (
    "NETWER is a free network toolkit for Windows and Linux. It monitors your traffic, finds the "
    "devices on your network, captures and decodes packets like Wireshark, and explains what it "
    "finds in plain language with Netwer AI, so you don't have to be a network engineer to fix it."
)

TECH_STACK = [
    ("Python 3.13", Theme.ACCENT),
    ("PyQt6", Theme.SUCCESS),
    ("PyQtGraph", Theme.ACCENT_PURPLE),
    ("scapy", Theme.WARNING),
    ("ReportLab", Theme.WARNING),
    ("psutil", Theme.ACCENT),
    ("qtawesome", Theme.SUCCESS),
]

FEATURES = [
    ("monitor", "Live monitoring", "Speed, latency and packet loss, recorded while Netwer runs."),
    ("capture", "Packet capture", "Live capture, display filters, streams and .pcap files."),
    ("ai", "Netwer AI", "Reads your results and explains them in your language."),
    ("ping_sweep", "Device discovery", "Every device on your network, with maker and open ports."),
    ("resources", "Network health", "Finds what is wrong: adapter, router, internet or DNS."),
    ("report", "PDF reports", "One click report of your network for school or work."),
]

LICENSES = """NETWER is free software under the GNU GPL v3.

It uses these open-source components:

• PyQt6 — Riverbank Computing (GPL v3 / Commercial)
• PyQtGraph — MIT License
• scapy — GPL v2
• Npcap — Npcap License (installed separately on Windows)
• ReportLab — BSD License
• psutil — BSD License
• qtawesome — MIT License
• Font Awesome — CC BY 4.0
• Material Design Icons — Apache 2.0

Full license texts are available from each project's website."""


class AboutPage(BasePage):
    PAGE_TITLE = "About"
    PAGE_SUBTITLE = "Version, features and the people behind NETWER"

    def __init__(self, core, parent=None):
        super().__init__(core, parent)
        self.body_layout.addWidget(self._build_hero())
        self.body_layout.addLayout(self._build_stats())
        self.body_layout.addLayout(self._build_features())
        self.body_layout.addWidget(self._build_footer())
        self.body_layout.addStretch(1)

    def _build_hero(self):
        hero = QFrame()
        hero.setObjectName("AboutHero")
        hero.setStyleSheet(
            f"#AboutHero {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {Theme.BG_ELEVATED},"
            f"stop:1 {Theme.GLASS_CARD}); border: 1px solid {Theme.GLASS_BORDER_HI};"
            f"border-radius: {Theme.RADIUS_CARD}px; }} #AboutHero QLabel {{ background: transparent; }}")
        lay = QHBoxLayout(hero)
        lay.setContentsMargins(26, 22, 26, 22)
        lay.setSpacing(26)

        brand = QVBoxLayout()
        brand.setSpacing(6)
        logo = QLabel()
        logo.setFixedSize(84, 84)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setPixmap(Icons.pixmap("globe", 42, "#ffffff"))
        logo.setStyleSheet(f"background: {Theme.GRAD_ACCENT}; border-radius: 22px;")
        brand.addWidget(logo, 0, Qt.AlignmentFlag.AlignHCenter)
        name = QLabel("NETWER")
        name.setStyleSheet(f"color: {Theme.TEXT_PRIMARY}; font-size: 22px; font-weight: 700; letter-spacing: 6px;")
        brand.addWidget(name, 0, Qt.AlignmentFlag.AlignHCenter)
        ver = QLabel(f"{APP_VERSION}  ·  Network Diagnostic Suite")
        ver.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: {Theme.FONT_SIZE_TINY}px;")
        brand.addWidget(ver, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addLayout(brand)

        info = QVBoxLayout()
        info.setSpacing(10)
        desc = QLabel(DESCRIPTION)
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {Theme.TEXT_BODY}; font-size: {Theme.FONT_SIZE_BODY}px; line-height: 160%;")
        info.addWidget(desc)
        stack = QHBoxLayout()
        stack.setSpacing(6)
        for tech, color in TECH_STACK:
            stack.addWidget(self._badge(tech, color))
        stack.addStretch()
        info.addLayout(stack)
        info.addStretch()
        lay.addLayout(info, 1)
        return hero

    def _build_stats(self):
        row = QHBoxLayout()
        row.setSpacing(Theme.GAP)
        for label, value in (("Modules", self._count_modules()), ("Lines of code", self._count_lines()),
                             ("Vendor database", self._count_vendors()), ("Pages", str(self._count_pages()))):
            row.addWidget(self._stat_tile(label, value))
        return row

    def _build_features(self):
        grid = QGridLayout()
        grid.setSpacing(Theme.GAP)
        for i, (icon, title, text) in enumerate(FEATURES):
            grid.addWidget(self._feature(icon, title, text), i // 3, i % 3)
        return grid

    def _build_footer(self):
        card = QFrame()
        card.setObjectName("AboutFooter")
        card.setStyleSheet(f"#AboutFooter {{ background: {card_bg()}; border: 1px solid {card_border()};"
                           f"border-radius: {Theme.RADIUS_CARD}px; }} #AboutFooter QLabel {{ background: transparent; }}")
        lay = QHBoxLayout(card)
        lay.setContentsMargins(20, 14, 20, 14)
        lay.setSpacing(8)
        col = QVBoxLayout()
        col.setSpacing(2)
        team = QLabel(f"Made by {TEAM}")
        team.setStyleSheet(f"color: {Theme.TEXT_BODY}; font-size: {Theme.FONT_SIZE_SMALL}px;")
        col.addWidget(team)
        lic = QLabel(f"© 2026 {AUTHOR}  ·  Free software under the GNU GPL v3")
        lic.setStyleSheet(f"color: {Theme.TEXT_FAINT}; font-size: {Theme.FONT_SIZE_TINY}px;")
        col.addWidget(lic)
        lay.addLayout(col)
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
        return card

    def _badge(self, text, color):
        lbl = QLabel(text)
        lbl.setFixedHeight(26)
        lbl.setStyleSheet(
            f"color: {color}; font-size: {Theme.FONT_SIZE_TINY}px; background: {input_bg()};"
            f"border: 1px solid {Theme.GLASS_BORDER}; border-radius: 6px; padding: 4px 10px;")
        return lbl

    def _stat_tile(self, label, value):
        tile = QFrame()
        tile.setObjectName("StatTile")
        tile.setStyleSheet(
            f"#StatTile {{ background: {card_bg()}; border: 1px solid {card_border()};"
            f"border-radius: {Theme.RADIUS_CARD}px; }} #StatTile QLabel {{ background: transparent; border: none; }}")
        lay = QVBoxLayout(tile)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(2)
        label_widget = QLabel(label)
        label_widget.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: {Theme.FONT_SIZE_SMALL}px;")
        lay.addWidget(label_widget)
        v = QLabel(str(value))
        v.setStyleSheet(f"color: {Theme.TEXT_PRIMARY}; font-family: {Theme.FONT_MONO}; font-size: 20px; font-weight: 600;")
        lay.addWidget(v)
        return tile

    def _feature(self, icon, title, text):
        card = QFrame()
        card.setObjectName("Feature")
        card.setStyleSheet(f"#Feature {{ background: {card_bg()}; border: 1px solid {card_border()};"
                           f"border-radius: {Theme.RADIUS_CARD}px; }} #Feature QLabel {{ background: transparent; }}")
        lay = QHBoxLayout(card)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(14)
        ic = QLabel()
        ic.setFixedSize(38, 38)
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ic.setPixmap(Icons.pixmap(icon, 17, Theme.ACCENT))
        ic.setStyleSheet(f"background: {input_bg()}; border: 1px solid {Theme.GLASS_BORDER}; border-radius: 10px;")
        lay.addWidget(ic, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(3)
        t = QLabel(title)
        t.setStyleSheet(f"color: {Theme.TEXT_PRIMARY}; font-size: {Theme.FONT_SIZE_BODY}px; font-weight: 600;")
        col.addWidget(t)
        d = QLabel(text)
        d.setWordWrap(True)
        d.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: {Theme.FONT_SIZE_SMALL}px;")
        col.addWidget(d)
        lay.addLayout(col, 1)
        return card

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

    # -- Footer actions --
    def _dialog_style(self):
        """Return dialog styling, including transparent message labels."""
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
            f"You're running NETWER {APP_VERSION}.\n\n"
            "Update checking isn't connected to the release feed yet. "
            "Releases are published on GitHub.")
        box.setIcon(QMessageBox.Icon.NoIcon)
        box.setStyleSheet(self._dialog_style())
        box.exec()

    # -- Project stats - computed, not hard-coded, so they stay honest --
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
            return "—"

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
            return f"~{total:,}"
        except Exception:
            return "—"

    def _count_vendors(self):
        try:
            return f"{len(self.core.OUI_TABLE)} vendors"
        except Exception:
            return "—"

    def _count_pages(self):
        try:
            root = os.path.join(self._project_root(), "ui", "pages")
            return sum(1 for f in os.listdir(root)
                       if f.endswith("_page.py") and f != "base_page.py")
        except Exception:
            return "—"
