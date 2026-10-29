"""Run network checks and present their results as actionable findings."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.activity import activity
from app.resources import Icons
from app.theme import Theme
from core import diagnostics as diag
from ui.pages.base_page import BasePage
from ui.widgets.ai_chat_panel import AIChatPanel
from ui.widgets.card import Card
from workers import StreamWorker

_SEVERITY_STYLE = {
    diag.CRITICAL: (Theme.DANGER, "\u2715"),
    diag.WARNING:  (Theme.WARNING, "!"),
    diag.INFO:     (Theme.ACCENT, "i"),
    diag.GOOD:     (Theme.SUCCESS, "\u2713"),
}


def _severity_colour(sev):
    return _SEVERITY_STYLE.get(sev, (Theme.TEXT_SECONDARY, "\u2022"))[0]


class _FindingRow(QFrame):
    # One issue - coloured bar, title, explanation and what to do.

    def __init__(self, finding, on_ask=None, parent=None):
        super().__init__(parent)
        colour, glyph = _SEVERITY_STYLE.get(
            finding["severity"], (Theme.TEXT_SECONDARY, "\u2022"))
        self.setObjectName("Finding")
        self.setStyleSheet(
            f"#Finding {{ background: {Theme.GLASS_INPUT};"
            f"border: 1px solid {Theme.GLASS_BORDER};"
            f"border-left: 3px solid {colour};"
            f"border-radius: 12px; }}"
            f"#Finding QLabel {{ background: transparent; }}")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 12, 16, 12)
        lay.setSpacing(13)

        badge = QLabel(glyph)
        badge.setFixedSize(26, 26)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(
            f"color: {colour}; background: transparent;"
            f"border: 1px solid {colour}; border-radius: 13px;"
            f"font-size: 13px; font-weight: 700;")
        lay.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)

        box = QVBoxLayout()
        box.setSpacing(3)
        title = QLabel(finding["title"])
        title.setStyleSheet(
            f"color: {Theme.TEXT_PRIMARY}; font-size: 14px; font-weight: 600;")
        box.addWidget(title)

        detail = QLabel(finding["detail"])
        detail.setWordWrap(True)
        detail.setStyleSheet(
            f"color: {Theme.TEXT_SECONDARY}; font-size: 12.5px;")
        box.addWidget(detail)

        if finding.get("action"):
            act = QLabel("\u2192  " + finding["action"])
            act.setWordWrap(True)
            act.setStyleSheet(
                f"color: {colour}; font-size: 12.5px; font-weight: 500;")
            box.addWidget(act)
        lay.addLayout(box, 1)

        if on_ask is not None and finding["severity"] != diag.GOOD:
            ask = QPushButton("Ask AI")
            ask.setCursor(Qt.CursorShape.PointingHandCursor)
            ask.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {Theme.ACCENT};"
                f"border: 1px solid {Theme.GLASS_BORDER}; border-radius: 8px; padding: 4px 10px;"
                f"font-size: 11.5px; }}"
                f"QPushButton:hover {{ border-color: {Theme.ACCENT}; }}")
            ask.clicked.connect(lambda: on_ask(finding))
            lay.addWidget(ask, 0, Qt.AlignmentFlag.AlignTop)


class HealthPage(BasePage):
    PAGE_TITLE = "Network Health"
    PAGE_SUBTITLE = "Find out what's actually wrong — in plain language"

    def __init__(self, core, parent=None):
        super().__init__(core, parent)

        self._worker = None
        self._report = None

        # -- Run bar --
        bar = QHBoxLayout()
        bar.setSpacing(12)
        self.btn_run = QPushButton("  Diagnose my network")
        self.btn_run.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_run.setIcon(Icons.get("ping", "#ffffff"))
        self.btn_run.setStyleSheet(
            f"QPushButton {{ background: {Theme.GRAD_ACCENT}; color: white;"
            f"border: none; border-radius: {Theme.RADIUS_CONTROL}px;"
            f"padding: 11px 22px; font-size: 13.5px; font-weight: 600; }}")
        self.btn_run.clicked.connect(self._run)
        bar.addWidget(self.btn_run)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(8)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setStyleSheet(
            f"QProgressBar {{ background: {Theme.GLASS_INPUT};"
            f"border: none; border-radius: 4px; }}"
            f"QProgressBar::chunk {{ background: {Theme.GRAD_ACCENT};"
            f"border-radius: 4px; }}")
        bar.addWidget(self.progress, 1)

        # Netwer AI opens only when asked for.
        self.btn_ai = QPushButton("  Ask AI")
        self.btn_ai.setCheckable(True)
        self.btn_ai.setIcon(Icons.get("ai", Theme.ACCENT))
        self.btn_ai.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_ai.setStyleSheet(
            f"QPushButton {{ background: {Theme.GLASS_INPUT}; color: {Theme.TEXT_PRIMARY};"
            f"border: 1px solid {Theme.GLASS_BORDER_HI}; border-radius: {Theme.RADIUS_CONTROL}px;"
            f"padding: 11px 20px; font-size: 13.5px; font-weight: 600; }}"
            f"QPushButton:hover {{ border-color: {Theme.ACCENT}; }}"
            f"QPushButton:checked {{ background: {Theme.BG_ELEVATED}; border-color: {Theme.ACCENT}; }}")
        bar.addWidget(self.btn_ai)
        self.body_layout.addLayout(bar)

        self.status = QLabel("Runs a few quick checks — takes about 15 seconds.")
        self.status.setStyleSheet(
            f"color: {Theme.TEXT_MUTED}; font-size: 12px;")
        self.body_layout.addWidget(self.status)

        # -- Verdict banner --
        self.verdict = QFrame()
        self.verdict.setObjectName("Verdict")
        self.verdict.hide()
        vl = QVBoxLayout(self.verdict)
        vl.setContentsMargins(20, 16, 20, 16)
        vl.setSpacing(5)
        self.verdict_title = QLabel("")
        self.verdict_title.setStyleSheet(
            f"color: {Theme.TEXT_PRIMARY}; font-size: 19px; font-weight: 700;"
            f"background: transparent;")
        self.verdict_text = QLabel("")
        self.verdict_text.setWordWrap(True)
        self.verdict_text.setStyleSheet(
            f"color: {Theme.TEXT_SECONDARY}; font-size: 13px;"
            f"background: transparent;")
        vl.addWidget(self.verdict_title)
        vl.addWidget(self.verdict_text)
        self.body_layout.addWidget(self.verdict)

        # -- Findings --
        self.findings_card = Card("What we found", "summary")
        self._findings_area = QScrollArea()
        self._findings_area.setWidgetResizable(True)
        self._findings_area.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }")
        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        self._findings_layout = QVBoxLayout(inner)
        self._findings_layout.setContentsMargins(0, 0, 6, 0)
        self._findings_layout.setSpacing(9)
        self._findings_placeholder = QLabel(
            "Press \u201cDiagnose my network\u201d and NETWER will work out "
            "where the problem is.")
        self._findings_placeholder.setWordWrap(True)
        self._findings_placeholder.setStyleSheet(
            f"color: {Theme.TEXT_MUTED}; font-size: 12.5px;")
        self._findings_layout.addWidget(self._findings_placeholder)
        self._findings_layout.addStretch()
        self._findings_area.setWidget(inner)
        self.findings_card.content_layout.addWidget(self._findings_area)
        columns = QHBoxLayout()
        columns.setSpacing(0)
        left = QVBoxLayout()
        left.setSpacing(Theme.GAP)
        left.addWidget(self.findings_card, 1)

        # -- Measurements strip --
        self.metrics_card = Card("Measurements", "monitor")
        self._metrics = QGridLayout()
        self._metrics.setHorizontalSpacing(26)
        self._metrics.setVerticalSpacing(8)
        self.metrics_card.content_layout.addLayout(self._metrics)
        self.metrics_card.hide()
        left.addWidget(self.metrics_card)
        columns.addLayout(left, 1)

        self.ai_panel = AIChatPanel()
        self.ai_panel.navigate.connect(self._navigate)
        self.ai_panel.expanded.connect(self._on_ai_expanded)
        self._hidden_for_ai = []
        self.ai_panel.toggled.connect(self.btn_ai.setChecked)
        self.btn_ai.clicked.connect(self.ai_panel.toggle)
        columns.addWidget(self.ai_panel)
        self._columns = columns
        self.body_layout.addLayout(columns, 1)

    def _on_ai_expanded(self, on: bool):
        self._columns.setStretch(0, 0 if on else 1)
        self._columns.setStretch(1, 1 if on else 0)
        if on:
            self._hidden_for_ai = [w for w in (self.verdict, self.findings_card, self.metrics_card, self.status) if w.isVisible()]
            for w in self._hidden_for_ai:
                w.hide()
        else:
            for w in self._hidden_for_ai:
                w.show()
            self._hidden_for_ai = []

    def _ask_about(self, finding):
        self.ai_panel.ask_about(finding)

    def _navigate(self, target: str):
        """Open a tool from a button inside an AI answer."""
        if target == "health_run":
            self._run()
            return
        win = self._window or self.window()
        if target.startswith("scan:") and hasattr(win, "scan_ports_for"):
            win.scan_ports_for(target[5:])
        elif hasattr(win, "goto"):
            win.goto(target)

    # -- Run --
    def _run(self):
        if self._worker is not None:
            return
        self.btn_run.setEnabled(False)
        self.btn_run.setText("  Checking\u2026")
        self.progress.setValue(0)
        self.verdict.hide()
        self.metrics_card.hide()
        self._clear_findings()

        self._worker = StreamWorker(diag.run_diagnostics_stream, self.core)
        self._worker.result.connect(self._on_event)
        self._worker.error.connect(self._on_error)
        self._worker.done.connect(self._on_done)
        self.register_worker(self._worker)
        self._worker.start()

    def _on_event(self, ev: dict):
        if ev.get("done"):
            self._report = ev.get("report")
            self._show_report(self._report)
            return
        if "progress" in ev:
            self.progress.setValue(ev["progress"])
            self.status.setText(ev.get("label", ""))

    def _on_error(self, err):
        self.status.setText(self.core.friendly_error(err))

    def _on_done(self):
        self._worker = None
        self.btn_run.setEnabled(True)
        self.btn_run.setText("  Diagnose my network")
        self.progress.setValue(100)

    # -- Results --
    def _clear_findings(self):
        while self._findings_layout.count():
            item = self._findings_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
        self._findings_layout.addStretch()

    def _show_report(self, report):
        if not report:
            return
        colour = _severity_colour(report["severity"])
        self.verdict.setStyleSheet(
            f"#Verdict {{ background: {Theme.GLASS_CARD};"
            f"border: 1px solid {Theme.GLASS_BORDER};"
            f"border-left: 4px solid {colour};"
            f"border-radius: {Theme.RADIUS_CARD}px; }}")
        self.verdict_title.setText(report["headline"])
        self.verdict_title.setStyleSheet(
            f"color: {colour}; font-size: 19px; font-weight: 700;"
            f"background: transparent;")
        self.verdict_text.setText(report["summary"])
        self.verdict.show()

        self._clear_findings()
        for f in report["findings"]:
            self._findings_layout.insertWidget(
                self._findings_layout.count() - 1, _FindingRow(f, self._ask_about))

        self._show_metrics(report.get("measurements", {}))
        self.ai_panel.set_report(report)
        self.status.setText("Done.")
        activity.add("Network diagnosis", report["headline"],
                     kind=("error" if report["severity"] == diag.CRITICAL
                           else "success"))

    def _show_metrics(self, m):
        while self._metrics.count():
            item = self._metrics.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)

        router = m.get("router") or {}
        internet = m.get("internet") or {}

        def fmt(v, unit=""):
            return "\u2014" if v is None else f"{v}{unit}"

        cells = [
            ("Router", fmt(router.get("avg"), " ms")),
            ("Router loss", fmt(router.get("loss"), "%")),
            ("Internet", fmt(internet.get("avg"), " ms")),
            ("Internet loss", fmt(internet.get("loss"), "%")),
            ("Jitter", fmt(internet.get("jitter"), " ms")),
            ("DNS A", fmt(m.get("dns_ipv4_ms"), " ms")),
            ("DNS AAAA", fmt(m.get("dns_ipv6_ms"), " ms")),
            ("IPv6", {"global": "Active", "ula": "Local only",
                      "link-local": "Link-local only"}.get(
                          m.get("ipv6_scope"), "None")),
        ]
        if m.get("wifi"):
            cells.append(("Wi-Fi signal", fmt(m.get("signal"), "%")))

        for i, (k, v) in enumerate(cells):
            col = i % 4
            row = (i // 4) * 2
            kl = QLabel(k)
            kl.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: 11.5px;")
            vl = QLabel(v)
            vl.setStyleSheet(
                f"color: {Theme.TEXT_PRIMARY}; font-size: 15px;"
                f"font-weight: 700; font-family: {Theme.FONT_MONO};")
            self._metrics.addWidget(kl, row, col)
            self._metrics.addWidget(vl, row + 1, col)
        self.metrics_card.show()
