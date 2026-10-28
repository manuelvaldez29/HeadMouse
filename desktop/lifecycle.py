"""Liberación explícita de widgets una vez finalizado el worker."""
from PySide6.QtCore import QCoreApplication, QEvent, QThread
from shiboken6 import isValid


def release_overlays(window):
    """Avisos flotantes sin dueño nativo (para que Windows no los esconda al minimizar
    la principal): se cierran y destruyen explícitamente con la ventana."""
    for overlay in getattr(window, "owned_overlays", ()):
        if isValid(overlay):
            overlay.close()
            overlay.deleteLater()
            QCoreApplication.sendPostedEvents(overlay, QEvent.Type.DeferredDelete)


def dispose_window(window):
    thread = getattr(window.bridge, "thread", None)
    if isinstance(thread, QThread) and thread.isRunning():
        raise RuntimeError("No destruir la ventana mientras el worker sigue activo")
    release_overlays(window)
    window.deleteLater()
    QCoreApplication.sendPostedEvents(window, QEvent.Type.DeferredDelete)
