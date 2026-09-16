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
import threading
import time
import urllib.request
from dataclasses import dataclass, field
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
MODEL_PATH = os.path.join("models", "face_landmarker.task")

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

@dataclass
class FaceData:
    """
    Snapshot de datos faciales para un frame.
    Es lo que el Vision Engine entrega al Gesture Engine en cada ciclo.

    Todas las coordenadas están normalizadas [0.0, 1.0] relativas al frame.
    Los ratios están normalizados por la escala facial (distancia entre orejas)
    para ser invariantes a la distancia del usuario a la cámara.
    """

    detected: bool                  # False si no hay cara en el cuadro

    # ── Cursor ────────────────────────────────────────────────────────────────
    nose_x: float = 0.5             # posición X de la nariz [0=izq, 1=der]
    nose_y: float = 0.5             # posición Y de la nariz [0=arr, 1=aba]

    # ── Ojos (ratio apertura, normalizado por escala facial) ──────────────────
    # ~0.10-0.15 = guiño / cerrado
    # ~0.25-0.35 = abierto normal
    eye_left_ratio:  float = 0.3
    eye_right_ratio: float = 0.3

    # ── Cejas (elevación relativa al puente nasal, normalizada) ───────────────
    # >0 = ceja levantada; ~0 = posición neutral; <0 = ceja fruncida
    brow_left_lift:  float = 0.0
    brow_right_lift: float = 0.0

    # ── Boca ──────────────────────────────────────────────────────────────────
    # ~0.0 = cerrada; >0.15 = claramente abierta
    mouth_open: float = 0.0

    # ── Metadata ──────────────────────────────────────────────────────────────
    face_scale:    float = 1.0      # distancia oreja-oreja (para debug)
    timestamp_ms:  int   = 0        # timestamp del frame en ms


# ══════════════════════════════════════════════════════════════════════════════
# VISION ENGINE
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

    def __init__(self, camera_index: int = 0, target_fps: int = 30):
        super().__init__(daemon=True, name="VisionEngine")
        self.camera_index = camera_index
        self.target_fps   = target_fps

        # ── Estado compartido ─────────────────────────────────────────────────
        self._lock      = threading.Lock()
        self._face_data = FaceData(detected=False)
        self._fps       = 0.0
        self._frame: Optional[np.ndarray] = None

        # ── Control del hilo ──────────────────────────────────────────────────
        self._running = False
        self._stopped = threading.Event()

        # ── Asegurar modelo descargado ────────────────────────────────────────
        self._ensure_model()

    # ── API pública ───────────────────────────────────────────────────────────

    def get_face_data(self) -> FaceData:
        """Devuelve el último FaceData procesado. Thread-safe."""
        with self._lock:
            return self._face_data

    def get_fps(self) -> float:
        """Devuelve los FPS reales del pipeline. Thread-safe."""
        with self._lock:
            return self._fps

    def get_frame(self) -> Optional[np.ndarray]:
        """Devuelve el último frame BGR capturado (para preview/debug)."""
        with self._lock:
            return self._frame.copy() if self._frame is not None else None

    def stop(self):
        """Detiene el hilo limpiamente. Bloquea hasta que termina (max 3s)."""
        self._running = False
        self._stopped.wait(timeout=3.0)
        print("[VisionEngine] Detenido.")

    # ── Loop principal ────────────────────────────────────────────────────────

    def run(self):
        self._running = True

        # Configurar Face Landmarker en modo LIVE_STREAM
        options = mp_vision.FaceLandmarkerOptions(
            base_options=mp_python.BaseOptions(
                model_asset_path=MODEL_PATH
            ),
            running_mode=mp_vision.RunningMode.LIVE_STREAM,
            num_faces=1,
            min_face_detection_confidence=0.5,
            min_face_presence_confidence=0.5,
            min_tracking_confidence=0.5,
            output_face_blendshapes=False,
            output_facial_transformation_matrixes=False,
            result_callback=self._on_result,    # callback asíncrono
        )

        cap = cv2.VideoCapture(self.camera_index)
        if not cap.isOpened():
            print(f"[VisionEngine] Error: no se pudo abrir la cámara {self.camera_index}")
            self._running = False
            self._stopped.set()
            return

        cap.set(cv2.CAP_PROP_FPS, self.target_fps)
        print(f"[VisionEngine] Cámara abierta. FPS objetivo: {self.target_fps}")

        # Buffer para calcular FPS suavizado
        fps_times = []
        frame_idx = 0

        with mp_vision.FaceLandmarker.create_from_options(options) as detector:
            while self._running:
                ok, frame = cap.read()
                if not ok:
                    time.sleep(0.01)
                    continue

                t_now = time.perf_counter()

                # Espejo horizontal: sin esto la cámara captura vista "ventana"
                # y los lados izq/der de MediaPipe no coinciden con los del usuario.
                # Con el flip el frame llega espejado a MediaPipe, sus etiquetas
                # left/right coinciden con la perspectiva física del usuario, y el
                # cursor se mueve correctamente (cabeza izq → cursor izq).
                frame = cv2.flip(frame, 1)

                # Timestamp en ms (debe ser monotónicamente creciente)
                ts_ms = int(t_now * 1000)

                # Enviar frame al detector (resultado llega por callback)
                rgb    = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                detector.detect_async(mp_img, ts_ms)

                # Actualizar frame y FPS
                fps_times.append(t_now)
                fps_times = [t for t in fps_times if t_now - t < 1.0]
                fps = len(fps_times)

                with self._lock:
                    self._frame = frame
                    self._fps   = fps

                frame_idx += 1

        cap.release()
        self._stopped.set()

    # ── Callback de resultados ────────────────────────────────────────────────

    def _on_result(self, result, output_image, timestamp_ms: int):
        """
        Callback interno llamado por MediaPipe cuando el resultado está listo.
        Corre en el hilo del detector, NO en el hilo principal.
        """
        face_data = self._extract(result, timestamp_ms)
        with self._lock:
            self._face_data = face_data

    # ── Extracción de datos faciales ──────────────────────────────────────────

    def _extract(self, result, timestamp_ms: int) -> FaceData:
        """Convierte el resultado de MediaPipe en un FaceData limpio."""

        if not result.face_landmarks:
            return FaceData(detected=False, timestamp_ms=timestamp_ms)

        lms = result.face_landmarks[0]

        # Escala facial: distancia entre orejas (invariante a distancia cámara)
        scale = abs(lms[LM_IDX["ear_left"]].x - lms[LM_IDX["ear_right"]].x)
        if scale < 1e-6:
            scale = 1.0

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
        )

    @staticmethod
    def _eye_ratio(upper, lower, scale: float) -> float:
        """Ratio de apertura de ojo normalizado por escala facial."""
        return abs(upper.y - lower.y) / scale

    # ── Descarga del modelo ───────────────────────────────────────────────────

    @staticmethod
    def _ensure_model():
        if os.path.exists(MODEL_PATH):
            return
        os.makedirs("models", exist_ok=True)
        print("[VisionEngine] Descargando modelo Face Landmarker (~30 MB)...")

        def progress(count, block_size, total):
            pct = min(count * block_size * 100 / total, 100)
            bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
            print(f"\r  [{bar}] {pct:.0f}%", end="", flush=True)

        urllib.request.urlretrieve(MODEL_URL, MODEL_PATH, reporthook=progress)
        print(f"\n[VisionEngine] Modelo guardado en {MODEL_PATH}")
