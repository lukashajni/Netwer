import subprocess
import sys

_NO_WINDOW = 0x08000000   # CREATE_NO_WINDOW


def hide_subprocess_windows():
    """Child processes started by Netwer never open a console window on Windows."""
    if sys.platform != "win32" or getattr(subprocess.Popen, "_netwer_hidden", False):
        return
    original = subprocess.Popen.__init__

    def init(self, *args, **kwargs):
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | _NO_WINDOW
        original(self, *args, **kwargs)

    subprocess.Popen.__init__ = init
    subprocess.Popen._netwer_hidden = True
