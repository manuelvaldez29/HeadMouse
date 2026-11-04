"""Al iniciar HeadMouse el centro se fija en la nariz, no en la postura de la calibración (2026-11-04)."""
import unittest
from dataclasses import replace
from unittest.mock import Mock

from config import ControlConfig, GestureConfig
from control_engine import ControlEngine
from face_data import FaceData
from gesture_engine import GestureEngine
from test_adaptive_session import ACTIVE, NEUTRAL
from test_core import calibration


class StartupCenteringTests(unittest.TestCase):
    def setUp(self):
        self.ms = 1000
        self.face = FaceData(True, timestamp_ms=self.ms, **NEUTRAL)
        self.vision = Mock()
        self.vision.get_fps.return_value = 15
        self.vision.get_face_data.side_effect = lambda: self.face
        self.backend = Mock()
        self.backend.size.return_value = (1920, 1080)
        self.backend.position.return_value = (500, 500)
        self.backend.FailSafeException = RuntimeError

    def clock(self):
        return self.ms / 1000

    def start(self):
        gesture = GestureEngine(self.vision, config=GestureConfig(), calibration=calibration(), clock=self.clock)
        control = ControlEngine(self.vision, gesture, config=ControlConfig(), backend=self.backend,
                                wheel_unit=1, clock=self.clock)
        control.toggle_pause()  # como activate_control
        self.assertTrue(control.begin_centering())
        return gesture, control

    def step(self, control, dt_ms=67, **values):
        self.ms += dt_ms
        self.face = replace(FaceData(True, timestamp_ms=self.ms, **NEUTRAL), **values)
        control._tick()

    def test_still_nose_below_the_calibrated_center_becomes_the_center(self):
        gesture, control = self.start()
        for _ in range(12):  # ~0,8 s quieto, 0,06 más abajo que al calibrar (fuera de la zona quieta)
            self.step(control, nose_y=.56)
        self.assertFalse(control.centering)
        self.assertTrue(control.last_recenter["ok"] and control.last_recenter["startup"])
        self.assertAlmostEqual(gesture.config.neutral_y, .56, places=3)
        self.backend.moveRel.assert_not_called()  # el cursor esperó y no se fue solo
        for _ in range(20):
            self.step(control, nose_y=.56)
        self.backend.moveRel.assert_not_called()  # y quieto en el centro nuevo no se mueve

    def test_gestures_wait_while_searching(self):
        gesture, control = self.start()
        self.step(control, nose_y=.6, nose_x=.4)
        for _ in range(5):
            self.step(control, nose_y=.6, nose_x=.4 + .02 * (_ % 2), **ACTIVE["LEFT_WINK"])
        self.backend.click.assert_not_called()

    def test_moving_head_keeps_the_calibrated_center_after_the_timeout(self):
        gesture, control = self.start()
        for k in range(70):  # ~4,7 s moviéndose
            self.step(control, nose_x=.5 + (.04 if k % 2 else -.04))
        self.assertFalse(control.centering)
        self.assertFalse(control.last_recenter["ok"])
        self.assertIn("calibración", control.last_recenter["reason"])
        self.assertEqual(gesture.config.neutral_x, .5)
        self.step(control, nose_x=.62)
        self.step(control, nose_x=.62)
        self.backend.moveRel.assert_called()  # pasado el plazo, el cursor funciona

    def test_pause_during_the_search_cancels_it(self):
        gesture, control = self.start()
        self.step(control, nose_y=.56)
        control.toggle_pause()
        self.assertFalse(control.centering)

    def test_not_for_eye_tracking_or_with_auto_recenter_off(self):
        gesture = Mock()
        gesture.strategy.name = "eye_absolute"
        gesture.config = GestureConfig()
        control = ControlEngine(self.vision, gesture, backend=self.backend, wheel_unit=1)
        self.assertFalse(control.begin_centering())
        gesture.strategy.name = "nose"
        gesture.config = GestureConfig(auto_recenter=False)
        self.assertFalse(control.begin_centering())

    def test_controller_reports_the_startup_center(self):
        from application_controller import ApplicationController
        c = ApplicationController.__new__(ApplicationController)
        c._report_recenter(dict(ok=True, dx=0, dy=.06, gestures=6, far=False, startup=True))
        self.assertIn("Centro en tu nariz", c.message)
        c._report_recenter(dict(ok=False, startup=True, reason="no hubo un momento con la cabeza quieta"))
        self.assertIn("Centro de la calibración", c.message)


if __name__ == "__main__":
    unittest.main()
