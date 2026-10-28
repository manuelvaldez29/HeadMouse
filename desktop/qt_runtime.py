"""Preparación de Qt en macOS cuando el entorno oculta sus plugins instalados."""
import logging
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile


def prepare_qt_platform_plugins():
    """Qt omite archivos con UF_HIDDEN al enumerar plugins en macOS.

    Copiar sólo los plugins de plataforma a un directorio temporal privado.
    No reinstala Qt, no abre dispositivos y respeta una ruta explícita del usuario.
    """
    if sys.platform != "darwin" or os.environ.get("QT_QPA_PLATFORM_PLUGIN_PATH"):
        return None
    from PySide6.QtCore import QLibraryInfo, qVersion
    source = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath)) / "platforms"
    plugins = list(source.glob("*.dylib"))
    if not any(p.stat().st_flags & stat.UF_HIDDEN for p in plugins):
        return None
    # mkdtemp evita reutilizar archivos reemplazables por otros procesos/usuarios.
    target = Path(tempfile.mkdtemp(prefix=f"headmouse-qt-{qVersion()}-"))
    try:
        for plugin in plugins:
            shutil.copyfile(plugin, target / plugin.name)
    except Exception:
        shutil.rmtree(target)
        raise
    os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(target)
    # Mantener archivos hasta finalizar QApplication; Qt puede cargarlos tarde.
    import atexit
    atexit.register(shutil.rmtree, target, ignore_errors=True)
    logging.info("Qt macOS: plugins de plataforma ocultos; usando copia temporal visible")
    return target
