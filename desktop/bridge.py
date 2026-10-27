"""Adaptador Qt con worker dedicado y mailbox de capacidad uno para preview."""
import logging
import threading
from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot, Qt
from application_controller import ApplicationController

COMMANDS = {"create_profile", "select_profile", "rename_profile", "delete_profile", "save_settings",
            "select_control_method", "select_eye_source", "save_public_settings", "upgrade_ocular_response",
            "start_vertical_diagnostic", "repeat_vertical_point", "cancel_vertical_diagnostic",
            "start_gaze_calibration", "repeat_gaze_point", "save_gaze_calibration", "cancel_gaze_calibration",
            "start_eye_calibration", "save_eye_calibration", "cancel_eye_calibration",
            "restore_defaults", "start_camera", "stop_camera", "activate_control", "stop_control",
            "start_diagnostic", "start_calibration", "validate_calibration", "repeat_calibration",
            "save_calibration", "start_experiment", "experiment_input", "cancel_experiment",
            "start_jitter", "prepare_model", "refresh_metrics", "shutdown", "set_calibration_gesture", "prepare_voice_model"}
CAMERA_COMMANDS = {"start_camera", "start_calibration", "validate_calibration", "repeat_calibration",
    "start_vertical_diagnostic",
    "start_eye_calibration", "start_gaze_calibration", "start_diagnostic", "activate_control", "start_jitter", "start_experiment"}


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
    snapshot_ready = Signal()

    def __init__(self, controller, mailbox):
        super().__init__()
        self.controller, self.mailbox = controller, mailbox
        self.profiles = []
        self.timer = None
        self.stopping = False
        self.pending_camera = None

    def failed(self, exc):
        self.controller.emergency_stop()
        logging.getLogger(__name__).exception("Fallo del worker")
        try:
            self.controller.fail(str(exc))
        except Exception:
            logging.getLogger(__name__).exception("Limpieza pendiente; se conserva el worker")
        self.error.emit(str(exc))

    @Slot()
    def start(self):
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        try:
            self.profiles = self.controller.profiles.list_profiles()
            self.publish()
        except Exception as exc:
            self.failed(exc)

    def publish(self):
        snapshot = self.controller.snapshot()
        snapshot["profiles"] = self.profiles
        self.mailbox.put(snapshot)
        self.snapshot_ready.emit()

    @Slot(str, object)
    def command(self, name, kwargs):
        if self.stopping and name != "shutdown":
            return
        if name not in COMMANDS:
            self.error.emit("Operación no disponible")
            return
        try:
            if name in ("stop_camera", "shutdown", "stop_control", "select_profile", "save_settings", "save_public_settings", "select_control_method", "select_eye_source", "upgrade_ocular_response", "cancel_eye_calibration", "cancel_gaze_calibration", "cancel_vertical_diagnostic"):
                pending = self.pending_camera
                self.pending_camera = None
                if pending:
                    self.controller.cancel_camera_startup()
                    if name not in ("stop_camera", "shutdown"):
                        self.controller.stop_camera()
            if self.pending_camera and name in CAMERA_COMMANDS:
                self.error.emit("La cámara ya se está iniciando; esperá o cancelá antes de reiniciar")
                return
            if name == "shutdown":
                self.stopping = True
                self.timer.stop()
            needs_camera = name in CAMERA_COMMANDS and not (name=="start_experiment" and kwargs.get("source","headmouse")!="headmouse")
            if needs_camera and isinstance(self.controller,ApplicationController) and self.controller.vision is None:
                if name == "activate_control":
                    self.controller.require_control_profile()
                    self.controller._require_tracking_calibration()
                    if not kwargs.get("confirmed") or self.controller.emergency.is_set():
                        raise ValueError("La activación fue cancelada o no está autorizada")
                self.controller.start_camera(wait=False)
                self.pending_camera = (name,kwargs)
                self.publish()
                return
            getattr(self.controller, name)(**kwargs)
            if name == "shutdown":
                self.timer.stop()
                self.finished.emit()
                return
            if name != "experiment_input":
                self.profiles = self.controller.profiles.list_profiles()
            self.publish()
        except Exception as exc:
            logging.getLogger(__name__).exception("No se pudo completar %s", name)
            self.controller.message = str(exc)
            self.error.emit(str(exc))
            if name == "shutdown":
                # Un driver aún vivo no permite destruir QThread ni sus recursos.
                logging.getLogger(__name__).error("Cierre pendiente: se reintentará sin terminar hilos nativos")
                QTimer.singleShot(1000, lambda: self.command("shutdown", {}))
                return
            self.controller.emergency_stop()

    @Slot()
    def tick(self):
        if self.stopping:
            return
        try:
            if self.pending_camera:
                if not self.controller.poll_camera_startup():
                    self.publish()
                    return
                name,kwargs = self.pending_camera
                self.pending_camera = None
                getattr(self.controller,name)(**kwargs)
            self.controller.step()
            self.publish()
        except Exception as exc:
            self.pending_camera = None
            self.failed(exc)


class DesktopBridge(QObject):
    command_requested = Signal(str, object)
    error = Signal(str)
    closed = Signal()
    snapshot_ready = Signal()

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
        self.worker.snapshot_ready.connect(self.snapshot_ready)
        self.worker.finished.connect(self.thread.quit, Qt.ConnectionType.DirectConnection)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.closed)
        self.thread.start()

    def request(self, command_name, **kwargs):
        if command_name in ("stop_camera", "shutdown", "cancel_eye_calibration", "cancel_gaze_calibration", "cancel_vertical_diagnostic"):
            self.controller.cancel_camera_startup()
        self.command_requested.emit(command_name, kwargs)

    def activate(self, screen_context=None):
        self.controller.emergency.clear()  # llamada solo después del diálogo de confirmación
        self.request("activate_control", confirmed=True, screen_context=screen_context)

    def stop(self):
        self.controller.emergency_stop()
        self.request("stop_control")

    def shutdown(self):
        self.controller.emergency_stop()
        self.request("shutdown")

    def finish_shutdown(self):
        """También cubre QApplication.quit externo al cierre de la ventana."""
        if self.thread.isRunning():
            self.shutdown()
            while not self.thread.wait(1000):
                logging.getLogger(__name__).warning("Esperando cierre seguro del worker")

    def snapshot(self):
        return self.mailbox.get()
