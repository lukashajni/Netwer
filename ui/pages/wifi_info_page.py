"""Display Wi-Fi connection details and scan nearby networks."""

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.activity import activity
from app.resources import Icons
from app.theme import Theme
from ui.pages.base_page import BasePage
from ui.widgets.card import Card, kv_row
from ui.widgets.channel_analyzer import ChannelAnalyzer
from ui.widgets.signal_bars import SignalBars, dbm_to_percent, signal_color, signal_quality
from ui.widgets.wifi_signal import WiFiSignal
from workers import OneshotWorker


class WiFiInfoPage(BasePage):
    PAGE_TITLE = "WiFi Information"
    PAGE_SUBTITLE = "Wireless connection details and signal quality"
    AI_QUESTION = "How good is my Wi-Fi connection, and how can I improve it?"

    def __init__(self, core, parent=None):
        super().__init__(core, parent)

        self._connected = False
        self._scan_worker = None
        self._info_worker = None
        self._last_scan_time = None

        # Live refresh of the connection info (adapter plugged in, roaming...)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(4000)
        self._refresh_timer.timeout.connect(self._refresh_info)

        # Keeps the "last scan: 2m ago" label current
        self._scan_label_timer = QTimer(self)
        self._scan_label_timer.setInterval(15000)
        self._scan_label_timer.timeout.connect(self._update_last_scan_label)

        self._build_headline_row()
        from ui.widgets.ui_kit import InsightRow
        self.findings = InsightRow(self.ask_ai)
        self.body_layout.addWidget(self.findings)
        self._build_detail_row()
        self.analyzer = ChannelAnalyzer()
        self.analyzer.rescan_requested.connect(self._scan_networks)
        self.body_layout.addWidget(self.analyzer)
        self._auto_scanned = False

        self.body_layout.addStretch(1)

    # -- UI -- 
    def _build_headline_row(self):
        row = QHBoxLayout()
        row.setSpacing(Theme.GAP)
        CARD_H = 88

        # Signal strength (icon + verdict)
        self.signal_card = Card("", "")
        self.signal_card.setFixedHeight(CARD_H)
        sig_body = QHBoxLayout()
        sig_body.setSpacing(12)
        self.signal_glyph = WiFiSignal(58)
        self.signal_glyph.set_disconnected()
        sig_body.addWidget(self.signal_glyph)

        sig_text = QVBoxLayout()
        sig_text.setSpacing(1)
        sig_label = QLabel("Signal Strength")
        sig_label.setStyleSheet(
            f"color: {Theme.TEXT_SECONDARY}; font-size: {Theme.FONT_SIZE_TINY}px;"
            f"background: transparent;")
        sig_text.addWidget(sig_label)
        self.signal_verdict = QLabel("—")
        self.signal_verdict.setStyleSheet(
            f"color: {Theme.TEXT_MUTED}; font-family: {Theme.FONT_DATA};"
            f"font-size: 19px; font-weight: 600; background: transparent;")
        sig_text.addWidget(self.signal_verdict)
        self.signal_detail = QLabel("Not connected")
        self.signal_detail.setStyleSheet(
            f"color: {Theme.TEXT_FAINT}; font-size: {Theme.FONT_SIZE_TINY}px;"
            f"background: transparent;")
        sig_text.addWidget(self.signal_detail)
        sig_body.addLayout(sig_text)
        sig_body.addStretch()
        self.signal_card.content_layout.addLayout(sig_body)
        row.addWidget(self.signal_card, 12)

        self.card_network = self._stat_card("wifi", "Network", CARD_H)
        row.addWidget(self.card_network["card"], 9)

        self.card_band = self._stat_card("monitor", "Band / Channel", CARD_H)
        row.addWidget(self.card_band["card"], 9)

        self.card_security = self._stat_card("check", "Security", CARD_H)
        row.addWidget(self.card_security["card"], 9)

        self.body_layout.addLayout(row)

    def _stat_card(self, icon_name, label, height):
        card = Card("", "")
        card.setFixedHeight(height)
        top = QHBoxLayout()
        top.setSpacing(6)
        icon = QLabel()
        icon.setPixmap(Icons.pixmap(icon_name, 13, Theme.TEXT_SECONDARY))
        icon.setStyleSheet("background: transparent;")
        top.addWidget(icon)
        lbl = QLabel(label)
        lbl.setStyleSheet(
            f"color: {Theme.TEXT_SECONDARY}; font-size: {Theme.FONT_SIZE_TINY}px;"
            f"background: transparent;")
        top.addWidget(lbl)
        top.addStretch()
        card.content_layout.addLayout(top)

        value = QLabel("—")
        value.setStyleSheet(
            f"color: {Theme.TEXT_MUTED}; font-family: {Theme.FONT_DATA};"
            f"font-size: 16px; font-weight: 600; background: transparent;")
        card.content_layout.addWidget(value)

        sub = QLabel("")
        sub.setStyleSheet(
            f"color: {Theme.TEXT_FAINT}; font-size: {Theme.FONT_SIZE_TINY}px;"
            f"background: transparent;")
        card.content_layout.addWidget(sub)
        card.content_layout.addStretch()

        return {"card": card, "value": value, "sub": sub}

    def _build_detail_row(self):
        row = QHBoxLayout()
        row.setSpacing(Theme.GAP)
        DETAIL_H = 300

        # -- Connection details --
        self.details_card = Card("Connection Details", "summary")
        self.details_card.setFixedHeight(DETAIL_H)
        self._detail_values = {}
        for key in ("SSID", "BSSID", "Signal", "Band", "Channel",
                    "Radio Type", "Authentication", "Cipher", "Link Speed"):
            mono = key in ("BSSID", "Signal", "Channel", "Link Speed")
            container, lbl = kv_row(key, "\u2014", mono=mono)
            self._detail_values[key] = lbl
            self.details_card.content_layout.addWidget(container)
        self.details_card.content_layout.addStretch()
        row.addWidget(self.details_card, 10)

        # -- Available networks --
        self.networks_card = Card("Available Networks", "ping_sweep")
        self.networks_card.setFixedHeight(DETAIL_H)

        # "Last scan" indicator, updated live so it reads "2m ago"
        self.last_scan_label = QLabel("Never scanned")
        self.last_scan_label.setStyleSheet(
            f"color: {Theme.TEXT_FAINT}; font-size: {Theme.FONT_SIZE_TINY}px;"
            f"background: transparent;")
        self.networks_card.header_layout.addWidget(self.last_scan_label)

        self.btn_scan = QPushButton("  Scan")
        self.btn_scan.setIcon(Icons.get("refresh", Theme.TEXT_BODY))
        self.btn_scan.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_scan.setStyleSheet(
            f"QPushButton {{ background: {Theme.BG_ELEVATED}; color: {Theme.TEXT_BODY};"
            f"border: 1px solid {Theme.BORDER_STRONG}; border-radius: 6px;"
            f"padding: 4px 12px; font-size: {Theme.FONT_SIZE_TINY}px; }}"
            f"QPushButton:hover {{ border-color: {Theme.ACCENT}; }}"
            f"QPushButton:disabled {{ color: {Theme.TEXT_FAINT}; }}")
        self.btn_scan.clicked.connect(self._scan_networks)
        self.networks_card.header_layout.addWidget(self.btn_scan)

        # Column header
        header = QWidget()
        header.setStyleSheet("background: transparent;")
        h = QHBoxLayout(header)
        h.setContentsMargins(0, 0, 0, 4)
        h.setSpacing(8)
        for text, width in (("", 30), ("SSID", 0), ("Band", 60),
                            ("Ch", 34), ("Security", 74), ("Signal", 60)):
            lbl = QLabel(text)
            lbl.setStyleSheet(
                f"color: {Theme.TEXT_FAINT}; font-size: 10px; background: transparent;")
            if width:
                lbl.setFixedWidth(width)
                if text == "Signal":
                    lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
                h.addWidget(lbl)
            else:
                h.addWidget(lbl, 1)
        self.networks_card.content_layout.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent; border: none;")
        holder = QWidget()
        holder.setStyleSheet("background: transparent;")
        self._net_list = QVBoxLayout(holder)
        self._net_list.setContentsMargins(0, 0, 0, 0)
        self._net_list.setSpacing(0)
        self._net_placeholder = QLabel("Click Scan to search for nearby networks")
        self._net_placeholder.setStyleSheet(
            f"color: {Theme.TEXT_MUTED}; font-size: {Theme.FONT_SIZE_SMALL}px;"
            f"background: transparent; padding: 8px 0;")
        self._net_list.addWidget(self._net_placeholder)
        self._net_list.addStretch()
        scroll.setWidget(holder)
        self.networks_card.content_layout.addWidget(scroll)

        row.addWidget(self.networks_card, 15)
        self.body_layout.addLayout(row)

    # -- Lifecycle --
    def preload(self):
        # Load the WiFi info once in the background at startup 
        self._refresh_info()

    def on_enter(self):
        self._refresh_info()
        self._refresh_timer.start()
        self._scan_label_timer.start()
        self._update_last_scan_label()

    def on_leave(self):
        self._refresh_timer.stop()
        self._scan_label_timer.stop()
        super().on_leave()

    def _update_last_scan_label(self):
        if self._last_scan_time is None:
            self.last_scan_label.setText("Never scanned")
            return
        from app.activity import time_ago
        self.last_scan_label.setText(f"Last scan: {time_ago(self._last_scan_time)}")

    # -- Connection info --
    def _refresh_info(self):
        if self._info_worker is not None and self._info_worker.isRunning():
            return
        w = OneshotWorker(self.core.get_wifi_info)
        w.result.connect(self._on_wifi)
        w.error.connect(lambda e: self._set_disconnected())
        self._info_worker = w
        w.start()

    def _on_wifi(self, d: dict):
        if not d or not d.get("ssid") or d.get("ssid") in ("Unknown", ""):
            self._set_disconnected()
            return

        self._connected = True
        signal_raw = d.get("signal", "")
        dbm = self._parse_dbm(signal_raw)
        pct = dbm_to_percent(dbm) if dbm is not None else self._parse_pct(signal_raw)

        # Headline: signal
        if dbm is not None:
            self.signal_glyph.set_signal(pct)
            color = signal_color(dbm)
            self.signal_verdict.setText(signal_quality(dbm))
            self.signal_verdict.setStyleSheet(
                f"color: {color}; font-family: {Theme.FONT_DATA};"
                f"font-size: 19px; font-weight: 600; background: transparent;")
            self.signal_detail.setText(f"{dbm} dBm · {pct}%")
        else:
            self.signal_glyph.set_signal(pct)
            self.signal_verdict.setText(f"{pct}%")
            self.signal_verdict.setStyleSheet(
                f"color: {Theme.SUCCESS}; font-family: {Theme.FONT_DATA};"
                f"font-size: 19px; font-weight: 600; background: transparent;")
            self.signal_detail.setText(str(signal_raw))

        # Headline: network / band / security
        self._set_stat(self.card_network, d.get("ssid", "\u2014"), "Connected",
                       Theme.TEXT_PRIMARY, Theme.SUCCESS)
        channel = d.get("channel", "")
        band = d.get("band", "")
        band_short = next((b for b in ("2.4 GHz", "5 GHz", "6 GHz") if b in band), band)
        ch_text = "" if channel in ("", "\u2014") else channel
        self._set_stat(self.card_band,
                       f"{band_short}" + (f"  ch {ch_text}" if ch_text else ""),
                       d.get("radio", ""), Theme.ACCENT)
        auth = d.get("auth", "\u2014")
        self._set_stat(self.card_security, auth,
                       f"{d.get('cipher', '')} cipher" if d.get("cipher") else "",
                       Theme.SUCCESS)

        # Detail table
        self._set_detail("SSID", d.get("ssid"))
        self._set_detail("BSSID", d.get("bssid"))
        self._set_detail("Signal", signal_raw)
        self._set_detail("Band", band)
        self._set_detail("Channel", channel)
        self._set_detail("Radio Type", d.get("radio"))
        self._set_detail("Authentication", auth)
        self._set_detail("Cipher", d.get("cipher"))
        self._set_detail("Link Speed", d.get("link_speed"))
        self._update_findings(dbm, pct, band_short, auth)

        # Channel Analyzer: knows which access point is yours and scans once automatically
        self.analyzer.set_connection(d.get("bssid", ""), channel, band_short)
        if not self._auto_scanned and self._last_scan_time is None:
            self._auto_scanned = True
            QTimer.singleShot(500, self._scan_networks)

    def _update_findings(self, dbm, pct, band, auth):
        items = []
        if pct is not None:
            weak = (dbm is not None and dbm < -70) or pct < 45
            items.append({"severity": "warning" if weak else "success",
                          "text": "Weak signal" if weak else "Good signal", "detail": f"{pct}%",
                          "question": f"My Wi-Fi signal is {pct}%" + (f" ({dbm} dBm)" if dbm is not None else "")
                                      + ". Is that good enough, and how can I improve it?"})
        if band.startswith("2.4"):
            items.append({"severity": "info", "text": "2.4 GHz band", "detail": "",
                          "question": "I'm on the 2.4 GHz Wi-Fi band. Would 5 GHz be faster for me?"})
        a = (auth or "").upper()
        if a and ("OPEN" in a or "WEP" in a or a == "WPA-PERSONAL"):
            items.append({"severity": "danger", "text": "Weak Wi-Fi security", "detail": auth,
                          "question": f"My Wi-Fi uses {auth}. Is that safe, and what should I switch to?"})
        self.findings.set_items(items)

    def _set_disconnected(self):
        self._connected = False
        self.analyzer.set_connection("", None, "")
        self.signal_glyph.set_disconnected()
        self.signal_verdict.setText("No WiFi")
        self.signal_verdict.setStyleSheet(
            f"color: {Theme.TEXT_MUTED}; font-family: {Theme.FONT_DATA};"
            f"font-size: 19px; font-weight: 600; background: transparent;")
        self.signal_detail.setText("Adapter off or wired connection")
        self.findings.set_items([{"severity": "info", "text": "Not on Wi-Fi", "detail": "wired or adapter off",
                                  "question": "My PC is not on Wi-Fi right now. Is a wired connection better, and when should I use Wi-Fi?"}])

        for card in (self.card_network, self.card_band, self.card_security):
            self._set_stat(card, "\u2014", "", Theme.TEXT_MUTED)
        for key in self._detail_values:
            self._set_detail(key, "\u2014")

    def _set_stat(self, card, value, sub, color, sub_color=None):
        card["value"].setText(str(value))
        card["value"].setStyleSheet(
            f"color: {color}; font-family: {Theme.FONT_DATA};"
            f"font-size: 16px; font-weight: 600; background: transparent;")
        card["sub"].setText(str(sub))
        card["sub"].setStyleSheet(
            f"color: {sub_color or Theme.TEXT_FAINT};"
            f"font-size: {Theme.FONT_SIZE_TINY}px; background: transparent;")

    def _set_detail(self, key, value):
        lbl = self._detail_values.get(key)
        if lbl:
            lbl.setText(str(value) if value else "\u2014")

    @staticmethod
    def _parse_dbm(text):
        import re
        m = re.search(r'(-?\d+)\s*dBm', str(text), re.IGNORECASE)
        return int(m.group(1)) if m else None

    @staticmethod
    def _parse_pct(text):
        import re
        m = re.search(r'(\d+)\s*%', str(text))
        return int(m.group(1)) if m else 50

    # -- Nearby networks scan --
    def _scan_networks(self):
        if self._scan_worker is not None and self._scan_worker.isRunning():
            return
        self.btn_scan.setEnabled(False)
        self.analyzer.set_scanning(True)
        self._clear_networks()
        self._net_placeholder.setText("Scanning for networks…")
        self._net_placeholder.show()

        w = OneshotWorker(self.core.scan_wifi_networks)
        w.result.connect(self._on_networks)
        w.error.connect(lambda e: self._net_placeholder.setText(f"Scan failed: {e}"))
        w.done.connect(lambda: (self.btn_scan.setEnabled(True), self.analyzer.set_scanning(False)))
        self.register_worker(w)
        self._scan_worker = w
        w.start()

    def _clear_networks(self):
        while self._net_list.count() > 1:
            item = self._net_list.takeAt(0)
            wdg = item.widget()
            if wdg and wdg is not self._net_placeholder:
                wdg.deleteLater()
        if self._net_placeholder.parent() is None:
            self._net_list.insertWidget(0, self._net_placeholder)

    def _on_networks(self, data: dict):
        import time
        self._last_scan_time = time.time()
        self._update_last_scan_label()

        self.analyzer.set_scan(data.get("aps", []))
        networks = data.get("networks", [])
        if not networks:
            self._net_placeholder.setText("No networks found")
            return

        self._net_placeholder.hide()
        current_ssid = self._detail_values["SSID"].text()

        for net in networks:
            idx = self._net_list.count() - 1
            self._net_list.insertWidget(
                idx, self._network_row(net, is_current=(net["ssid"] == current_ssid)))

        activity.add("WiFi scan completed",
                     f"{len(networks)} networks found", kind="success")

    def _network_row(self, net: dict, is_current: bool) -> QWidget:
        w = QWidget()
        w.setStyleSheet(
            f"background: transparent; border-bottom: 1px solid {Theme.BORDER};")
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 6, 0, 6)
        row.setSpacing(8)

        dbm = net.get("signal_dbm", -100)

        bars = SignalBars(dbm)
        bars_holder = QWidget()
        bars_holder.setFixedWidth(30)
        bars_holder.setStyleSheet("background: transparent;")
        bh = QHBoxLayout(bars_holder)
        bh.setContentsMargins(0, 0, 0, 0)
        bh.addWidget(bars)
        row.addWidget(bars_holder)

        ssid_text = net.get("ssid", "")
        if is_current:
            ssid_text += "  · connected"
        ssid = QLabel(ssid_text)
        ssid.setStyleSheet(
            f"color: {Theme.SUCCESS if is_current else Theme.TEXT_BODY};"
            f"font-family: {Theme.FONT_DATA}; font-size: {Theme.FONT_SIZE_SMALL}px;"
            f"font-weight: {'600' if is_current else '400'};"
            f"background: transparent; border: none;")
        row.addWidget(ssid, 1)

        for text, width in ((net.get("band", ""), 60),
                            (net.get("channel", ""), 34),
                            (net.get("auth", ""), 74)):
            lbl = QLabel(str(text))
            lbl.setFixedWidth(width)
            lbl.setStyleSheet(
                f"color: {Theme.TEXT_MUTED}; font-size: {Theme.FONT_SIZE_TINY}px;"
                f"background: transparent; border: none;")
            row.addWidget(lbl)

        sig = QLabel(f"{dbm} dBm")
        sig.setFixedWidth(60)
        sig.setAlignment(Qt.AlignmentFlag.AlignRight)
        sig.setStyleSheet(
            f"color: {signal_color(dbm)}; font-family: {Theme.FONT_MONO};"
            f"font-size: {Theme.FONT_SIZE_TINY}px; background: transparent; border: none;")
        row.addWidget(sig)

        return w
