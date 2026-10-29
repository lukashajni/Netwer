"""Small shared styles for the redesigned pages (buttons, chips, pills)."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QPushButton

from app.resources import Icons
from app.theme import Theme, input_bg


def button(text: str, icon: str = "", kind: str = "normal", tip: str = "") -> QPushButton:
    """kind: normal | primary | danger | ai | toggle"""
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


SEVERITY_COLORS = {"success": "SUCCESS", "warning": "WARNING", "danger": "DANGER", "info": "ACCENT"}


def insight_chip(text: str, detail: str, severity: str) -> QPushButton:
    """A clickable finding with a coloured severity bar on the left."""
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
