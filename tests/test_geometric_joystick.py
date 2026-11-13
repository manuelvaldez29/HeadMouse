import math
import unittest
from unittest.mock import Mock, patch

from dataclasses import asdict
from config import EyeTrackingConfig, load_config, settings_for_save
from direction_diagnostic import DIRECTIONS, TARGETS
from face_data import FaceData
from geometric_calibration import GeometricSession, fit, gate_weighted, local_point, repair_axis
from geometric_joystick import GeometricJoystick, calibration_quality
import test_gui


def samples(point):
    return [({"local_both": point}, (.5,.5,-1.4,0.,0.,0.)) for _ in range(10)]


class GeometricTests(unittest.TestCase):
    def record(self):
        data = [(label,samples(TARGETS[label])) for _ in range(2) for label in DIRECTIONS]
        return fit(data,"both",False) | {"context": dict(source="both", camera=dict(frame_width=640,frame_height=480),
            blink_limits=dict(left=.04,right=.04))}

    def test_migration_preserves_nose_and_dwell(self):
        settings = load_config(overrides={"ui":{"tracking_method":"nose","ocular_engine":"eye_openvino",
            "openvino_keyboard_dwell":True}, "gesture":{"sensitivity":83}, "openvino_eye":{"sensitivity":40}})
        self.assertEqual(settings.ui.tracking_method,"nose")
        self.assertEqual(settings.ui.ocular_engine,"eye_joystick")
        self.assertEqual(settings.gesture.sensitivity,83)
        self.assertTrue(settings.ui.ocular_keyboard_dwell)

    def test_projection_uses_comisures_and_weights_reject_disagreement(self):
        eye = dict(blink=False,available=True,eye_ratio=.1,geometry=dict(
            width_px=20.,corner_1_x_px=30.,corner_1_y_px=30.,corner_2_x_px=30.,corner_2_y_px=50.,
            iris_x_px=29.,iris_y_px=38.,canthi_y_raw=.55))
        self.assertEqual(local_point(eye),(.4,.55))
        self.assertIsNone(local_point(eye|{"blink":True}))
        values = dict(local_left=(.4,.5),local_right=(.6,.5),weighted=(.5,.5))
        self.assertNotIn("weighted",gate_weighted(values,(.15,.15)))

    def test_axis_repair_preserves_other_axis_and_invalidates_physical(self):
        record=self.record()
        record["validation"]={"fingerprint":"old"}
        rows=[(label,samples((TARGETS[label][0],TARGETS[label][1]+.01))) for label in ("center","up","down")]
        rows += [(label,samples(TARGETS[label])) for label in DIRECTIONS]
        updated=repair_axis(record,rows,1)
        for label in DIRECTIONS:
            self.assertEqual(updated["candidates"]["local_both"]["centers"][label][0],TARGETS[label][0])
        self.assertNotIn("validation", updated)

    def test_center_and_signal_loss_stop_without_physical_output(self):
        now=100.
        record=self.record()
        joystick=GeometricJoystick(Mock(_frame_size=(640,480)),record,EyeTrackingConfig(),.25,lambda:now)
        def feed(point, detected=True):
            nonlocal now
            now += .075
            fd=FaceData(detected,timestamp_ms=int(now*1000),eye_left_ratio=.12,eye_right_ratio=.12,
                        nose_x=.5,nose_y=.5,face_scale=math.exp(-1.4),
                        head_pitch=0.,head_yaw=0.,head_roll=0.)
            with patch("geometric_joystick.observe_direction",return_value={"head":(.5,.5,.25,0.,0.,0.)}), \
                 patch("geometric_joystick.signals",return_value={"local_both":point}):
                return joystick.update(fd,now)
        for _ in range(4):
            self.assertIsNone(feed(TARGETS["center"]))
        self.assertIsNone(feed(TARGETS["right"]))
        self.assertGreater(feed(TARGETS["right"]).dx,0)
        self.assertIsNone(feed(TARGETS["center"]))
        self.assertEqual(joystick.movement,(0.,0.))
        self.assertIsNone(feed(TARGETS["right"],False))
        self.assertFalse(joystick.armed)

    def test_safety_requires_an_axis_with_usable_range_and_center(self):
        record = self.record()
        candidate = record["candidates"]["local_both"]
        self.assertTrue(all(calibration_quality(record, EyeTrackingConfig())[3]))
        candidate["noise"] = (.0, .3)
        horizontal, vertical = calibration_quality(record, EyeTrackingConfig())[3]
        self.assertIsNotNone(horizontal)
        self.assertIsNone(vertical)
        candidate["noise"] = (.3, .3)
        self.assertFalse(any(calibration_quality(record, EyeTrackingConfig())[3]))

    def test_movement_preferences_survive_switching_between_both_ocular_modes(self):
        direct = load_config(overrides={"ui":{"tracking_method":"eye_absolute","unified_eyes":True}})
        edited = asdict(direct)
        edited["ui"].update(tracking_method="eye_joystick", ocular_engine="eye_joystick")
        joystick = settings_for_save(direct, edited)
        edited = asdict(joystick)
        edited["eye"]["sensitivity"] = 73
        edited["ui"].update(tracking_method="eye_absolute", ocular_engine="eye_absolute")
        restored = settings_for_save(joystick, edited)
        self.assertEqual(restored.eye.sensitivity, direct.eye.sensitivity)
        edited = asdict(restored)
        edited["ui"].update(tracking_method="eye_joystick", ocular_engine="eye_joystick")
        self.assertEqual(settings_for_save(restored, edited).eye.sensitivity, 73)

    def test_recenter_is_bounded_and_retains_original(self):
        record = self.record()
        record["validation"] = {"fingerprint": "histórico"}
        session = GeometricSession(lambda: 0., record["context"], "recenter", saved=record)
        with self.assertRaisesRegex(ValueError, "cambió demasiado"):
            session._recenter(samples((.9,.9)))
        self.assertIsNone(session.checkpoint)
        session._recenter(samples((.53,.48)))
        self.assertEqual(session.checkpoint["previous"], record)
        self.assertNotIn("validation", session.checkpoint)
        before = record["candidates"]["local_both"]["centers"]
        after = session.checkpoint["candidates"]["local_both"]["centers"]
        self.assertEqual(after["center"], (.53,.48))
        self.assertAlmostEqual(after["right"][0] - after["center"][0], before["right"][0] - before["center"][0])


@unittest.skipUnless(test_gui.QT_AVAILABLE, "Requiere PySide6")
class GeometricGuiTests(unittest.TestCase):
    setUpClass = classmethod(test_gui.GUITests.setUpClass.__func__)
    setUp = test_gui.GUITests.setUp
    tearDown = test_gui.GUITests.tearDown
    wait = test_gui.GUITests.wait
    select_calibrated = test_gui.GUITests.select_calibrated

    def test_home_switches_modes_and_joystick_calibration_never_acquires_mouse(self):
        self.select_calibrated()
        self.bridge.request("select_ocular_mode", mode="eye_joystick")
        self.wait(lambda: self.bridge.snapshot()["settings"]["ui"]["tracking_method"] == "eye_joystick")
        self.window.refresh()
        self.assertEqual(self.window.home_ocular.currentData(), "eye_joystick")
        self.assertFalse(self.window.activate_button.isEnabled())
        self.window.open_eye_calibration()
        self.window.start_public_ocular_movement()
        self.wait(lambda: self.bridge.snapshot().get("direction_diagnostic") is not None)
        self.assertEqual(self.bridge.snapshot()["direction_diagnostic"]["total"], 5)
        self.window.stop_immediately()
        self.wait(lambda: not self.bridge.snapshot().get("camera"))
        self.bridge.request("select_ocular_mode", mode="eye_absolute")
        self.wait(lambda: self.bridge.snapshot()["settings"]["ui"]["tracking_method"] == "eye_absolute")
        self.assertEqual(self.manager.store.load("julian")["settings"]["ui"]["tracking_method"], "eye_absolute")
        self.backend_factory.assert_not_called()
