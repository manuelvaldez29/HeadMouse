"""Liberación explícita de widgets una vez finalizado el worker."""
from PySide6.QtCore import QCoreApplication, QEvent, QThread


def dispose_window(window):
    thread = getattr(window.bridge, "thread", None)
    if isinstance(thread, QThread) and thread.isRunning():
        raise RuntimeError("No destruir la ventana mientras el worker sigue activo")
    window.deleteLater()
    QCoreApplication.sendPostedEvents(window, QEvent.Type.DeferredDelete)
