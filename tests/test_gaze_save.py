"""Regresión del guardado real: rangos firmados, captura y disco temporal.

Webcam y backend del SO simulados. Nunca importa ni acciona PyAutoGUI.
"""
import tempfile
import unittest
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

from application_controller import ApplicationController
from eye_geometry import extract_gaze
from gaze_mapping import GazeCalibrationSession, GazeModel
from gaze_source import gaze_position
from ocular_profiles import calibration_for, with_calibration
from profile_manager import ProfileManager
from profiles import ProfileStore
from tracking import create_strategy
from tracking_calibration import TrackingCalibration
from test_core import calibration
from test_eye_tracking import eye_face, eye_landmarks
from test_eye_sources import completed_source_session
from test_gaze_mapping import CONTEXT, SCREEN, completed_session


class CaptureRegressionTests(unittest.TestCase):
    def session(self, source="both", relative=True):
        self.now = 1.
        return GazeCalibrationSession(CONTEXT, clock=lambda:self.now,
            countdown_s=0, settle_s=0, duration_s=.2, min_samples=5,
            relative=relative, eye_source=source)

    def capture(self, session, x, y, transform=lambda face:face):
        previous = (session.phase, session.index)
        for _ in range(12):
            self.now = round(self.now+.05, 3)
            session.update(transform(eye_face(x, y, round(self.now*1000))))
            if session.state in ("ready", "invalid", "error") or (session.phase, session.index) != previous:
                break

    def completed(self, source="both", relative=True):
        session = self.session(source, relative)
        for _ in range(20):
            target = session.snapshot()["target"]
            self.capture(session, .25+.5*target[0], .25+.5*target[1])
            if session.state in ("ready", "invalid", "error"):
                break
        self.assertEqual(session.state, "ready", session.message)
        return session

    def test_reported_small_up_range_is_rejected_before_advance(self):
        session = self.completed()
        before = deepcopy(session.points)
        session.repeat(3)
        self.capture(session, .5, .5-.0038342737639921465)
        self.assertEqual(session.state, "invalid")
        self.assertEqual(session.index, 3)
        self.assertIn("arriba insuficiente", session.message)
        self.assertFalse(session.snapshot()["can_save"])
        self.assertNotIn(3, session.points)
        for index in (0, 1, 2, 4):
            self.assertEqual(session.points[index], before[index])
        self.assertAlmostEqual(session.last_check["delta"][1], -.0038342737639921465)

    def test_reported_negative_down_range_has_visible_signed_reason(self):
        session = self.completed()
        session.repeat(4)
        self.capture(session, .5, .5-.017683836886550786)
        self.assertEqual(session.state, "invalid")
        self.assertIn("abajo no coincide", session.message)
        self.assertIn("-0.017684", session.message)
        self.assertIn(4, session.rejected_points)
        with self.assertRaises(ValueError): session.result()

    def test_repeat_only_failed_point_then_ready_and_constructible(self):
        session = self.completed()
        session.repeat(3)
        self.capture(session, .5, .49)
        retained = deepcopy(session.points)
        session.repeat(3)
        self.capture(session, .5, .3)
        self.assertTrue(session.snapshot()["can_save"])
        TrackingCalibration.from_record(session.result())
        for index, point in retained.items():
            self.assertEqual(session.points[index], point)

    def test_inverted_y_signal_is_rejected_during_up_capture_for_all_sources(self):
        for source in ("both", "left", "right"):
            session = self.session(source)
            for x, y in ((.5,.5),(.3,.5),(.7,.5),(.5,.3)):
                self.capture(session, x, 1-y)
            self.assertEqual(session.index, 3)
            self.assertEqual(session.state, "invalid")
            self.assertIn("no coincide", session.message)

    def test_wrong_horizontal_direction_does_not_advance(self):
        session = self.session()
        self.capture(session, .5, .5)
        self.capture(session, .7, .5)
        self.assertEqual(session.index, 1)
        self.assertIn("izquierda no coincide", session.message)

    def test_new_neutral_rechecks_old_points_and_keeps_compatible_ones(self):
        session = self.completed()
        old = deepcopy(session.points)
        session.repeat(0)
        self.capture(session, .5, .72)
        self.assertNotIn(4, session.points)  # viejo abajo .7 ahora está arriba
        self.assertEqual(session.index, 4)
        self.assertIn(4, session.rejected_points)
        self.assertEqual(session.points[1]["features"], old[1]["features"])
        self.assertEqual(session.points[3]["features"], old[3]["features"])
        self.assertFalse(session.snapshot()["can_save"])

    def test_neutral_outside_relative_domain_is_rejected_immediately(self):
        session = self.session()
        self.capture(session, .5, .02)
        self.assertEqual(session.state, "invalid")
        self.assertIn("Neutral fuera", session.message)

    def test_selected_missing_iris_blink_stale_and_duplicates_do_not_accept(self):
        for transform in (
            lambda f:replace(f, left_gaze_x=None),
            lambda f:replace(f, eye_left_ratio=.001),
            lambda f:replace(f, timestamp_ms=f.timestamp_ms-400),
            lambda f:replace(f, timestamp_ms=1000),
        ):
            session = self.session()
            self.capture(session, .5, .5, transform)
            self.assertEqual(session.points, {})
            self.assertFalse(session.snapshot()["can_save"])

    def test_head_change_rejected_and_other_eye_is_optional_in_monocular(self):
        for source in ("both", "left", "right"):
            session = self.session(source)
            self.capture(session, .5, .5)
            self.capture(session, .3, .5, lambda f:replace(f, nose_y=.7))
            self.assertEqual(session.state, "invalid")
            self.assertIn("cabeza cambió", session.message)
        for source in ("left", "right"):
            session = self.session(source)
            other = "right" if source == "left" else "left"
            self.capture(session, .5, .5, lambda f:replace(f, **{f"{other}_gaze_x":None, f"{other}_gaze_y":None}))
            self.assertIn(0, session.points)

    def test_unstable_gaze_or_head_cannot_advance(self):
        for head in (False, True):
            session = self.session()
            for index in range(20):
                self.now = round(self.now+.05, 3)
                face = eye_face(.5, .5 if head else (.3 if index%2 else .7), round(self.now*1000))
                if head:
                    face = replace(face, head_pitch=20 if index%2 else -20)
                session.update(face)
            self.assertFalse(session.points)
            self.assertIn("inestable", session.message)

    def test_all_sources_relative_and_absolute_models_remain_independent(self):
        for source in ("both", "left", "right"):
            relative = self.completed(source).result()
            absolute = self.completed(source, relative=False).result()
            self.assertEqual(relative["method"], "eye")
            self.assertEqual(absolute["method"], "eye_absolute")
            self.assertEqual(absolute["eye_source"], source)
            GazeModel(absolute)
            TrackingCalibration.from_record(relative)
            with self.assertRaises(ValueError): TrackingCalibration.from_record(absolute)
            with self.assertRaises(ValueError): GazeModel(relative)

    def test_absolute_captures_center_first_and_defers_direction_to_fit(self):
        session = self.session(relative=False)
        self.assertEqual(session.snapshot()["target"], (.5,.5))
        self.capture(session, .5, .5)
        self.capture(session, .7, .7)  # objetivo arriba/izquierda
        self.assertEqual(session.state, "countdown")
        self.assertIn(0, session.points)
        self.assertIsNone(session.model)
        self.assertFalse(session.snapshot()["can_save"])

    def test_absolute_validation_has_no_relative_range_minimum(self):
        session = self.session(relative=False)
        for _ in range(20):
            target = session.snapshot()["target"]
            # Semirrango .032 válido para el absoluto; sus objetivos de
            # validación tienen excursión .016, menor que el mínimo relativo.
            self.capture(session, .5+.08*(target[0]-.5), .5+.08*(target[1]-.5))
            if session.state in ("ready", "invalid", "error"):
                break
        self.assertEqual(session.state,"ready",session.message)
        GazeModel(session.result())

    def test_save_defense_revalidates_ready_relative_data(self):
        session = self.completed()
        session.points[4]["features"][1] = .4
        session.points[4]["features"][3] = .4
        with self.assertRaisesRegex(ValueError, "abajo no coincide"):
            session.result()
        self.assertFalse(session.snapshot()["can_save"])

    def test_geometry_and_tracking_signed_y_with_and_without_mirror(self):
        for mirrored in (False, True):
            for source in ("both", "left", "right"):
                for y, sign in ((.3,-1),(.7,1)):
                    geometry = extract_gaze(eye_landmarks(.5,y,mirror=mirrored),640,480,mirrored=mirrored)
                    face = replace(eye_face(), **geometry)
                    self.assertAlmostEqual(gaze_position(face,source)[1],y)
                    strategy = create_strategy("eye",TrackingCalibration(eye_source=source).record(),eye_source=source)
                    self.assertEqual(np.sign(strategy.position(face)[1]),sign)

    def test_moving_eyelids_can_reverse_normalized_signal_without_code_axis_inversion(self):
        from types import SimpleNamespace
        from eye_geometry import EYES
        neutral=extract_gaze(eye_landmarks(.5,.5),640,480)
        points=eye_landmarks(.5,.5)
        for _,_,upper,lower,iris,_ in EYES.values():
            points[upper]=SimpleNamespace(x=points[upper].x,y=.36)
            points[lower]=SimpleNamespace(x=points[lower].x,y=.41)
            points[iris]=SimpleNamespace(x=points[iris].x,y=.398)
        # Iris en imagen subió .400 -> .398, pero el marco de párpados cambió.
        moved=extract_gaze(points,640,480)
        self.assertAlmostEqual(neutral["gaze_y"],.5)
        self.assertAlmostEqual(moved["gaze_y"],.76)
        self.assertGreater(moved["gaze_y"],neutral["gaze_y"])


class SaveControllerRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = ProfileStore(self.root/"profiles")
        profile = calibration() | {"validation":{"passed":True}, "settings":{"ui":{"tracking_method":"eye"}}}
        profile = with_calibration(profile, completed_session().result())
        for source in ("both", "left", "right"):
            profile = with_calibration(profile, TrackingCalibration(eye_source=source).record())
        self.store.save(profile)
        self.now = 1.
        self.face = eye_face(.5,.5,1000)
        self.vision = Mock(error=None)
        self.vision.get_face_data.side_effect = lambda:self.face
        self.vision.get_frame.return_value = np.zeros((480,640,3),dtype=np.uint8)
        self.vision.get_fps.return_value = 30
        self.backend = Mock()
        self.backend.size.return_value = (1920,1080)
        self.backend.position.return_value = (960,540)
        self.factory = Mock(return_value=self.backend)
        self.c = ApplicationController(ProfileManager(self.store),Mock(return_value=self.vision),self.factory,
                                       self.root,clock=lambda:self.now)
        self.addCleanup(self.c.shutdown)
        self.c.start_diagnostic()

    def install_session(self, relative=True, source="both"):
        self.c.gaze_calibration = completed_source_session(source, relative=relative)
        self.c.state = "GAZE_CALIBRATING"
        return self.c.gaze_calibration

    def test_save_reload_and_activate_relative_four_directions_with_mock_backend(self):
        before = deepcopy(self.c.profile)
        self.install_session()
        self.assertTrue(self.c.save_gaze_calibration())
        saved = self.store.load(self.c.profile["user_id"])
        self.assertTrue(calibration_for(saved,"eye")["ranges_measured"])
        self.assertEqual(saved["absolute_calibration"],before["absolute_calibration"])
        self.assertEqual(saved["tracking_calibrations"]["left"],before["tracking_calibrations"]["left"])
        self.factory.assert_not_called()
        self.c.emergency.clear()
        self.c.activate_control(True)
        for x,y,axis,sign in ((.3,.5,0,-1),(.7,.5,0,1),(.5,.3,1,-1),(.5,.7,1,1)):
            self.backend.moveRel.reset_mock()
            for _ in range(12):
                self.now = round(self.now+.05, 3)
                self.face = eye_face(x,y,round(self.now*1000))
                with patch("control_engine.time.monotonic",return_value=self.now): self.c.step()
            self.backend.moveRel.assert_called()
            self.assertEqual(np.sign(self.backend.moveRel.call_args.args[axis]),sign)
        self.c.emergency_stop()
        self.c.step()
        self.assertIsNone(self.c.control)

    def test_invalid_session_preserves_disk_memory_and_useful_captures(self):
        session = self.install_session()
        session.points[3]["features"][1] = .5-.0038342737639921465
        session.points[3]["features"][3] = .5-.0038342737639921465
        original = self.store.path(self.c.profile["user_id"]).read_bytes()
        before = deepcopy(self.c.profile)
        self.assertFalse(self.c.save_gaze_calibration())
        self.assertEqual(self.store.path(self.c.profile["user_id"]).read_bytes(),original)
        self.assertEqual(self.c.profile,before)
        self.assertIs(self.c.gaze_calibration,session)
        self.assertIn("arriba insuficiente",session.message)
        self.assertFalse(session.snapshot()["can_save"])
        self.assertEqual(len(session.points),5)
        self.factory.assert_not_called()

    def test_atomic_write_failure_is_visible_and_retryable(self):
        session = self.install_session()
        path = self.store.path(self.c.profile["user_id"])
        original = path.read_bytes()
        with patch("profiles.replace_with_retry",side_effect=PermissionError("archivo ocupado")):
            self.assertFalse(self.c.save_gaze_calibration())
        self.assertEqual(path.read_bytes(),original)
        self.assertIn("archivo ocupado",session.message)
        self.assertTrue(session.snapshot()["can_save"])
        self.assertEqual(list(path.parent.glob("*.tmp")),[])
        self.assertTrue(self.c.save_gaze_calibration())

    def test_source_changed_cannot_write_wrong_bank(self):
        self.install_session(source="left")
        original = deepcopy(self.c.profile)
        self.assertFalse(self.c.save_gaze_calibration())
        self.assertIn("fuente seleccionada cambió",self.c.message)
        self.assertEqual(self.c.profile,original)

    def test_absolute_save_does_not_construct_tracking_calibration(self):
        before = deepcopy(self.c.profile)
        self.install_session(relative=False)
        with patch("application_controller.TrackingCalibration") as relative_type:
            relative_type.from_record.side_effect = AssertionError("ruta relativa")
            self.assertTrue(self.c.save_gaze_calibration())
            relative_type.from_record.assert_not_called()
        self.assertEqual(self.c.profile["tracking_calibrations"],before["tracking_calibrations"])
        self.assertTrue(self.c.profile["absolute_calibration"]["validated"])
        self.factory.assert_not_called()

    def test_activation_missing_iris_or_confirmation_never_creates_backend(self):
        self.c.emergency.clear()
        with self.assertRaises(ValueError): self.c.activate_control(False)
        self.face = replace(self.face,left_gaze_y=None)
        with self.assertRaisesRegex(ValueError,"Iris seleccionado"):
            self.c.activate_control(True)
        conditions = self.c.snapshot(False)["activation_conditions"]
        self.assertTrue(any("Iris" in reason for reason in conditions))
        self.assertTrue(any("confirmación" in reason for reason in conditions))
        self.factory.assert_not_called()

    def test_missing_model_gestures_and_resolution_are_explained(self):
        self.c.profile.pop("tracking_calibrations")
        self.c.profile.pop("tracking_calibration")
        self.c.profile["validation"] = {"passed":False}
        reasons = self.c.snapshot(False)["activation_conditions"]
        self.assertTrue(any("Sin calibración" in reason for reason in reasons))
        self.assertTrue(any("Gestos pendientes" in reason for reason in reasons))
        with self.assertRaises(ValueError): self.c.activate_control(True)
        self.factory.assert_not_called()


if __name__ == "__main__": unittest.main()
