"""NETWER — Core package initialization.

Extends the built-in OUI lookup table with additional MAC vendors and
pre-warms system monitoring hooks.
"""
from core import netwer_core
from core.oui_extended import EXTENDED_OUI

# Populate the OUI lookup table with extended vendor mappings.
# setdefault() ensures existing core vendor entries are preserved without overwriting.
for prefix, vendor in EXTENDED_OUI.items():
    netwer_core.OUI_TABLE.setdefault(prefix, vendor)

# Warm up psutil CPU tracking upon module load.
# The initial cpu_percent() call always returns 0.0 because it lacks a prior baseline point.
# Calling it here ensures all subsequent UI gauge updates report accurate metrics immediately.
try:
    import psutil
    psutil.cpu_percent(interval=None)
except Exception:
    pass
