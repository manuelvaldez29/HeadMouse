"""Diagnóstico local de procesos; sin frames, landmarks ni muestras de mirada."""
import faulthandler
import logging
from logging.handlers import RotatingFileHandler
import platform
import sys
import threading
from datetime import datetime, timezone
from importlib.metadata import version, PackageNotFoundError

_fault_stream = None  # debe vivir mientras faulthandler escribe desde código nativo
_emergency_handler = None


def register_emergency_handler(handler):
    global _emergency_handler
    _emergency_handler = handler


def revoke_output():
    if _emergency_handler:
        try:
            _emergency_handler()
        except Exception:
            logging.exception("No se pudo revocar salida tras excepción no controlada")


def install(directory):
    global _fault_stream
    directory.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(directory / "headmouse.log", maxBytes=2_000_000,
                                  backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s [%(threadName)s] %(name)s: %(message)s"))
    logging.getLogger().addHandler(handler)
    if _fault_stream is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        _fault_stream = (directory / f"fault-{stamp}.log").open("a", encoding="utf-8")
        faulthandler.enable(file=_fault_stream, all_threads=True)
    previous = sys.excepthook
    def unhandled(kind, value, traceback):
        revoke_output()
        logging.critical("Excepción Python no controlada", exc_info=(kind, value, traceback))
        previous(kind, value, traceback)
    sys.excepthook = unhandled
    def thread_error(args):
        revoke_output()
        logging.critical("Excepción no controlada en %s", args.thread.name,
                         exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
    threading.excepthook = thread_error
    dependencies = {}
    for name in ("mediapipe", "opencv-contrib-python", "numpy", "PySide6", "PyAutoGUI"):
        try:
            dependencies[name] = version(name)
        except PackageNotFoundError:
            dependencies[name] = "ausente"
    logging.info("Inicio HeadMouse Python=%s plataforma=%s dependencias=%s",
                 platform.python_version(), sys.platform, dependencies)
    return handler
