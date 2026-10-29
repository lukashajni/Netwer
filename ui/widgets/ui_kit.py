from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from app.resources import Icons
from app.theme import Theme, input_bg


def button(text: str, icon: str = "", kind: str = "normal", tip: str = "") -> QPushButton:
    b = QPushButton(("  " + text) if (icon and text) else text)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if tip:
        b.setToolTip(tip)
    style_button(b, kind, icon)
    return b


def style_button(b: QPushButton, kind: str = "normal", icon: str = "") -> None:
    fg = {"primary": "#ffffff", "danger": Theme.DANGER, "ai": Theme.ACCENT_GLOW}.get(kind, Theme.TEXT_BODY)
    if icon:
        b.setIcon(Icons.get(icon, fg))
    base = (f"padding: 5px 12px; border-radius: {Theme.RADIUS_CONTROL - 3}px;"
            f"font-size: {Theme.FONT_SIZE_SMALL}px;")
    if kind == "primary":
        css = (f"QPushButton {{ background: {Theme.ACCENT}; color: #ffffff; border: 1px solid {Theme.ACCENT}; {base} }}"
               f"QPushButton:hover {{ background: {Theme.ACCENT_HOVER}; }}")
    elif kind == "danger":
        css = (f"QPushButton {{ background: transparent; color: {Theme.DANGER}; border: 1px solid {Theme.DANGER}; {base} }}"
               f"QPushButton:hover {{ background: {Theme.DANGER}; color: #ffffff; }}")
    elif kind == "ai":
        css = (f"QPushButton {{ background: {input_bg()}; color: {Theme.TEXT_PRIMARY};"
               f"border: 1px solid {Theme.ACCENT_PURPLE}; {base} }}"
               f"QPushButton:hover {{ background: {Theme.BG_ELEVATED}; }}")
    else:
        css = (f"QPushButton {{ background: {input_bg()}; color: {Theme.TEXT_BODY};"
               f"border: 1px solid {Theme.GLASS_BORDER}; {base} }}"
               f"QPushButton:hover {{ border-color: {Theme.GLASS_BORDER_HI}; color: {Theme.TEXT_PRIMARY}; }}"
               f"QPushButton:checked {{ border-color: {Theme.ACCENT}; color: {Theme.ACCENT}; }}"
               f"QPushButton:disabled {{ color: {Theme.TEXT_FAINT}; }}")
    b.setStyleSheet(css)


def chip(text: str, tip: str = "") -> QPushButton:
    b = QPushButton(text)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if tip:
        b.setToolTip(tip)
    b.setStyleSheet(
        f"QPushButton {{ background: {input_bg()}; color: {Theme.TEXT_SECONDARY};"
        f"border: 1px solid {Theme.GLASS_BORDER}; border-radius: 7px; padding: 3px 9px;"
        f"font-family: {Theme.FONT_MONO}; font-size: {Theme.FONT_SIZE_TINY}px; }}"
        f"QPushButton:hover {{ color: {Theme.TEXT_PRIMARY}; border-color: {Theme.GLASS_BORDER_HI}; }}")
    return b


def empty_state(icon: str, title: str, text: str, width: int = 420) -> QWidget:
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 30, 0, 30)
    lay.setSpacing(8)
    lay.addStretch()
    ic = QLabel()
    ic.setFixedSize(52, 52)
    ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
    ic.setPixmap(Icons.pixmap(icon, 22, Theme.ACCENT))
    ic.setStyleSheet(f"background: {input_bg()}; border: 1px solid {Theme.GLASS_BORDER}; border-radius: 14px;")
    lay.addWidget(ic, 0, Qt.AlignmentFlag.AlignHCenter)
    t = QLabel(title)
    t.setStyleSheet(f"color: {Theme.TEXT_PRIMARY}; font-size: {Theme.FONT_SIZE_HEADING}px; font-weight: 600;"
                    "background: transparent;")
    lay.addWidget(t, 0, Qt.AlignmentFlag.AlignHCenter)
    d = QLabel(text)
    d.setWordWrap(True)
    d.setFixedWidth(width)
    d.setAlignment(Qt.AlignmentFlag.AlignCenter)
    d.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: {Theme.FONT_SIZE_SMALL}px; background: transparent;")
    # wrapped labels don't grow on their own inside a centred layout
    d.ensurePolished()
    d.setMinimumHeight(d.heightForWidth(width))
    lay.addWidget(d, 0, Qt.AlignmentFlag.AlignHCenter)
    lay.addStretch()
    return w


SEVERITY_COLORS ={"success": "SUCCESS", "warning": "WARNING", "danger": "DANGER", "info": "ACCENT"}


def insight_chip(text: str, detail: str, severity: str) -> QPushButton:
    color = getattr(Theme, SEVERITY_COLORS.get(severity, "ACCENT"))
    label = text + (f"  ·  {detail}" if detail else "")
    b = QPushButton(label)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setStyleSheet(
        f"QPushButton {{ background: {input_bg()}; color: {Theme.TEXT_BODY};"
        f"border: 1px solid {Theme.GLASS_BORDER}; border-left: 4px solid {color};"
        f"border-radius: 7px; padding: 4px 10px; font-size: {Theme.FONT_SIZE_SMALL}px; text-align: left; }}"
        f"QPushButton:hover {{ border-color: {Theme.GLASS_BORDER_HI}; border-left-color: {color}; color: {Theme.TEXT_PRIMARY}; }}")
    return b


# row of finding chips, a click asks Netwer AI about it
class InsightRow(QWidget):
    def __init__(self, on_ask, label="FINDINGS", parent=None):
        super().__init__(parent)
        self._on_ask = on_ask
        self._sig = None
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        title = QLabel(label)
        title.setStyleSheet(f"color: {Theme.ACCENT_GLOW}; font-size: 10px; font-weight: 700;"
                            "letter-spacing: 1.2px; background: transparent;")
        lay.addWidget(title)
        self._chips = QHBoxLayout()
        self._chips.setSpacing(8)
        lay.addLayout(self._chips)
        lay.addStretch()
        self.hide()

    def set_items(self, items):
        # items: dicts with severity, text, detail and question
        sig = [(i["text"], i.get("detail", "")) for i in items]
        if sig == self._sig:
            return
        self._sig = sig
        while self._chips.count():
            w = self._chips.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        for it in items[:5]:
            b = insight_chip(it["text"], it.get("detail", ""), it["severity"])
            b.clicked.connect(lambda _=False, it=it: self._clicked(it))
            self._chips.addWidget(b)
        self.setVisible(bool(items))

    def _clicked(self, it):
        # "before" lets a page react first, e.g. apply a filter
        if it.get("before"):
            it["before"]()
        self._on_ask(it["question"])
