"""Reposo que se desplaza durante la sesión y validación que no se traba.

Reproduce la prueba física del 2026-10-11: la ceja izquierda se calibró con un
reposo de ~0.195 y activación 0.2088, pero en la validación la cara relajada
medía 0.2107. La ceja quedaba "activa" en reposo y la validación fallaba en
0.35 s con "Gesto sostenido durante neutral", sin decir qué gesto era.
"""
import unittest
from calibration_session import CalibrationSession
from calibration_validation import CalibrationValidation
from config import load_config
from face_data import FaceData
from gesture_engine import GestureEngine
from gesture_signals import GESTURE_SIGNALS
from test_adaptive_session import NEUTRAL
from test_core import calibration

REST, RAISED = .195, .23


class SessionNeutralTests(unittest.TestCase):
    def setUp(self):
        self.ms = 1000
        self.config = load_config()
        cc = self.config.calibration
        cc.countdown_s = cc.measuring_s = cc.transition_s = cc.neutral_window_s = .5

    def clock(self): return self.ms / 1000

    def face(self, **values):
        self.ms += 50
        return FaceData(True, timestamp_ms=self.ms, **(NEUTRAL | dict(brow_left_lift=REST) | values))

    def calibrate(self, drifted_rest):
        """Ceja izquierda primero; durante los neutrales de la boca la ceja reposa más alta."""
        s = CalibrationSession({"user_id": "drift"}, self.config, self.clock,
                               {key: key in ("LEFT_BROW", "MOUTH_OPEN") for key in GESTURE_SIGNALS})
        s.start()
        for frame in range(3000):
            if s.state in ("measured", "error") or s.gesture_id == "LEFT_BROW" and s.models["LEFT_BROW"].retries:
                return s
            values = {}
            if s.gesture_id == "MOUTH_OPEN":
                values["brow_left_lift"] = drifted_rest
            if s.stage == "active":
                # Gesto breve con reacción y liberación, como en la prueba física.
                phase = len(s._rows) % 30
                if 3 <= phase < 15:
                    values |= {"brow_left_lift": RAISED} if s.gesture_id == "LEFT_BROW" else {"mouth_open": .3}
            s.update(self.face(**values))
        self.fail("La calibración no terminó")

    def test_moderate_drift_raises_activation_above_observed_rest(self):
        s = self.calibrate(drifted_rest=.215)
        self.assertEqual(s.state, "measured", s.snapshot())
        record = s.candidate["gesture_calibrations"]["LEFT_BROW"]
        self.assertGreater(record["release_threshold"]["left"], .215)
        self.assertLess(record["activation_threshold"]["left"], RAISED)
        self.assertGreaterEqual(record["session_neutral"]["left"], .215)
        # Con la cara relajada en el reposo desplazado, la validación avanza.
        s.validate()
        for _ in range(45): s.update(self.face(brow_left_lift=.215))
        self.assertIsNone(s.validator.error)
        self.assertFalse(s.validator.neutral)
        self.assertEqual(s.validator.blocking, [])

    def test_severe_drift_asks_to_repeat_only_that_gesture(self):
        s = self.calibrate(drifted_rest=.229)
        self.assertNotEqual(s.state, "error", s.snapshot())
        self.assertEqual(s.gesture_id, "LEFT_BROW")
        self.assertEqual(s.models["LEFT_BROW"].retries, 1)
        self.assertEqual(len(s.models["MOUTH_OPEN"].active_samples), 3)
        self.assertIn("Ceja izquierda", s.capture_message)
        self.assertIn("reposo", s.capture_message)
        failed = s.telemetry[-1]
        self.assertEqual((failed["gesture_id"], failed["quality_label"]), ("LEFT_BROW", "DÉBIL"))

    def test_validation_waits_and_names_gesture_that_does_not_release(self):
        s = self.calibrate(drifted_rest=.215)
        record = s.candidate["gesture_calibrations"]["LEFT_BROW"]
        between = (record["release_threshold"]["left"] + record["activation_threshold"]["left"]) / 2
        s.validate()
        v = s.validator
        for _ in range(100): s.update(self.face(brow_left_lift=between))  # 5 s sin acción
        self.assertIsNone(v.error)
        self.assertTrue(v.neutral)
        self.assertEqual(v.blocking, ["LEFT_BROW"])
        self.assertIn("Ceja izquierda", s.snapshot()["instruction"])
        for _ in range(round(v.timeout_s / .05)): s.update(self.face(brow_left_lift=between))
        self.assertIn("Ceja izquierda", v.error)
        self.assertIn("Tiempo agotado", v.error)

    def test_brow_lingering_after_both_brows_is_not_scroll(self):
        engine = GestureEngine(None, calibration=calibration(), clock=self.clock)
        events = []
        for _ in range(12): events += engine.update(self.face(brow_left_lift=.4, brow_right_lift=.5))
        for _ in range(12):
            events += engine.update(self.face(brow_left_lift=.4, brow_right_lift=.22))
            self.assertFalse(engine.last_active["LEFT_BROW"])
        self.assertEqual([e.type for e in events if e.type != "CURSOR_MOVE"], ["BOTH_BROWS"])
        for _ in range(25): engine.update(self.face(brow_left_lift=.2, brow_right_lift=.22))
        events = []
        for _ in range(12): events += engine.update(self.face(brow_left_lift=.4, brow_right_lift=.22))
        self.assertEqual([e.type for e in events if e.type != "CURSOR_MOVE"], ["SCROLL_UP"])

    def test_wrong_action_during_neutral_still_fails_with_its_name(self):
        engine = GestureEngine(None, calibration=calibration(), clock=self.clock)
        v = CalibrationValidation(engine, clock=self.clock)
        for _ in range(15): v.update(self.face(brow_left_lift=.2, mouth_open=.3))
        self.assertIn("Boca", v.error)



class BrowMotionGateTests(unittest.TestCase):
    """Sesión del 2026-10-11: 20 pausas detectadas en 7 min al mover el cursor hacia arriba."""

    def setUp(self):
        self.ms = 1000

    def clock(self): return self.ms / 1000

    def run_engine(self, engine, frames, **values):
        events = []
        for _ in range(frames):
            self.ms += 50
            events += engine.update(FaceData(True, timestamp_ms=self.ms, **(NEUTRAL | values)))
        return [e.type for e in events if e.type != "CURSOR_MOVE"]

    def engine(self, **settings):
        config = load_config(overrides={"gesture": settings}).gesture
        return GestureEngine(None, config=config, calibration=calibration(), clock=self.clock)

    def test_looking_up_does_not_pause_but_still_head_does(self):
        engine = self.engine()
        # Mirar hacia arriba para subir el cursor: la señal de cejas sube sola.
        moving = self.run_engine(engine, 20, nose_y=.42, brow_left_lift=.4, brow_right_lift=.5)
        self.assertEqual(moving, [])
        self.assertFalse(engine.head_still)
        self.assertFalse(engine.last_active["BOTH_BROWS"])
        self.run_engine(engine, 20)
        still = self.run_engine(engine, 20, brow_left_lift=.4, brow_right_lift=.5)
        self.assertEqual(still, ["BOTH_BROWS"])

    def test_gate_blocks_scroll_but_not_clicks_or_mouth(self):
        engine = self.engine()
        self.assertEqual(self.run_engine(engine, 12, nose_y=.42, brow_left_lift=.4), [])
        self.assertEqual(self.run_engine(engine, 12, nose_y=.42, eye_left_ratio=.02), ["LEFT_CLICK"])
        self.run_engine(engine, 20, nose_y=.42)
        self.assertEqual(self.run_engine(engine, 12, nose_y=.42, mouth_open=.3), ["MOUTH_OPEN"])

    def test_gate_can_be_disabled_per_profile(self):
        engine = self.engine(brow_motion_gate=False)
        self.assertEqual(self.run_engine(engine, 20, nose_y=.42, brow_left_lift=.4, brow_right_lift=.5),
                         ["BOTH_BROWS"])
        with self.assertRaises(ValueError):
            load_config(overrides={"gesture": {"brow_motion_gate": "si"}})


if __name__ == "__main__": unittest.main()
