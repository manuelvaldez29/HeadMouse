"""Estrategias de tracking sin inferencia ni acciones del sistema."""
from typing import Protocol, runtime_checkable
from face_data import FaceData


@runtime_checkable
class TrackingStrategy(Protocol):
    def position(self, face: FaceData) -> tuple[float, float] | None: ...


class NoseTrackingStrategy:
    name = "nose"
    label = "Nariz"
    def position(self, face):
        return face.nose_x, face.nose_y


class EyeGazeTrackingStrategy:
    name = "eye"
    label = "Ojos — Experimental"

    def __init__(self, calibration=None, config=None):
        from config import EyeTrackingConfig
        from tracking_calibration import TrackingCalibration
        self.calibration = (TrackingCalibration.from_record(calibration) if isinstance(calibration, dict)
                            else calibration)
        if self.calibration is not None and not isinstance(self.calibration, TrackingCalibration):
            raise ValueError("Calibración ocular inválida")
        self.config = config or EyeTrackingConfig()
        self.config.__post_init__()

    def position(self, face):
        if self.calibration is None or not face.gaze_available:
            return None
        c = self.calibration
        dx, dy = face.gaze_x-c.neutral_x, face.gaze_y-c.neutral_y
        x = dx/(c.right_range if dx >= 0 else c.left_range)
        y = dy/(c.down_range if dy >= 0 else c.up_range)
        return max(-1., min(1., x)), max(-1., min(1., y))


def create_strategy(name="nose", calibration=None, config=None) -> TrackingStrategy:
    if name == "nose":
        return NoseTrackingStrategy()
    if name == "eye":
        return EyeGazeTrackingStrategy(calibration, config)
    raise ValueError("Método de tracking no disponible")
