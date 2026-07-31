"""
NETWER — MainWindow.

Main application window ("skeleton"):
  - holds Sidebar (left) + stacked pages (right)
  - shows a FULL-WINDOW loading overlay on startup (over everything,
    sidebar included); when the first page signals it's ready, the
    overlay fades out revealing the populated app at once
  - handles navigation lifecycle (on_leave / on_enter) + fade transitions
"""

from PyQt6.QtCore import Qt, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QStackedWidget,
    QGraphicsOpacityEffect
)

from app.theme import Theme, apply_theme, apply_accent
from app.resources import LOGO_PATH
from app.store import store
from app.notifications import notifications
from ui.components.sidebar import Sidebar
from ui.components.topbar import TopBar
from ui.components.settings_panel import SettingsPanel
from ui.components.notifications_panel import NotificationsPanel
from ui.pages.base_page import BasePage
from ui.widgets.loading_overlay import LoadingOverlay


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

        # Outer padding so the sidebar + content float as cards over the
        # gradient background (like the redesign preview).
        outer = QHBoxLayout(central)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(18)

        # ── Left: floating sidebar panel (owns the NETWER logo) ──
        self.sidebar = Sidebar()
        self.sidebar.navigate.connect(self._navigate)
        outer.addWidget(self.sidebar)

        # ── Right: a column with the search top bar, then content ──
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
        right_col.addWidget(self.topbar)

        # Content row: the page stack, plus the sliding panels on the right.
        row = QWidget()
        root = QHBoxLayout(row)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        right_col.addWidget(row, 1)

        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)

        # Sliding panels (settings + notifications) on the far right.
        self.settings_panel = SettingsPanel()
        self.settings_panel.closed.connect(lambda: self._show_panel(None))
        self.settings_panel.theme_changed.connect(self._change_theme)
        self.settings_panel.accent_changed.connect(self._change_accent)
        self.settings_panel.glass_toggled.connect(self._change_glass)
        self.settings_panel.setMaximumWidth(0)
        root.addWidget(self.settings_panel)

        self.notifications_panel = NotificationsPanel()
        self.notifications_panel.closed.connect(lambda: self._show_panel(None))
        self.notifications_panel.setMaximumWidth(0)
        root.addWidget(self.notifications_panel)

        self._open_panel = None  # None | "settings" | "notifications"
        self._panel_anim = None

        # Keep the bell badge in sync with the notification center.
        notifications.subscribe(
            lambda: self.topbar.set_unread(notifications.unread_count()))

        # Background scan scheduler (off unless enabled in Settings).
        from app.scheduler import ScanScheduler
        self.scheduler = ScanScheduler(core, self)
        self.settings_panel.schedule_toggled.connect(self._on_schedule_toggled)
        self.settings_panel.schedule_interval_changed.connect(
            self.scheduler.set_interval)
        if store.get_setting("schedule_enabled", False):
            # Start shortly after launch so it doesn't compete with startup.
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(3000, self.scheduler.start)

        self._pages: dict[str, BasePage] = {}
        self._current_key: str | None = None
        self._fade_anim: QPropertyAnimation | None = None

        # Full-window loading overlay (child of the window, covers all).
        self._overlay = LoadingOverlay(self, message="Starting up…")
        self._overlay.hide()
        self._loading_active = False

    # ── Sliding panels ─────────────────────────────────────────
    def _toggle_settings(self):
        self._show_panel(None if self._open_panel == "settings" else "settings")

    def _toggle_notifications(self):
        if self._open_panel != "notifications":
            notifications.mark_all_read()
        self._show_panel(
            None if self._open_panel == "notifications" else "notifications")

    def _show_panel(self, which):
        """Animate the chosen panel open and the other closed."""
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

    # ── Theme switching ────────────────────────────────────────
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
        """Toggle the glass (translucent-card) look on or off."""
        Theme.GLASS_ENABLED = bool(enabled)
        store.set_setting("glass_enabled", bool(enabled))
        self._reskin_all()

    def _reskin_all(self):
        """Re-apply the global stylesheet and rebuild pages so every widget
        picks up the new theme colors."""
        import main as app_main
        from PyQt6.QtWidgets import QApplication
        QApplication.instance().setStyleSheet(app_main.build_global_qss())
        self.setStyleSheet(f"QMainWindow {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {Theme.BG_SIDEBAR}, stop:0.5 {Theme.BG_APP}, stop:1 {Theme.BG_SIDEBAR}); }}")
        self.topbar.refresh_theme()
        self.settings_panel.refresh_theme()
        self.notifications_panel.refresh_theme()
        self.sidebar.refresh_theme()
        self._rebuild_pages()

    def _rebuild_pages(self):
        """Recreate every page so inline stylesheets reflect the new theme."""
        import main as app_main
        current = self._current_key
        # Stop workers on EVERY page (not just the current one) before tearing
        # down — a live background thread calling back into a deleted widget
        # segfaults. on_leave() cancels each page's registered workers.
        for page in self._pages.values():
            try:
                page.on_leave()
            except Exception:
                pass
            # Give workers a moment to actually finish.
            for w in list(getattr(page, "_workers", [])):
                try:
                    w.stop()
                    if hasattr(w, "wait"):
                        w.wait(1500)
                except Exception:
                    pass
        # Remove old pages from the stack.
        for page in self._pages.values():
            self.stack.removeWidget(page)
            page.deleteLater()
        self._pages.clear()
        self.sidebar.clear_items()
        self._current_key = None
        # Rebuild from the registration function (which finalizes the sidebar).
        app_main._register_pages(self)
        if current:
            self.start(current)
        # Re-warm the other pages in the background (rebuild reset their
        # one-time load flags, so their cached data was thrown away).
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(400, self._preload_pages)

    # ── Loading overlay covers the whole window ────────────────
    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._overlay is not None:
            self._overlay.setGeometry(self.rect())

    def begin_loading(self) -> None:
        """Show the full-window loading screen."""
        self._loading_active = True
        self._overlay.setGeometry(self.rect())
        self._overlay.show_loading()

    def loading_progress(self, text: str) -> None:
        self._overlay.set_progress(text)

    def end_loading(self) -> None:
        """Fade out the loading screen, revealing the populated app."""
        if not self._loading_active:
            return
        self._loading_active = False
        self._overlay.finish()
        # Once the app is visible, warm up the other pages in the background
        # so their data is already there when the user clicks them (no
        # "loading…" on first visit). Only on real startup, not theme rebuilds.
        if not getattr(self, "_preloaded", False):
            self._preloaded = True
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(600, self._preload_pages)

    def _preload_pages(self) -> None:
        """Call preload() on every page except the current one, staggered so
        the background work doesn't hit all at once. Safe/idempotent."""
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

    # ── Page registration ──────────────────────────────────────
    def register_page(self, key: str, icon_name: str, page: BasePage,
                      subtitle: str = "") -> None:
        self._pages[key] = page
        self.stack.addWidget(page)
        self.sidebar.add_item(key, icon_name, page.PAGE_TITLE, subtitle)
        # Let the page talk back to the window for loading coordination.
        page.set_window(self)

    def register_section(self, label: str) -> None:
        """Dodaj naslov sekcije u sidebar prije sljedećih stranica."""
        self.sidebar.add_section(label)

    def finalize_sidebar(self) -> None:
        self.sidebar.add_stretch_and_status()
        self._register_shortcuts()

    def _register_shortcuts(self) -> None:
        """Global keyboard shortcuts:
          Ctrl+1..9  → jump to the Nth registered page
          Esc        → tell the current page to stop its running task
        """
        from PyQt6.QtGui import QShortcut, QKeySequence
        keys = list(self._pages.keys())
        for i, key in enumerate(keys[:9], start=1):
            sc = QShortcut(QKeySequence(f"Ctrl+{i}"), self)
            sc.activated.connect(lambda k=key: self.goto(k))
        esc = QShortcut(QKeySequence("Escape"), self)
        esc.activated.connect(self._stop_current)

    def _stop_current(self) -> None:
        """Esc → ask the current page to stop any running scan/ping."""
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

    # ── Search ─────────────────────────────────────────────────
    #: Keywords (lowercase) → page key. First match wins.
    SEARCH_MAP = {
        "dashboard": "dashboard", "home": "dashboard", "overview": "dashboard",
        "network": "network", "ip": "network", "mac": "network",
        "adapter": "network",
        "wifi": "wifi", "wireless": "wifi", "signal": "wifi", "ssid": "wifi",
        "system": "system", "hardware": "system", "cpu": "system",
        "os": "system", "ram": "system",
        "ping": "ping", "latency": "ping",
        "sweep": "ping_sweep", "discover": "ping_sweep", "devices": "ping_sweep",
        "port": "port_scanner", "scan": "port_scanner", "ports": "port_scanner",
        "dns": "dns_tools", "trace": "dns_tools", "traceroute": "dns_tools",
        "reverse": "dns_tools", "lookup": "dns_tools", "route": "dns_tools",
        "speed": "speedtest", "bandwidth": "speedtest", "speedtest": "speedtest",
        "report": "report", "export": "report", "pdf": "report", "save": "report",
        "about": "about", "version": "about", "info": "about",
    }

    #: Full page titles (lowercase) → key, so typing the visible name works.
    PAGE_TITLES = {
        "dashboard": "dashboard",
        "network information": "network", "network info": "network",
        "wifi information": "wifi", "wifi info": "wifi",
        "system information": "system", "system info": "system",
        "ping": "ping",
        "ping sweep": "ping_sweep",
        "port scanner": "port_scanner",
        "dns tools": "dns_tools", "dns": "dns_tools",
        "reverse dns": "dns_tools", "dns lookup": "dns_tools",
        "traceroute": "dns_tools",
        "speed test": "speedtest",
        "save report": "report", "report": "report",
        "about": "about",
    }

    def _on_search(self, query: str) -> None:
        """Jump to the tool that best matches the typed query. Tolerant of
        case, extra spaces, plurals and small typos, and matches multi-word
        names ('speed test' → Speed Test) as well as single keywords."""
        import difflib
        raw = query.strip().lower()
        q = " ".join(raw.split())          # collapse whitespace
        if not q:
            return

        target = None
        # 1) exact full page title ("speed test", "network information", ...)
        target = self.PAGE_TITLES.get(q)
        # 2) exact single keyword ("ping", "cpu", "trace", ...)
        if not target:
            target = self.SEARCH_MAP.get(q)
        # 3) any word of the query is a keyword (handles "run a ping", "show
        #    wifi signal") — first strong hit wins.
        if not target:
            for word in q.split():
                word = word.rstrip("s")   # crude plural strip: ports→port
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
                # try the last word alone (e.g. "the ping tool" → "ping")
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

    # ── Navigation ─────────────────────────────────────────────
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
        """Public navigation used by cross-page actions (e.g. Ping Sweep
        jumping to the Port Scanner). Updates the sidebar highlight too."""
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
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity")
        anim.setDuration(Theme.ANIM_NORMAL)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(lambda: widget.setGraphicsEffect(None))
        anim.start()
        self._fade_anim = anim

    def closeEvent(self, event):
        if self._current_key is not None:
            self._pages[self._current_key].on_leave()
        super().closeEvent(event)
