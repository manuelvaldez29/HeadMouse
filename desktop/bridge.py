"""Adaptador Qt con worker dedicado y mailbox de capacidad uno para preview."""
import logging
import threading
from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot, Qt
from application_controller import ApplicationController

COMMANDS = {"create_profile", "select_profile", "rename_profile", "delete_profile", "save_settings",
            "restore_defaults", "start_camera", "stop_camera", "activate_control", "stop_control",
            "start_diagnostic", "start_calibration", "validate_calibration", "repeat_calibration",
            "save_calibration", "start_experiment", "experiment_input", "cancel_experiment",
            "start_jitter", "prepare_model", "refresh_metrics", "shutdown"}


class Mailbox:
    def __init__(self):
        self.lock = threading.Lock()
        self.latest = {}

    def put(self, snapshot):
        with self.lock:
            self.latest = snapshot

    def get(self):
        with self.lock:
            return self.latest  # snapshot publicado no se modifica después


class ControllerWorker(QObject):
    error = Signal(str)
    finished = Signal()

    def __init__(self, controller, mailbox):
        super().__init__()
        self.controller, self.mailbox = controller, mailbox
        self.profiles = []

    @Slot()
    def start(self):
        self.profiles = self.controller.profiles.list_profiles()
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        self.publish()

    def publish(self):
        snapshot = self.controller.snapshot()
        snapshot["profiles"] = self.profiles
        self.mailbox.put(snapshot)

    @Slot(str, object)
    def command(self, name, kwargs):
        if name not in COMMANDS:
            self.error.emit("Operación no disponible")
            return
        try:
            getattr(self.controller, name)(**kwargs)
            if name == "shutdown":
                self.timer.stop()
                self.finished.emit()
                return
            if name != "experiment_input":
                self.profiles = self.controller.profiles.list_profiles()
        except Exception as exc:
            logging.getLogger(__name__).exception("No se pudo completar %s", name)
            self.controller.message = str(exc)
            self.error.emit(str(exc))
            if name == "shutdown":
                self.timer.stop()
                self.finished.emit()
                return
        self.publish()

    @Slot()
    def tick(self):
        try:
            self.controller.step()
        except Exception as exc:
            logging.getLogger(__name__).exception("Sesión detenida")
            try:
                self.controller.fail(str(exc))
            except Exception:
                logging.getLogger(__name__).exception("Error durante limpieza")
            self.error.emit(str(exc))
        self.publish()


class DesktopBridge(QObject):
    command_requested = Signal(str, object)
    error = Signal(str)
    closed = Signal()

    def __init__(self, controller=None, parent=None):
        super().__init__(parent)
        self.controller = controller or ApplicationController()
        self.mailbox = Mailbox()
        self.thread = QThread(self)
        self.thread.setObjectName("HeadMouseApplication")
        self.worker = ControllerWorker(self.controller, self.mailbox)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.start)
        self.command_requested.connect(self.worker.command, Qt.ConnectionType.QueuedConnection)
        self.worker.error.connect(self.error)
        self.worker.finished.connect(self.thread.quit, Qt.ConnectionType.DirectConnection)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.closed)
        self.thread.start()

    def request(self, command_name, **kwargs):
        self.command_requested.emit(command_name, kwargs)

    def activate(self):
        self.controller.emergency.clear()  # llamada solo después del diálogo de confirmación
        self.request("activate_control", confirmed=True)

    def stop(self):
        self.controller.emergency_stop()
        self.request("stop_control")

    def shutdown(self):
        self.controller.emergency_stop()
        self.request("shutdown")

    def snapshot(self):
        return self.mailbox.get()
