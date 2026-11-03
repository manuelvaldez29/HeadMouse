"""Besito (2026-11-03): gesto opcional por el ancho de la boca, con mouthPucker de control.

La primera versión usaba sólo el blendshape mouthPucker. En la calibración real del
usuario marcó 0.85-0.93 con la cara relajada (labios cerrados o apretados) durante
28 s, y 0.03-0.35 relajado después: el mismo rango que el besito (0.8-1.0).
"""
import unittest
from copy import deepcopy
from types import SimpleNamespace

from action_mapping import ActionMapping
from calibration_session import CalibrationSession
from config import MappingConfig, load_config
from face_data import FaceData
from gesture_engine import GestureEngine, GestureEvent
from gesture_signals import GESTURE_SIGNALS, extract_blendshapes
from profiles import migrate_legacy_lip_gestures, validate_profile
from test_adaptive_session import ACTIVE, NEUTRAL

WIDE, NARROW = .53, .38      # comisuras / interocular: relajado y con el besito
RELAXED, PRESSED, KISS = .25, .9, .85  # mouthPucker


class KissGestureTests(unittest.TestCase):
    def setUp(self):
        self.timestamp = 1000
        self.config = load_config()
        cc = self.config.calibration
        cc.countdown_s, cc.measuring_s, cc.min_samples, cc.min_window_samples = .1, .2, 3, 3
        cc.active_window_s = cc.neutral_window_s = .15
        cc.transition_s = .05

    def clock(self):
        return self.timestamp / 1000

    def face(self, values=None, width=WIDE, pucker=RELAXED):
        self.timestamp += 50
        return FaceData(True, timestamp_ms=self.timestamp, mouth_width=width,
                        blendshapes=(("mouthPucker", pucker),), **(NEUTRAL | (values or {})))

    def calibrated(self, kiss=True, rest_pucker=RELAXED):
        session = CalibrationSession({"user_id": "besito"}, self.config, self.clock, {"KISS": kiss})
        session.start()
        for _ in range(2000):
            if session.state in ("measured", "error"):
                break
            active = session.stage == "active"
            kissing = active and session.gesture_id == "KISS"
            session.update(self.face(ACTIVE.get(session.gesture_id, {}) if active else {},
                                     NARROW if kissing else WIDE, KISS if kissing else rest_pucker))
        self.assertEqual(session.state, "measured", session.snapshot())
        profile = deepcopy(session.candidate)
        profile["validation"] = {"passed": True}
        return profile

    def events(self, engine, frames=10, values=None, width=WIDE, pucker=RELAXED):
        found = []
        for _ in range(frames):
            found += [e.type for e in engine.update(self.face(values, width, pucker)) if e.type != "CURSOR_MOVE"]
        return found

    def engine(self, profile):
        return GestureEngine(None, config=load_config().gesture, calibration=profile, clock=self.clock)

    def test_signal_is_the_mouth_width(self):
        self.assertEqual(GESTURE_SIGNALS["KISS"].extract(self.face(width=.4)), (.4,))
        self.assertIsNone(GESTURE_SIGNALS["KISS"].extract(FaceData(True, timestamp_ms=1)))  # sin medir
        categories = [SimpleNamespace(category_name=n, score=s) for n, s in (("mouthPucker", .7), ("jawOpen", .4))]
        self.assertEqual(dict(extract_blendshapes(categories)), {"mouthPucker": .7})

    def test_calibrated_kiss_double_clicks(self):
        profile = self.calibrated()
        validate_profile(deepcopy(profile))
        record = profile["gesture_calibrations"]["KISS"]
        self.assertTrue(record["enabled"])
        self.assertEqual(record["channels"], ["mouth_width"])
        self.assertEqual(record["repetitions_valid"], 3)
        engine = self.engine(profile)
        self.events(engine)
        self.assertEqual(self.events(engine, width=NARROW, pucker=KISS), ["KISS"])
        self.assertEqual(ActionMapping().resolve(GestureEvent(type="KISS")).type, "DOUBLE_CLICK")

    def test_pressed_lips_are_neutral_for_calibration_and_never_a_kiss(self):
        # El caso real: labios apretados, mouthPucker 0.9, boca de ancho normal.
        profile = self.calibrated(rest_pucker=PRESSED)
        engine = self.engine(profile)
        self.events(engine)
        self.assertEqual(self.events(engine, frames=40, pucker=PRESSED), [])
        self.assertEqual(self.events(engine, width=NARROW, pucker=KISS), ["KISS"])

    def test_narrow_mouth_needs_puckered_lips_closed_and_centered(self):
        engine = self.engine(self.calibrated())
        self.events(engine)
        self.assertEqual(self.events(engine, width=NARROW, pucker=.1), [])  # otra mueca, no besito
        self.assertNotIn("KISS", self.events(engine, values=ACTIVE["MOUTH_OPEN"], width=NARROW, pucker=KISS))
        self.events(engine, frames=30)
        fired = self.events(engine, values=ACTIVE["MOUTH_LEFT"], width=NARROW, pucker=KISS)
        self.assertNotIn("KISS", fired)  # labios corridos: es el scroll
        self.assertIn("SCROLL_UP", fired)

    def test_profiles_without_kiss_stay_valid_and_off(self):
        old = self.calibrated(kiss=False)  # perfil guardado antes de que existiera el besito
        del old["gesture_calibrations"]["KISS"]
        del old["settings"]["actions"]["bindings"]["KISS"]
        validate_profile(deepcopy(old))
        engine = self.engine(old)
        self.assertNotIn("KISS", engine.enabled_gestures)
        self.events(engine)
        self.assertEqual(self.events(engine, width=NARROW, pucker=KISS), [])
        self.assertEqual(MappingConfig(old["settings"]["actions"]["bindings"]).bindings["KISS"], "DOUBLE_CLICK")

    def test_kiss_recorded_with_the_old_pucker_signal_is_dropped_not_invalid(self):
        profile = self.calibrated(kiss=False)
        stale = dict(profile["gesture_calibrations"]["KISS"], channels=["kiss"], directions=[1], source="BLENDSHAPE")
        profile["gesture_calibrations"]["KISS"] = stale
        profile["gesture_modes"] = {"nose": {"gesture_calibrations": deepcopy(profile["gesture_calibrations"])}}
        migrated = migrate_legacy_lip_gestures(deepcopy(profile))
        self.assertNotIn("KISS", migrated["gesture_calibrations"])
        self.assertNotIn("KISS", migrated["gesture_modes"]["nose"]["gesture_calibrations"])
        self.assertTrue(migrated["validation"]["passed"])

    def test_kiss_is_opt_in_and_then_remembered(self):
        fresh = CalibrationSession({"user_id": "nuevo"}, self.config, self.clock)
        self.assertFalse(fresh.models["KISS"].enabled)
        self.assertTrue(fresh.models["LEFT_WINK"].enabled)
        self.assertTrue(CalibrationSession(self.calibrated(), self.config, self.clock).models["KISS"].enabled)


if __name__ == "__main__":
    unittest.main()
