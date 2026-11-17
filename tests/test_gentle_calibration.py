"""Calibración más amable (2026-11-17), después de la prueba con una chica con ELA.

- Recalibrar un solo gesto conserva los demás: antes, rehacer el guiño izquierdo
  obligaba a calibrar todo de nuevo.
- Modo «movimientos suaves»: 2 intentos, más tiempo, umbral más cerca del reposo, se
  acepta el promedio; a cambio, el gesto se sostiene 350 ms para actuar.
"""
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import test_adaptive_session as base
from adaptive_calibration import GestureCalibration
from calibration_session import CalibrationSession
from config import GENTLE_HOLD_MS, effective_gesture, load_config
from gesture_signals import GESTURE_SIGNALS
from profiles import validate_profile

ACTIVE, NEUTRAL = base.ACTIVE, base.NEUTRAL


class Harness(unittest.TestCase):
    setUp = base.AdaptiveSessionTests.setUp
    clock = base.AdaptiveSessionTests.clock
    face = base.AdaptiveSessionTests.face
    capture = base.AdaptiveSessionTests.capture
    feed = base.AdaptiveSessionTests.feed

    def validate_all(self, session, variants=ACTIVE):
        session.validate()
        for event, _instruction in session.validator.gestures:
            key = next(k for k, s in GESTURE_SIGNALS.items() if s.event_type == event)
            self.feed(session, 2.2)
            self.feed(session, .45, variants[key])
            self.assertIsNone(session.validator.error, key)
        self.feed(session, 2.2)
        self.assertEqual(session.state, "validated")
        return session.result()

    def calibrated_profile(self, enabled=None):
        s = CalibrationSession({"user_id": "synthetic"}, self.config, self.clock, enabled)
        s.start()
        self.capture(s)
        return self.validate_all(s)


class SingleGestureTests(Harness):
    def test_recalibrating_one_gesture_keeps_the_others_untouched(self):
        profile = self.calibrated_profile()
        before = deepcopy(profile["gesture_calibrations"])
        s = CalibrationSession(profile, self.config, self.clock, only=["LEFT_WINK"])
        s.start()
        stronger = dict(ACTIVE, LEFT_WINK={"eye_left_ratio": .04})
        self.capture(s, stronger)
        self.assertEqual(s.state, "measured")
        self.assertEqual([r["gesture_id"] for r in s.telemetry], ["LEFT_WINK"])  # sólo se midió ése
        result = self.validate_all(s, stronger)
        self.assertEqual([event for event, _ in s.validator.gestures], ["LEFT_CLICK"])  # sólo se prueba ése
        records = result["gesture_calibrations"]
        for key in GESTURE_SIGNALS:
            if key != "LEFT_WINK":
                self.assertEqual(records[key]["activation_threshold"], before[key]["activation_threshold"], key)
                self.assertEqual(records[key]["quality_score"], before[key]["quality_score"], key)
        self.assertNotEqual(records["LEFT_WINK"]["activation_threshold"], before["LEFT_WINK"]["activation_threshold"])
        self.assertEqual(result["neutral_nose_x"], profile["neutral_nose_x"])
        validate_profile(result)

    def test_a_kept_gesture_that_fires_during_the_test_is_still_noticed(self):
        s = CalibrationSession(self.calibrated_profile(), self.config, self.clock, only=["LEFT_WINK"])
        s.start()
        self.capture(s)
        s.validate()
        self.feed(s, 2.2)
        self.feed(s, .5, ACTIVE["MOUTH_OPEN"])  # gesto guardado, que se cuela
        self.assertEqual(s.validator.strikes.get("MOUTH_OPEN"), 1)

    def test_kept_gestures_show_as_saved_and_can_be_brought_back(self):
        s = CalibrationSession(self.calibrated_profile(), self.config, self.clock, only=["LEFT_WINK"])
        s.start()
        quality = s.snapshot()["quality"]
        self.assertTrue(quality["MOUTH_OPEN"]["label"].endswith("· guardado"))
        self.assertEqual(s.snapshot()["only"], ["LEFT_WINK"])
        s.repeat("RIGHT_WINK")  # «este también»: pasa a medirse
        self.assertIn("RIGHT_WINK", s.snapshot()["only"])
        self.assertNotIn("RIGHT_WINK", s.snapshot()["kept"])

    def test_needs_a_saved_calibration(self):
        with self.assertRaisesRegex(ValueError, "calibración completa"):
            CalibrationSession({"user_id": "nuevo"}, self.config, self.clock, only=["LEFT_WINK"])

    def test_a_gesture_that_was_off_can_be_calibrated_alone_later(self):
        profile = self.calibrated_profile({key: key != "KISS" for key in GESTURE_SIGNALS})
        self.assertFalse(profile["gesture_calibrations"]["KISS"]["enabled"])
        s = CalibrationSession(profile, self.config, self.clock, only=["KISS"])
        s.start()
        self.capture(s)
        result = self.validate_all(s)
        self.assertTrue(result["gesture_calibrations"]["KISS"]["enabled"])
        self.assertTrue(result["gesture_calibrations"]["LEFT_WINK"]["enabled"])
        validate_profile(result)


class GentleModeTests(Harness):
    def gentle(self):
        config = deepcopy(self.config)
        config.calibration.gentle = True
        return config

    def test_two_attempts_and_the_chosen_settings_are_what_gets_saved(self):
        s = CalibrationSession({"user_id": "synthetic"}, self.gentle(), self.clock,
                               {key: key in ("LEFT_WINK", "BOTH_BROWS") for key in GESTURE_SIGNALS})
        s.start()
        self.capture(s)
        self.assertEqual(s.state, "measured")
        for key in ("LEFT_WINK", "BOTH_BROWS"):
            record = s.candidate["gesture_calibrations"][key]
            self.assertEqual(record["repetitions_captured"], 2)
            self.assertEqual(record["min_quality"], .75)
        saved = s.candidate["settings"]["calibration"]
        self.assertTrue(saved["gentle"])
        self.assertEqual(saved["repetitions"], 3)  # apagar el modo suave vuelve a lo de siempre
        self.assertEqual(saved["min_quality"], .85)
        validate_profile(s.candidate)

    def test_gestures_must_be_held_longer_to_act(self):
        config = load_config(overrides={"calibration": {"gentle": True}})
        held = effective_gesture(config)
        for name in ("blink_hold_ms", "brow_hold_ms", "mouth_hold_ms", "both_brows_hold_ms"):
            self.assertGreaterEqual(getattr(held, name), GENTLE_HOLD_MS)
        self.assertEqual(effective_gesture(load_config()).blink_hold_ms, load_config().gesture.blink_hold_ms)

    def test_quality_floor_follows_the_mode(self):
        model = GestureCalibration("MOUTH_OPEN", ("mouth_open",), (1,))
        model.activation_threshold = {"mouth_open": .1}
        model.quality_score = .8
        self.assertFalse(model.usable)  # normal: hace falta 0,85
        model.min_quality = .75
        self.assertTrue(model.usable)

    def test_profile_accepts_gentle_quality_only_when_calibrated_gently(self):
        profile = self.calibrated_profile()
        record = profile["gesture_calibrations"]["MOUTH_OPEN"]
        record["quality_score"] = .8
        with self.assertRaises(ValueError):
            validate_profile(profile)
        record["min_quality"] = .75
        validate_profile(profile)
        record["min_quality"] = .5  # nadie puede bajar el piso a mano
        with self.assertRaises(ValueError):
            validate_profile(profile)


class ControllerTests(Harness):
    def test_repeat_after_saving_recalibrates_only_that_gesture(self):
        import test_gui
        from application_controller import ApplicationController
        from profile_manager import ProfileManager
        from profiles import ProfileStore
        profile = self.calibrated_profile()
        with tempfile.TemporaryDirectory() as folder:
            manager = ProfileManager(ProfileStore(Path(folder) / "profiles"))
            manager.store.save(profile)
            controller = ApplicationController(manager, test_gui.FakeVision, Mock(), folder)
            self.addCleanup(controller.shutdown)
            controller.select_profile("synthetic")
            controller.repeat_calibration(gesture_id="LEFT_WINK")
            self.assertEqual(controller.state, "CALIBRATING")
            self.assertEqual(controller.wizard.only, {"LEFT_WINK"})
            self.assertIn("MOUTH_OPEN", controller.wizard.kept)
            controller.start_calibration(gentle=True)
            self.assertTrue(controller.wizard.config.calibration.gentle)
            self.assertIsNone(controller.wizard.only)
            with self.assertRaises(ValueError):
                controller.start_calibration(gentle="sí")



class SetupScreenTests(Harness):
    def window(self):
        import test_gui
        case = test_gui.GUITests("test_window_pages_safe_start_and_no_backend")
        test_gui.GUITests.setUpClass()
        case.setUp()
        self.addCleanup(case.tearDown)
        return case

    def test_new_profile_starts_with_two_recommended_gestures(self):
        case = self.window()
        case.manager.create("Nueva")
        case.bridge.request("select_profile", user_id=case.manager.list_profiles()[0]["user_id"])
        case.wait(lambda: case.bridge.snapshot().get("profile") is not None)
        w = case.window
        w.show_page(2)
        w.refresh()
        self.assertTrue(w.calibration_setup.isVisible())
        self.assertEqual({k for k, c in w.calibration_enabled.items() if c.isChecked()}, {"LEFT_WINK", "BOTH_BROWS"})
        self.assertFalse(w.single_gesture_button.isEnabled())  # todavía no hay nada guardado
        self.assertIn("Click izquierdo", w.calibration_enabled["LEFT_WINK"].text())
        w.calibration_enabled["KISS"].setChecked(True)
        w.calibration_gentle.setChecked(True)
        sent = Mock()
        w.bridge.request = sent
        self.addCleanup(delattr, w.bridge, "request")  # el cierre de la ventana usa el real
        w.calibration_primary_action()
        name, kwargs = sent.call_args.args[0], sent.call_args.kwargs
        self.assertEqual(name, "start_calibration")
        self.assertEqual({k for k, v in kwargs["enabled"].items() if v}, {"LEFT_WINK", "BOTH_BROWS", "KISS"})
        self.assertTrue(kwargs["gentle"])

    def test_saved_profile_can_redo_a_single_gesture(self):
        case = self.window()
        case.manager.store.save(self.calibrated_profile({key: key != "KISS" for key in GESTURE_SIGNALS}))
        case.bridge.request("select_profile", user_id="synthetic")
        case.wait(lambda: case.bridge.snapshot().get("saved_gestures"))
        w = case.window
        w.show_page(2)
        w.refresh()
        self.assertTrue(w.single_gesture_button.isEnabled())
        self.assertFalse(w.calibration_enabled["KISS"].isChecked())  # lo guardado, no lo recomendado
        self.assertTrue(w.calibration_enabled["MOUTH_OPEN"].isChecked())
        sent = Mock()
        w.bridge.request = sent
        self.addCleanup(delattr, w.bridge, "request")  # el cierre de la ventana usa el real
        w.single_gesture.setCurrentIndex(w.single_gesture.findData("RIGHT_WINK"))
        w.single_gesture_button.click()
        self.assertEqual(sent.call_args.args[0], "start_calibration")
        self.assertEqual(sent.call_args.kwargs["only"], ["RIGHT_WINK"])

    def test_nothing_chosen_does_not_start(self):
        case = self.window()
        case.select_calibrated()
        w = case.window
        w.refresh()
        for check in w.calibration_enabled.values():
            check.setChecked(False)
        sent = Mock()
        w.bridge.request = sent
        self.addCleanup(delattr, w.bridge, "request")  # el cierre de la ventana usa el real
        w.start_calibration()
        sent.assert_not_called()


if __name__ == "__main__":
    unittest.main()
