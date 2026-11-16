"""Recursos de sólo lectura y datos persistentes por usuario, también en PyInstaller."""
import os
from pathlib import Path
import sys

RESOURCE_ROOT = Path(__file__).resolve().parent
VERSION = "0.6.0"
APP_NAME = "CONFA"
APP_FULL_NAME = "Controlador Facial y Asistente de voz"
ASSISTANT_NAME = "Gema"  # asistente de voz de CONFA; con una m (Gemma es otra cosa, de Google)
LEGACY_APP_NAME = "HeadMouse"  # nombre hasta noviembre de 2026: carpeta de datos y registro de inicio

_resolved = {}


def data_root():
    override = os.environ.get("CONFA_DATA_DIR") or os.environ.get("HEADMOUSE_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    base = Path(os.environ.get("LOCALAPPDATA", Path.home()/"AppData"/"Local")) if sys.platform == "win32" else Path.home()/".local"/"share"
    if base not in _resolved:
        _resolved[base] = adopt_legacy_root(base/APP_NAME, base/LEGACY_APP_NAME)
    return _resolved[base]


def adopt_legacy_root(current, legacy):
    """La primera vez que abre CONFA, la carpeta de HeadMouse (perfiles, modelos, métricas) pasa a
    llamarse CONFA. Se renombra, no se copia: los modelos pesan cientos de MB. Si no se puede
    (por ejemplo, la versión anterior sigue abierta) se sigue usando la vieja y se reintenta
    en el próximo inicio; nunca se mezclan ni se pisan dos carpetas."""
    if current.exists() or not legacy.is_dir():
        return current
    try:
        legacy.rename(current)
    except OSError:
        return legacy
    return current


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
