"""Validación guiada sin SO, usando los eventos del GestureEngine real."""
import time
from config import CalibrationConfig
from gesture_signals import GESTURE_SIGNALS

GESTURES = (
    ("LEFT_CLICK", "Guina el ojo IZQUIERDO"),
    ("RIGHT_CLICK", "Guina el ojo DERECHO"),
    ("SCROLL_UP", "Levanta la ceja IZQUIERDA"),
    ("SCROLL_DOWN", "Levanta la ceja DERECHA"),
    ("MOUTH_OPEN", "Abri la boca"),
    ("BOTH_BROWS", "Levanta AMBAS cejas"),
)


class CalibrationValidation:
    def __init__(self, gesture, timeout_s=None, clock=time.monotonic, neutral_s=None,
                 noise_s=None, wrong_s=None):
        self.gesture = gesture
        self.clock = clock
        defaults = CalibrationConfig()
        self.timeout_s = defaults.validation_timeout_s if timeout_s is None else timeout_s
        self.neutral_s = defaults.validation_neutral_s if neutral_s is None else neutral_s
        self.noise_s = defaults.validation_noise_s if noise_s is None else noise_s
        self.wrong_s = defaults.validation_wrong_s if wrong_s is None else wrong_s
        if not 0 < self.noise_s < self.wrong_s < self.timeout_s:
            raise ValueError("Tiempos de tolerancia de validación incompatibles")
        enabled = getattr(gesture, "enabled_gestures", None)
        self.gestures = tuple((spec.event_type, spec.instruction) for key,spec in GESTURE_SIGNALS.items()
                              if enabled is None or not isinstance(enabled, (set,list,tuple)) or key in enabled)
        self.index = 0
        self.neutral = True
        self.neutral_since = None
        self.started = clock()
        self.passed = False
        self.error = None
        self.recognized = []
        self._last_timestamp = 0
        self._clear_tolerance()

    def _clear_tolerance(self):
        self._neutral_elapsed = 0.
        self._neutral_sample_at = None
        self._noise_since = None
        self._wrong_since = None
        self._wrong_types = set()

    @property
    def instruction(self):
        if self.error:
            return self.error
        if self.passed:
            return "Validacion correcta. SPACE: guardar; Q: descartar"
        if self.neutral:
            return f"Cara neutral durante {self.neutral_s:g} segundos"
        return self.gestures[self.index][1]

    def retry_current(self):
        """Repite el gesto actual (o el recién reconocido), conservando anteriores."""
        if self.neutral and self.index > 0:
            self.index -= 1
        self.index = max(0, min(self.index, len(self.gestures) - 1))
        self.recognized = self.recognized[:self.index]
        self.neutral = True
        self.neutral_since = None
        self.started = self.clock()
        self.passed = False
        self.error = None
        self._clear_tolerance()
        self._last_timestamp = 0
        self.gesture.reset()

    def update(self, face):
        if self.passed or self.error:
            return
        now = self.clock()
        if now - self.started > self.timeout_s:
            self.error = "Tiempo agotado. Repetí la validación."
            return
        events = self.gesture.update(face)
        if not face.fresh(self.gesture.config.stale_after_s, now):
            self._neutral_sample_at = None
            if self._noise_since is None:
                self._noise_since = now
            if now - self._noise_since > self.noise_s:
                self.neutral_since = None
                self._neutral_elapsed = 0.
            self._wrong_since = None
            return
        if face.timestamp_ms <= self._last_timestamp:
            return
        if self._last_timestamp and face.timestamp_ms - self._last_timestamp > self.gesture.config.stale_after_s * 1000:
            self.neutral_since = None
            self._clear_tolerance()
        self._last_timestamp = face.timestamp_ms
        types = [ev.type for ev in events if ev.type != "CURSOR_MOVE"]
        if self.neutral:
            # No basta silencio de eventos durante cooldown: exigir ratios liberados.
            released = self.gesture.signals_released(face)
            if not released or types:
                self._neutral_sample_at = None
                if self._noise_since is None:
                    self._noise_since = now
                duration = now - self._noise_since
                if duration > self.noise_s:
                    self.neutral_since = None
                    self._neutral_elapsed = 0.
                if duration >= self.wrong_s:
                    self.error = "Gesto sostenido durante neutral. Volvé a neutral y repetí."
                return
            if self._noise_since is not None:
                if now - self._noise_since > self.noise_s:
                    self._neutral_elapsed = 0.
                self._noise_since = None
            elif self._neutral_sample_at is not None:
                self._neutral_elapsed += now - self._neutral_sample_at
            self._neutral_sample_at = now
            if self.neutral_since is None:
                self.neutral_since = now
            if self._neutral_elapsed >= self.neutral_s:
                self.gesture.reset()
                self.neutral = False
                self.started = now
                self._clear_tolerance()
                if self.index == len(self.gestures):
                    self.passed = True
        else:
            expected = self.gestures[self.index][0]
            activity = getattr(self.gesture, "last_active", {})
            sustained = {GESTURE_SIGNALS[key].event_type for key,value in activity.items()
                         if value and key in GESTURE_SIGNALS} if isinstance(activity,dict) else set()
            wrong = (sustained | set(types)) - {expected}
            if wrong:
                if self._wrong_since is None or not wrong.intersection(self._wrong_types):
                    self._wrong_since = now
                self._wrong_types = wrong
                if now - self._wrong_since >= self.wrong_s:
                    self.error = "Gesto incorrecto sostenido. Repetí el gesto solicitado."
                # Nunca aprobar un evento esperado mezclado con un gesto incorrecto.
                return
            self._wrong_since = None
            self._wrong_types = set()
            if expected in types:
                self.recognized.append(expected)
                self.index += 1
                self.neutral = True
                self.neutral_since = None
                self.started = now
                self._clear_tolerance()
