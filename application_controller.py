"""Coordinación desktop sin dependencia de Qt. Un único worker posee el estado."""
import json
import threading
import time
import uuid
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from action_mapping import ActionMapping, gesture_identity
from calibration_session import CalibrationSession
from config import ROOT, load_config
from control_engine import ControlEngine
from experiment_engine import ExperimentEngine, JitterMeasurement, ResultStore
from face_data import FaceData
from gesture_engine import GestureEngine
from metrics import SessionMetrics
from profile_manager import ProfileManager
from tracking import create_strategy


class ApplicationController:
    def __init__(self, profiles=None, vision_factory=None, backend_factory=None,
                 data_dir=None, clock=time.monotonic, dictation_factory=None):
        self.profiles = profiles or ProfileManager()
        self.vision_factory = vision_factory
        self.backend_factory = backend_factory
        self.dictation_factory = dictation_factory
        self.dictation = None
        self._voice_download = None
        self._models, self._models_checked = {}, -1e9
        self.data_dir = Path(data_dir) if data_dir else ROOT / "data"
        self.clock = clock
        self.emergency = threading.Event()
        self.emergency.set()
        self.profile = None
        self.config = load_config()
        self.vision = self.gesture = self.control = self.metrics = None
        self.wizard = self.experiment = self.jitter = None
        self._calibration_session_id = None
        self._calibration_logged = 0
        self.jitter_result = None
        self.state = "HOME"
        self.message = "Elegí o creá un perfil para comenzar."
        self.last_gesture = self.last_action = "—"
        self._event_at = 0.
        self._last_face = 0
        self.cursor = (400., 250.)
        self.closed = False
        self.history = []
        self.refresh_metrics()
        self._restore_last_profile()

    # ── Último perfil usado ───────────────────────────────────────────────────
    # Al abrir la app el último perfil queda elegido: con un solo click se inicia.

    @property
    def _last_profile_path(self):
        return self.data_dir / "last_profile.json"

    def _remember_profile(self):
        from profiles import replace_with_retry
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            temporary = self._last_profile_path.with_suffix(".tmp")
            temporary.write_text(json.dumps({"user_id": self.profile["user_id"]}), encoding="utf-8")
            replace_with_retry(temporary, self._last_profile_path)
        except OSError:
            pass  # recordarlo es una comodidad, nunca un error para el usuario

    def _restore_last_profile(self):
        try:
            user_id = json.loads(self._last_profile_path.read_text(encoding="utf-8"))["user_id"]
        except (OSError, ValueError, KeyError, TypeError):
            profiles = [p for p in self.profiles.list_profiles() if not p["error"]]
            if len(profiles) != 1:
                return
            user_id = profiles[0]["user_id"]  # un solo perfil: no hay nada que elegir
        try:
            self.select_profile(user_id)
        except Exception:
            self.profile = None

    def emergency_stop(self):
        """Única operación permitida desde otro hilo: revoca salida inmediatamente."""
        self.emergency.set()
        control = self.control
        if control is not None:
            control.output_allowed.clear()
        dictation = self.dictation
        if dictation is not None:
            dictation.cancel()  # nunca escribir texto después de F8 / Detener

    def _require_profile(self, calibrated=False, validated=False):
        if self.profile is None:
            raise ValueError("Primero elegí o creá un perfil")
        if calibrated and self.profile.get("status") == "draft":
            raise ValueError("Calibrá este perfil antes de continuar")
        if validated and not self.profile.get("validation", {}).get("passed", False):
            raise ValueError("Validá la calibración antes de activar el control")

    def create_profile(self, name):
        p = self.profiles.create(name)
        self.select_profile(p["user_id"])

    def select_profile(self, user_id):
        self.stop_camera()
        self.profile = self.profiles.store.load(user_id)
        self.config = load_config(overrides=self.profile.get("settings", {}))
        self.state = "HOME"
        self.wizard = None
        self.message = self.profiles.status(self.profile)
        self._remember_profile()

    def rename_profile(self, name):
        self._require_profile()
        self.profile = self.profiles.rename(self.profile["user_id"], name)

    def delete_profile(self, confirmed=False):
        self._require_profile()
        if not confirmed:
            raise ValueError("Confirmá la eliminación")
        self.stop_camera()
        self.profiles.delete(self.profile["user_id"], confirmed)
        self.profile = None
        try:
            self._last_profile_path.unlink()
        except OSError:
            pass
        self.config = load_config()
        self.state, self.message = "HOME", "Perfil eliminado. Los resultados históricos se conservaron."

    def save_settings(self, settings):
        self._require_profile()
        validated = load_config(overrides=settings)  # validar antes de detener/modificar
        self.stop_camera()
        self.profile = self.profiles.save_settings(self.profile, asdict(validated))
        self.config = validated
        self.wizard = None
        self.message = "Configuración guardada. Volvé a abrir la cámara cuando quieras."

    def restore_defaults(self):
        self.save_settings(asdict(load_config()))

    def _make_gesture(self):
        if self.profile and self.profile.get("status") != "draft":
            self.gesture = GestureEngine(self.vision, config=self.config.gesture, calibration=self.profile,
                                         strategy=create_strategy(self.config.ui.tracking_method), clock=self.clock)
        else:
            self.gesture = None

    def start_camera(self):
        self._require_profile()
        if self.vision is not None:
            return
        factory = self.vision_factory
        if factory is None:
            from vision_engine import VisionEngine
            factory = VisionEngine
        self.metrics = SessionMetrics(self.profile["user_id"], self.data_dir / "metrics",
                                      self.config.metrics_enabled, self.clock)
        try:
            self.vision = factory(config=self.config.vision, metrics=self.metrics)
            self.vision.start()
            self.vision.wait_ready()
            self._make_gesture()
            self._last_face = 0
            self.state, self.message = "PREVIEW", "Cámara lista. El control del sistema sigue desactivado."
        except Exception:
            self.stop_camera()
            raise

    def stop_control(self):
        self.emergency_stop()
        try:
            if self.control:
                self.control.stop()
                self.control = None
        finally:
            if self.dictation:
                self.dictation.close()
                self.dictation = None
        if self.state == "CONTROL":
            self.state = "PREVIEW" if self.vision else "HOME"
        self.message = "Control del sistema desactivado."

    def stop_camera(self):
        errors = []
        try:
            self.stop_control()
        except Exception as exc:
            errors.append(exc)
        try:
            if self.experiment and self.experiment.active:
                self.experiment.cancel()
        except Exception as exc:
            errors.append(exc)
        try:
            if self.vision:
                self.vision.stop()
        except Exception as exc:
            errors.append(exc)
        finally:
            self.vision = None
        try:
            if self.metrics:
                self.metrics.close()
        except Exception as exc:
            errors.append(exc)
        finally:
            self.metrics = None
        self.gesture = None
        self.jitter = None
        self.state = "HOME"
        self.refresh_metrics()
        if errors:
            raise RuntimeError("No se pudieron cerrar todos los recursos: " + "; ".join(str(e) for e in errors))

    def activate_control(self, confirmed=False):
        self._require_profile(calibrated=True, validated=True)
        if not confirmed or self.emergency.is_set():
            raise ValueError("La activación fue cancelada o no está autorizada")
        if self.state in ("CALIBRATING", "JITTER") or (self.experiment and self.experiment.active):
            raise ValueError("Terminá o cancelá la medición antes de activar")
        self.start_camera()
        if self.emergency.is_set():
            return  # F8/STOP durante inicialización no puede ser anulado
        voice_warning = ""
        if not self.control:
            backend = self.backend_factory() if self.backend_factory else None
            voice_warning = self._start_dictation()
            self.control = ControlEngine(self.vision, self.gesture, self.config.control,
                                         backend=backend, metrics=self.metrics,
                                         mapping=ActionMapping(self.config.actions.bindings),
                                         dictation=self.dictation)
            self.control.toggle_pause()
        if self.emergency.is_set():
            self.stop_control()
            return
        self.state, self.message = "CONTROL", "Control del sistema activo. F8 o Detener control para salir." + voice_warning

    def _report_recenter(self, result):
        if not result:
            return
        if not result["ok"]:
            self.message = f"Centro sin cambios: {result['reason']}."
        elif result.get("pinned"):
            self.message = "Centro ajustado solo: el cursor estaba trabado contra el borde con la cabeza quieta."
        elif result.get("far"):
            self.message = ("Centro ajustado. Tu postura está lejos de la calibrada: "
                            "si los gestos fallan, recalibrá con esta posición de cámara.")
        else:
            self.message = "Centro ajustado a tu postura actual."

    def _start_dictation(self):
        """El dictado es opcional: si no está preparado, el control funciona igual."""
        if not self.config.voice.enabled:
            return ""
        try:
            if self.dictation_factory:
                self.dictation = self.dictation_factory(self.config.voice, self.metrics)
            else:
                from dictation import create_dictation
                self.dictation = create_dictation(self.config.voice, self.metrics)
            self.dictation.start()
            return " Dictado por voz activo."
        except Exception as exc:
            self.dictation = None
            return f" Dictado no disponible: {exc}"

    def prepare_voice_model(self, model=None):
        """Descarga en segundo plano: puede tardar minutos y no debe frenar la GUI."""
        if self._voice_download and self._voice_download.is_alive():
            raise ValueError("La descarga del modelo de voz ya está en curso")
        model = model or self.config.voice.model
        def download():
            try:
                from dictation import WhisperTranscriber
                WhisperTranscriber.download(model)
                self.message = f"Modelo de voz '{model}' listo. Activá el dictado en Configuración y guardá."
            except Exception as exc:
                self.message = f"No se pudo preparar el modelo de voz: {exc}"
        self.message = f"Descargando el modelo de voz '{model}'… podés seguir usando la aplicación."
        self._voice_download = threading.Thread(target=download, name="VoiceDownload", daemon=True)
        self._voice_download.start()

    def start_diagnostic(self):
        self.stop_control()
        self._require_profile(calibrated=True)
        if self.experiment and self.experiment.active:
            self.experiment.cancel()
        self.jitter = None
        self.start_camera()
        self.state, self.message = "DIAGNOSTIC", "Diagnóstico seguro: el cursor del sistema no se mueve."

    def start_calibration(self, enabled=None, source=None):
        self.stop_control()
        if self.experiment and self.experiment.active:
            self.experiment.cancel()
        self.jitter = None
        self.start_camera()
        self.wizard = CalibrationSession(self.profile, self.config, self.clock, enabled, source)
        self._calibration_session_id = uuid.uuid4().hex
        self._calibration_logged = 0
        self.wizard.start()
        self.state = "CALIBRATING"

    def validate_calibration(self):
        self.stop_control()
        if self.experiment and self.experiment.active:
            self.experiment.cancel()
        self.jitter = None
        self.start_camera()
        if self.wizard is None:
            self._require_profile(calibrated=True)
            self.wizard = CalibrationSession(self.profile, self.config, self.clock)
            self.wizard.candidate = deepcopy(self.profile)
        self.wizard.validate()
        self.state = "CALIBRATING"

    def repeat_calibration(self, gesture_id=None):
        if self.wizard:
            self.stop_control()
            self.start_camera()
            self.wizard.repeat(gesture_id)
            self.state = "CALIBRATING"

    def set_calibration_gesture(self, gesture_id, enabled):
        if self.wizard is None or self.state != "CALIBRATING":
            raise ValueError("Iniciá la calibración para modificar este intento")
        self.wizard.set_enabled(gesture_id, enabled)

    def _flush_calibration_telemetry(self):
        if not self.wizard or not self._calibration_session_id:
            return
        while self._calibration_logged < len(self.wizard.telemetry):
            record = self.wizard.telemetry[self._calibration_logged]
            ResultStore(self.data_dir / "calibration").append(self._calibration_session_id,
                dict(experiment="gesture_calibration", schema_version=1, profile_id=self.profile["user_id"],
                     recorded_at=time.time(), **record))
            self._calibration_logged += 1

    def save_calibration(self):
        if self.wizard is None:
            raise ValueError("No hay calibración para guardar")
        result = self.wizard.result()
        self.profiles.store.save(result)
        self.profile = self.profiles.store.load(result["user_id"])
        self.config = load_config(overrides=self.profile.get("settings", {}))
        self._make_gesture()
        self.state = "PREVIEW"
        self.message = "Perfil guardado y validado. Ya podés probar HeadMouse."

    def start_experiment(self, mode="simulation", source="headmouse"):
        if mode == "real" and (not self.control or self.emergency.is_set()):
            raise ValueError("Activá el control explícitamente antes del experimento real")
        if self.experiment and self.experiment.active:
            self.experiment.cancel()
        if mode == "simulation":
            self.stop_control()
        if source == "headmouse":
            self._require_profile(calibrated=True)
            self.start_camera()
        self.jitter = None
        self.experiment = ExperimentEngine(self.profile["user_id"] if self.profile else "demo", mode, source,
                                            ResultStore(self.data_dir / "experiments"), self.clock)
        self.state = "EXPERIMENT"
        self.message = "Seleccioná los objetivos. Los resultados se guardan automáticamente."

    def experiment_input(self, x=0, y=0, click=False, absolute=False):
        if not self.experiment or not self.experiment.active:
            return
        if absolute and self.experiment.mode == "real":
            face = self.vision.get_face_data() if self.vision else FaceData(False)
            self.experiment.observe(x, y, self.vision.get_fps() if self.vision else 0, face.processing_ms)
        elif self.experiment.mode == "simulation" and self.experiment.source == "keyboard":
            self.experiment.move(x, y)
        if click:
            self.experiment.click()

    def cancel_experiment(self):
        if self.experiment:
            self.experiment.cancel()
        self.stop_control()
        self.state = "PREVIEW" if self.vision else "HOME"

    def start_jitter(self):
        self.stop_control()
        self._require_profile(calibrated=True)
        self.start_camera()
        if self.experiment and self.experiment.active:
            self.experiment.cancel()
        self.jitter = JitterMeasurement((self.profile.get("neutral_nose_x", .5),
                                        self.profile.get("neutral_nose_y", .5)),
                                       self.config.gesture.dead_zone, clock=self.clock)
        self.jitter_result = None
        self.state = "JITTER"
        self.message = "Mantené la cabeza en neutral durante 10 segundos."

    def prepare_model(self):
        from vision_engine import VisionEngine
        VisionEngine.download_model(ROOT / self.config.vision.model_path)
        self.message = "Modelo local preparado. Ya podés abrir la cámara."

    def refresh_metrics(self):
        self.history = []
        for path in sorted((self.data_dir / "metrics").glob("session-*.json"), reverse=True):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self.history.append(data)
            except (OSError, ValueError):
                continue

    def step(self):
        if self.emergency.is_set() and self.control:
            self.stop_control()
        if self.experiment:
            self.experiment.tick()
        if self.vision is None:
            return
        if self.vision.error or not self.vision.is_alive():
            raise RuntimeError("La cámara o MediaPipe se detuvo. Revisá la conexión y volvé a abrir la cámara.")
        face = self.vision.get_face_data()
        fresh = face.fresh(self.config.gesture.stale_after_s, self.clock())
        events, actions = [], []
        if self.state == "CALIBRATING" and self.wizard:
            self.wizard.update(face)
            self._flush_calibration_telemetry()
            if self.wizard.state == "measured" and self.wizard.validator is None:
                # La prueba de gestos arranca sola: antes había que descubrir el botón Validar.
                self.wizard.validate()
        elif self.control:
            self.control._tick()  # mismo ciclo seguro v0.2, conducido por el worker Qt
            events, actions = list(self.control.last_events), list(self.control.last_actions)
            recenter, self.control.last_recenter = self.control.last_recenter, None
            self._report_recenter(recenter)
        elif self.gesture:
            self.gesture.both_brows_anywhere = True  # sin control: probar el recentrado desde cualquier postura
            events = self.gesture.update(face)
            actions = [ActionMapping(self.config.actions.bindings).resolve(ev) for ev in events]
            if self.metrics:
                self.metrics.generated(events)
            # Sin control no hay pausa real: en vista previa y diagnóstico, el gesto
            # de pausa recentra igual, para poder probar el ajuste sin mover el mouse.
            pause = next((ev for ev in actions if ev.type == "PAUSE"), None)
            if pause and self.config.gesture.auto_recenter:
                c = self.config.gesture
                self._report_recenter(self.gesture.recenter(
                    pause.source_timestamp_ms, guard_ms=c.brow_decision_ms + c.both_brows_hold_ms + 250))
        if self.metrics:
            self.metrics.tracking(fresh)
        discrete = [e for e in events if e.type != "CURSOR_MOVE"]
        if discrete:
            self.last_gesture = gesture_identity(discrete[-1])
            self.last_action = ActionMapping(self.config.actions.bindings).resolve(discrete[-1]).type
            self._event_at = self.clock()
        elif self.clock()-self._event_at > 2:
            self.last_gesture = self.last_action = "—"
        cursor = next((e for e in events if e.type == "CURSOR_MOVE"), None)
        dx = int(max(-self.config.control.max_cursor_delta, min(self.config.control.max_cursor_delta, cursor.dx))) if cursor else 0
        dy = int(max(-self.config.control.max_cursor_delta, min(self.config.control.max_cursor_delta, cursor.dy))) if cursor else 0
        if cursor:
            self.cursor = (max(0, min(800, self.cursor[0]+dx)), max(0, min(500, self.cursor[1]+dy)))
        if self.experiment and self.experiment.active and self.experiment.mode == "simulation" and self.experiment.source == "headmouse":
            if face.timestamp_ms != self._last_face and fresh:
                self.experiment.move(dx, dy, self.vision.get_fps(), face.processing_ms)
                if any(e.type in ("LEFT_CLICK", "DOUBLE_CLICK") for e in actions):
                    self.experiment.click()
        if self.jitter:
            self.jitter.add(face, self.config.gesture.stale_after_s)
            if self.jitter.done:
                self.jitter_result = self.jitter.summary()
                record = dict(experiment="jitter", profile_id=self.profile["user_id"], tracking_method="nose",
                              recorded_at=time.time(), **self.jitter_result)
                self.jitter_result["path"] = ResultStore(self.data_dir / "experiments").append(uuid.uuid4().hex, record)
                self.jitter = None
                self.state = "DIAGNOSTIC"
        self._last_face = face.timestamp_ms

    def snapshot(self, include_frame=True):
        face = self.vision.get_face_data() if self.vision else FaceData(False)
        fresh = face.fresh(self.config.gesture.stale_after_s, self.clock())
        return dict(state=self.state, message=self.message, profile=deepcopy(self.profile),
                    profile_status=self.profiles.status(self.profile) if self.profile else "Sin perfil",
                    settings=asdict(self.config), camera=self.vision is not None,
                    mediapipe="Listo" if self.vision and self.vision.ready.is_set() else "Sin iniciar",
                    face=face, detected=fresh, fps=self.vision.get_fps() if self.vision else 0,
                    processing_ms=face.processing_ms if fresh else 0,
                    frame=self.vision.get_frame() if self.vision and include_frame else None,
                    control_enabled=bool(self.control and not self.emergency.is_set()),
                    paused=self.control.paused if self.control else True,
                    gesture=self.last_gesture, action=self.last_action, cursor=self.cursor,
                    diagnostic=self.gesture.diagnostic() if self.gesture else {},
                    wizard=self.wizard.snapshot() if self.wizard else None,
                    experiment=self.experiment.snapshot() if self.experiment else None,
                    jitter=self.jitter_result, jitter_remaining=max(0, self.jitter.duration_s-(self.clock()-self.jitter.started)) if self.jitter else None,
                    metrics=self.metrics.snapshot() if self.metrics else {}, history=deepcopy(self.history),
                    dictation=self.dictation.snapshot() if self.dictation else None,
                    models=self._model_status())

    def _model_status(self):
        """Qué modelos locales ya están instalados (se revisa cada 2 s)."""
        now = self.clock()
        if now - self._models_checked >= 2:
            from config import WHISPER_MODELS
            from dictation import MODEL_DIR
            face = Path(self.config.vision.model_path)
            face = face if face.is_absolute() else ROOT / face
            self._models = dict(face=face.is_file() and face.stat().st_size > 0,
                                voice={m: (MODEL_DIR / m / "model.bin").is_file() for m in WHISPER_MODELS})
            self._models_checked = now
        return self._models

    def fail(self, message):
        self.emergency_stop()
        try:
            self.stop_camera()
        finally:
            self.state, self.message = "ERROR", str(message)

    def shutdown(self):
        self.stop_camera()
        self.closed = True
        self.state = "CLOSED"
