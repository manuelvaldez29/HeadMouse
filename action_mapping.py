"""Identidad de gesto y acciones permitidas, independiente de Qt/SO."""
from dataclasses import replace

DEFAULT_MAPPING = {
    "LEFT_WINK": "LEFT_CLICK", "RIGHT_WINK": "RIGHT_CLICK",
    "LEFT_BROW": "SCROLL_UP", "RIGHT_BROW": "SCROLL_DOWN",
    "BOTH_BROWS": "PAUSE", "MOUTH_OPEN": "OPEN_START_MENU",
}
ACTIONS = ("LEFT_CLICK", "RIGHT_CLICK", "DOUBLE_CLICK", "SCROLL_UP", "SCROLL_DOWN",
           "PAUSE", "KEY_ENTER", "KEY_ESCAPE", "KEY_SPACE", "OPEN_START_MENU", "NONE")
LEGACY_GESTURES = dict(LEFT_CLICK="LEFT_WINK", RIGHT_CLICK="RIGHT_WINK",
                       SCROLL_UP="LEFT_BROW", SCROLL_DOWN="RIGHT_BROW",
                       BOTH_BROWS="BOTH_BROWS", MOUTH_OPEN="MOUTH_OPEN")


def gesture_identity(event):
    return event.gesture or LEGACY_GESTURES.get(event.type, event.type)


class ActionMapping:
    def __init__(self, mapping=None):
        self.mapping = DEFAULT_MAPPING.copy() if mapping is None else dict(mapping)
        if set(self.mapping) != set(DEFAULT_MAPPING) or any(v not in ACTIONS for v in self.mapping.values()):
            raise ValueError("Cada gesto debe tener una acción válida")

    def resolve(self, event):
        if event.type == "CURSOR_MOVE":
            return event
        identity = gesture_identity(event)
        if identity not in self.mapping:
            raise ValueError(f"Gesto desconocido: {identity}")
        return replace(event, type=self.mapping[identity], gesture=identity)
