"""Contrato inmutable compartido; no importa cámara ni bibliotecas nativas."""
import math
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class FaceData:
    detected: bool
    nose_x: float = 0.5
    nose_y: float = 0.5
    eye_left_ratio: float = 0.3
    eye_right_ratio: float = 0.3
    brow_left_lift: float = 0.0
    brow_right_lift: float = 0.0
    mouth_open: float = 0.0
    face_scale: float = 1.0
    timestamp_ms: int = 0
    detected_at: float = 0.0  # monotonic: final de extracción
    processing_ms: float = 0.0  # envío a MediaPipe → extracción, no captura
    landmarks: tuple = ()  # puntos relevantes volátiles para preview; nunca persistidos
    blendshapes: tuple = ()  # pares (nombre, score), solo memoria; opcionales
    # Señal de cejas en el sistema de la cara y pose aproximada; None si no se calculó.
    brow_left_3d: float | None = None
    brow_right_3d: float | None = None
    head_pitch: float | None = None
    head_yaw: float | None = None
    head_roll: float | None = None
    left_gaze_x: float | None = None
    left_gaze_y: float | None = None
    right_gaze_x: float | None = None
    right_gaze_y: float | None = None
    gaze_x: float | None = None
    gaze_y: float | None = None
    gaze_confidence: float = 0.0  # cobertura: .5 un ojo, 1 ambos; no probabilidad
    iris_points: tuple = ()  # centros normalizados del preview, solo RAM
    gaze_mirrored: bool = True  # imagen presentada al detector; pipeline histórico
    left_canthi_y: float | None = None
    right_canthi_y: float | None = None
    ocular_geometry: tuple = ()  # mediciones transitorias por canal; nunca imágenes

    @property
    def gaze_available(self):
        # La señal opcional se valida aparte: ausencia de iris no invalida nariz/gestos.
        unit = lambda v: (isinstance(v, (int, float)) and not isinstance(v, bool)
                          and math.isfinite(v) and 0 <= v <= 1)
        pairs = ((self.left_gaze_x, self.left_gaze_y), (self.right_gaze_x, self.right_gaze_y))
        count = sum(all(unit(v) for v in pair) for pair in pairs)
        return (self.detected and self.valid() and count > 0
                and all(all(v is None for v in p) or all(unit(v) for v in p) for p in pairs)
                and unit(self.gaze_x) and unit(self.gaze_y) and unit(self.gaze_confidence)
                and self.gaze_confidence == count/2)

    def valid(self):
        values = (self.nose_x, self.nose_y, self.eye_left_ratio,
                  self.eye_right_ratio, self.brow_left_lift, self.brow_right_lift,
                  self.mouth_open, self.face_scale, self.timestamp_ms,
                  self.detected_at, self.processing_ms)
        optional = ((self.brow_left_3d, 10), (self.brow_right_3d, 10),
                    (self.head_pitch, 180), (self.head_yaw, 180), (self.head_roll, 180))
        return (all(isinstance(v, (int, float)) and not isinstance(v, bool)
                    and math.isfinite(v) for v in values)
                and all(v is None or (isinstance(v, (int, float)) and not isinstance(v, bool)
                                      and math.isfinite(v) and abs(v) <= limit) for v, limit in optional)
                and isinstance(self.detected, bool)
                and type(self.gaze_mirrored) is bool
                and 0 <= self.nose_x <= 1 and 0 <= self.nose_y <= 1
                and 0 <= self.eye_left_ratio <= 10 and 0 <= self.eye_right_ratio <= 10
                and abs(self.brow_left_lift) <= 10 and abs(self.brow_right_lift) <= 10
                and 0 <= self.mouth_open <= 10 and 1e-6 < self.face_scale <= 1
                and isinstance(self.timestamp_ms, int) and self.timestamp_ms > 0
                and self.detected_at >= 0 and self.processing_ms >= 0)

    def fresh(self, max_age_s, now=None):
        now = time.monotonic() if now is None else now
        age = now - self.timestamp_ms / 1000
        return self.detected and self.valid() and 0 <= age <= max_age_s
