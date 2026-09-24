"""Punto de extensión experimental; v0.2 conserva exclusivamente landmark nasal."""
from typing import Protocol, runtime_checkable
from face_data import FaceData


@runtime_checkable
class TrackingStrategy(Protocol):
    def position(self, face: FaceData) -> tuple[float, float]: ...


class NoseTrackingStrategy:
    name = "nose"
    label = "Nariz"
    def position(self, face):
        return face.nose_x, face.nose_y


def create_strategy(name="nose") -> TrackingStrategy:
    if name != "nose":
        raise ValueError("Método de tracking no disponible")
    return NoseTrackingStrategy()
