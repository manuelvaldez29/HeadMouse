"""Estrategias de tracking sin inferencia ni acciones del sistema."""
from typing import Protocol, runtime_checkable
from face_data import FaceData
from gaze_source import gaze_position, validate_source


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

    def __init__(self, calibration=None, config=None, eye_source="both"):
        from config import EyeTrackingConfig
        from tracking_calibration import TrackingCalibration
        self.calibration = (TrackingCalibration.from_record(calibration) if isinstance(calibration, dict)
                            else calibration)
        if self.calibration is not None and not isinstance(self.calibration, TrackingCalibration):
            raise ValueError("Calibración ocular inválida")
        self.config = config or EyeTrackingConfig()
        self.vertical_reference=self.config.vertical_reference
        self.config.__post_init__()
        self.eye_source = validate_source(eye_source)
        self.reason = ""

    def position(self, face):
        if self.calibration is None or self.calibration.eye_source != self.eye_source:
            self.reason = "falta calibración compatible con la fuente ocular"
            return None
        if self.calibration.vertical_reference!=self.vertical_reference:
            self.reason="cambió la referencia vertical: recalibrá el movimiento ocular"
            return None
        position = gaze_position(face, self.eye_source,self.vertical_reference)
        if position is None:
            self.reason = "se requieren ambos iris válidos" if self.eye_source == "both" else "iris seleccionado ausente o inválido"
            return None
        self.reason = ""
        c = self.calibration
        dx, dy = position[0]-c.neutral_x, position[1]-c.neutral_y
        x = dx/(c.right_range if dx >= 0 else c.left_range)
        y = dy/(c.down_range if dy >= 0 else c.up_range)
        return max(-1., min(1., x)), max(-1., min(1., y))


class AbsoluteGazeTrackingStrategy:
    name = "eye_absolute"
    label = "Ojos absolutos — Experimental"

    def __init__(self, calibration=None, config=None, eye_source="both"):
        from config import AbsoluteTrackingConfig
        from gaze_mapping import GazeModel
        self.config = config or AbsoluteTrackingConfig()
        self.model = GazeModel(calibration) if calibration else None
        self.eye_source = validate_source(eye_source)
        self.reason = "falta calibración absoluta validada"

    def position(self, face):
        if not self.model or not self.model.record["validated"] or self.model.eye_source != self.eye_source:
            self.reason = "falta calibración absoluta validada"
            return None
        position = self.model.predict(face)
        self.reason = "" if position else "iris, postura o predicción fuera del dominio calibrado"
        return position


def create_strategy(name="nose", calibration=None, config=None, eye_source="both") -> TrackingStrategy:
    if name == "nose":
        return NoseTrackingStrategy()
    if name == "eye":
        return EyeGazeTrackingStrategy(calibration, config, eye_source)
    if name == "eye_absolute":
        return AbsoluteGazeTrackingStrategy(calibration, config, eye_source)
    raise ValueError("Método de tracking no disponible")
