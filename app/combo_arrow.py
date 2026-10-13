import os
import re
import tempfile

from PyQt6.QtCore import QEvent, QObject
from PyQt6.QtWidgets import QApplication, QComboBox

from app.resources import Icons
from app.theme import Theme

_DROP_DOWN = re.compile(r"QComboBox::drop-down\s*\{[^}]*\}")


def arrow_url() -> str:
    # icons need a running QApplication
    if QApplication.instance() is None:
        return ""
    # One PNG per colour so a theme change never shows a stale arrow
    name = f"netwer_chevron_{Theme.TEXT_SECONDARY.lstrip('#')}.png"
    path = os.path.join(tempfile.gettempdir(), name)
    if not os.path.exists(path):
        Icons.pixmap("chevron_down", 12, Theme.TEXT_SECONDARY).save(path, "PNG")
    return path.replace("\\", "/")


def arrow_rules() -> str:
    return (
        "QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: center right;"
        " border: none; width: 26px; }"
        f"QComboBox::down-arrow {{ image: url({arrow_url()}); width: 12px; height: 12px; }}")


class ComboArrowFilter(QObject):
    """Gives every drop-down a visible arrow, whatever style it already has."""

    def eventFilter(self, obj, event):
        if (event.type() == QEvent.Type.Show and isinstance(obj, QComboBox)
                and not obj.property("netwer_arrow")):
            obj.setProperty("netwer_arrow", True)
            sheet = obj.styleSheet()
            if sheet:
                obj.setStyleSheet(_DROP_DOWN.sub("", sheet) + arrow_rules())
        return False
