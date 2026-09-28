"""Adaptadores de señal: identidad y extracción, sin estadística ni hardware.

Cada adaptador devuelve uno o más canales. El motor compartido exige que todos
los canales estén activos (AND); BOTH_BROWS usa dos canales calibrados juntos.
"""
import math
from dataclasses import dataclass

SOURCES = ("GEOMETRIC", "BLENDSHAPE", "HYBRID")
BROW_BLENDSHAPES = ("browInnerUp", "browOuterUpLeft", "browOuterUpRight",
                    "browDownLeft", "browDownRight")


def extract_blendshapes(categories):
    """Nombres category_name oficiales; conservar solo scores válidos conocidos."""
    values = {}
    for category in categories:
        name, score = getattr(category, "category_name", None), getattr(category, "score", None)
        if name in BROW_BLENDSHAPES and isinstance(score, (int,float)) and not isinstance(score,bool) and math.isfinite(score) and 0 <= score <= 1:
            values[name] = float(score)
    return tuple(sorted(values.items()))


def brow_signal(face, side, source):
    geometric = getattr(face, f"brow_{side}_lift")
    if source == "GEOMETRIC":
        return geometric
    values = dict(face.blendshapes)
    suffix = "Left" if side == "left" else "Right"
    names = ("browInnerUp", "browOuterUp" + suffix, "browDown" + suffix)
    if any(name not in values for name in names):
        return None  # Nunca sustituir por geometría usando thresholds de otra escala.
    inner, outer, down = (values[name] for name in names)
    if any(not isinstance(v, (int, float)) or isinstance(v, bool) or
           not math.isfinite(v) or not 0 <= v <= 1 for v in (inner, outer, down)):
        return None
    blend = (outer + inner - down) / 2
    # Mezcla experimental definida, no aprendida ni supuestamente más precisa.
    # 0.25 es escala fija de geometría, NO threshold; requiere recalibrar.
    return blend if source == "BLENDSHAPE" else (geometric / .25 + blend) / 2


@dataclass(frozen=True)
class GestureSignal:
    gesture_id: str
    phase_id: str
    label: str
    instruction: str
    event_type: str
    channels: tuple
    directions: tuple
    legacy_keys: tuple
    brow: bool = False

    def extract(self, face, source="GEOMETRIC"):
        if source not in SOURCES:
            raise ValueError("Fuente de señal desconocida")
        values = tuple(brow_signal(face, channel, source) if self.brow else
                       getattr(face, channel) for channel in self.channels)
        if any(v is None or isinstance(v, bool) or not isinstance(v, (int, float))
               or not math.isfinite(v) for v in values):
            return None
        return tuple(float(v) for v in values)


# Extender este registro incorpora identidad/adaptador; no duplica el calibrador.
GESTURE_SIGNALS = {
    s.gesture_id: s for s in (
        GestureSignal("LEFT_WINK", "wink_left", "Guiño izquierdo", "Guiñá el ojo izquierdo",
                      "LEFT_CLICK", ("eye_left_ratio",), (-1,), ("blink_left",)),
        GestureSignal("RIGHT_WINK", "wink_right", "Guiño derecho", "Guiñá el ojo derecho",
                      "RIGHT_CLICK", ("eye_right_ratio",), (-1,), ("blink_right",)),
        GestureSignal("LEFT_BROW", "brow_left", "Ceja izquierda", "Levantá la ceja izquierda cómodamente",
                      "SCROLL_UP", ("left",), (1,), ("brow_left",), True),
        GestureSignal("RIGHT_BROW", "brow_right", "Ceja derecha", "Levantá la ceja derecha cómodamente",
                      "SCROLL_DOWN", ("right",), (1,), ("brow_right",), True),
        GestureSignal("MOUTH_OPEN", "mouth", "Boca", "Abrí la boca cómodamente",
                      "MOUTH_OPEN", ("mouth_open",), (1,), ("mouth_open",)),
        GestureSignal("BOTH_BROWS", "both_brows", "Ambas cejas", "Levantá ambas cejas cómodamente",
                      "BOTH_BROWS", ("left", "right"), (1, 1), ("brow_left", "brow_right"), True),
    )
}


def get_signal(gesture_id):
    try:
        return GESTURE_SIGNALS[gesture_id]
    except KeyError as exc:
        raise ValueError(f"Gesto no registrado: {gesture_id}") from exc


def disabled_eye_suppression(gesture_id, records, activation, release):
    """Solo veto de parpadeo bilateral, nunca habilita el guiño omitido.

    Sin captura activa de ese ojo, transportar la fracción de cierre del ojo
    calibrado a su neutral observado. Evita comparar neutral personal contra
    un threshold genérico que podría interpretarlo como permanentemente cerrado.
    Es un fallback de supresión, no una calibración del gesto deshabilitado.
    """
    other="RIGHT_WINK" if gesture_id=="LEFT_WINK" else "LEFT_WINK"
    peer=records.get(other,{})
    if not peer.get("enabled"): return activation,release
    channel=GESTURE_SIGNALS[gesture_id].channels[0]
    peer_channel=GESTURE_SIGNALS[other].channels[0]
    own=records[gesture_id].get("neutral_statistics",{}).get(channel,{}).get("median")
    reference=peer.get("neutral_statistics",{}).get(peer_channel,{}).get("median")
    if any(type(v) not in (int,float) or not math.isfinite(v) or v<=0 for v in (own,reference)):
        return activation,release
    a=peer["activation_threshold"][peer_channel]/reference
    r=peer["release_threshold"][peer_channel]/reference
    if not 0<a<=r<1: return activation,release
    return {channel:own*a},{channel:own*r}
