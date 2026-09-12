"""
NETWER — DNS Tools page.

A single page that hosts three related tools behind an internal tab bar:
DNS Lookup, Reverse DNS and Traceroute. Each tab embeds the corresponding
tool page (without its own header) inside a stacked view, so switching tabs
is instant and each tool keeps its own workers and lifecycle.

Leaving the page (or switching tabs) stops the active tool's workers.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QPushButton, QStackedWidget, QButtonGroup
)

from app.theme import Theme
from app.resources import Icons
from ui.pages.base_page import BasePage
from ui.pages.dns_lookup_page import DnsLookupPage
from ui.pages.reverse_dns_page import ReverseDnsPage
from ui.pages.traceroute_page import TraceroutePage


class DnsToolsPage(BasePage):
    PAGE_TITLE = "DNS Tools"
    PAGE_SUBTITLE = "Resolve domains, reverse-lookup IPs and trace network paths"

    def __init__(self, core, parent=None):
        super().__init__(core, parent)

        self._tabs_meta = [
            ("DNS Lookup", "dns", DnsLookupPage),
            ("Reverse DNS", "reverse_dns", ReverseDnsPage),
            ("Traceroute", "traceroute", TraceroutePage),
        ]
        self._build_tabs()
        self._build_stack()

    # ── Tab bar ────────────────────────────────────────────────
    def _build_tabs(self):
        row = QHBoxLayout()
        row.setSpacing(8)
        self._tab_group = QButtonGroup(self)
        self._tab_group.setExclusive(True)
        self._tab_buttons = []

        for idx, (label, icon, _cls) in enumerate(self._tabs_meta):
            btn = QPushButton(f"  {label}")
            btn.setIcon(Icons.get(icon, Theme.TEXT_SECONDARY))
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _=False, i=idx: self._switch(i))
            self._tab_buttons.append(btn)
            self._tab_group.addButton(btn, idx)
            row.addWidget(btn)

        row.addStretch()
        self.body_layout.addLayout(row)

    def _style_tab(self, btn, active):
        if active:
            btn.setStyleSheet(
                f"QPushButton {{ background: {Theme.GRAD_ACCENT}; color: white;"
                f"border: none; border-radius: {Theme.RADIUS_CONTROL}px;"
                f"padding: 9px 16px; font-size: {Theme.FONT_SIZE_BODY}px;"
                f"font-weight: 600; text-align: left; }}")
        else:
            btn.setStyleSheet(
                f"QPushButton {{ background: {Theme.GLASS_INPUT};"
                f"color: {Theme.TEXT_SECONDARY};"
                f"border: 1px solid {Theme.GLASS_BORDER};"
                f"border-radius: {Theme.RADIUS_CONTROL}px;"
                f"padding: 9px 16px; font-size: {Theme.FONT_SIZE_BODY}px;"
                f"text-align: left; }}"
                f"QPushButton:hover {{ border-color: {Theme.GLASS_BORDER_HI};"
                f"color: {Theme.TEXT_BODY}; }}")

    # ── Stacked tool panels ────────────────────────────────────
    def _build_stack(self):
        self._stack = QStackedWidget()
        self._panels = []
        for _label, icon, cls in self._tabs_meta:
            panel = cls(self.core, embedded=True)
            panel.set_window(self._window)
            self._panels.append(panel)
            self._stack.addWidget(panel)
        self.body_layout.addWidget(self._stack, 1)

        self._active = 0
        self._switch(0, first=True)

    def _switch(self, index, first=False):
        if not first and index == self._active:
            self._refresh_tab_styles(index)
            return
        # Stop workers on the tab we're leaving.
        if not first:
            self._panels[self._active].on_leave()
        self._active = index
        self._stack.setCurrentIndex(index)
        self._refresh_tab_styles(index)
        self._panels[index].on_enter()

    def _refresh_tab_styles(self, active_index):
        for i, btn in enumerate(self._tab_buttons):
            btn.setChecked(i == active_index)
            self._style_tab(btn, i == active_index)

    # ── Lifecycle ──────────────────────────────────────────────
    def set_window(self, window):
        super().set_window(window)
        # Propagate to child panels (built before window may be set).
        for panel in getattr(self, "_panels", []):
            panel.set_window(window)

    def on_enter(self):
        self._panels[self._active].on_enter()

    def on_leave(self):
        for panel in self._panels:
            panel.on_leave()
        super().on_leave()
