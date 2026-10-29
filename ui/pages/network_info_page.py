"""Display detailed IP configuration for a selected network adapter."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.adapter_state import adapter_state
from app.resources import Icons
from app.theme import Theme
from ui.pages.base_page import BasePage
from ui.widgets.card import Card
from ui.widgets.info_table import InfoTable
from workers import OneshotWorker


class NetworkInfoPage(BasePage):
    PAGE_TITLE = "Network Information"
    PAGE_SUBTITLE = "Detailed configuration for each network adapter"
    AI_QUESTION = "Explain my network adapter settings. Is anything misconfigured?"

    def __init__(self, core, parent=None):
        super().__init__(core, parent)

        self._loaded_once = False
        self._current_adapter = None
        self._public_ip = None

        # -- Toolbar: adapter selector + actions --
        toolbar = QHBoxLayout()
        toolbar.setSpacing(10)

        self.adapter_label = QLabel("Adapter: \u2026")
        self.adapter_label.setStyleSheet(
            f"color: {Theme.TEXT_BODY}; font-size: {Theme.FONT_SIZE_SMALL}px; font-weight: 600;")
        toolbar.addWidget(self.adapter_label)
        hint = QLabel("change it in Settings")
        hint.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: {Theme.FONT_SIZE_TINY}px;")
        toolbar.addWidget(hint)
        adapter_state.changed.connect(lambda _n: self._load_adapters())

        toolbar.addStretch()

        self.btn_refresh = self._tool_button("refresh", "Refresh")
        self.btn_refresh.clicked.connect(self._refresh_current)
        toolbar.addWidget(self.btn_refresh)

        self.body_layout.addLayout(toolbar)
        from ui.widgets.ui_kit import InsightRow
        self.findings = InsightRow(self.ask_ai)
        self.body_layout.addWidget(self.findings)
        self._last = None

        # -- Details card with the table --
        self.details_card = Card("Adapter Details", "network")
        self.info_table = InfoTable()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        holder = QWidget()
        holder_lay = QVBoxLayout(holder)
        holder_lay.setContentsMargins(0, 0, 0, 0)
        holder_lay.addWidget(self.info_table)
        holder_lay.addStretch()
        scroll.setWidget(holder)
        self.details_card.content_layout.addWidget(scroll)

        self.body_layout.addWidget(self.details_card, 1)

        # Status line (for copy confirmation etc.)
        self._status = QLabel("")
        self._status.setStyleSheet(
            f"color: {Theme.SUCCESS}; font-size: {Theme.FONT_SIZE_TINY}px;"
        )
        self.body_layout.addWidget(self._status)

    # -- Styling helpers --
    def _combo_style(self):
        return (
            f"QComboBox {{ background: {Theme.BG_ELEVATED}; color: {Theme.TEXT_BODY};"
            f"border: 1px solid {Theme.BORDER_STRONG}; border-radius: 6px;"
            f"padding: 5px 10px; font-size: {Theme.FONT_SIZE_SMALL}px; }}"
            f"QComboBox::drop-down {{ border: none; width: 20px; }}"
            f"QComboBox QAbstractItemView {{ background: {Theme.BG_ELEVATED};"
            f"color: {Theme.TEXT_BODY}; selection-background-color: {Theme.ACCENT};"
            f"border: 1px solid {Theme.BORDER_STRONG}; outline: none; }}"
        )

    def _tool_button(self, icon_name, text):
        btn = QPushButton(text)
        btn.setIcon(Icons.get(icon_name, Theme.TEXT_BODY))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(
            f"QPushButton {{ background: {Theme.BG_ELEVATED}; color: {Theme.TEXT_BODY};"
            f"border: 1px solid {Theme.BORDER_STRONG}; border-radius: 6px;"
            f"padding: 6px 14px; font-size: {Theme.FONT_SIZE_SMALL}px; }}"
            f"QPushButton:hover {{ background: {Theme.BG_CARD_HOVER};"
            f"border-color: {Theme.ACCENT}; }}"
        )
        return btn

    # -- Lifecycle --
    def preload(self):
        # Load adapters and the public IP in the background at startup
        if not self._loaded_once:
            self._loaded_once = True
            self._load_adapters()
            self._load_public_ip()

    def on_enter(self):
        if not self._loaded_once:
            self._loaded_once = True
            self._load_adapters()
            self._load_public_ip()

    # -- Data loading --
    def _resolve_adapter(self):
        # The adapter chosen in Settings, or the active one when set to Auto
        name = adapter_state.get()
        if not name:
            name = self.core.get_network_config().get("adapter", "")
        if not name:
            adapters = self.core.list_adapters()
            adapters = adapters.get("items", adapters) if isinstance(adapters, dict) else adapters
            up = [a for a in adapters or [] if a.get("status") == "Up"]
            name = (up or adapters or [{}])[0].get("name", "")
        return {"name": name}

    def _load_adapters(self):
        self._status.setText("Loading adapters…")
        w = OneshotWorker(self._resolve_adapter)
        w.result.connect(self._on_adapters)
        w.error.connect(lambda e: self._status.setText(self.core.friendly_error(e)))
        self.register_worker(w)
        w.start()

    def _on_adapters(self, data):
        name = data.get("name", "") if isinstance(data, dict) else ""
        if not name:
            self._status.setText("No adapter found")
            return
        self._status.setText("")
        self._current_adapter = name
        self.adapter_label.setText(f"Adapter: {name}")
        self._load_details(name)

    def _load_public_ip(self):
        w = OneshotWorker(self.core.get_public_ip)
        w.result.connect(self._on_public_ip)
        w.error.connect(lambda e: None)
        self.register_worker(w)
        w.start()

    def _on_public_ip(self, data):
        if isinstance(data, dict):
            self._public_ip = data.get("public_ip") or data.get("value") or data.get("ip")
        else:
            self._public_ip = str(data)
        # If a table is already shown, refresh it to include the public IP
        if self._current_adapter:
            self._refresh_current()

    def _load_details(self, name):
        self.info_table.clear()
        self.info_table.add_row("Status", "Loading…", value_color=Theme.TEXT_MUTED)
        w = OneshotWorker(self.core.get_adapter_details, name)
        w.result.connect(self._on_details)
        w.error.connect(lambda e: self._show_error(e))
        self.register_worker(w)
        w.start()

    def _on_details(self, d: dict):
        self.info_table.clear()

        status = d.get("status", "")
        status_color = Theme.SUCCESS if status == "Up" else Theme.TEXT_MUTED

        self.info_table.add_section("Identity")
        self.info_table.add_row("Adapter Name", d.get("name", ""))
        self.info_table.add_row("Description", d.get("description", ""))
        self.info_table.add_row("Status", status, value_color=status_color)
        self.info_table.add_row("Type", "Virtual" if d.get("virtual") else "Physical")

        self.info_table.add_section("Addressing")
        self.info_table.add_row("IPv4 Address", d.get("ipv4", ""), mono=True)
        self.info_table.add_row("Subnet Mask", d.get("subnet_mask", ""), mono=True)
        self.info_table.add_row("Gateway", d.get("gateway", ""), mono=True)
        self.info_table.add_row("DNS Servers", d.get("dns", ""), mono=True)
        if d.get("ipv6"):
            self.info_table.add_row("IPv6 Address", d.get("ipv6", ""), mono=True)
        self.info_table.add_row("DHCP", d.get("dhcp", ""))
        if self._public_ip:
            self.info_table.add_row("Public IP", self._public_ip, mono=True,
                                    value_color=Theme.ACCENT)

        self.info_table.add_section("Hardware")
        self.info_table.add_row("MAC Address", d.get("mac", ""), mono=True)
        self.info_table.add_row("Link Speed", d.get("link_speed", ""))
        self.info_table.add_row("MTU", str(d.get("mtu", "")))

        self._status.setText("")
        self._last = {k: v for k, v in d.items() if k != "mac"}
        self._update_findings(d)

    def _update_findings(self, d):
        items = []
        ip, gw, dns = d.get("ipv4", "") or "", d.get("gateway", "") or "", d.get("dns", "") or ""
        if d.get("status") and d.get("status") != "Up":
            items.append({"severity": "danger", "text": "Adapter is down", "detail": d.get("status"),
                          "question": "My network adapter shows as down. How do I bring it back up?"})
        if ip.startswith("169.254."):
            items.append({"severity": "danger", "text": "No address from the router", "detail": ip,
                          "question": f"My adapter has the address {ip}. Why didn't the router give me an address?"})
        if str(d.get("dhcp", "")).lower() in ("disabled", "no", "false"):
            items.append({"severity": "info", "text": "Static IP", "detail": ip,
                          "question": "My adapter uses a static IP instead of DHCP. Is that set up correctly?"})
        if dns and gw and gw in dns:
            items.append({"severity": "info", "text": "DNS through the router", "detail": dns,
                          "question": "My DNS server is my router. Should I switch to a public DNS like 1.1.1.1?"})
        speed = str(d.get("link_speed", ""))
        if speed in ("10 Mbps", "100 Mbps"):
            items.append({"severity": "warning", "text": f"Link only {speed}", "detail": "",
                          "question": f"My wired link runs at only {speed}. Could the cable or port be the problem?"})
        elif speed:
            items.append({"severity": "success", "text": f"Link {speed}", "detail": "",
                          "question": f"My adapter links at {speed}. Is that the limit of my internet speed?"})
        mtu = str(d.get("mtu", ""))
        if mtu and mtu != "1500":
            items.append({"severity": "info", "text": f"MTU {mtu}", "detail": "",
                          "question": f"My adapter MTU is {mtu}, not 1500. What does that mean?"})
        self.findings.set_items(items)

    def ai_context(self):
        return {"adapter": self._last} if self._last else {}

    def _show_error(self, msg):
        self.info_table.clear()
        self.info_table.add_row(
            "Error", self.core.friendly_error(msg), value_color=Theme.DANGER)

    # -- Actions --
    def _refresh_current(self):
        if self._current_adapter:
            self._load_details(self._current_adapter)
