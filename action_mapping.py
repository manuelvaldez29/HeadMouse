"""Identidad de gesto y acciones permitidas, independiente de Qt/SO."""
from dataclasses import replace

DEFAULT_MAPPING = {
    "LEFT_WINK": "LEFT_CLICK", "RIGHT_WINK": "RIGHT_CLICK",
    "MOUTH_LEFT": "SCROLL_UP", "MOUTH_RIGHT": "SCROLL_DOWN",
    "LEFT_BROW": "SCROLL_UP", "RIGHT_BROW": "SCROLL_DOWN",
    "BOTH_BROWS": "PAUSE", "MOUTH_OPEN": "OPEN_START_MENU",
    "KISS": "DOUBLE_CLICK",  # opcional: apagado hasta calibrarlo
}
ACTIONS = ("LEFT_CLICK", "RIGHT_CLICK", "DOUBLE_CLICK", "SCROLL_UP", "SCROLL_DOWN",
           "PAUSE", "KEY_ENTER", "KEY_ESCAPE", "KEY_SPACE", "OPEN_START_MENU", "DICTATE", "ASSISTANT", "KEY_BACKSPACE", "DELETE_WORD", "NONE")
LEGACY_GESTURES = dict(LEFT_CLICK="LEFT_WINK", RIGHT_CLICK="RIGHT_WINK",
                       SCROLL_UP="MOUTH_LEFT", SCROLL_DOWN="MOUTH_RIGHT",
                       BOTH_BROWS="BOTH_BROWS", MOUTH_OPEN="MOUTH_OPEN")


def gesture_identity(event):
    return event.gesture or LEGACY_GESTURES.get(event.type, event.type)


class ActionMapping:
    def __init__(self, mapping=None):
        self.mapping = DEFAULT_MAPPING.copy() if mapping is None else dict(mapping)
        if set(self.mapping) != set(DEFAULT_MAPPING) or any(v not in ACTIONS for v in self.mapping.values()):
            raise ValueError("Cada gesto debe tener una acción válida")

    def resolve(self, event):
        if event.type in ("CURSOR_MOVE", "CURSOR_ABSOLUTE"):
            return event
        identity = gesture_identity(event)
        if identity not in self.mapping:
            raise ValueError(f"Gesto desconocido: {identity}")
        return replace(event, type=self.mapping[identity], gesture=identity)


# Cómo nombrar cada gesto en los mensajes: (indicación, nombre corto). Los mensajes
# salen de la asignación de cada perfil (2026-11-04: con el besito para pausar, la
# mini cámara y el inicio seguían diciendo "ambas cejas").
GESTURE_PHRASES = {
    "LEFT_WINK": ("guiñá el ojo izquierdo", "guiño izq."),
    "RIGHT_WINK": ("guiñá el ojo derecho", "guiño der."),
    "MOUTH_LEFT": ("llevá los labios a la izquierda", "labios izq."),
    "MOUTH_RIGHT": ("llevá los labios a la derecha", "labios der."),
    "LEFT_BROW": ("levantá la ceja izquierda", "ceja izq."),
    "RIGHT_BROW": ("levantá la ceja derecha", "ceja der."),
    "MOUTH_OPEN": ("abrí la boca", "boca abierta"),
    "BOTH_BROWS": ("levantá ambas cejas", "ambas cejas"),
    "KISS": ("tirá un besito", "besito"),
}


def gesture_phrase(bindings, action, enabled=None, short=False):
    """«tirá un besito», «levantá ambas cejas o tirá un besito»… o None si ningún gesto
    habilitado hace esa acción. `enabled` None: no se sabe, se toman todos."""
    keys = [k for k in GESTURE_PHRASES if (bindings or {}).get(k) == action and (enabled is None or k in enabled)]
    return " o ".join(GESTURE_PHRASES[k][1 if short else 0] for k in keys) if keys else None


def capitalized(text):
    return text[:1].upper() + text[1:] if text else text
