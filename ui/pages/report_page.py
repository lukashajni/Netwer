"""Generate, preview, and save a PDF network report."""

import os
import tempfile
from datetime import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtPdf import QPdfDocument
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.resources import Icons
from app.theme import Theme
from reports import report_data
from reports.pdf_report import (
    ALL_SECTIONS,
    SECTION_LABELS,
    _device_display_name,
    build_report,
)
from ui.pages.base_page import BasePage
from ui.pages.port_scanner_page import PROFILE_OPTIONS
from ui.widgets.card import Card
from ui.widgets.spinner import Spinner
from workers import OneshotWorker


class ReportPage(BasePage):
    PAGE_TITLE = "Save Report"
    PAGE_SUBTITLE = "Generate a professional PDF network report"

    def __init__(self, core, parent=None):
        super().__init__(core, parent)

        self._temp_pdf = None
        self._pdf_doc = QPdfDocument(self)
        self._devices_loading = False

        row = QHBoxLayout()
        row.setSpacing(Theme.GAP)

        # -- Left: options panel --
        options_card = Card("Report Options", "report")
        options_card.setFixedWidth(300)

        hint = QLabel("Select the sections to include:")
        hint.setStyleSheet(
            f"color: {Theme.TEXT_SECONDARY}; font-size: {Theme.FONT_SIZE_SMALL}px;"
            f"background: transparent; padding-bottom: 4px;"
        )
        options_card.content_layout.addWidget(hint)

        # Section icons for a nicer look
        section_icons = {
            "network": "network",
            "system": "system",
            "devices": "devices",
            "connectivity": "ping",
            "port_scan": "port_scanner",
        }
        self._checks = {}
        for key in ALL_SECTIONS:
            option = self._section_option(key, SECTION_LABELS[key],
                                          section_icons.get(key, "report"))
            options_card.content_layout.addWidget(option)

        self._build_port_scan_options(options_card)
        options_card.content_layout.addSpacing(10)

        self.btn_generate = QPushButton("  Generate Preview")
        self.btn_generate.setIcon(Icons.get("refresh", Theme.TEXT_PRIMARY))
        self.btn_generate.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_generate.setStyleSheet(self._primary_button_style())
        self.btn_generate.clicked.connect(self._generate)
        options_card.content_layout.addWidget(self.btn_generate)

        self.btn_save = QPushButton("  Save PDF")
        self.btn_save.setIcon(Icons.get("save", Theme.TEXT_PRIMARY))
        self.btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_save.setStyleSheet(self._secondary_button_style())
        self.btn_save.clicked.connect(self._save)
        self.btn_save.setEnabled(False)
        options_card.content_layout.addWidget(self.btn_save)

        self._status = QLabel("")
        self._status.setStyleSheet(
            f"color: {Theme.TEXT_MUTED}; font-size: {Theme.FONT_SIZE_TINY}px;"
            f"background: transparent;"
        )
        self._status.setWordWrap(True)
        options_card.content_layout.addWidget(self._status)
        options_card.content_layout.addStretch()

        row.addWidget(options_card)

        # -- Right: preview panel --
        preview_card = Card("Preview", "report")
        self._preview_scroll = QScrollArea()
        self._preview_scroll.setWidgetResizable(True)
        self._preview_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._preview_scroll.setStyleSheet(
            f"QScrollArea {{ background: {Theme.BG_APP}; border: none; }}"
        )
        self._preview_holder = QWidget()
        self._preview_layout = QVBoxLayout(self._preview_holder)
        self._preview_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_layout.setSpacing(10)

        from ui.widgets.ui_kit import empty_state
        self._preview_placeholder = empty_state(
            "report", "No preview yet",
            "Pick the sections on the left and press Generate Preview. The PDF looks exactly like the preview.")
        self._preview_layout.addWidget(self._preview_placeholder)
        self._preview_scroll.setWidget(self._preview_holder)
        preview_card.content_layout.addWidget(self._preview_scroll)

        row.addWidget(preview_card, 1)
        self.body_layout.addLayout(row)

    # -- Port scan target --
    def _build_port_scan_options(self, card):
        """Device + profile pickers shown while the Port Scan section is on."""
        self._ps_box = QFrame()
        self._ps_box.setObjectName("PsOpts")
        self._ps_box.setStyleSheet(
            "#PsOpts { background: transparent; border: none; }"
            "#PsOpts QLabel { background: transparent; border: none; }")
        lay = QVBoxLayout(self._ps_box)
        lay.setContentsMargins(2, 6, 2, 0)
        lay.setSpacing(6)

        caption = QLabel("Port scan target")
        caption.setStyleSheet(
            f"color: {Theme.TEXT_SECONDARY}; font-size: {Theme.FONT_SIZE_TINY}px;")
        lay.addWidget(caption)

        self.ps_target = QComboBox()
        self.ps_target.setEditable(True)
        self.ps_target.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.ps_target.lineEdit().setPlaceholderText(
            "Pick a device or type an IP / host")
        self.ps_target.setStyleSheet(self._combo_style())
        lay.addWidget(self.ps_target)

        self.ps_profile = QComboBox()
        for label, spec in PROFILE_OPTIONS:
            if spec != "__custom__":
                self.ps_profile.addItem(label, spec)
        self.ps_profile.setStyleSheet(self._combo_style())
        lay.addWidget(self.ps_profile)

        card.content_layout.addWidget(self._ps_box)
        port_check = self._checks["port_scan"]
        port_check.toggled.connect(self._ps_box.setVisible)
        self._ps_box.setVisible(port_check.isChecked())

    def _combo_style(self):
        return (
            f"QComboBox {{ background: {Theme.GLASS_INPUT}; color: {Theme.TEXT_BODY};"
            f"border: 1px solid {Theme.BORDER}; border-radius: 8px;"
            f"padding: 7px 10px; font-size: {Theme.FONT_SIZE_SMALL}px; }}"
            f"QComboBox:focus {{ border-color: {Theme.GLASS_BORDER_HI}; }}"
            f"QComboBox::drop-down {{ border: none; width: 22px; }}"
            f"QComboBox QAbstractItemView {{ background: {Theme.BG_ELEVATED};"
            f"color: {Theme.TEXT_BODY}; selection-background-color: {Theme.ACCENT};"
            f"border: 1px solid {Theme.BORDER_STRONG}; outline: none; }}")

    def on_enter(self):
        super().on_enter()
        self._load_devices()

    def _load_devices(self):
        if self._devices_loading:
            return
        self._devices_loading = True
        w = OneshotWorker(self.core.get_top_devices, 512)
        w.result.connect(self._on_devices)
        w.done.connect(lambda: setattr(self, "_devices_loading", False))
        self.register_worker(w)
        w.start()

    def _on_devices(self, result: dict):
        devices = result.get("devices") or []
        if not devices:
            return
        previous_ip, _name = self._selected_target()
        typed = self.ps_target.currentText().strip()
        self.ps_target.clear()
        for d in devices:
            ip = d.get("ip", "")
            name = _device_display_name(d)
            label = f"{name}  \u2014  {ip}" if name and name != ip else ip
            self.ps_target.addItem(label, (ip, name if name != ip else ""))
        # Keep what the user already picked or typed; otherwise start on the router.
        keep = next((i for i in range(self.ps_target.count())
                     if self.ps_target.itemData(i)[0] == previous_ip), -1)
        if keep >= 0:
            self.ps_target.setCurrentIndex(keep)
        elif typed:
            self.ps_target.setCurrentIndex(-1)
            self.ps_target.setEditText(typed)
        else:
            self.ps_target.setCurrentIndex(0)

    def _selected_target(self):
        """Return (ip_or_host, display_name) for the chosen port scan target."""
        text = self.ps_target.currentText().strip()
        idx = self.ps_target.currentIndex()
        if idx >= 0 and self.ps_target.itemText(idx) == text:
            ip, name = self.ps_target.itemData(idx)
            return ip, name
        return text, ""

    # -- Styling --
    def _section_option(self, key, label, icon_name):
        """Create a row whose icon, label, or checkbox toggles the option."""
        frame = QFrame()
        frame.setObjectName("SectOpt")
        frame.setCursor(Qt.CursorShape.PointingHandCursor)
        frame.setStyleSheet(
            f"#SectOpt {{ background: {Theme.BG_ELEVATED};"
            f"border: 1px solid {Theme.BORDER}; border-radius: 8px; }}"
            f"#SectOpt:hover {{ border-color: {Theme.ACCENT}; }}"
            f"#SectOpt QLabel {{ background: transparent; border: none; }}"
        )
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(10)

        icon_lbl = QLabel()
        icon_lbl.setPixmap(Icons.pixmap(icon_name, 15, Theme.ACCENT))
        lay.addWidget(icon_lbl)

        text = QLabel(label)
        text.setStyleSheet(
            f"color: {Theme.TEXT_BODY}; font-size: {Theme.FONT_SIZE_SMALL}px;"
        )
        lay.addWidget(text)
        lay.addStretch()

        cb = QCheckBox()
        cb.setChecked(True)
        cb.setStyleSheet(self._checkbox_style())
        cb.setCursor(Qt.CursorShape.PointingHandCursor)
        self._checks[key] = cb
        lay.addWidget(cb)

        # Click anywhere on the row toggles the checkbox
        def toggle(event):
            cb.setChecked(not cb.isChecked())
        frame.mousePressEvent = toggle

        return frame

    def _checkbox_style(self):
        check_png = Icons.png_path("checkmark", 13, "#ffffff")
        return (
            f"QCheckBox {{ background: transparent; spacing: 0; }}"
            f"QCheckBox::indicator {{ width: 20px; height: 20px; border-radius: 5px;"
            f"border: 1px solid {Theme.BORDER_STRONG}; background: {Theme.BG_CARD}; }}"
            f"QCheckBox::indicator:hover {{ border-color: {Theme.ACCENT}; }}"
            f"QCheckBox::indicator:checked {{ background: {Theme.ACCENT};"
            f"border-color: {Theme.ACCENT}; image: url({check_png}); }}"
        )

    def _primary_button_style(self):
        return (
            f"QPushButton {{ background: {Theme.GRAD_ACCENT}; color: white;"
            f"border: none; border-radius: 6px; padding: 9px 14px;"
            f"font-size: {Theme.FONT_SIZE_SMALL}px; font-weight: 600; }}"
            f"QPushButton:hover {{ background: {Theme.ACCENT_PURPLE}; }}"
        )

    def _secondary_button_style(self):
        return (
            f"QPushButton {{ background: {Theme.BG_ELEVATED}; color: {Theme.TEXT_BODY};"
            f"border: 1px solid {Theme.BORDER_STRONG}; border-radius: 6px;"
            f"padding: 9px 14px; font-size: {Theme.FONT_SIZE_SMALL}px; }}"
            f"QPushButton:hover {{ border-color: {Theme.ACCENT}; }}"
            f"QPushButton:disabled {{ color: {Theme.TEXT_FAINT}; }}"
        )

    # -- Generate --
    def _generate(self):
        sections = [k for k, cb in self._checks.items() if cb.isChecked()]
        if not sections:
            self._status.setText("Select at least one section.")
            return
        target, target_name, profile = "", "", "common"
        if "port_scan" in sections:
            target, target_name = self._selected_target()
            if not target:
                self._status.setText(
                    "Pick a device (or type an IP) for the port scan.")
                return
            profile = self.ps_profile.currentData() or "common"
        self.btn_generate.setEnabled(False)
        self.btn_save.setEnabled(False)
        self._status.setText("Collecting data… (scanning may take a few seconds)")
        self._show_loading("Collecting network data\u2026")

        # Collect data in a worker, then build the PDF
        w = OneshotWorker(report_data.collect, self.core, sections,
                          target, profile, target_name)
        w.result.connect(lambda data: self._on_data(data, sections))
        w.error.connect(self._on_error)
        self.register_worker(w)
        w.start()

    def _on_data(self, data, sections):
        # Build the PDF in a temporary file.
        try:
            tmp = os.path.join(tempfile.gettempdir(),
                               f"netwer_preview_{datetime.now():%H%M%S}.pdf")
            build_report(tmp, data, sections)
            self._temp_pdf = tmp
            self._show_preview(tmp)
            self.btn_save.setEnabled(True)
            self._status.setText("Preview ready. Click Save PDF to export.")
        except Exception as e:
            self._status.setText(f"Build failed: {e}")
        finally:
            self.btn_generate.setEnabled(True)

    def _on_error(self, msg):
        self._clear_preview()
        self._status.setText(f"Error: {msg}")
        self.btn_generate.setEnabled(True)

    def _clear_preview(self):
        while self._preview_layout.count():
            item = self._preview_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _show_loading(self, text):
        """Show a centered progress indicator in the preview area."""
        self._clear_preview()
        self._preview_layout.addStretch()
        spin = Spinner(size=40)
        self._preview_layout.addWidget(spin, alignment=Qt.AlignmentFlag.AlignCenter)
        spin.start()
        lbl = QLabel(text)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet(
            f"color: {Theme.TEXT_SECONDARY}; font-size: {Theme.FONT_SIZE_BODY}px;"
            f"background: transparent; padding-top: 14px;")
        self._preview_layout.addWidget(lbl, alignment=Qt.AlignmentFlag.AlignCenter)
        self._preview_layout.addStretch()

    # -- Preview rendering --
    def _show_preview(self, pdf_path):
        # Clear existing preview
        while self._preview_layout.count():
            item = self._preview_layout.takeAt(0)
            wgt = item.widget()
            if wgt:
                wgt.deleteLater()

        self._pdf_doc.load(pdf_path)
        page_count = self._pdf_doc.pageCount()
        for i in range(page_count):
            size = self._pdf_doc.pagePointSize(i)
            # Render at ~1.4x for crisp preview
            scale = 1.4
            from PyQt6.QtCore import QSize
            img_size = QSize(int(size.width() * scale), int(size.height() * scale))
            image = self._pdf_doc.render(i, img_size)
            if image.isNull():
                continue
            pm = QPixmap.fromImage(image)
            lbl = QLabel()
            lbl.setPixmap(pm)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet(f"background: white; border: 1px solid {Theme.BORDER_STRONG};")
            self._preview_layout.addWidget(lbl, alignment=Qt.AlignmentFlag.AlignCenter)
        self._preview_layout.addStretch()

    # -- Save --
    def _save(self):
        if not self._temp_pdf or not os.path.exists(self._temp_pdf):
            self._status.setText("Generate a preview first.")
            return
        from PyQt6.QtWidgets import QFileDialog
        default = os.path.join(
            os.path.join(os.path.expanduser("~"), "Desktop"),
            f"NETWER_Report_{datetime.now():%Y%m%d_%H%M}.pdf")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save PDF Report", default, "PDF files (*.pdf)")
        if not path:
            return
        try:
            import shutil
            shutil.copyfile(self._temp_pdf, path)
            self._status.setText(f"Saved \u2713  {path}")
            import os as _os

            from app.activity import activity
            activity.add("Report saved", _os.path.basename(path), kind="success")
        except Exception as e:
            self._status.setText(f"Save failed: {e}")
