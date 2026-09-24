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

    def valid(self):
        values = (self.nose_x, self.nose_y, self.eye_left_ratio,
                  self.eye_right_ratio, self.brow_left_lift, self.brow_right_lift,
                  self.mouth_open, self.face_scale, self.timestamp_ms,
                  self.detected_at, self.processing_ms)
        return (all(isinstance(v, (int, float)) and not isinstance(v, bool)
                    and math.isfinite(v) for v in values)
                and isinstance(self.detected, bool)
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
