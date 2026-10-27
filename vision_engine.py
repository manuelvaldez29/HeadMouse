"""
vision_engine.py
HeadMouse — Módulo 1: Vision Engine
Tesis UNSTA 2026 — Bloj · Domfrocht · Petrelli · Valdez

Responsabilidad:
    Capturar frames de la webcam y extraer landmarks faciales con
    MediaPipe Face Landmarker. Corre en un hilo separado (daemon thread)
    para no bloquear al Gesture Engine ni al Control Engine.

Uso desde otro módulo:
    engine = VisionEngine()
    engine.start()

    while True:
        data = engine.get_face_data()
        if data.detected:
            print(f"Nariz: ({data.nose_x:.3f}, {data.nose_y:.3f})")
            print(f"Ojo izq: {data.eye_left_ratio:.3f}")

    engine.stop()
"""

import os
import sys
import math
import logging
from pathlib import Path
from dataclasses import replace
from config import ROOT, VisionConfig
from face_data import FaceData
from gesture_signals import extract_blendshapes
from face_geometry import brow_lift_3d, head_pose
from eye_geometry import extract_gaze

logger = logging.getLogger(__name__)
import threading
import time
import urllib.request
from typing import Optional

import cv2
import numpy as np
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision as mp_vision


# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTES
# ══════════════════════════════════════════════════════════════════════════════

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "face_landmarker/face_landmarker/float16/1/face_landmarker.task"
)
MODEL_PATH = str(ROOT / "models" / "face_landmarker.task")

# Índices de landmarks clave del Face Mesh de MediaPipe (478 puntos total)
# Referencia: https://developers.google.com/mediapipe/solutions/vision/face_landmarker
LM_IDX = {
    # ── Control del cursor ────────────────────────────────────────────────────
    "nose_tip":         1,     # punto de control principal del cursor

    # ── Detección de guiño (click) ────────────────────────────────────────────
    "eye_left_upper":   159,   # párpado superior izquierdo
    "eye_left_lower":   145,   # párpado inferior izquierdo
    "eye_right_upper":  386,   # párpado superior derecho
    "eye_right_lower":  374,   # párpado inferior derecho

    # ── Detección de cejas (scroll) ───────────────────────────────────────────
    "brow_left":  [70, 63, 105, 66, 107],    # 5 puntos ceja izquierda
    "brow_right": [336, 296, 334, 293, 300], # 5 puntos ceja derecha

    # ── Detección de boca abierta (gesto combinado) ───────────────────────────
    "mouth_upper": 13,   # labio superior interno
    "mouth_lower": 14,   # labio inferior interno

    # ── Referencias para normalización ───────────────────────────────────────
    "ear_left":    234,  # trago oreja izquierda
    "ear_right":   454,  # trago oreja derecha
    "nose_bridge": 6,    # puente nasal (referencia vertical para cejas)
}


# ══════════════════════════════════════════════════════════════════════════════
# DATACLASS DE DATOS FACIALES
# ══════════════════════════════════════════════════════════════════════════════

class VisionEngine(threading.Thread):
    """
    Hilo de captura y detección facial.

    Usa MediaPipe Face Landmarker en modo LIVE_STREAM (asíncrono) para
    minimizar latencia. Los resultados se entregan via callback interno
    y se almacenan en un atributo compartido protegido por Lock.

    Attributes:
        camera_index: índice de la webcam (0 = cámara por defecto)
        target_fps:   FPS objetivo de captura
    """

    def __init__(self, camera_index: int = 0, target_fps: int = 30, config=None, metrics=None):
        super().__init__(daemon=True, name="VisionEngine")
        self.config = config or VisionConfig(camera_index=camera_index, target_fps=target_fps)
        self.config.__post_init__()
        self.camera_index = self.config.camera_index
        self.target_fps = self.config.target_fps
        self.metrics = metrics
        self.error = None
        self.ready = threading.Event()
        self.first_frame = threading.Event()
        self.detector_ready = threading.Event()
        self.first_result = threading.Event()
        self._usable = threading.Event()
        self._stop_requested = threading.Event()
        self.model_path = Path(self.config.model_path)
        if not self.model_path.is_absolute():
            self.model_path = ROOT / self.model_path

        # ── Estado compartido ─────────────────────────────────────────────────
        self._lock      = threading.Lock()
        self._face_data = FaceData(detected=False)
        self._fps       = 0.0
        self._frame: Optional[np.ndarray] = None
        self._frame_size = (1, 1)  # ancho, alto: escala de x/y/z para geometría 3D

        # ── Control del hilo ──────────────────────────────────────────────────
        self._running = False
        self._stopped = threading.Event()
        self._created_at = time.monotonic()
        self._stage = "CREATED"
        self._operation = "idle"
        self._operation_at = self._created_at
        self._timeline = {}
        self._captured = self._processed = 0
        self._raw_face_results = self._valid_face_results = self._rejected_face_results = 0
        self._face_status = "WAITING"
        self._processing_times = []
        self._backend_effective = None
        self._accepted = {}

        # ── Asegurar modelo descargado ────────────────────────────────────────
        self._ensure_model(self.model_path)

    # ── API pública ───────────────────────────────────────────────────────────

    def get_face_data(self) -> FaceData:
        """Devuelve el último FaceData procesado. Thread-safe."""
        with self._lock:
            return self._face_data

    def get_fps(self) -> float:
        """FPS de captura en la última ventana de un segundo, no inferencia."""
        with self._lock:
            return self._fps

    def get_frame(self) -> Optional[np.ndarray]:
        """Devuelve el último frame BGR capturado (para preview/debug)."""
        with self._lock:
            return self._frame.copy() if self._frame is not None else None

    def wait_ready(self, timeout=None):
        if not self.ready.wait(self.config.startup_timeout_s if timeout is None else timeout):
            status = self.diagnostics()
            self.request_stop()
            raise TimeoutError(f"Inicio de cámara/MediaPipe agotado: etapa {status['stage']}, "
                               f"operación {status['operation']} ({status['operation_elapsed_s']:.2f} s). "
                               f"Frames={status['captured_frames']}, resultados={status['processed_results']}")
        if self.error is not None:
            raise RuntimeError(f"No se pudo iniciar VisionEngine: {self.error}") from self.error
        if self._stop_requested.is_set():
            raise InterruptedError("Inicio de cámara cancelado; el motor no está autorizado")
        if not self._usable.is_set():
            raise RuntimeError("Motor detenido antes de completar captura y primer resultado")

    def diagnostics(self):
        now = time.monotonic()
        with self._lock:
            times = [t for t in self._processing_times if now-t < 1]
            return dict(stage=self._stage, operation=self._operation,
                operation_elapsed_s=max(0., now-self._operation_at),
                elapsed_s=max(0., now-self._created_at), timeline=dict(self._timeline),
                backend_requested=self.config.capture_backend, backend_effective=self._backend_effective,
                actual_frame=dict(width=self._frame_size[0],height=self._frame_size[1]),
                camera_index=self.camera_index, requested=dict(width=self.config.frame_width,
                    height=self.config.frame_height, fps=self.target_fps), accepted=dict(self._accepted),
                captured_frames=self._captured, processed_results=self._processed,
                raw_face_results=self._raw_face_results, valid_face_results=self._valid_face_results,
                rejected_face_results=self._rejected_face_results, face_status=self._face_status,
                processing_fps=len(times), ready=self._usable.is_set(),
                stop_requested=self._stop_requested.is_set(), stopped=self._stopped.is_set(),
                error=str(self.error) if self.error else None)

    def _note(self, stage, operation=None, **details):
        now = time.monotonic()
        with self._lock:
            # Un evento tardío nunca sobrescribe el cierre ni restaura readiness.
            if self._stop_requested.is_set() and stage not in ("CLOSING", "STOPPED", "TERMINAL_ERROR"):
                return
            previous_s = now-self._operation_at
            self._stage = stage
            if operation is not None:
                self._operation, self._operation_at = operation, now
            current_operation = self._operation
            self._timeline.setdefault(stage, now-self._created_at)
        logger.info("Cámara[%s] %s op=%s t=%.3fs duración_previa=%.3fs %s",
                    self.camera_index, stage, current_operation, now-self._created_at, previous_s, details or "")

    def request_stop(self):
        """Cancelación thread-safe; el propietario nativo realiza close/release."""
        with self._lock:
            self._stop_requested.set()
            self._usable.clear()
            self._face_data = FaceData(False)
            self._frame = None
        self.ready.set()  # liberar wait_ready, que comprueba la cancelación
        self._running = False

    def stop(self):
        self.request_stop()
        if self.ident is not None and threading.current_thread() is not self:
            self.join(timeout=self.config.shutdown_timeout_s)
            if self.is_alive():
                status = self.diagnostics()
                raise RuntimeError(f"Cierre pendiente tras {self.config.shutdown_timeout_s:g} s: "
                    f"etapa {status['stage']}, operación {status['operation']} "
                    f"({status['operation_elapsed_s']:.2f} s); se conserva el hilo y sus recursos")

    def _open_capture(self):
        backend = self.config.capture_backend
        if backend != "auto" and sys.platform != "win32":
            raise ValueError(f"El backend {backend} requiere Windows; seleccioná auto")
        api = {"auto":cv2.CAP_ANY, "dshow":cv2.CAP_DSHOW, "msmf":cv2.CAP_MSMF}[backend]
        self._note("CAMERA_OPENING", "camera_open", backend=backend)
        cap = cv2.VideoCapture(self.camera_index, api)
        return cap

    def _configure_capture(self, cap):
        self._note("CAMERA_OPEN", "camera_configure")
        self._backend_effective = cap.getBackendName()
        settings = ((cv2.CAP_PROP_FRAME_WIDTH, self.config.frame_width),
                    (cv2.CAP_PROP_FRAME_HEIGHT, self.config.frame_height),
                    (cv2.CAP_PROP_FPS, self.target_fps))
        for prop, value in settings:
            if value:
                accepted = cap.set(prop, value)
                logger.info("Cámara[%s] solicitar propiedad %s=%s; set=%s", self.camera_index, prop, value, accepted)
        def measured(prop):
            value=cap.get(prop)
            return value if isinstance(value,(float,int)) and math.isfinite(value) else None
        self._accepted = dict(width=measured(cv2.CAP_PROP_FRAME_WIDTH), height=measured(cv2.CAP_PROP_FRAME_HEIGHT),
                              fps=measured(cv2.CAP_PROP_FPS))
        self._note("CAMERA_OPEN", "idle", backend=self._backend_effective, accepted=self._accepted)

    def _read_capture(self, cap):
        with self._lock:
            self._operation, self._operation_at = "camera_read", time.monotonic()
        started = time.monotonic()
        ok, frame = cap.read()
        if self._stop_requested.is_set():
            return None
        if not ok or frame is None:
            return None
        height, width = frame.shape[:2]
        if width < 2 or height < 2:
            return None
        frame = cv2.flip(frame, 1)  # espejo histórico, sin cambiar tracking
        now = time.monotonic()
        with self._lock:
            if self._stop_requested.is_set():
                return None
            self._frame_size = (width, height)
            self._frame = frame
            self._captured += 1
        if not self.first_frame.is_set():
            self.first_frame.set()
            self._note("FIRST_FRAME", read_s=now-started, width=width, height=height)
        return frame

    def _mark_ready(self):
        with self._lock:
            if self._stop_requested.is_set() or self.error is not None:
                return
            complete = self.first_frame.is_set() and self.detector_ready.is_set() and self.first_result.is_set()
            new = complete and not self._usable.is_set()
            if complete:
                self._usable.set()
                self.ready.set()
        if new:
            self._note("READY")

    def run(self):
        cap = detector = None
        self._running = not self._stop_requested.is_set()
        try:
            if self._stop_requested.is_set():
                return
            cap = self._open_capture()
            if self._stop_requested.is_set():
                return
            if not cap.isOpened():
                raise RuntimeError(f"No se pudo abrir la cámara {self.camera_index} con {self.config.capture_backend}")
            self._configure_capture(cap)
            failures = 0
            frame = None
            # Probar primero OpenCV permite separar hardware/driver de MediaPipe.
            while frame is None and not self._stop_requested.is_set():
                frame = self._read_capture(cap)
                if frame is None:
                    failures += 1
                    if time.monotonic()-self._created_at >= self.config.startup_timeout_s:
                        raise TimeoutError("La cámara abrió pero no entregó el primer frame dentro del tiempo inicial")
                    if failures == 1:
                        self._note("RECOVERABLE_ERROR", "camera_read", failures=failures)
                    self._stop_requested.wait(.01)
            if self._stop_requested.is_set():
                return
            self._note("MEDIAPIPE_INITIALIZING", "detector_init")
            with open(str(self.model_path), "rb") as f:
                model_bytes = f.read()
            options = mp_vision.FaceLandmarkerOptions(
                base_options=mp_python.BaseOptions(model_asset_buffer=model_bytes),
                running_mode=mp_vision.RunningMode.LIVE_STREAM,
                num_faces=1,
                min_face_detection_confidence=self.config.detection_confidence,
                min_face_presence_confidence=self.config.presence_confidence,
                min_tracking_confidence=self.config.tracking_confidence,
                output_face_blendshapes=True,
                output_facial_transformation_matrixes=False,
                result_callback=self._on_result,
            )
            previous_ts = 0
            fps_times = []
            detector = mp_vision.FaceLandmarker.create_from_options(options)
            if self._stop_requested.is_set():
                return  # cerrar detector recién creado sin enviarle una imagen
            self.detector_ready.set()
            self._note("MEDIAPIPE_READY")
            frame = None  # el frame de prueba puede haberse envejecido al cargar el grafo
            failures = 0
            if detector is not None:
                while not self._stop_requested.is_set():
                    started = time.monotonic()
                    if frame is None:
                        frame = self._read_capture(cap)
                    if frame is None:
                        if self._stop_requested.is_set():
                            break
                        failures += 1
                        with self._lock:
                            self._face_data = FaceData(False)
                        if failures >= self.config.capture_failure_limit:
                            raise RuntimeError("La cámara dejó de entregar frames")
                        if failures == 1:
                            self._note("RECOVERABLE_ERROR", "camera_read", failures=failures)
                        self._stop_requested.wait(0.01)
                        continue
                    recovered = failures > 0
                    failures = 0
                    if recovered and self._usable.is_set():
                        self._note("READY", "idle", recovered=True)
                    ts_ms = max(previous_ts + 1, int(time.monotonic() * 1000))
                    previous_ts = ts_ms
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                    with self._lock:
                        self._operation, self._operation_at = "detect_async", time.monotonic()
                    if not self.first_result.is_set() and previous_ts == ts_ms and not fps_times:
                        self._note("FIRST_SUBMISSION", "detect_async", timestamp_ms=ts_ms)
                    detector.detect_async(mp_img, ts_ms)
                    fps_times.append(started)
                    fps_times = [t for t in fps_times if started - t < 1]
                    with self._lock:
                        self._fps = float(len(fps_times))
                    frame = None
                    self._mark_ready()
                    self._stop_requested.wait(max(0, 1 / self.target_fps - (time.monotonic() - started)))
        except Exception as exc:
            self.error = exc
            self.request_stop()
            self._note("TERMINAL_ERROR", self._operation, error=str(exc))
            self.ready.set()
            logger.exception("VisionEngine detenido por error")
        finally:
            self.request_stop()
            if detector is not None:
                self._note("CLOSING", "detector_close")
                try:
                    detector.close()
                except Exception as exc:
                    self.error = self.error or exc
                    logger.exception("Error al cerrar MediaPipe")
            try:
                if cap is not None:
                    self._note("CLOSING", "camera_release")
                    cap.release()
            except Exception as exc:
                self.error = self.error or exc
                logger.exception("Error al liberar cámara")
            with self._lock:
                self._frame = None
                self._face_data = FaceData(False)
            self._running = False
            self._usable.clear()
            self.ready.set()
            self._stopped.set()
            self._note("STOPPED", "idle")

    # ── Callback de resultados ────────────────────────────────────────────────

    def _on_result(self, result, output_image, timestamp_ms: int):
        """
        Callback interno llamado por MediaPipe cuando el resultado está listo.
        Corre en el hilo del detector, NO en el hilo principal.
        """
        if self._stop_requested.is_set():
            return
        try:
            raw_faces = len(getattr(result,"face_landmarks",()) or ())
            face_data = self._extract(result, timestamp_ms)
            face_status = "VALID_FACE" if face_data.detected else "EXTRACTION_REJECTED" if raw_faces else "NO_LANDMARKS"
            now = time.monotonic()
            face_data = replace(face_data, detected_at=now,
                                processing_ms=max(0, (now - timestamp_ms / 1000) * 1000))
            if face_data.detected and not face_data.valid():
                face_status = "INVALID_FACE_DATA"
                face_data = FaceData(False, timestamp_ms=timestamp_ms, detected_at=now,
                                     processing_ms=face_data.processing_ms)
            with self._lock:
                if self._stop_requested.is_set() or timestamp_ms <= self._face_data.timestamp_ms:
                    return
                self._face_data = face_data
                self._processed += 1
                self._raw_face_results += int(raw_faces > 0)
                self._valid_face_results += int(face_data.detected)
                self._rejected_face_results += int(raw_faces > 0 and not face_data.detected)
                self._face_status = face_status
                self._processing_times.append(now)
                self._processing_times = [t for t in self._processing_times if now-t < 1]
            if self.metrics:
                self.metrics.frame(face_data)
            if not self.first_result.is_set():
                self.first_result.set()
                self._note("FIRST_RESULT", processing_ms=face_data.processing_ms,
                           face_status=face_status, raw_faces=raw_faces)
            self._mark_ready()
        except Exception as exc:
            self.error = exc
            self.request_stop()
            self._note("TERMINAL_ERROR", error=str(exc))
            logger.exception("Error procesando callback facial")

    # ── Extracción de datos faciales ──────────────────────────────────────────

    def _extract(self, result, timestamp_ms: int) -> FaceData:
        """Convierte el resultado de MediaPipe en un FaceData limpio."""

        if not result.face_landmarks:
            return FaceData(detected=False, timestamp_ms=timestamp_ms)

        lms = result.face_landmarks[0]
        if len(lms) < 455 or not all(np.isfinite(p.x) and np.isfinite(p.y) for p in lms[:468]):
            return FaceData(False, timestamp_ms=timestamp_ms)

        # Escala facial: distancia entre orejas (invariante a distancia cámara)
        scale = abs(lms[LM_IDX["ear_left"]].x - lms[LM_IDX["ear_right"]].x)
        if scale <= 1e-6:
            return FaceData(False, timestamp_ms=timestamp_ms)

        # Nariz
        nose = lms[LM_IDX["nose_tip"]]

        # Ratios de apertura de ojos
        eye_l = self._eye_ratio(
            lms[LM_IDX["eye_left_upper"]],
            lms[LM_IDX["eye_left_lower"]],
            scale,
        )
        eye_r = self._eye_ratio(
            lms[LM_IDX["eye_right_upper"]],
            lms[LM_IDX["eye_right_lower"]],
            scale,
        )

        # Elevación de cejas relativa al puente nasal
        brow_l_y    = np.mean([lms[i].y for i in LM_IDX["brow_left"]])
        brow_r_y    = np.mean([lms[i].y for i in LM_IDX["brow_right"]]) 

        # Referencia: comisura del ojo del mismo lado (landmark 33=izq, 263=der).
        # Esto hace la medición robusta a la rotación de cabeza: cuando el usuario
        # inclina la cabeza, la ceja y el ojo se mueven juntos → distancia constante.
        # Solo un levantamiento real de ceja aumenta esta distancia.
        eye_l_y     = lms[33].y
        eye_r_y     = lms[263].y
        brow_l_lift = float((eye_l_y - brow_l_y) / scale)
        brow_r_lift = float((eye_r_y - brow_r_y) / scale)            

        width, height = self._frame_size
        gaze = extract_gaze(lms, width, height, mirrored=True)
        lift_3d = brow_lift_3d(lms, width, height) if all(
            np.isfinite(getattr(p, "z", np.nan)) for p in lms) else None
        pose = head_pose(lms, width, height) if lift_3d is not None else None

        # Apertura de boca
        mouth_open = abs(
            lms[LM_IDX["mouth_upper"]].y - lms[LM_IDX["mouth_lower"]].y
        ) / scale

        return FaceData(
            detected        = True,
            **gaze,
            nose_x          = nose.x,
            nose_y          = nose.y,
            eye_left_ratio  = eye_l,
            eye_right_ratio = eye_r,
            brow_left_lift  = brow_l_lift,
            brow_right_lift = brow_r_lift,
            mouth_open      = mouth_open,
            face_scale      = scale,
            timestamp_ms    = timestamp_ms,
            blendshapes     = extract_blendshapes((getattr(result, "face_blendshapes", None) or [[]])[0]),
            brow_left_3d    = lift_3d[0] if lift_3d else None,
            brow_right_3d   = lift_3d[1] if lift_3d else None,
            head_pitch      = pose[0] if pose else None,
            head_yaw        = pose[1] if pose else None,
            head_roll       = pose[2] if pose else None,
            landmarks       = tuple((float(lms[i].x), float(lms[i].y)) for i in
                                    (1, 159, 145, 386, 374, 70, 105, 107, 336, 334, 300, 13, 14)),
        )

    @staticmethod
    def _eye_ratio(upper, lower, scale: float) -> float:
        """Ratio de apertura de ojo normalizado por escala facial."""
        return abs(upper.y - lower.y) / scale

    # ── Descarga del modelo ───────────────────────────────────────────────────

    @staticmethod
    def _ensure_model(path=MODEL_PATH):
        if not Path(path).is_file() or Path(path).stat().st_size == 0:
            raise FileNotFoundError(
                f"Falta el modelo local: {path}. Ejecutar python main.py --download-model "
                "durante la preparación con Internet.")

    @staticmethod
    def download_model(path=MODEL_PATH):
        """Descarga explícita de preparación; nunca durante uso normal."""
        import tempfile
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with urllib.request.urlopen(MODEL_URL, timeout=30) as response:
                with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
                    temporary = stream.name
                    while chunk := response.read(1024 * 1024):
                        stream.write(chunk)
            if not Path(temporary).stat().st_size:
                raise ValueError("Modelo descargado vacío")
            os.replace(temporary, path)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)
        logger.info("Modelo preparado: %s", path)
