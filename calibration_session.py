"""Máquina de wizard sin UI: reutiliza estadística y validación de v0.2."""
import math
import time
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
from calibration_logic import Samples, build_calibration
from calibration_validation import CalibrationValidation
from gesture_engine import GestureEngine

PHASES = (("neutral", "Relajá la cara y mirá al centro"),
          ("wink_left", "Guiñá el ojo izquierdo"), ("wink_right", "Guiñá el ojo derecho"),
          ("brow_left", "Levantá la ceja izquierda"), ("brow_right", "Levantá la ceja derecha"),
          ("mouth", "Abrí la boca"))


class CalibrationSession:
    def __init__(self, profile, config, clock=time.monotonic):
        self.profile = deepcopy(profile)
        self.config = config
        self.clock = clock
        self.phase = 0
        self.samples = Samples()
        self.phases = {}
        self.candidate = None
        self.validator = None
        self.state = "ready"
        self.error = ""
        self.started = clock()

    def start(self):
        self.state = "countdown"
        self.started = self.clock()
        self.samples = Samples()
        self.error = ""

    def repeat(self):
        if self.validator is not None:
            self.validator.retry_current()
            self.state = "validation"
        elif self.phase < len(PHASES):
            self.start()
        else:
            self.restart()

    def restart(self):
        self.__init__(self.profile, self.config, self.clock)
        self.start()

    def validate(self):
        if self.candidate is None:
            raise ValueError("Primero completá las mediciones")
        gesture = GestureEngine(None, config=self.config.gesture,
                                calibration=self.candidate, clock=self.clock)
        cc = self.config.calibration
        self.validator = CalibrationValidation(gesture, cc.validation_timeout_s,
                                               self.clock, cc.validation_neutral_s)
        self.state = "validation"

    def update(self, face):
        now, cc = self.clock(), self.config.calibration
        elapsed = now - self.started
        if self.state == "countdown" and elapsed >= cc.countdown_s:
            self.state, self.started = "measuring", now
        elif self.state == "measuring":
            self.samples.add(face, self.config.gesture.stale_after_s, now)
            if elapsed >= cc.measuring_s:
                if len(self.samples.eye_left) < cc.min_samples:
                    self.error, self.state = "No hubo suficientes muestras. Volvé a intentar.", "error"
                    return
                self.phases[PHASES[self.phase][0]] = self.samples
                self.phase += 1
                if self.phase < len(PHASES):
                    self.start()
                else:
                    try:
                        self.candidate = build_calibration(self.profile["user_id"], self.phases, cc)
                        self.candidate["display_name"] = self.profile.get("display_name", self.profile["user_id"])
                        self.candidate["settings"] = asdict(self.config)
                        self.state = "measured"
                    except ValueError as exc:
                        self.error, self.state = str(exc), "error"
        elif self.state == "validation":
            self.validator.update(face)
            if self.validator.passed:
                self.state = "validated"

    def result(self):
        if self.state != "validated" or not self.validator.passed:
            raise ValueError("Completá la validación antes de guardar")
        result = deepcopy(self.candidate)
        result["status"] = "calibrated"
        result["validation"] = dict(passed=True, recognized=self.validator.recognized.copy(),
                                    validated_at=datetime.now(timezone.utc).isoformat())
        return result

    def snapshot(self):
        elapsed = self.clock() - self.started
        instruction = PHASES[self.phase][1] if self.phase < len(PHASES) else "Medición completada"
        detected = []
        if self.validator:
            instruction = self.validator.instruction
            detected = self.validator.recognized.copy()
            if self.validator.passed:
                instruction = "Validación completa. Guardá tu perfil."
            elif self.validator.error:
                instruction = "No pudimos confirmar este gesto. Volvé a intentar."
        return dict(state=self.state, phase=min(self.phase+1, 6), instruction=instruction,
                    countdown=max(0, math.ceil(self.config.calibration.countdown_s-elapsed)),
                    progress=min(1, elapsed/self.config.calibration.measuring_s) if self.state == "measuring" else 0,
                    samples=len(self.samples.eye_left), recognized=detected,
                    error=self.error or ("Usá Repetir gesto o Comenzar / recalibrar." if self.validator and self.validator.error else ""),
                    can_save=self.state == "validated")
