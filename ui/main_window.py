"""Main application window and page navigation."""

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, Qt, pyqtProperty
from PyQt6.QtGui import QColor, QIcon, QPainter
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.notifications import notifications
from app.resources import LOGO_PATH
from app.store import store
from app.theme import Theme, apply_accent, apply_theme
from ui.components.notifications_panel import NotificationsPanel
from ui.components.settings_panel import SettingsPanel
from ui.components.sidebar import RAIL_WIDTH, Sidebar
from ui.components.topbar import TopBar
from ui.pages.base_page import BasePage
from ui.widgets.loading_overlay import LoadingOverlay


class _FadeCover(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._alpha = 255

    def _get(self):
        return self._alpha

    def _set(self, value):
        self._alpha = int(value)
        self.update()

    cover = pyqtProperty(int, _get, _set)

    def paintEvent(self, event):
        p = QPainter(self)
        color = QColor(Theme.BG_APP)
        color.setAlpha(self._alpha)
        p.fillRect(self.rect(), color)


class MainWindow(QMainWindow):
    def __init__(self, core):
        super().__init__()
        self.core = core
        self.setWindowTitle("NETWER — Network Diagnostic Suite")
        self.setWindowIcon(QIcon(LOGO_PATH))
        self.resize(1400, 860)
        self.setMinimumSize(1100, 700)
        self.setStyleSheet(f"QMainWindow {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {Theme.BG_SIDEBAR}, stop:0.5 {Theme.BG_APP}, stop:1 {Theme.BG_SIDEBAR}); }}")

        central = QWidget()
        self.setCentralWidget(central)

        outer = QHBoxLayout(central)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(18)

        # The sidebar floats above the pages so it can open over them on hover;
        # this placeholder keeps the rail's width free in the layout.
        self._rail_slot = QWidget()
        self._rail_slot.setFixedWidth(RAIL_WIDTH)
        outer.addWidget(self._rail_slot)
        self.sidebar = Sidebar(central)
        self.sidebar.navigate.connect(self._navigate)
        central.installEventFilter(self)
        self._central = central

        right = QWidget()
        right_col = QVBoxLayout(right)
        right_col.setContentsMargins(0, 0, 0, 0)
        right_col.setSpacing(18)
        outer.addWidget(right, 1)

        self.topbar = TopBar()
        self.topbar.toggle_settings.connect(self._toggle_settings)
        self.topbar.toggle_notifications.connect(self._toggle_notifications)
        self.topbar.theme_selected.connect(self._change_theme)
        self.topbar.search_submitted.connect(self._on_search)
        self.topbar.suggestion_chosen.connect(self.open_suggestion)
        self.topbar.suggestion_provider = self.search_suggestions
        self.topbar.toggle_ai.connect(self._toggle_ai)
        right_col.addWidget(self.topbar)

        row = QWidget()
        root = QHBoxLayout(row)
        self._row_layout = root
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        right_col.addWidget(row, 1)

        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)

        # Netwer AI dock; shares its conversation with the panels on other pages
        self.ai_dock = self._build_ai_dock()
        root.addWidget(self.ai_dock)

        self.settings_panel = SettingsPanel()
        self.settings_panel.closed.connect(lambda: self._show_panel(None))
        self.settings_panel.theme_changed.connect(self._change_theme)
        self.settings_panel.accent_changed.connect(self._change_accent)
        self.settings_panel.glass_toggled.connect(self._change_glass)
        self.settings_panel.resolution_changed.connect(self._change_resolution)
        self.settings_panel.offline_mode_toggled.connect(self._on_offline_mode_toggled)
        self.settings_panel.setMaximumWidth(0)
        root.addWidget(self.settings_panel)

        self.notifications_panel = NotificationsPanel()
        self.notifications_panel.closed.connect(lambda: self._show_panel(None))
        self.notifications_panel.setMaximumWidth(0)
        root.addWidget(self.notifications_panel)

        self._open_panel = None  # None | "settings" | "notifications"
        self._panel_anim = None

        notifications.subscribe(
            lambda: self.topbar.set_unread(notifications.unread_count()))

        from app.scheduler import ScanScheduler
        self.scheduler = ScanScheduler(core, self)
        self.settings_panel.schedule_toggled.connect(self._on_schedule_toggled)
        self.settings_panel.schedule_interval_changed.connect(
            self.scheduler.set_interval)
        if store.get_setting("schedule_enabled", False):
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(3000, self.scheduler.start)

        self._pages: dict[str, BasePage] = {}
        self._current_key: str | None = None
        self._fade_anim: QPropertyAnimation | None = None

        # Full-window loading overlay (child of the window, covers all).
        self._overlay = LoadingOverlay(self, message="Starting up…")
        self._overlay.hide()
        self._loading_active = False

    # -- Sidebar rail --
    def eventFilter(self, obj, event):
        from PyQt6.QtCore import QEvent
        if obj is self._central and event.type() == QEvent.Type.Resize:
            self._place_sidebar()
        return super().eventFilter(obj, event)

    def _place_sidebar(self):
        m = self._central.layout().contentsMargins()
        self.sidebar.setGeometry(m.left(), m.top(), self.sidebar.railWidth,
                                 self._central.height() - m.top() - m.bottom())
        self.sidebar.raise_()

    # -- Netwer AI dock --
    def _build_ai_dock(self):
        from ui.widgets.ai_chat_panel import AIChatPanel
        dock = AIChatPanel()
        dock.btn_expand.hide()
        dock.navigate.connect(self._on_ai_target)
        dock.toggled.connect(lambda on: self.topbar.set_ai_open(on))
        return dock

    def _toggle_ai(self):
        if not self.ai_dock.is_open:
            self._show_panel(None)
        self.ai_dock.toggle()

    def ask_ai(self, question: str) -> None:
        """Open the dock and ask the assistant (used by pages such as Packet Capture)."""
        self._show_panel(None)
        self.ai_dock.ask(question)

    def _on_ai_target(self, target: str) -> None:
        if target == "health_run":
            page = self._pages.get("health")
            self.goto("health")
            if page is not None and hasattr(page, "_run"):
                page._run()
        elif target.startswith("scan:"):
            self.scan_ports_for(target[5:])
        else:
            self.goto(target)

    def set_capture_state(self, on: bool) -> None:
        self.topbar.set_capturing(on)

    # -- Sliding panels --
    def _toggle_settings(self):
        self._show_panel(None if self._open_panel == "settings" else "settings")

    def _toggle_notifications(self):
        if self._open_panel != "notifications":
            notifications.mark_all_read()
        self._show_panel(
            None if self._open_panel == "notifications" else "notifications")

    def _show_panel(self, which):
        """Animate the chosen panel open and the other closed."""
        if which is not None and self.ai_dock.is_open:
            self.ai_dock.close_panel()
        self._open_panel = which
        targets = {
            self.settings_panel: SettingsPanel.WIDTH if which == "settings" else 0,
            self.notifications_panel: (
                NotificationsPanel.WIDTH if which == "notifications" else 0),
        }
        self._panel_anims = []
        for panel, target in targets.items():
            anim = QPropertyAnimation(panel, b"maximumWidth")
            anim.setDuration(180)
            anim.setStartValue(panel.maximumWidth())
            anim.setEndValue(target)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.start()
            self._panel_anims.append(anim)

    def _on_schedule_toggled(self, enabled):
        store.set_setting("schedule_enabled", enabled)
        if enabled:
            self.scheduler.start()
        else:
            self.scheduler.stop()

    def _on_offline_mode_toggled(self, enabled):
        from core.privacy import set_offline_mode
        enabled = bool(enabled)
        store.set_setting("offline_mode", enabled)
        set_offline_mode(enabled)

    # -- Theme switching --
    def _change_theme(self, theme_name):
        from app.theme import current_accent_name
        # Apply the theme, then re-apply the current accent on top so a
        # user's accent choice survives a theme change.
        apply_theme(theme_name, current_accent_name())
        store.set_setting("theme", theme_name)
        self._reskin_all()

    def _change_accent(self, accent_name):
        apply_accent(accent_name)
        store.set_setting("accent", accent_name)
        self._reskin_all()

    def _change_glass(self, enabled):
        # Toggle the glass (translucent-card) look on or off.
        Theme.GLASS_ENABLED = bool(enabled)
        store.set_setting("glass_enabled", bool(enabled))
        self._reskin_all()

    def apply_resolution(self, key: str, persist: bool = True) -> None:
        """Size and centre the window, applying the matching UI density."""
        from PyQt6.QtWidgets import QApplication

        from app import display
        from app import theme as theme_mod

        screen = self.screen() or QApplication.primaryScreen()
        geo = screen.availableGeometry() if screen else None
        screen_w = geo.width() if geo else 1920
        screen_h = geo.height() if geo else 1080

        width, height = display.resolve(key, screen_w, screen_h)
        theme_mod.apply_ui_scale(display.profile_for(width))

        win_w, win_h, min_w, min_h = display.window_geometry(width, height)
        self.setMinimumSize(min_w, min_h)
        self.resize(win_w, win_h)
        if geo is not None:
            x = geo.x() + max(0, (geo.width() - win_w) // 2)
            y = geo.y() + max(0, (geo.height() - win_h) // 2)
            self.move(x, y)

        if persist:
            store.set_setting("resolution", key)
        # At startup pages are registered afterwards, so only rebuild if present.
        if self._pages:
            self._reskin_all()

    def _change_resolution(self, key: str):
        self.apply_resolution(key)

    def _reskin_all(self):
        """Apply the current theme to the window and its pages."""
        from PyQt6.QtWidgets import QApplication

        import main as app_main
        QApplication.instance().setStyleSheet(app_main.build_global_qss())
        self.setStyleSheet(f"QMainWindow {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {Theme.BG_SIDEBAR}, stop:0.5 {Theme.BG_APP}, stop:1 {Theme.BG_SIDEBAR}); }}")
        self.topbar.refresh_theme()
        self.settings_panel.refresh_theme()
        self.notifications_panel.refresh_theme()
        self.sidebar.refresh_theme()
        old = self.ai_dock
        was_open = old.is_open
        self.ai_dock = self._build_ai_dock()
        self._row_layout.replaceWidget(old, self.ai_dock)
        old.setParent(None)
        old.deleteLater()
        if was_open:
            self.ai_dock.open()
        self._rebuild_pages()

    def _rebuild_pages(self):
        import main as app_main
        current = self._current_key
        # Stop workers before deleting pages to avoid callbacks to deleted widgets.
        dash = self._pages.get("dashboard")
        if dash is not None and hasattr(dash, "shutdown"):
            dash.shutdown()
        for page in self._pages.values():
            try:
                page.on_leave()
            except Exception:
                pass
            for w in list(getattr(page, "_workers", [])):
                try:
                    w.stop()
                    if hasattr(w, "wait"):
                        w.wait(1500)
                except Exception:
                    pass
        for page in self._pages.values():
            self.stack.removeWidget(page)
            page.deleteLater()
        self._pages.clear()
        self.sidebar.clear_items()
        self._current_key = None
        app_main._register_pages(self)
        if current:
            self.start(current)
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(400, self._preload_pages)

    # -- Loading overlay covers the whole window --
    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._overlay is not None:
            self._overlay.setGeometry(self.rect())

    def begin_loading(self) -> None:
        self._loading_active = True
        self._overlay.setGeometry(self.rect())
        self._overlay.show_loading()

    def loading_progress(self, text: str) -> None:
        self._overlay.set_progress(text)

    def end_loading(self) -> None:
        if not self._loading_active:
            return
        self._loading_active = False
        self._overlay.finish()
        # Preload once at startup; theme rebuilds handle their own page setup.
        if not getattr(self, "_preloaded", False):
            self._preloaded = True
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(600, self._preload_pages)

    def _preload_pages(self) -> None:
        """Preload pages other than the current one at staggered intervals."""
        from PyQt6.QtCore import QTimer
        keys = [k for k in self._pages if k != self._current_key]
        delay = 0
        for key in keys:
            page = self._pages.get(key)
            if page is None:
                continue
            # Stagger by 250 ms each so scans/queries don't stampede.
            QTimer.singleShot(delay, lambda p=page: self._safe_preload(p))
            delay += 250

    def _safe_preload(self, page) -> None:
        try:
            page.preload()
        except Exception:
            pass

    # -- Page registration --
    def register_page(self, key: str, icon_name: str, page: BasePage,
                      subtitle: str = "", badge: str = "") -> None:
        self._pages[key] = page
        self.stack.addWidget(page)
        self.sidebar.add_item(key, icon_name, page.PAGE_TITLE, subtitle, badge)
        page.set_window(self)

    def register_section(self, label: str) -> None:
        self.sidebar.add_section(label)

    def finalize_sidebar(self) -> None:
        self.sidebar.add_stretch_and_status()
        self._register_shortcuts()

    def _register_shortcuts(self) -> None:
        """Register page navigation and current-task cancellation shortcuts."""
        from PyQt6.QtGui import QKeySequence, QShortcut
        keys = list(self._pages.keys())
        for i, key in enumerate(keys[:9], start=1):
            sc = QShortcut(QKeySequence(f"Ctrl+{i}"), self)
            sc.activated.connect(lambda k=key: self.goto(k))
        esc = QShortcut(QKeySequence("Escape"), self)
        esc.activated.connect(self._stop_current)

    def _stop_current(self) -> None:
        page = self._pages.get(self._current_key)
        if page is None:
            return
        for meth in ("_stop", "stop"):
            fn = getattr(page, meth, None)
            if callable(fn):
                try:
                    fn()
                except Exception:
                    pass
                break

    def start(self, first_key: str) -> None:
        self.sidebar.set_active(first_key)
        self._navigate(first_key)

    # -- Search --
    #: Keywords (lowercase) - page key. First match wins.
    SEARCH_MAP = {
        "dashboard": "dashboard", "home": "dashboard", "overview": "dashboard",
        "network": "network", "ip": "network", "mac": "network",
        "adapter": "network",
        "wifi": "wifi", "wireless": "wifi", "signal": "wifi", "ssid": "wifi",
        "system": "system", "hardware": "system", "cpu": "system",
        "os": "system", "ram": "system",
        "ping": "ping", "latency": "ping",
        "health": "health", "diagnose": "health", "diagnosis": "health",
        "problem": "health", "slow": "health", "fix": "health",
        "sweep": "ping_sweep", "discover": "ping_sweep", "devices": "ping_sweep",
        "port": "port_scanner", "scan": "port_scanner", "ports": "port_scanner",
        "dns": "dns_tools", "trace": "dns_tools", "traceroute": "dns_tools",
        "reverse": "dns_tools", "lookup": "dns_tools", "route": "dns_tools",
        "speed": "speedtest", "bandwidth": "speedtest", "speedtest": "speedtest",
        "capture": "capture", "packet": "capture", "packets": "capture",
        "wireshark": "capture", "pcap": "capture", "sniff": "capture",
        "report": "report", "export": "report", "pdf": "report", "save": "report",
        "about": "about", "version": "about", "info": "about",
    }

    #: Full page titles (lowercase) - key, so typing the visible name works.
    PAGE_TITLES = {
        "dashboard": "dashboard",
        "network information": "network", "network info": "network",
        "wifi information": "wifi", "wifi info": "wifi",
        "system information": "system", "system info": "system",
        "ping": "ping",
        "network health": "health", "diagnose my network": "health",
        "ping sweep": "ping_sweep",
        "port scanner": "port_scanner",
        "dns tools": "dns_tools", "dns": "dns_tools",
        "reverse dns": "dns_tools", "dns lookup": "dns_tools",
        "traceroute": "dns_tools",
        "speed test": "speedtest",
        "packet capture": "capture",
        "save report": "report", "report": "report",
        "about": "about",
    }

    # Suggestions are considered in this order when scores tie.
    SEARCH_ITEMS = [
        ("dashboard", "Dashboard", "Overview of your network",
         ["dashboard", "home", "overview", "start"]),
        ("health", "Network Health", "Diagnose problems in plain language",
         ["health", "diagnose", "diagnosis", "problem", "slow", "fix",
          "why", "broken", "troubleshoot"]),
        ("network", "Network Information", "IP, MAC, adapter details",
         ["network", "information", "adapter", "ip", "mac", "subnet",
          "gateway", "dhcp", "mtu"]),
        ("wifi", "WiFi Information", "Signal, SSID, channel",
         ["wifi", "wireless", "signal", "ssid", "channel", "band"]),
        ("system", "System Information", "Hardware and OS",
         ["system", "hardware", "cpu", "memory", "ram", "disk", "os"]),
        ("ping", "Ping", "Test connectivity to a host",
         ["ping", "latency", "rtt", "connectivity", "reachable"]),
        ("ping_sweep", "Ping Sweep", "Discover devices on your network",
         ["sweep", "discover", "devices", "scan network", "hosts"]),
        ("port_scanner", "Port Scanner", "Open and filtered ports",
         ["port", "ports", "scanner", "open ports", "service"]),
        ("dns_tools", "DNS Tools", "DNS, reverse DNS, traceroute",
         ["dns", "traceroute", "tracert", "trace", "route", "lookup",
          "reverse", "resolve", "nslookup", "hops"]),
        ("capture", "Packet Capture", "Capture and inspect packets",
         ["capture", "packet", "packets", "wireshark", "sniff", "pcap", "traffic",
          "filter", "tls", "protocol"]),
        ("speedtest", "Speed Test", "Measure bandwidth",
         ["speed", "speedtest", "bandwidth", "download", "upload", "mbps"]),
        ("report", "Save Report", "Export a PDF report",
         ["report", "save", "export", "pdf", "document"]),
        ("about", "About", "About NETWER",
         ["about", "version", "info", "credits", "licence", "license"]),
    ]

    def search_suggestions(self, query: str, limit: int = 7):
        """Rank page and device matches for the search dropdown."""
        q = " ".join((query or "").strip().lower().split())
        if not q:
            return []

        scored = []
        for key, title, subtitle, keywords in self.SEARCH_ITEMS:
            best = None
            tl = title.lower()
            if tl.startswith(q):
                best = 0
            elif any(k.startswith(q) for k in keywords):
                best = 1
            elif q in tl:
                best = 2
            elif any(q in k for k in keywords):
                best = 3
            else:
                # last resort: every word of the query appears somewhere
                hay = tl + " " + " ".join(keywords) + " " + subtitle.lower()
                if all(w in hay for w in q.split()):
                    best = 4
            if best is not None:
                scored.append((best, len(title), {
                    "kind": "page", "key": key,
                    "title": title, "subtitle": subtitle}))

        scored.sort(key=lambda t: (t[0], t[1]))
        results = [s[2] for s in scored[:limit]]

        dash = self._pages.get("dashboard")
        devices = getattr(dash, "_all_devices", None) or []
        if devices and len(results) < limit:
            from ui.widgets.network_map import device_display_name
            for dev in devices:
                name = device_display_name(dev)
                hay = " ".join([
                    name, dev.get("hostname") or "", dev.get("vendor") or "",
                    dev.get("ip") or "", dev.get("mac") or "",
                ]).lower()
                if q in hay:
                    results.append({
                        "kind": "device", "key": dev.get("ip", ""),
                        "title": name,
                        "subtitle": dev.get("ip", ""), "device": dev})
                if len(results) >= limit:
                    break
        return results

    def open_suggestion(self, item: dict) -> None:
        if not item:
            return
        if item.get("kind") == "device":
            dash = self._pages.get("dashboard")
            self.sidebar.set_active("dashboard")
            self._navigate("dashboard")
            if hasattr(dash, "_open_device_details"):
                dash._open_device_details(item["device"])
            return
        key = item.get("key")
        if key in self._pages:
            self.sidebar.set_active(key)
            self._navigate(key)

    def _find_device(self, q: str):
        """Return a discovered device matching an IP or identifying text."""
        import re
        dash = self._pages.get("dashboard")
        devices = getattr(dash, "_all_devices", None) or []
        if not devices:
            return None
        from ui.widgets.network_map import device_display_name

        # Exact IP wins.
        if re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", q):
            for d in devices:
                if d.get("ip") == q:
                    return d
            return None
        # Last octet on its own (".45" or "45") when it's unambiguous.
        if re.fullmatch(r"\.?\d{1,3}", q):
            octet = q.lstrip(".")
            hits = [d for d in devices
                    if d.get("ip", "").split(".")[-1] == octet]
            if len(hits) == 1:
                return hits[0]
        # Name / hostname / vendor / MAC substring.
        for d in devices:
            haystack = " ".join([
                device_display_name(d), d.get("hostname") or "",
                d.get("vendor") or "", d.get("mac") or "", d.get("ip") or "",
            ]).lower()
            if q in haystack:
                return d
        return None

    def _on_search(self, query: str) -> None:
        """Navigate to the page or discovered device matching the query."""
        import difflib
        raw = query.strip().lower()
        q = " ".join(raw.split())          # collapse whitespace
        if not q:
            return

        # A device match takes priority only when the query is clearly not a
        # tool name - otherwise "ping" would open a device called "ping".
        if q not in self.PAGE_TITLES and q not in self.SEARCH_MAP:
            dev = self._find_device(q)
            if dev is not None:
                dash = self._pages.get("dashboard")
                self.sidebar.set_active("dashboard")
                self._navigate("dashboard")
                if hasattr(dash, "_open_device_details"):
                    dash._open_device_details(dev)
                return

        target = None
        # 1) exact full page title ("speed test", "network information", ...)
        target = self.PAGE_TITLES.get(q)
        # 2) exact single keyword ("ping", "cpu", "trace", ...)
        if not target:
            target = self.SEARCH_MAP.get(q)
        # 3) any word of the query is a keyword (handles "run a ping", "show
        #    wifi signal") - first strong hit wins.
        if not target:
            for word in q.split():
                word = word.rstrip("s")   # crude plural strip: ports -> port
                if word in self.SEARCH_MAP:
                    target = self.SEARCH_MAP[word]
                    break
                if word in self.PAGE_TITLES:
                    target = self.PAGE_TITLES[word]
                    break
        # 4) prefix / substring against every keyword and title
        if not target:
            for kw, key in list(self.PAGE_TITLES.items()) + list(self.SEARCH_MAP.items()):
                if kw.startswith(q) or q in kw:
                    target = key
                    break
        # 5) fuzzy match for small typos ("spede test", "netwrok")
        if not target:
            candidates = list(self.PAGE_TITLES.keys()) + list(self.SEARCH_MAP.keys())
            close = difflib.get_close_matches(q, candidates, n=1, cutoff=0.7)
            if not close and " " not in q:
                # try the last word alone (e.g. "the ping tool" - "ping")
                close = difflib.get_close_matches(
                    q.split()[-1], candidates, n=1, cutoff=0.75)
            if close:
                hit = close[0]
                target = self.PAGE_TITLES.get(hit) or self.SEARCH_MAP.get(hit)

        if target:
            self.sidebar.set_active(target)
            self._navigate(target)
        else:
            notifications.push(
                "Search", f"No tool matches \u201c{query}\u201d.", kind="info")

    # -- Navigation --
    def _navigate(self, key: str) -> None:
        if key not in self._pages or key == self._current_key:
            return
        if self._current_key is not None:
            self._pages[self._current_key].on_leave()
        new_page = self._pages[key]
        self.stack.setCurrentWidget(new_page)
        self._current_key = key
        new_page.on_enter()
        # Only fade the page if we're not in the startup loading screen
        if not self._loading_active:
            self._fade_in(new_page)
        # Keep overlay on top if still loading
        if self._loading_active:
            self._overlay.raise_()

    def goto(self, key: str) -> None:
        """Navigate to a page and update the sidebar selection.
        "filter:<expr>" opens Packet Capture with that display filter applied."""
        if key.startswith("filter:"):
            page = self._pages.get("capture")
            self.goto("capture")
            if page is not None:
                page.set_filter(key[7:])
            return
        if key in self._pages:
            self.sidebar.set_active(key)
            self._navigate(key)

    def scan_ports_for(self, ip: str) -> None:
        """Jump to the Port Scanner pre-targeted at ip and start scanning."""
        page = self._pages.get("port_scanner")
        if page is None:
            return
        self.goto("port_scanner")
        if hasattr(page, "set_target"):
            page.set_target(ip, autostart=True)

    def _fade_in(self, widget: QWidget) -> None:
        # A background-coloured cover fades out over the page; the page itself is never
        # rendered through a graphics effect, so its text stays sharp during the transition.
        parent = widget.parentWidget() or widget
        cover = _FadeCover(parent)
        cover.setGeometry(parent.rect())
        cover.show()
        cover.raise_()
        anim = QPropertyAnimation(cover, b"cover")
        anim.setDuration(Theme.ANIM_NORMAL)
        anim.setStartValue(255)
        anim.setEndValue(0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(cover.deleteLater)
        anim.start()
        self._fade_anim = anim

    def closeEvent(self, event):
        dash = self._pages.get("dashboard")
        if dash is not None and hasattr(dash, "shutdown"):
            dash.shutdown()
        from core.capture import get_capture_service
        get_capture_service().stop()
        if self._current_key is not None:
            self._pages[self._current_key].on_leave()
        super().closeEvent(event)
