"""Coordinación desktop sin dependencia de Qt. Un único worker posee el estado."""
import json
import logging
import threading
import time
import uuid
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from action_mapping import ActionMapping, gesture_identity
from calibration_session import CalibrationSession
from config import ROOT, DEFAULT_THRESHOLDS, load_config, settings_for_save, method_bank
from control_engine import ControlEngine
from experiment_engine import ExperimentEngine, JitterMeasurement, ResultStore
from face_data import FaceData
from gesture_engine import GestureEngine
from metrics import SessionMetrics
from profile_manager import ProfileManager
from tracking import create_strategy
from tracking_calibration import EyeTrackingCalibrationSession, TrackingCalibration
from profiles import gesture_profile, save_gesture_mode
from ocular_profiles import calibration_for, with_calibration, selected_profile, migrate_public_eyes
from gaze_source import eye_coordinates, gaze_position, SOURCE_LABELS


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
        self._pending_stop_reason = None  # motivo de una parada pedida desde otro hilo
        self.emergency.set()
        self.profile = None
        self.config = load_config()
        self.vision = self.gesture = self.control = self.metrics = None
        self._camera_starting = False
        self._camera_cancelled = threading.Event()
        self._camera_started_at = 0.
        self.wizard = self.experiment = self.jitter = None
        self.eye_calibration = None
        self.gaze_calibration = None
        self.vertical_diagnostic=None
        self._vertical_trace=None
        self._vertical_saved=False
        self._gaze_logged = None
        self.screen_context = None
        self._calibration_session_id = None
        self._calibration_logged = 0
        self._calibration_diagnostic_key = None
        self._calibration_diagnostic_at = -1e9
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

    def emergency_stop(self, reason=None):
        """Única operación permitida desde otro hilo: revoca salida inmediatamente.

        `reason` se guarda ANTES de revocar: si el ciclo del worker detiene el
        control antes de procesar el comando encolado, igual informa el motivo
        (antes mostraba "Control del sistema desactivado." y el motivo llegaba después).
        """
        if reason:
            self._pending_stop_reason = reason
        self.emergency.set()
        self.cancel_camera_startup()
        control = self.control
        if control is not None:
            control.output_allowed.clear()
        dictation = self.dictation
        if dictation is not None:
            dictation.cancel()  # nunca escribir texto después de F8 / Detener

    def _require_profile(self, calibrated=False, validated=False):
        if self.profile is None:
            raise ValueError("Primero elegí o creá un perfil")
        profile = gesture_profile(self.profile, method_bank(self.config))
        if calibrated and profile.get("status") == "draft":
            raise ValueError("Calibrá este perfil antes de continuar")
        if validated and not profile.get("validation", {}).get("passed", False):
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
        incoming = load_config(overrides=settings)  # validar antes de detener/modificar
        validated = settings_for_save(self.config, asdict(incoming))
        self.stop_camera()
        candidate=migrate_public_eyes(self.profile,validated.ui.ocular_engine) if validated.ui.unified_eyes else self.profile
        self.profile = self.profiles.save_settings(candidate, asdict(validated))
        self.config = validated
        self.wizard = None
        self.message = "Configuración guardada. Volvé a abrir la cámara cuando quieras."

    def select_control_method(self,method):
        if method not in ("nose","eyes"):
            raise ValueError("Elegí Nariz u Ojos")
        self._require_profile()
        current="nose" if self.config.ui.tracking_method=="nose" else "eyes"
        if method==current and (method=="nose" or self.config.ui.unified_eyes):
            return
        settings=asdict(self.config)
        engine=self.config.ui.tracking_method if not self.config.ui.unified_eyes and self.config.ui.tracking_method!="nose" else self.config.ui.ocular_engine
        settings["ui"].update(tracking_method="nose" if method=="nose" else engine,ocular_engine=engine,
                               unified_eyes=self.config.ui.unified_eyes or method=="eyes")
        self.save_settings(settings)
        self.message="Configuración de "+("Nariz" if method=="nose" else "Ojos")+" cargada para este perfil."

    def select_eye_source(self,source):
        from gaze_source import validate_source
        validate_source(source)
        if self.config.ui.tracking_method=="nose" or not self.config.ui.unified_eyes:
            self.select_control_method("eyes")
        settings=asdict(self.config);settings["ui"]["eye_source"]=source
        self.save_settings(settings)

    def save_public_settings(self,settings,method):
        before=asdict(self.config)
        changed=method!=("nose" if self.config.ui.tracking_method=="nose" else "eyes") or (method=="eyes" and not self.config.ui.unified_eyes)
        if changed:
            self.select_control_method(method)
            data=asdict(self.config)
            for section,values in settings.items():
                if section in ("methods","ui"):continue
                if isinstance(values,dict):
                    for key,value in values.items():
                        if value!=before.get(section,{}).get(key):data[section][key]=deepcopy(value)
                elif values!=before.get(section):data[section]=deepcopy(values)
            for key in ("eye_source","show_overlay","show_landmarks"):
                if settings["ui"][key]!=before["ui"][key]:data["ui"][key]=settings["ui"][key]
        else:data=deepcopy(settings)
        data["ui"].update(tracking_method=self.config.ui.tracking_method,
            ocular_engine=self.config.ui.ocular_engine,unified_eyes=self.config.ui.unified_eyes)
        self.save_settings(data)

    def upgrade_ocular_response(self,confirmed=False):
        if not confirmed:raise ValueError("Confirmá la nueva calibración de respuesta ocular")
        self.select_control_method("eyes")
        settings=asdict(self.config)
        settings["ui"].update(ocular_engine="eye_absolute",tracking_method="eye_absolute")
        self.save_settings(settings)
        self.message="Ojos preparado para calibrar posición en pantalla. El modelo anterior sigue conservado; no se cambia de respuesta automáticamente."

    def restore_defaults(self):
        settings = asdict(load_config())
        settings["ui"]["tracking_method"] = self.config.ui.tracking_method
        self.save_settings(settings)

    def _make_gesture(self):
        profile = gesture_profile(self.profile, method_bank(self.config)) if self.profile else None
        ocular=self.config.ui.tracking_method!="nose"
        if profile and (ocular or profile.get("status") != "draft"):
            absolute = self.config.ui.tracking_method == "eye_absolute"
            runtime=dict(thresholds=DEFAULT_THRESHOLDS.copy()) if profile.get("status")=="draft" else profile
            self.gesture = GestureEngine(self.vision, config=self.config.gesture, calibration=runtime,
                                         strategy=create_strategy(self.config.ui.tracking_method,
                                             self._tracking_record(), self.config.absolute if absolute else self.config.eye,
                                             self.config.ui.eye_source), clock=self.clock,movement_only=ocular and not self._actions_ready())
        else:
            self.gesture = None

    def _actions_ready(self):
        p=gesture_profile(self.profile,method_bank(self.config)) if self.profile else {}
        measured=self.config.ui.tracking_method=="nose" or (self.profile or {}).get("gesture_mode_origin",{}).get(method_bank(self.config))=="measured"
        return measured and p.get("status")!="draft" and p.get("validation",{}).get("passed") is True

    def require_control_profile(self):
        self._require_profile(calibrated=self.config.ui.tracking_method=="nose",validated=self.config.ui.tracking_method=="nose")

    def cancel_camera_startup(self):
        """Solo eventos: se puede llamar desde Qt sin cerrar recursos nativos."""
        if self._camera_starting:
            self._camera_cancelled.set()
            request = getattr(self.vision, "request_stop", None)
            if callable(request):
                request()

    def camera_status(self):
        if self.vision is not None:
            reader = getattr(self.vision, "diagnostics", None)
            status = reader() if callable(reader) else None
            if isinstance(status, dict):
                return status
            return dict(stage="READY" if self.vision.ready.is_set() and not self.vision.error else "STARTING",
                        ready=not bool(self.vision.error) and self.vision.ready.is_set())
        return dict(stage="STARTING" if self._camera_starting else "STOPPED", ready=False)

    def _camera_became_ready(self):
        self._camera_starting = False
        self._make_gesture()
        self._last_face = 0
        self.state, self.message = "PREVIEW", "Cámara y MediaPipe listos. El control del sistema sigue desactivado."

    def poll_camera_startup(self):
        if not self._camera_starting:
            return True
        if self._camera_cancelled.is_set():
            raise InterruptedError("Inicio de cámara cancelado")
        if self.vision.error:
            raise RuntimeError(f"Falló el inicio de cámara/MediaPipe: {self.vision.error}") from self.vision.error
        if self.vision.ready.is_set():
            self.vision.wait_ready(timeout=0)
            self._camera_became_ready()
            return True
        if not self.vision.is_alive():
            raise RuntimeError("El motor terminó antes de entregar el primer resultado")
        status = self.camera_status()
        self.message = f"Iniciando cámara: {status['stage']} · {status.get('operation','')} · {self.clock()-self._camera_started_at:.1f} s"
        if self.clock()-self._camera_started_at > self.config.vision.startup_timeout_s:
            self.cancel_camera_startup()
            raise TimeoutError(f"Inicio agotado tras {self.config.vision.startup_timeout_s:g} s: "
                f"etapa {status['stage']}, operación {status.get('operation','')}; "
                f"frames={status.get('captured_frames',0)}, resultados={status.get('processed_results',0)}")
        return False

    def start_camera(self, wait=True):
        self._require_profile()
        if self.vision is not None:
            if self.camera_status().get("stop_requested"):
                raise RuntimeError("El motor anterior todavía está cerrando; no se abrirá otra cámara")
            if self._camera_starting:
                if wait:
                    raise RuntimeError("La cámara todavía está iniciándose; esperá o cancelá antes de calibrar")
                return
            if self.vision.error or not self.vision.is_alive():
                raise RuntimeError("La cámara anterior no está disponible; detenela antes de reiniciar")
            return
        self._camera_starting = True
        self._camera_cancelled.clear()
        self._camera_started_at = self.clock()
        self.state, self.message = "CAMERA_STARTING", "Preparando cámara y MediaPipe…"
        logging.getLogger(__name__).info("Solicitud de cámara: índice=%s backend=%s timeout=%.1fs",
            self.config.vision.camera_index,self.config.vision.capture_backend,self.config.vision.startup_timeout_s)
        try:
            factory = self.vision_factory
            if factory is None:
                from vision_engine import VisionEngine
                factory = VisionEngine
            self.metrics = SessionMetrics(self.profile["user_id"], self.data_dir / "metrics",
                                          self.config.metrics_enabled, self.clock)
            self.vision = factory(config=self.config.vision, metrics=self.metrics)
            if self._camera_cancelled.is_set():
                self.vision.request_stop()
            self.vision.start()
            if not wait:
                return
            self.vision.wait_ready()
            self._camera_became_ready()
        except Exception as exc:
            self.emergency_stop()
            try:
                self.stop_camera()
            except Exception as closing:
                raise RuntimeError(f"{exc}. Limpieza pendiente: {closing}") from exc
            raise

    def stop_control(self, reason=None):
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
        reason = reason or self._pending_stop_reason
        self._pending_stop_reason = None
        self.message = reason or "Control del sistema desactivado."
        if reason:
            logging.getLogger(__name__).warning("Control detenido: %s", reason)

    def stop_camera(self):
        self.cancel_camera_startup()
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
        else:
            self.vision = None
        self._camera_starting = False
        try:
            if self.metrics:
                self.metrics.close()
        except Exception as exc:
            errors.append(exc)
        finally:
            self.metrics = None
        self.gesture = None
        self.jitter = None
        self.eye_calibration = None
        self.gaze_calibration = None
        self.state = "ERROR" if errors else "HOME"
        self.vertical_diagnostic=self._vertical_trace=None
        self.refresh_metrics()
        if errors:
            raise RuntimeError("No se pudieron cerrar todos los recursos: " + "; ".join(str(e) for e in errors))

    def activate_control(self, confirmed=False, screen_context=None):
        logging.getLogger(__name__).info("Activación solicitada: método=%s banco=%s confirmada=%s emergencia=%s cámara=%s acciones_validadas=%s",
            self.config.ui.tracking_method, method_bank(self.config), confirmed, self.emergency.is_set(),
            self.camera_status().get("stage"), self._actions_ready())
        self.require_control_profile()
        self._require_tracking_calibration()
        if not confirmed or self.emergency.is_set():
            raise ValueError("La activación fue cancelada o no está autorizada")
        if self.state in ("CALIBRATING", "EYE_CALIBRATING", "GAZE_CALIBRATING", "VERTICAL_DIAGNOSTIC", "JITTER") or (self.experiment and self.experiment.active):
            raise ValueError("Terminá o cancelá la medición antes de activar")
        self.start_camera()
        if self.config.ui.tracking_method == "eye_absolute":
            self._check_absolute_context(screen_context)
        elif self.config.ui.tracking_method == "eye":
            context = (self._tracking_record() or {}).get("camera_context")
            if context and context != self._relative_camera_context():
                raise ValueError("Cambió la cámara o resolución: recalibrá el tracking ocular de esta fuente")
        if self.config.ui.tracking_method != "nose":
            face = self.vision.get_face_data()
            ref=self.config.eye.vertical_reference if self.config.ui.tracking_method=="eye" else (self._tracking_record() or {}).get("vertical_reference","eyelids")
            if not face.fresh(self.config.gesture.stale_after_s, self.clock()) or eye_coordinates(face, self.config.ui.eye_source,ref) is None:
                raise ValueError("Iris seleccionado no detectado o frame vencido. Verificá el diagnóstico seguro antes de activar.")
        if self.emergency.is_set():
            return  # F8/STOP durante inicialización no puede ser anulado
        voice_warning = ""
        if not self.control:
            backend = self.backend_factory() if self.backend_factory else None
            movement_only=self.config.ui.tracking_method!="nose" and not self._actions_ready()
            voice_warning = self._start_dictation() if not movement_only else " Sólo movimiento; clics y acciones faciales pendientes."
            bounds=None
            if self.config.ui.tracking_method=="eye_absolute":
                from screen_mapping import screen_display
                bounds=screen_display(screen_context)["physical_rect"]
            self.control = ControlEngine(self.vision, self.gesture, self.config.control,
                                         backend=backend, metrics=self.metrics,
                                         mapping=ActionMapping(self.config.actions.bindings),
                                         dictation=self.dictation,screen_bounds=bounds,movement_only=movement_only)
            if self.config.ui.tracking_method == "eye_absolute":
                context = self._tracking_record()["context"]
                if (self.control._screen_w, self.control._screen_h) != (context["width"], context["height"]):
                    self.stop_control()
                    raise ValueError("La resolución del backend cambió: recalibrá con una sola pantalla")
            self.control.toggle_pause()
        if self.emergency.is_set():
            self.stop_control()
            return
        self.state, self.message = "CONTROL", "Control del sistema activo. F8 o Detener control para salir." + voice_warning
        logging.getLogger(__name__).info("Activación completada: método=%s sólo_movimiento=%s", self.config.ui.tracking_method, self.control.movement_only)

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
        self._require_profile()
        if self.experiment and self.experiment.active:
            self.experiment.cancel()
        self.jitter = None
        self.eye_calibration = None
        self.gaze_calibration = None
        self.start_camera()
        self.state, self.message = "DIAGNOSTIC", "Diagnóstico seguro: el cursor del sistema no se mueve."

    def start_calibration(self, enabled=None, source=None):
        self.stop_control()
        if self.experiment and self.experiment.active:
            self.experiment.cancel()
        self.jitter = None
        self.eye_calibration = None
        self.start_camera()
        self.gaze_calibration = None
        self.wizard = CalibrationSession(gesture_profile(self.profile, method_bank(self.config)), self.config, self.clock, enabled, source)
        self._calibration_session_id = uuid.uuid4().hex
        self._calibration_logged = 0
        self._calibration_diagnostic_key = None
        self._calibration_diagnostic_at = -1e9
        self.wizard.start()
        self.state = "CALIBRATING"

    def validate_calibration(self):
        self.stop_control()
        if self.experiment and self.experiment.active:
            self.experiment.cancel()
        self.jitter = None
        self.eye_calibration = None
        self.gaze_calibration = None
        self.start_camera()
        if self.wizard is None:
            self._require_profile(calibrated=True)
            self.wizard = CalibrationSession(gesture_profile(self.profile, method_bank(self.config)), self.config, self.clock)
            self.wizard.candidate = gesture_profile(self.profile, method_bank(self.config))
            self._calibration_session_id = uuid.uuid4().hex
            self._calibration_logged = 0
            self._calibration_diagnostic_key = None
            self._calibration_diagnostic_at = -1e9
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
                     public_method="nose" if self.config.ui.tracking_method=="nose" else "eyes",
                     gesture_bank=method_bank(self.config), parameter_source="profile.settings",
                     recorded_at=time.time(), **record))
            self._calibration_logged += 1
        diagnostic=self.wizard.diagnostic()
        key=(diagnostic["state"],diagnostic["stage"],diagnostic["requested_gesture"],
             diagnostic["rejection_reason"],tuple(diagnostic["recognized"]))
        if key!=self._calibration_diagnostic_key or self.clock()-self._calibration_diagnostic_at>=1:
            ResultStore(self.data_dir / "calibration").append(self._calibration_session_id,
                dict(experiment="gesture_diagnostic", schema_version=1, profile_id=self.profile["user_id"],
                     public_method="nose" if self.config.ui.tracking_method=="nose" else "eyes",
                     gesture_bank=method_bank(self.config), parameter_source="profile.settings",
                     recorded_at=time.time(), **diagnostic))
            self._calibration_diagnostic_key=key
            self._calibration_diagnostic_at=self.clock()

    def save_calibration(self):
        if self.wizard is None:
            raise ValueError("No hay calibración para guardar")
        result = self.wizard.result()
        settings = settings_for_save(self.config, result["settings"]) if self.profile and "settings" in result else None
        # La calibración facial reconstruye su perfil; preservar el tracking aparte.
        if self.profile and "tracking_calibration" in self.profile:
            result["tracking_calibration"] = deepcopy(self.profile["tracking_calibration"])
        result = save_gesture_mode(self.profile, result, method_bank(self.config))
        if settings is not None:
            result["settings"] = asdict(settings)
        bank=method_bank(self.config)
        try:
            self.profiles.store.save(result)
            loaded=self.profiles.store.load(result["user_id"])
            if loaded.get("gesture_modes",{}).get(bank)!=result.get("gesture_modes",{}).get(bank):
                raise ValueError("La lectura posterior no coincide con el banco de gestos guardado")
        except (OSError, ValueError, RuntimeError) as exc:
            label="Nariz" if bank=="nose" else "Ojos"
            self.message=f"No se confirmó el guardado de gestos de {label}: {exc}. El intento se conserva para reintentar."
            logging.getLogger(__name__).exception("Guardado de gestos fallido: banco=%s",bank)
            raise RuntimeError(self.message) from exc
        self.profile = loaded
        self.config = load_config(overrides=self.profile.get("settings", {}))
        self._make_gesture()
        self.state = "PREVIEW"
        self.message = "Gestos de "+("Nariz" if bank=="nose" else "Ojos")+" guardados, validados y releídos. Ya podés probar HeadMouse."
        logging.getLogger(__name__).info("Gestos guardados y releídos: banco=%s gestos=%s",bank,
            [k for k,r in loaded.get("gesture_modes",{}).get(bank,{}).get("gesture_calibrations",{}).items() if r.get("enabled")])

    def _require_tracking_calibration(self):
        record = self._tracking_record()
        if self.config.ui.tracking_method == "eye_absolute":
            if not record or not record.get("validated"):
                raise ValueError(f"{SOURCE_LABELS[self.config.ui.eye_source]}: completá el aprendizaje y la comprobación de precisión en Calibración → Ojos antes de activar")
        if self.config.ui.tracking_method == "eye" and not record:
            raise ValueError(f"{SOURCE_LABELS[self.config.ui.eye_source]}: calibrá el tracking ocular antes de continuar")
        if self.config.ui.tracking_method=="eye" and record and record.get("vertical_reference","eyelids")!=self.config.eye.vertical_reference:
            raise ValueError("Cambió la referencia vertical: calibrá el movimiento ocular antes de activar")
        if self.config.ui.tracking_method=="eye" and record and self.config.eye.vertical_reference=="canthi" and not record.get("ranges_measured"):
            raise ValueError("La referencia de comisuras requiere medir los cinco rangos; el neutral solo no habilita esta prueba")
        if record:
            context = record.get("camera_context") or record.get("context")
            if context and context["camera_index"] != self.config.vision.camera_index:
                raise ValueError("La calibración corresponde a otra cámara: recalibrá la fuente seleccionada")

    def _tracking_record(self):
        if self.config.ui.tracking_method == "nose":
            return None
        return calibration_for(self.profile, self.config.ui.tracking_method, self.config.ui.eye_source)

    def _relative_camera_context(self):
        if self.vision is None:
            return None
        frame = self.vision.get_frame()
        shape = getattr(frame, "shape", None)
        if not isinstance(shape, tuple) or len(shape) < 2 or not all(isinstance(v, int) and v > 1 for v in shape[:2]):
            return None
        return dict(camera_index=self.config.vision.camera_index, frame_width=shape[1], frame_height=shape[0])

    def start_eye_calibration(self):
        if self.state == "CALIBRATING":
            raise ValueError("Terminá o cancelá la calibración de gestos primero")
        self.stop_control()
        if self.experiment and self.experiment.active:
            self.experiment.cancel()
        self.jitter = None
        self.gaze_calibration = None
        self.start_camera()
        thresholds = gesture_profile(self.profile, method_bank(self.config)).get("thresholds", {})
        self.eye_calibration = EyeTrackingCalibrationSession(
            self.clock, stale_after_s=self.config.gesture.stale_after_s,
            eye_limits=(thresholds.get("blink_left", .045), thresholds.get("blink_right", .045)),
            eye_source=self.config.ui.eye_source, camera_context=self._relative_camera_context(),vertical_reference=self.config.eye.vertical_reference)
        self.state = "EYE_CALIBRATING"
        self.message = "Modo experimental: calibración de tracking ocular, con el control desactivado."

    def start_vertical_diagnostic(self):
        from vertical_diagnostic import VerticalDiagnosticSession,DiagnosticMovementTrace
        self.stop_control()
        if self.experiment and self.experiment.active:self.experiment.cancel()
        self.jitter=self.eye_calibration=self.gaze_calibration=None
        self.start_camera()
        thresholds=gesture_profile(self.profile,method_bank(self.config)).get("thresholds",{})
        self.vertical_diagnostic=VerticalDiagnosticSession(self.config.ui.eye_source,self.clock,
            limits=(thresholds.get("blink_left",.045),thresholds.get("blink_right",.045)))
        self._vertical_trace=DiagnosticMovementTrace(self.profile,self.config,self.clock)
        self.vertical_diagnostic.trace_method=self._vertical_trace.method
        self.vertical_diagnostic.trace_context=dict(selected_method=self.config.ui.tracking_method,
            eye=asdict(self.config.eye),absolute=asdict(self.config.absolute),camera_index=self.config.vision.camera_index,
            saved_context=self._vertical_trace.saved_context,profile_id=self.profile["user_id"])
        self._vertical_saved=False
        self.state="VERTICAL_DIAGNOSTIC"
        self.message="Seguí centro, arriba y abajo. El backend es sólo memoria: no mueve el mouse."

    def repeat_vertical_point(self,index=None):
        if not self.vertical_diagnostic:raise ValueError("Iniciá el diagnóstico vertical")
        self.vertical_diagnostic.repeat(self.vertical_diagnostic.index if index is None else index)
        self._vertical_saved=False

    def cancel_vertical_diagnostic(self):
        self.stop_control()
        self.vertical_diagnostic=self._vertical_trace=None
        if self.state=="VERTICAL_DIAGNOSTIC":self.state="PREVIEW"

    def save_eye_calibration(self):
        if self.state != "EYE_CALIBRATING" or self.eye_calibration is None:
            raise ValueError("Iniciá la calibración ocular primero")
        if not self._persist_ocular_session(self.eye_calibration, "eye"):
            return False
        self.eye_calibration = None
        self._make_gesture()
        self.state, self.message = "DIAGNOSTIC", "Neutral ocular guardado. Probá las direcciones en Diagnóstico seguro."
        return True

    def _persist_ocular_session(self, session, method):
        """No mutar el perfil en memoria ni descartar la sesión hasta releerlo."""
        written = False
        try:
            result = session.result()
            if result.get("method") != method or result.get("eye_source", "both") != session.eye_source:
                raise ValueError("El modelo no corresponde al método/fuente de la sesión")
            if session.eye_source != self.config.ui.eye_source:
                raise ValueError("La fuente seleccionada cambió: restaurá la fuente de esta sesión antes de guardar")
            if method == "eye":
                TrackingCalibration.from_record(result)
                if result.get("vertical_reference","eyelids")!=self.config.eye.vertical_reference:
                    raise ValueError("La referencia vertical cambió durante la captura: repetí la calibración ocular")
                if result.get("camera_context") and result["camera_context"] != self._relative_camera_context():
                    raise ValueError("Cambió la cámara o resolución durante la captura: recalibrá")
            else:
                from gaze_mapping import GazeModel
                if not GazeModel(result).record["validated"]:
                    raise ValueError("Falta aprobar la validación absoluta independiente")
                if {key:result["context"][key] for key in ("camera_index", "frame_width", "frame_height")} != self._relative_camera_context():
                    raise ValueError("Cambió la cámara o resolución durante la captura: recalibrá")
            candidate = with_calibration(self.profile, result)
            self.profiles.store.save(candidate)
            written = True
            loaded = self.profiles.store.load(candidate["user_id"])
            if calibration_for(loaded, method, session.eye_source) != result:
                raise ValueError("La lectura posterior no coincide con la calibración guardada")
        except (ValueError, OSError, RuntimeError) as exc:
            status = "El perfil se escribió, pero no se confirmó su lectura" if written else "No se guardó la sesión"
            session.message = self.message = f"{status}: {exc}. La sesión se conserva; repetí el punto indicado o reintentá el guardado."
            return False
        self.profile = loaded
        return True

    def cancel_eye_calibration(self):
        self.eye_calibration = None
        if self.state == "EYE_CALIBRATING":
            self.state, self.message = "PREVIEW", "Calibración ocular cancelada."

    def _camera_context(self, screen_context):
        from screen_mapping import screen_display
        if not isinstance(screen_context,dict):
            raise ValueError("Falta identificar la pantalla principal")
        screen_display(screen_context)
        frame = self.vision.get_frame()
        if frame is None:
            raise ValueError("Esperá un frame de cámara antes de calibrar")
        from screen_mapping import capture_host_id
        context=dict(capture_host=capture_host_id(), width=screen_context["width"], height=screen_context["height"],
                    dpr=screen_context["dpr"], screen=screen_context["screen"],
                    camera_index=self.config.vision.camera_index,
                    frame_width=frame.shape[1], frame_height=frame.shape[0])
        if "display" in screen_context:
            context["display"]=deepcopy(screen_context["display"])
        return context

    def _check_absolute_context(self, screen_context):
        context = self._camera_context(screen_context)
        from screen_mapping import same_context
        if not same_context(self._tracking_record()["context"],context):
            raise ValueError("El entorno guardado no coincide o no identifica este equipo (pantalla, DPI, cámara o resolución). Recalibrá ojos absolutos")

    def start_gaze_calibration(self, screen_context, relative=False):
        from gaze_mapping import GazeCalibrationSession
        if self.state == "CALIBRATING":
            raise ValueError("Terminá la calibración de gestos primero")
        self.stop_control()
        if self.experiment and self.experiment.active:
            self.experiment.cancel()
        self.jitter = self.eye_calibration = None
        self.start_camera()
        context = self._camera_context(screen_context)
        profile = gesture_profile(self.profile, method_bank(self.config))
        thresholds = profile.get("thresholds", {})
        self.gaze_calibration = GazeCalibrationSession(context, self.clock,
            self.config.gesture.stale_after_s,
            eye_limits=(thresholds.get("blink_left", .045), thresholds.get("blink_right", .045)), relative=relative,
            eye_source=self.config.ui.eye_source)
        self.gaze_calibration.vertical_reference=self.config.eye.vertical_reference if relative else "eyelids"
        self._gaze_logged = None
        self.state, self.message = "GAZE_CALIBRATING", "Captura guiada sin salida al mouse. Escape cancela."

    def repeat_gaze_point(self, index=None):
        if self.gaze_calibration is None or self.state != "GAZE_CALIBRATING":
            raise ValueError("Iniciá la calibración multipunto primero")
        self.gaze_calibration.repeat(index)

    def record_gaze_viewport(self, phase, index, logical_rect, dpr, target_local_logical=None):
        session = self.gaze_calibration
        if session and session.phase == phase and session.index == index:
            # Telemetría de la ventana real; no se cambian las coordenadas del modelo.
            local = target_local_logical or [session.snapshot()["target"][0]*(logical_rect[2]-1),session.snapshot()["target"][1]*(logical_rect[3]-1)]
            session.viewport = dict(phase=phase, point_index=index, logical_rect=list(logical_rect), dpr=dpr,
                expected_physical_size=[session.context["width"],session.context["height"]],
                drawn_target_local_physical=[local[0]*dpr,local[1]*dpr],
                drawn_target_global_logical=[logical_rect[0]+local[0],logical_rect[1]+local[1]])

    def export_gaze_attempt(self):
        if self.gaze_calibration is None or self.state != "GAZE_CALIBRATING":
            raise ValueError("No hay intento ocular para exportar")
        path = ResultStore(self.data_dir / "calibration").append(uuid.uuid4().hex,
            dict(recorded_at=time.time(), **self.gaze_calibration.diagnostic_record()))
        self.gaze_calibration.message = "Diagnóstico guardado en "+str(path)+". No aprueba calibración ni habilita el control."

    def review_gaze_training(self):
        if self.gaze_calibration is None or self.state != "GAZE_CALIBRATING":
            raise ValueError("Iniciá la calibración multipunto primero")
        self.gaze_calibration.review_training()

    def save_gaze_calibration(self):
        if self.gaze_calibration is None or self.state != "GAZE_CALIBRATING":
            raise ValueError("No hay calibración multipunto para guardar")
        session = self.gaze_calibration
        method = "eye" if session.relative else "eye_absolute"
        if not self._persist_ocular_session(session, method):
            return False
        self.gaze_calibration = None
        self._make_gesture()
        self.state, self.message = "DIAGNOSTIC", f"Movimiento ocular · {SOURCE_LABELS[session.eye_source]} guardado y releído. Probá el diagnóstico seguro antes de activar control."
        if method != self.config.ui.tracking_method:
            self.message += " Se conservó el modelo de otra respuesta ocular; revisá su compatibilidad antes de activar."
        return True

    def cancel_gaze_calibration(self):
        self.emergency_stop()
        self.gaze_calibration = None
        if self.state == "GAZE_CALIBRATING":
            self.state, self.message = "PREVIEW", "Calibración multipunto descartada; perfil anterior conservado."

    def start_experiment(self, mode="simulation", source="headmouse", conditions=None):
        if self.state in ("CALIBRATING", "EYE_CALIBRATING", "GAZE_CALIBRATING"):
            raise ValueError("Terminá o cancelá la calibración antes de medir")
        if source == "headmouse":
            self._require_tracking_calibration()
        if mode == "real" and source == "headmouse" and (not self.control or self.emergency.is_set()):
            raise ValueError("Activá el control explícitamente antes del experimento real")
        if self.experiment and self.experiment.active:
            self.experiment.cancel()
        if mode == "simulation":
            self.stop_control()
        if source == "mouse":
            self.stop_camera()
        if source == "headmouse":
            self._require_profile(calibrated=True)
            self.start_camera()
        self.jitter = None
        metadata = dict(operator=deepcopy(conditions or {}), settings=asdict(self.config))
        if self.profile:
            active = selected_profile(gesture_profile(self.profile, method_bank(self.config)), self.config.ui.eye_source)
            metadata["calibration"] = {key:deepcopy(active[key]) for key in
                ("thresholds", "gesture_calibrations", "tracking_calibration", "absolute_calibration") if key in active}
        self.experiment = ExperimentEngine(self.profile["user_id"] if self.profile else "demo", mode, source,
                                            ResultStore(self.data_dir / "experiments"), self.clock,
                                            tracking_method=self.config.ui.tracking_method, metadata=metadata)
        self.state = "EXPERIMENT"
        self.message = "Seleccioná los objetivos. Los resultados se guardan automáticamente."

    def experiment_input(self, x=0, y=0, click=False, absolute=False):
        if not self.experiment or not self.experiment.active:
            return
        if absolute and self.experiment.mode == "real":
            if self.experiment.source == "mouse":
                self.experiment.observe(x, y)
                if click:
                    self.experiment.click()
                return
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
        if self.state in ("CALIBRATING", "EYE_CALIBRATING", "GAZE_CALIBRATING"):
            raise ValueError("Terminá o cancelá la calibración antes de medir")
        self.stop_control()
        self._require_profile(calibrated=True)
        self._require_tracking_calibration()
        self.start_camera()
        if self.experiment and self.experiment.active:
            self.experiment.cancel()
        eye = self.config.ui.tracking_method == "eye"
        absolute = self.config.ui.tracking_method == "eye_absolute"
        self.jitter = JitterMeasurement((0., 0.) if eye else (self.profile.get("neutral_nose_x", .5),
                                        self.profile.get("neutral_nose_y", .5)),
                                       self.config.eye.dead_zone if eye else self.config.gesture.dead_zone,
                                       clock=self.clock, strategy=self.gesture.strategy)
        if absolute:
            self.jitter.neutral = (.5, .5)
            self.jitter.dead_zone = .03
        self.jitter_result = None
        self.state = "JITTER"
        self.message = "Mantené la mirada en neutral durante 10 segundos." if eye else "Mantené la cabeza en neutral durante 10 segundos."

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
        if self._camera_starting:
            return
        if self.state == "ERROR":
            return  # conservar el diagnóstico original; nunca procesar acciones tras fallar
        if self.emergency.is_set() and self.control:
            self.stop_control(self._pending_stop_reason)
        if self.experiment:
            self.experiment.tick()
        if self.vision is None:
            return
        if self.vision.error or not self.vision.is_alive():
            raise RuntimeError("La cámara o MediaPipe se detuvo. Revisá la conexión y volvé a abrir la cámara.")
        face = self.vision.get_face_data()
        if self.control and self.config.ui.tracking_method in ("eye", "eye_absolute"):
            size = getattr(self.vision, "_frame_size", None)
            record = self._tracking_record() or {}
            context = record.get("context") or record.get("camera_context")
            if context and isinstance(size, tuple) and size != (context["frame_width"], context["frame_height"]):
                self.emergency_stop()
                raise RuntimeError("Cambió la resolución de cámara: recalibrá la fuente ocular seleccionada")
        fresh = face.fresh(self.config.gesture.stale_after_s, self.clock())
        events, actions = [], []
        if self.state=="VERTICAL_DIAGNOSTIC" and self.vertical_diagnostic:
            self.vertical_diagnostic.update(face,self._vertical_trace.feed(face))
            if self.vertical_diagnostic.state in ("ready","error") and not self._vertical_saved:
                path=ResultStore(self.data_dir/"experiments").append(uuid.uuid4().hex,
                    dict(experiment="vertical_diagnostic",schema_version=1,recorded_at=time.time(),**self.vertical_diagnostic.report()))
                self.message="Diagnóstico vertical guardado en "+path+". No se modificaron calibraciones."
                self._vertical_saved=True
        elif self.state == "GAZE_CALIBRATING" and self.gaze_calibration:
            self.gaze_calibration.update(face)
            session = self.gaze_calibration
            key = (session.revision, session.state if session.state in ("ready", "invalid", "error") else "progress",
                   session.phase, session.index, len(session.points), len(session.validation_points))
            if (session.points or session.validation_points or session.state in ("invalid", "error")) and key != self._gaze_logged:
                ResultStore(self.data_dir / "calibration").append(uuid.uuid4().hex,
                    dict(experiment="relative_ranges" if session.relative else "absolute_calibration", schema_version=1,
                         profile_id=self.profile["user_id"], recorded_at=time.time(), context=session.context,
                         eye_source=session.eye_source,
                         state=session.state, outcome=session.outcome, message=session.message,
                         training_report=session.model.record.get("training_report") if session.model else None,
                         model=session.model.record if session.model else None,
                         validation_points=list(session.validation_points.values()),
                         points=[{k:v for k,v in point.items() if k!="features"} for point in session.points.values()],
                         rejected_points={i:{k:v for k,v in point.items() if k!="features"} for i,point in session.rejected_points.items()},
                         direction_check=session.last_check,
                         validation=session.model.record["validation"] if session.model else None))
                self._gaze_logged = key
        elif self.state == "EYE_CALIBRATING" and self.eye_calibration:
            self.eye_calibration.update(face)
        elif self.state == "CALIBRATING" and self.wizard:
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
        discrete = [e for e in events if e.type not in ("CURSOR_MOVE", "CURSOR_ABSOLUTE")]
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
        absolute = next((e for e in events if e.type == "CURSOR_ABSOLUTE"), None)
        if absolute:
            target = (absolute.dx*800, absolute.dy*500)
            dx, dy = target[0]-self.cursor[0], target[1]-self.cursor[1]
            self.cursor = target
        if self.experiment and self.experiment.active and self.experiment.mode == "simulation" and self.experiment.source == "headmouse":
            if face.timestamp_ms != self._last_face and fresh:
                self.experiment.move(dx, dy, self.vision.get_fps(), face.processing_ms)
                if any(e.type in ("LEFT_CLICK", "DOUBLE_CLICK") for e in actions):
                    self.experiment.click()
        if self.jitter:
            self.jitter.add(face, self.config.gesture.stale_after_s)
            if self.jitter.done:
                self.jitter_result = self.jitter.summary()
                record = dict(experiment="jitter", profile_id=self.profile["user_id"], tracking_method=self.config.ui.tracking_method,
                              recorded_at=time.time(), **self.jitter_result)
                self.jitter_result["path"] = ResultStore(self.data_dir / "experiments").append(uuid.uuid4().hex, record)
                self.jitter = None
                self.state = "DIAGNOSTIC"
        self._last_face = face.timestamp_ms

    def snapshot(self, include_frame=True):
        face = self.vision.get_face_data() if self.vision else FaceData(False)
        fresh = face.fresh(self.config.gesture.stale_after_s, self.clock())
        profile = selected_profile(gesture_profile(self.profile, method_bank(self.config)), self.config.ui.eye_source) if self.profile else None
        record = self._tracking_record()
        compatible = not record or (record.get("camera_context") or record.get("context") or {}).get("camera_index", self.config.vision.camera_index) == self.config.vision.camera_index
        if self.config.ui.tracking_method=="eye" and record and record.get("vertical_reference","eyelids")!=self.config.eye.vertical_reference:compatible=False
        if self.config.ui.tracking_method=="eye" and record and self.config.eye.vertical_reference=="canthi" and not record.get("ranges_measured"):compatible=False
        camera_status = self.camera_status()
        capture_context = self._relative_camera_context()
        conditions = []
        warnings = []
        if not profile:
            conditions.append("Seleccioná un perfil")
        if not self._actions_ready():
            text="Gestos pendientes de validar para este método"+("; sólo movimiento, sin clics" if self.config.ui.tracking_method!="nose" else "")
            (warnings if self.config.ui.tracking_method!="nose" else conditions).append(text)
        if self.config.ui.tracking_method != "nose":
            if not record:
                conditions.append("Sin calibración para el método y fuente seleccionados")
            elif not compatible or (self.config.ui.tracking_method == "eye_absolute" and not record.get("validated")):
                conditions.append("Calibración incompatible o sin comprobación de precisión")
            context = (record or {}).get("camera_context") or (record or {}).get("context")
            current = capture_context
            if context and current and any(context[k] != current[k] for k in current):
                compatible = False
                conditions.append("Calibración incompatible con la cámara/resolución actual")
            if record and self.config.ui.tracking_method=="eye_absolute":
                from screen_mapping import capture_host_id
                if context.get("capture_host") != capture_host_id():
                    compatible = False
                    conditions.append("La calibración no identifica este equipo; recalibrá el movimiento ocular")
            if not fresh or eye_coordinates(face, self.config.ui.eye_source,
                self.config.eye.vertical_reference if self.config.ui.tracking_method=="eye" else (record or {}).get("vertical_reference","eyelids")) is None:
                conditions.append("Iris seleccionado no detectado o frame vencido")
        if not camera_status.get("ready"):
            conditions.append("Cámara no iniciada o todavía no lista")
        if self.state in ("CALIBRATING", "EYE_CALIBRATING", "GAZE_CALIBRATING", "VERTICAL_DIAGNOSTIC", "JITTER") or (self.experiment and self.experiment.active):
            conditions.append("Terminá o cancelá la medición en curso")
        blockers = list(conditions)
        if not self.control:
            conditions.append("Falta confirmación explícita de activación")
        elif self.control.paused:
            conditions.append("Control pausado")
        tracking_ready=self.config.ui.tracking_method=="nose" or bool(record and compatible and
            (record.get("validated") if self.config.ui.tracking_method=="eye_absolute" else True))
        profile_status=self.profiles.status(profile) if profile else "Sin perfil"
        if profile and self.config.ui.unified_eyes and self.config.ui.tracking_method!="nose":
            profile_status="Ojos · Movimiento "+("calibrado" if tracking_ready else "pendiente o incompatible")+" · Gestos "+("validados" if self._actions_ready() else "pendientes")
        return dict(state=self.state, message=self.message, profile=profile,
                    public_method="nose" if self.config.ui.tracking_method=="nose" else "eyes",
                    ocular_response="posición en pantalla" if self.config.ui.ocular_engine=="eye_absolute" else "dirección conservada del perfil anterior",
                    profile_status=profile_status,
                    settings=asdict(self.config), camera=self.vision is not None,
                    mediapipe="Listo" if camera_status.get("ready") else camera_status["stage"],
                    camera_status=camera_status,
                    activation_conditions=conditions+warnings,
                    activation_blockers=blockers, activation_warnings=warnings,
                    capture_context=capture_context,
                    actions_ready=self._actions_ready(),
                    face=face, detected=fresh, fps=self.vision.get_fps() if self.vision else 0,
                    processing_ms=face.processing_ms if fresh else 0,
                    frame=self.vision.get_frame() if self.vision and include_frame else None,
                    control_enabled=bool(self.control and not self.emergency.is_set()),
                    paused=self.control.paused if self.control else True,
                    gesture=self.last_gesture, action=self.last_action, cursor=self.cursor,
                    diagnostic=self.gesture.diagnostic() if self.gesture else {},
                    wizard=self.wizard.snapshot() if self.wizard else None,
                    eye_calibration=self.eye_calibration.snapshot() if self.eye_calibration else None,
                    gaze_calibration=self.gaze_calibration.snapshot() if self.gaze_calibration else None,
                    vertical_diagnostic=self.vertical_diagnostic.snapshot() if self.vertical_diagnostic else None,
                    vertical_report=self.vertical_diagnostic.report() if self.vertical_diagnostic else None,
                    vertical_trace=deepcopy(self._vertical_trace.last) if self._vertical_trace else {},
                    eye_source=self.config.ui.eye_source,
                    eye_source_label=SOURCE_LABELS[self.config.ui.eye_source],
                    eye_availability={side: bool(fresh and eye_coordinates(face, side) is not None) for side in ("left", "right")},
                    used_gaze=gaze_position(face, self.config.ui.eye_source,
                        self.config.eye.vertical_reference if self.config.ui.tracking_method=="eye" else
                        (self.gaze_calibration.vertical_reference if self.gaze_calibration else (record or {}).get("vertical_reference","eyelids"))) if fresh else None,
                    tracking_calibrated=tracking_ready,
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
