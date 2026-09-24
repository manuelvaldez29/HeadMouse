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
import logging
from pathlib import Path
from dataclasses import replace
from config import ROOT, VisionConfig
from face_data import FaceData

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
        self._stop_requested = threading.Event()
        self.model_path = Path(self.config.model_path)
        if not self.model_path.is_absolute():
            self.model_path = ROOT / self.model_path

        # ── Estado compartido ─────────────────────────────────────────────────
        self._lock      = threading.Lock()
        self._face_data = FaceData(detected=False)
        self._fps       = 0.0
        self._frame: Optional[np.ndarray] = None

        # ── Control del hilo ──────────────────────────────────────────────────
        self._running = False
        self._stopped = threading.Event()

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
            raise TimeoutError("La cámara/MediaPipe no entregó un frame a tiempo")
        if self.error is not None:
            raise RuntimeError("No se pudo iniciar VisionEngine") from self.error

    def stop(self):
        self._stop_requested.set()
        self._running = False
        if self.ident is not None and threading.current_thread() is not self:
            self.join(timeout=3.0)
            if self.is_alive():
                raise RuntimeError("El driver de cámara no respondió al cierre en 3 s")

    def run(self):
        cap = None
        self._running = not self._stop_requested.is_set()
        try:
            if self._stop_requested.is_set():
                return
            options = mp_vision.FaceLandmarkerOptions(
                base_options=mp_python.BaseOptions(model_asset_path=str(self.model_path)),
                running_mode=mp_vision.RunningMode.LIVE_STREAM,
                num_faces=1,
                min_face_detection_confidence=self.config.detection_confidence,
                min_face_presence_confidence=self.config.presence_confidence,
                min_tracking_confidence=self.config.tracking_confidence,
                output_face_blendshapes=False,
                output_facial_transformation_matrixes=False,
                result_callback=self._on_result,
            )
            cap = cv2.VideoCapture(self.camera_index)
            if not cap.isOpened():
                raise RuntimeError(f"No se pudo abrir la cámara {self.camera_index}")
            logger.info("Cámara %s abierta; FPS objetivo %s", self.camera_index, self.target_fps)
            cap.set(cv2.CAP_PROP_FPS, self.target_fps)
            failures = 0
            previous_ts = 0
            fps_times = []
            with mp_vision.FaceLandmarker.create_from_options(options) as detector:
                while not self._stop_requested.is_set():
                    started = time.monotonic()
                    ok, frame = cap.read()
                    if not ok:
                        failures += 1
                        with self._lock:
                            self._face_data = FaceData(False)
                        if failures >= self.config.capture_failure_limit:
                            raise RuntimeError("La cámara dejó de entregar frames")
                        self._stop_requested.wait(0.01)
                        continue
                    failures = 0
                    frame = cv2.flip(frame, 1)  # conservar espejo y landmark nasal
                    ts_ms = max(previous_ts + 1, int(time.monotonic() * 1000))
                    previous_ts = ts_ms
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                    detector.detect_async(mp_img, ts_ms)
                    fps_times.append(started)
                    fps_times = [t for t in fps_times if started - t < 1]
                    with self._lock:
                        self._frame = frame
                        self._fps = float(len(fps_times))
                    self._stop_requested.wait(max(0, 1 / self.target_fps - (time.monotonic() - started)))
        except Exception as exc:
            self.error = exc
            logger.exception("VisionEngine detenido por error")
        finally:
            try:
                if cap is not None:
                    cap.release()
            except Exception as exc:
                self.error = self.error or exc
                logger.exception("Error al liberar cámara")
            with self._lock:
                self._frame = None
                self._face_data = FaceData(False)
            self._running = False
            self.ready.set()
            self._stopped.set()

    # ── Callback de resultados ────────────────────────────────────────────────

    def _on_result(self, result, output_image, timestamp_ms: int):
        """
        Callback interno llamado por MediaPipe cuando el resultado está listo.
        Corre en el hilo del detector, NO en el hilo principal.
        """
        if self._stop_requested.is_set():
            return
        try:
            face_data = self._extract(result, timestamp_ms)
            now = time.monotonic()
            face_data = replace(face_data, detected_at=now,
                                processing_ms=max(0, (now - timestamp_ms / 1000) * 1000))
            if face_data.detected and not face_data.valid():
                face_data = FaceData(False, timestamp_ms=timestamp_ms, detected_at=now,
                                     processing_ms=face_data.processing_ms)
            with self._lock:
                if timestamp_ms <= self._face_data.timestamp_ms:
                    return
                self._face_data = face_data
            if self.metrics:
                self.metrics.frame(face_data)
            self.ready.set()
        except Exception as exc:
            self.error = exc
            self._stop_requested.set()
            self.ready.set()
            logger.exception("Error procesando callback facial")

    # ── Extracción de datos faciales ──────────────────────────────────────────

    def _extract(self, result, timestamp_ms: int) -> FaceData:
        """Convierte el resultado de MediaPipe en un FaceData limpio."""

        if not result.face_landmarks:
            return FaceData(detected=False, timestamp_ms=timestamp_ms)

        lms = result.face_landmarks[0]
        if len(lms) < 455 or not all(np.isfinite(p.x) and np.isfinite(p.y) for p in lms):
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
        brow_l_lift = (eye_l_y - brow_l_y) / scale
        brow_r_lift = (eye_r_y - brow_r_y) / scale            

        # Apertura de boca
        mouth_open = abs(
            lms[LM_IDX["mouth_upper"]].y - lms[LM_IDX["mouth_lower"]].y
        ) / scale

        return FaceData(
            detected        = True,
            nose_x          = nose.x,
            nose_y          = nose.y,
            eye_left_ratio  = eye_l,
            eye_right_ratio = eye_r,
            brow_left_lift  = brow_l_lift,
            brow_right_lift = brow_r_lift,
            mouth_open      = mouth_open,
            face_scale      = scale,
            timestamp_ms    = timestamp_ms,
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
