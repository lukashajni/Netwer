"""
NETWER — Report page.

Generate a branded PDF network report. The user picks which sections to
include (checkboxes), clicks Generate to build a preview shown inside the
app, then Save PDF to write it wherever they choose.

Data collection + PDF building run in a worker (they hit the network and
scan devices), so the UI never freezes.
"""

import os
import tempfile
from datetime import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox, QPushButton,
    QScrollArea, QFrame
)
from PyQt6.QtGui import QPixmap
from PyQt6.QtPdf import QPdfDocument

from app.theme import Theme
from app.resources import Icons
from ui.pages.base_page import BasePage
from ui.widgets.card import Card
from ui.widgets.spinner import Spinner
from workers import OneshotWorker
from reports import report_data
from reports.pdf_report import build_report, SECTION_LABELS, ALL_SECTIONS


class ReportPage(BasePage):
    PAGE_TITLE = "Save Report"
    PAGE_SUBTITLE = "Generate a professional PDF network report"

    def __init__(self, core, parent=None):
        super().__init__(core, parent)

        self._temp_pdf = None
        self._pdf_doc = QPdfDocument(self)

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

        self._preview_placeholder = QLabel(
            "Choose sections and click Generate Preview")
        self._preview_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_placeholder.setStyleSheet(
            f"color: {Theme.TEXT_MUTED}; font-size: {Theme.FONT_SIZE_BODY}px;"
            f"background: transparent; padding: 40px;"
        )
        self._preview_layout.addWidget(self._preview_placeholder)
        self._preview_scroll.setWidget(self._preview_holder)
        preview_card.content_layout.addWidget(self._preview_scroll)

        row.addWidget(preview_card, 1)
        self.body_layout.addLayout(row)

    # -- Styling --
    def _section_option(self, key, label, icon_name):
        """A clickable row with an icon, label, and a checkbox — nicer than
        a bare checkbox. Clicking anywhere toggles it."""
        from ui.widgets.card import Card  # not needed, build a frame
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
        self.btn_generate.setEnabled(False)
        self.btn_save.setEnabled(False)
        self._status.setText("Collecting data… (scanning may take a few seconds)")
        self._show_loading("Collecting network data\u2026")

        # Collect data in a worker, then build the PDF
        w = OneshotWorker(report_data.collect, self.core, sections)
        w.result.connect(lambda data: self._on_data(data, sections))
        w.error.connect(self._on_error)
        self.register_worker(w)
        w.start()

    def _on_data(self, data, sections):
        # Build PDF to a temp file (still off the UI-blocking path, building
        # is fast once data is gathered)
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
        """Replace the preview area with a centered spinner + message so it's
        obvious the report is being built (not just a small status line)."""
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
        from PyQt6.QtCore import QSizeF
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
            from app.activity import activity
            import os as _os
            activity.add("Report saved", _os.path.basename(path), kind="success")
        except Exception as e:
            self._status.setText(f"Save failed: {e}")
