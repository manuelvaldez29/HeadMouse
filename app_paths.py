"""Recursos de sólo lectura y datos persistentes por usuario, también en PyInstaller."""
import os
from pathlib import Path
import sys

RESOURCE_ROOT = Path(__file__).resolve().parent
VERSION = "0.4.0"


def data_root():
    override = os.environ.get("HEADMOUSE_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    base = Path(os.environ.get("LOCALAPPDATA", Path.home()/"AppData"/"Local")) if sys.platform == "win32" else Path.home()/".local"/"share"
    return base/"HeadMouse"


def face_model_path(value="models/face_landmarker.task"):
    path = Path(value)
    if path.is_absolute():
        return path
    bundled = RESOURCE_ROOT/path
    return bundled if bundled.is_file() else data_root()/path


def launch_command():
    if getattr(sys,"frozen",False):
        return [sys.executable,"--autostart"]
    python = Path(sys.executable).with_name("pythonw.exe") if sys.platform=="win32" else Path(sys.executable)
    return [str(python),str(RESOURCE_ROOT/"app.py"),"--autostart"]
