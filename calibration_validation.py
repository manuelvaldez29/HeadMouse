"""Validación guiada sin SO, usando los eventos del GestureEngine real."""
import time
from config import CalibrationConfig

GESTURES = (
    ("LEFT_CLICK", "Guina el ojo IZQUIERDO"),
    ("RIGHT_CLICK", "Guina el ojo DERECHO"),
    ("SCROLL_UP", "Levanta la ceja IZQUIERDA"),
    ("SCROLL_DOWN", "Levanta la ceja DERECHA"),
    ("MOUTH_OPEN", "Abri la boca"),
    ("BOTH_BROWS", "Levanta AMBAS cejas"),
)


class CalibrationValidation:
    def __init__(self, gesture, timeout_s=None, clock=time.monotonic, neutral_s=None):
        self.gesture = gesture
        self.clock = clock
        defaults = CalibrationConfig()
        self.timeout_s = defaults.validation_timeout_s if timeout_s is None else timeout_s
        self.neutral_s = defaults.validation_neutral_s if neutral_s is None else neutral_s
        self.index = 0
        self.neutral = True
        self.neutral_since = None
        self.started = clock()
        self.passed = False
        self.error = None
        self.recognized = []
        self._last_timestamp = 0

    @property
    def instruction(self):
        if self.error:
            return self.error
        if self.passed:
            return "Validacion correcta. SPACE: guardar; Q: descartar"
        if self.neutral:
            return f"Cara neutral durante {self.neutral_s:g} segundos"
        return GESTURES[self.index][1]

    def retry_current(self):
        """Repite el gesto actual (o el recién reconocido), conservando anteriores."""
        if self.neutral and self.index > 0:
            self.index -= 1
        self.index = min(self.index, len(GESTURES) - 1)
        self.recognized = self.recognized[:self.index]
        self.neutral = True
        self.neutral_since = None
        self.started = self.clock()
        self.passed = False
        self.error = None
        self.gesture.reset()

    def update(self, face):
        if self.passed or self.error:
            return
        now = self.clock()
        if now - self.started > self.timeout_s:
            self.error = "Tiempo agotado. R: repetir validacion"
            return
        events = self.gesture.update(face)
        if not face.fresh(self.gesture.config.stale_after_s, now):
            self.neutral_since = None
            return
        if face.timestamp_ms <= self._last_timestamp:
            return
        if self._last_timestamp and face.timestamp_ms - self._last_timestamp > self.gesture.config.stale_after_s * 1000:
            self.neutral_since = None
        self._last_timestamp = face.timestamp_ms
        types = [ev.type for ev in events if ev.type != "CURSOR_MOVE"]
        if self.neutral:
            # No basta silencio de eventos durante cooldown: exigir ratios liberados.
            t = self.gesture._thresholds
            released = (face.eye_left_ratio >= t["blink_left"]
                        and face.eye_right_ratio >= t["blink_right"]
                        and face.brow_left_lift <= t["brow_left"]
                        and face.brow_right_lift <= t["brow_right"]
                        and face.mouth_open <= t["mouth_open"])
            if types:
                self.error = "Gesto inesperado en neutral. R: repetir"
            elif not released:
                self.neutral_since = None
            elif self.neutral_since is None:
                self.neutral_since = now
            elif now - self.neutral_since >= self.neutral_s:
                self.gesture.reset()
                self.neutral = False
                self.started = now
                if self.index == len(GESTURES):
                    self.passed = True
        elif types:
            expected = GESTURES[self.index][0]
            if types != [expected]:
                self.error = "Gesto distinto al solicitado. R: repetir"
                return
            self.recognized.append(expected)
            self.index += 1
            self.neutral = True
            self.neutral_since = None
            self.started = now
