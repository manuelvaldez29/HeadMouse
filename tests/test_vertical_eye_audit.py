from dataclasses import replace
import unittest

import numpy as np

from eye_geometry import extract_gaze
from gaze_mapping import GazeCalibrationSession, GazeModel
from gesture_engine import GestureEngine
from tracking import create_strategy
from tracking_calibration import TrackingCalibration
from test_core import calibration
from test_eye_tracking import eye_face, eye_landmarks
from test_gaze_mapping import CONTEXT, completed_session, fitted_model, target_face
from test_ocular_reference_model import reference_face


class VerticalEyeAuditTests(unittest.TestCase):
    def test_corner_y_preserves_sign_under_rotation_translation_and_scale(self):
        for source in ("left", "right"):
            for y in (.35, .5, .65):
                neutral = extract_gaze(eye_landmarks(.5, .5), 640, 480)[source + "_canthi_y"]
                original = extract_gaze(eye_landmarks(.5, y), 640, 480)[source + "_canthi_y"]
                rotated = extract_gaze(eye_landmarks(.5, y, scale=.8, tx=.04, ty=.03, roll=.2),
                                       640, 480)[source + "_canthi_y"]
                self.assertAlmostEqual(original, rotated)
                self.assertAlmostEqual(np.sign(original - neutral), np.sign(y - .5))

    def test_relative_corner_calibration_respects_axis_noise_and_keeps_horizontal_ranges(self):
        now = [1.]
        session = GazeCalibrationSession(CONTEXT, clock=lambda: now[0], countdown_s=0,
                                         settle_s=0, duration_s=.2, min_samples=5, relative=True,
                                         vertical_reference="canthi")
        for i in range(100):
            if session.state in ("ready", "invalid", "error"):
                break
            now[0] += .05
            x, y = session.snapshot()["target"]
            face = eye_face(.5 + .2 * (x - .5) + (-1)**i * .015, .5, round(now[0] * 1000))
            vertical = .5 + .02 * (y - .5)
            session.update(replace(face, left_canthi_y=vertical, right_canthi_y=vertical))
        self.assertEqual(session.state, "ready", session.message)
        record = TrackingCalibration.from_record(session.result())
        self.assertEqual(record.schema_version, 2)
        self.assertAlmostEqual(record.up_range, .008)
        self.assertAlmostEqual(record.down_range, .008)
        self.assertGreater(record.left_range, .04)
        self.assertGreater(record.right_range, .04)
        self.assertGreater(session.last_check["minimum_by_axis"][0], .02)
        self.assertEqual(session.last_check["minimum_by_axis"][1], .002)
        with self.assertRaises(ValueError):
            TrackingCalibration.from_record(record.record() | {"vertical_reference": "eyelids"})
        with self.assertRaises(ValueError):
            TrackingCalibration.from_record(record.record() | {"schema_version": 1})

    def test_small_vertical_excursion_below_own_noise_still_fails(self):
        session = GazeCalibrationSession(CONTEXT, relative=True, vertical_reference="canthi")
        center = [.5, .5, .5, .5, .5, .5, 1., 0., 0., 0.]
        session.points[0] = dict(features=center, target=[.5, .5], spread=.015, gaze_spread=[.002, .015])
        top = center.copy()
        top[1] = top[3] = .492
        point = dict(features=top, target=[.5, .1], spread=.001, gaze_spread=[.001, .001])
        self.assertIn("arriba insuficiente", session._point_problem(3, point))

    def test_binocular_unmirrored_training_keeps_each_corner_on_its_own_channel(self):
        now = [1.]
        session = GazeCalibrationSession(CONTEXT, clock=lambda: now[0], countdown_s=0,
                                         settle_s=0, duration_s=.2, min_samples=5)

        def face_at(target):
            face = reference_face(target, int(now[0] * 1000))
            return replace(face, gaze_mirrored=False, left_canthi_y=face.left_canthi_y - .1,
                           right_canthi_y=face.right_canthi_y + .1)

        for _ in range(180):
            if session.state in ("ready", "invalid", "error"):
                break
            now[0] += .05
            session.update(face_at(session.snapshot()["target"]))
        self.assertEqual(session.state, "ready", session.message)
        model = GazeModel(session.result())
        self.assertEqual(model.vertical_reference, "canthi")
        self.assertLess(model.upper[1], model.lower[3])
        np.testing.assert_allclose(model.predict(face_at((.3, .7))), (.3, .7), atol=.005)

    def test_pose_rejection_has_specific_reason_and_needs_valid_recovery_frames(self):
        model = fitted_model()
        face = target_face((.5, .5))
        out = replace(face, nose_y=.9)
        self.assertIsNone(model.predict(out))
        self.assertIn("altura", model.evaluate(out)[1])
        self.assertIn("iris", model.evaluate(replace(face, left_gaze_x=None))[1])
        strategy = create_strategy("eye_absolute", completed_session().result())
        engine = GestureEngine(None, calibration=calibration(), strategy=strategy, clock=lambda: 1.2)
        self.assertIsNotNone(engine._update_eye_cursor(face))
        self.assertIsNone(engine._update_eye_cursor(replace(out, timestamp_ms=1030)))
        self.assertIsNone(engine._update_eye_cursor(replace(out, timestamp_ms=1060)))
        for stamp in (1090, 1120):
            self.assertIsNone(engine._update_eye_cursor(replace(face, timestamp_ms=stamp)))
        self.assertIsNotNone(engine._update_eye_cursor(replace(face, timestamp_ms=1150)))
