"""Fuente ocular anatómica explícita; sin Qt, cámara, NumPy ni backend del SO.

Los canales históricos left/right son los grupos 468/473. MediaPipe nombra
RIGHT_IRIS al 468 y LEFT_IRIS al 473 en entrada no espejada. VisionEngine
espeja ANTES de inferencia: en esa entrada el 468 representa el izquierdo físico.
No se renombran los canales de gestos ni se cambia el espejo histórico.
"""
import math

EYE_SOURCES = ("both", "left", "right")
SOURCE_LABELS = {"both": "Ambos ojos", "left": "Ojo izquierdo", "right": "Ojo derecho"}


def validate_source(source):
    if not isinstance(source, str) or source not in EYE_SOURCES:
        raise ValueError("Fuente ocular inválida: usar both, left o right")
    return source


def channels(source, mirrored=True):
    validate_source(source)
    if source == "both":
        return ("left", "right")
    return (source if mirrored else {"left": "right", "right": "left"}[source],)


def validate_vertical_reference(value):
    if value not in ("eyelids","canthi"):
        raise ValueError("Referencia vertical inválida")
    return value


def eye_coordinates(face, source="both", vertical_reference="eyelids"):
    """Solo se validan iris seleccionados; nunca hay fallback implícito."""
    validate_vertical_reference(vertical_reference)
    if not face.detected or not face.valid():
        return None
    values = []
    for side in channels(source, face.gaze_mirrored):
        pair = (getattr(face, f"{side}_gaze_x"), getattr(face, f"{side}_gaze_y" if vertical_reference=="eyelids" else f"{side}_canthi_y"))
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                   and math.isfinite(v) and 0 <= v <= 1 for v in pair):
            return None
        values.extend(pair)
    return tuple(values)


def gaze_position(face, source="both", vertical_reference="eyelids"):
    values = eye_coordinates(face, source, vertical_reference)
    if values is None:
        return None
    return ((values[0]+values[2])/2, (values[1]+values[3])/2) if source == "both" else values


def selected_eyes_open(face, source, limits):
    return all(getattr(face, f"eye_{side}_ratio") > limits[0 if side == "left" else 1]
               for side in channels(source, face.gaze_mirrored))


def feature_gaze(rows, source):
    # Acepta arrays NumPy sin importarlos en este módulo.
    return (rows[..., :2]+rows[..., 2:4])/2 if source == "both" else rows[..., :2]


def iris_markers(face, source):
    valid = [side for side in ("left", "right") if
             eye_coordinates(face, side if face.gaze_mirrored else {"left":"right", "right":"left"}[side]) is not None]
    if len(valid) != len(face.iris_points):
        return ()  # no atribuir lateralidad a un snapshot inconsistente
    return tuple((side if face.gaze_mirrored else {"left":"right", "right":"left"}[side], x, y)
                 for side, (x, y) in zip(valid, face.iris_points))
