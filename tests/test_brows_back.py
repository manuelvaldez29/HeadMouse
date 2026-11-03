"""Cejas separadas de vuelta (2026-11-03) junto a los labios a los costados.

El 2026-11-02 se reemplazaron por los labios. Volvieron como gestos propios
(LEFT_BROW / RIGHT_BROW) que se pueden destildar, sin quitarle nada a los labios.
"""
import unittest
from copy import deepcopy

from action_mapping import ActionMapping
from calibration_session import CalibrationSession
from config import load_config
from face_data import FaceData
from gesture_engine import GestureEngine
from profiles import validate_profile
from test_adaptive_session import ACTIVE, NEUTRAL


class BrowsBackTests(unittest.TestCase):
    def setUp(self):
        self.timestamp = 1000
        self.config = load_config()
        cc = self.config.calibration
        cc.countdown_s, cc.measuring_s, cc.min_samples, cc.min_window_samples = .1, .2, 3, 3
        cc.active_window_s = cc.neutral_window_s = .15
        cc.transition_s = .05

    def clock(self):
        return self.timestamp / 1000

    def face(self, values=None):
        self.timestamp += 50
        return FaceData(True, timestamp_ms=self.timestamp, **(NEUTRAL | (values or {})))

    def calibrated(self, enabled=None):
        session = CalibrationSession({"user_id": "cejas"}, self.config, self.clock, enabled)
        session.start()
        for _ in range(3000):
            if session.state in ("measured", "error"):
                break
            session.update(self.face(ACTIVE.get(session.gesture_id, {}) if session.stage == "active" else {}))
        self.assertEqual(session.state, "measured", session.snapshot())
        profile = deepcopy(session.candidate)
        profile["validation"] = {"passed": True}
        return profile

    def actions(self, engine, frames=12, values=None):
        mapping, found = ActionMapping(), []
        for _ in range(frames):
            found += [mapping.resolve(e).type for e in engine.update(self.face(values)) if e.type != "CURSOR_MOVE"]
        return found

    def engine(self, profile):
        return GestureEngine(None, config=load_config().gesture, calibration=profile, clock=self.clock)

    def test_brows_are_calibrated_by_default_and_scroll(self):
        fresh = CalibrationSession({"user_id": "nuevo"}, self.config, self.clock)
        self.assertTrue(fresh.models["LEFT_BROW"].enabled and fresh.models["RIGHT_BROW"].enabled)
        engine = self.engine(self.calibrated())
        self.actions(engine)
        self.assertEqual(self.actions(engine, values=ACTIVE["LEFT_BROW"]), ["SCROLL_UP"])
        self.actions(engine, frames=30)
        self.assertEqual(self.actions(engine, values=ACTIVE["RIGHT_BROW"]), ["SCROLL_DOWN"])
        self.actions(engine, frames=30)
        self.assertEqual(self.actions(engine, values=ACTIVE["MOUTH_LEFT"]), ["SCROLL_UP"])  # los labios siguen

    def test_raising_both_brows_pauses_without_scrolling(self):
        engine = self.engine(self.calibrated())
        self.actions(engine)
        # Levantar ambas suele empezar por una: el árbitro espera y decide "ambas".
        fired = self.actions(engine, frames=2, values=ACTIVE["LEFT_BROW"])
        fired += self.actions(engine, frames=12, values=ACTIVE["BOTH_BROWS"] | {"brow_left_lift": .4, "brow_right_lift": .5})
        self.assertEqual(fired, ["PAUSE"])

    def test_brows_can_be_unchecked(self):
        profile = self.calibrated({"LEFT_BROW": False, "RIGHT_BROW": False})
        engine = self.engine(profile)
        self.assertFalse({"LEFT_BROW", "RIGHT_BROW"} & engine.enabled_gestures)
        self.actions(engine)
        self.assertEqual(self.actions(engine, values=ACTIVE["LEFT_BROW"]), [])
        self.assertEqual(self.actions(engine, frames=12, values=ACTIVE["BOTH_BROWS"]), ["PAUSE"])  # al instante

    def test_profile_calibrated_without_brows_stays_valid_and_off(self):
        old = self.calibrated()  # como uno guardado entre el 2026-11-02 y hoy
        for key in ("LEFT_BROW", "RIGHT_BROW"):
            del old["gesture_calibrations"][key]
            del old["settings"]["actions"]["bindings"][key]
        validate_profile(deepcopy(old))
        engine = self.engine(old)
        self.assertFalse({"LEFT_BROW", "RIGHT_BROW"} & engine.enabled_gestures)
        self.assertEqual(load_config(overrides=old["settings"]).actions.bindings["LEFT_BROW"], "SCROLL_UP")
        again = CalibrationSession(old, self.config, self.clock)
        self.assertTrue(again.models["LEFT_BROW"].enabled)  # la próxima calibración las incluye


if __name__ == "__main__":
    unittest.main()
