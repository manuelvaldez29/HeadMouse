"""Recorrido absoluto y bancos de perfiles con mouse/cámara simulados."""
import json
import math
import tempfile
import time
import unittest
from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import Mock
import numpy as np

from application_controller import ApplicationController
from config import ROOT, EyeTrackingConfig, load_config, settings_for_save
from control_engine import ControlEngine
from face_data import FaceData
from gaze_mapping import GazeCalibrationSession, GazeModel, TRAIN_TARGETS, VALIDATION_TARGETS, features
from gesture_engine import GestureEngine, GestureEvent
from profile_manager import ProfileManager
from profiles import ProfileStore, gesture_profile, save_gesture_mode, validate_profile
from tracking import create_strategy
from tracking_calibration import TrackingCalibration
from test_core import calibration
from test_eye_tracking import eye_face

from screen_mapping import capture_host_id

CONTEXT = dict(capture_host=capture_host_id(), width=1920, height=1080, dpr=1., screen="synthetic", camera_index=0, frame_width=640, frame_height=480)
SCREEN = {k:CONTEXT[k] for k in ("width", "height", "dpr", "screen")} | dict(monitor_count=1, origin=[0,0])


def target_face(target, timestamp=1000):
    return eye_face(.25+.5*target[0], .25+.5*target[1], timestamp)


def fitted_model():
    return GazeModel.fit([features(target_face(p)) for p in TRAIN_TARGETS], TRAIN_TARGETS, CONTEXT)


def completed_session(relative=False, wrong_validation=False):
    now = [1.]
    session = GazeCalibrationSession(CONTEXT, clock=lambda:now[0], countdown_s=.1,
        settle_s=.1, duration_s=.2, min_samples=5, relative=relative)
    for _ in range(1200):
        snap = session.snapshot()
        if session.state in ("ready", "invalid", "error"):
            break
        now[0] += .05
        target = (.5, .5) if wrong_validation and session.phase == "validation" else snap["target"]
        session.update(target_face(target, round(now[0]*1000)))
    return session


class GazeMappingTests(unittest.TestCase):
    def test_fit_selects_linear_for_linear_data_and_predicts_unseen_targets(self):
        model = fitted_model()
        self.assertEqual(model.degree, 1)
        self.assertFalse(model.record["validated"])
        for point in VALIDATION_TARGETS:
            prediction = model.predict(target_face(point))
            self.assertLess(math.dist(prediction, point), .005)

    def test_quadratic_mapping_is_selected_when_it_improves_held_out_error(self):
        # Distorsión sintética invertible; no afirmación de precisión real.
        rows=[]
        for x,y in TRAIN_TARGETS:
            gx=(-.5+math.sqrt(.25+2*x))/2
            rows.append(features(eye_face(.25+.5*gx, .25+.5*y)))
        model=GazeModel.fit(rows, TRAIN_TARGETS, CONTEXT)
        self.assertEqual(model.degree, 2)

    def test_degenerate_or_insufficient_data_is_rejected(self):
        row=features(target_face((.5,.5)))
        for rows in ([row]*9, [row]*8, [[float("nan")]*10]*9):
            with self.assertRaises(ValueError): GazeModel.fit(rows, TRAIN_TARGETS, CONTEXT)

    def test_abstention_for_monocular_invalid_and_changed_posture(self):
        model=fitted_model()
        self.assertIsNone(model.predict(FaceData(False)))
        self.assertIsNone(model.predict(replace(target_face((.5,.5)),left_gaze_x=None,left_gaze_y=None,gaze_confidence=.5)))
        self.assertIsNone(model.predict(replace(target_face((.5,.5)),head_yaw=30)))
        self.assertIsNone(model.predict(replace(target_face((.5,.5)),nose_x=.9)))
        self.assertIsNone(model.predict(eye_face(.99,.99)))

    def test_roundtrip_and_malformed_models_fail_closed(self):
        model=fitted_model()
        restored=GazeModel(json.loads(json.dumps(model.record)))
        self.assertEqual(restored.predict(target_face((.3,.7))),model.predict(target_face((.3,.7))))
        for changes in (dict(coefficients=[[0,0]]),dict(scale=[0,1]),dict(degree=True),
                        dict(lower=[float("nan")]*10),dict(validated=True),dict(context={})):
            with self.assertRaises(ValueError): GazeModel(model.record|changes)

    def test_nine_point_capture_independent_validation_and_metrics(self):
        session=completed_session()
        self.assertEqual(session.state,"ready",session.message)
        self.assertEqual(len(session.points),9)
        record=session.result()
        self.assertTrue(record["validated"])
        self.assertEqual(len(record["validation"]["points"]),5)
        for point in record["validation"]["points"]:
            self.assertNotIn(tuple(point["target"]),TRAIN_TARGETS)
            self.assertLess(point["error_mean_px"],10)
            self.assertEqual(point["jitter_rms_px"],0)
        GazeModel(record)
        self.assertNotIn("features",json.dumps(record))

    def test_bad_independent_validation_blocks_save_and_can_repeat(self):
        session=completed_session(wrong_validation=True)
        self.assertEqual(session.state,"invalid")
        with self.assertRaises(ValueError):session.result()
        session.repeat(0)
        self.assertEqual(session.state,"countdown")
        self.assertNotIn(0,session.validation_points)

    def test_duplicate_stale_blink_and_loss_do_not_complete_capture(self):
        now=[1.]
        session=GazeCalibrationSession(CONTEXT,clock=lambda:now[0],countdown_s=0,settle_s=0)
        face=target_face((.1,.1))
        for _ in range(60): session.update(face)
        self.assertEqual(len(session.rows),1)
        for face in (FaceData(False,timestamp_ms=1010), replace(target_face((.1,.1),1020),eye_left_ratio=.001)):
            now[0]=face.timestamp_ms/1000
            session.update(face)
            self.assertEqual(len(session.rows),0)
        now[0]=20
        session.update(FaceData(False,timestamp_ms=20000))
        self.assertEqual(session.state,"error")

    def test_relative_ranges_are_measured_and_do_not_need_absolute_validation(self):
        session=completed_session(relative=True)
        record=session.result()
        self.assertTrue(record["ranges_measured"])
        self.assertAlmostEqual(record["left_range"],.2)
        self.assertAlmostEqual(record["down_range"],.2)
        TrackingCalibration.from_record(record)

    def test_unvalidated_model_never_emits_absolute_movement(self):
        strategy=create_strategy("eye_absolute", fitted_model().record)
        self.assertIsNone(strategy.position(target_face((.7,.7))))


class ModePersistenceTests(unittest.TestCase):
    def test_timing_edit_invalidates_only_the_selected_mode(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            manager=ProfileManager(ProfileStore(tmp))
            profile=calibration()
            profile["validation"]={"passed":True}
            config=load_config()
            incoming=asdict(config); incoming["ui"]["tracking_method"]="eye"
            config=settings_for_save(config,incoming)
            profile["settings"]=asdict(config)
            manager.store.save(profile)
            incoming=asdict(config); incoming["gesture"]["blink_hold_ms"]+=50
            result=manager.save_settings(profile,asdict(settings_for_save(config,incoming)))
            self.assertTrue(gesture_profile(result,"nose")["validation"]["passed"])
            self.assertTrue(gesture_profile(result,"eye_absolute")["validation"]["passed"])
            self.assertFalse(gesture_profile(result,"eye")["validation"]["passed"])

    def test_three_modes_preserve_independent_actions_and_parameters(self):
        config=load_config()
        nasal=asdict(config)
        nasal["gesture"]["sensitivity"]=110
        config=settings_for_save(config,nasal)
        switch=asdict(config); switch["ui"]["tracking_method"]="eye"
        config=settings_for_save(config,switch)
        eye=asdict(config)
        eye["actions"]["bindings"]["LEFT_WINK"]="DOUBLE_CLICK"
        eye["gesture"]["sensitivity"]=45
        config=settings_for_save(config,eye)
        switch=asdict(config); switch["ui"]["tracking_method"]="eye_absolute"
        config=settings_for_save(config,switch)
        self.assertEqual(config.actions.bindings["LEFT_WINK"],"LEFT_CLICK")
        absolute=asdict(config); absolute["absolute"]["max_step_px"]=12
        config=settings_for_save(config,absolute)
        switch=asdict(config); switch["ui"]["tracking_method"]="nose"
        config=settings_for_save(config,switch)
        self.assertEqual(config.gesture.sensitivity,110)
        self.assertEqual(config.actions.bindings["LEFT_WINK"],"LEFT_CLICK")
        switch=asdict(config); switch["ui"]["tracking_method"]="eye"
        config=settings_for_save(config,switch)
        self.assertEqual(config.gesture.sensitivity,45)
        self.assertEqual(config.actions.bindings["LEFT_WINK"],"DOUBLE_CLICK")
        self.assertEqual(config.methods["eye_absolute"]["absolute"]["max_step_px"],12)

    def test_gesture_calibration_is_independent_and_old_profile_unchanged(self):
        original=calibration()
        saved=deepcopy(original)
        candidate=deepcopy(original)
        candidate["validation"]={"passed":True}
        candidate["neutral_nose_x"]=.6
        profile=save_gesture_mode(original,candidate,"eye")
        validate_profile(profile)
        self.assertEqual(original,saved)
        self.assertEqual(gesture_profile(profile,"eye")["neutral_nose_x"],.6)
        self.assertEqual(gesture_profile(profile,"nose")["neutral_nose_x"],.5)
        self.assertNotIn("validation",gesture_profile(profile,"eye_absolute"))

    def test_model_and_banks_roundtrip_without_rewriting_legacy_input(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            store=ProfileStore(tmp)
            original=calibration()
            store.save(original)
            before=store.path("julian").read_bytes()
            validate_profile(store.load("julian"))
            self.assertEqual(store.path("julian").read_bytes(),before)
            profile=store.load("julian")
            profile["absolute_calibration"]=completed_session().result()
            store.save(profile)
            self.assertTrue(store.load("julian")["absolute_calibration"]["validated"])


class AbsoluteControllerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.manager=ProfileManager(ProfileStore(self.root/"profiles"))
        profile=calibration()
        profile["validation"]={"passed":True}
        profile["settings"]={"ui":{"tracking_method":"eye_absolute"}}
        profile["absolute_calibration"]=completed_session().result()
        self.manager.store.save(profile)
        self.vision=Mock(error=None)
        self.vision.get_frame.return_value=np.zeros((480,640,3),dtype=np.uint8)
        self.vision.get_face_data.side_effect=lambda:target_face((.7,.3),int(time.monotonic()*1000))
        self.vision.get_fps.return_value=30
        self.backend=Mock()
        self.backend.size.return_value=(1920,1080)
        self.backend.position.return_value=(960,540)
        self.factory=Mock(return_value=self.backend)
        self.controller=ApplicationController(self.manager,Mock(return_value=self.vision),self.factory,self.root)
        self.addCleanup(self.controller.shutdown)

    def test_safe_diagnostic_predictions_never_create_backend(self):
        self.controller.start_diagnostic()
        self.controller.step()
        prediction=self.controller.snapshot()["diagnostic"]["tracking"]["prediction"]
        self.assertIsNotNone(prediction)
        self.factory.assert_not_called()

    def test_activation_checks_screen_and_backend_then_limits_absolute_move(self):
        c=self.controller
        c.emergency.clear()
        c.activate_control(True,SCREEN)
        c.step()
        self.backend.moveTo.assert_called_once()
        x,y=self.backend.moveTo.call_args.args
        self.assertLessEqual(math.dist((x,y),(960,540)),36)
        self.backend.click.assert_not_called()
        c.emergency_stop()
        c.step()
        self.assertIsNone(c.control)

    def test_dpi_multimonitor_camera_mismatch_prevent_backend_creation(self):
        for screen in (SCREEN|dict(dpr=1.5),SCREEN|dict(monitor_count=2),SCREEN|dict(width=1280),SCREEN|dict(origin=[-1920,0])):
            self.controller.emergency.clear()
            with self.assertRaises(ValueError): self.controller.activate_control(True,screen)
            self.factory.assert_not_called()

    def test_calibration_cancels_control_and_preserves_saved_model_on_cancel(self):
        c=self.controller
        original=deepcopy(c.profile["absolute_calibration"])
        c.start_gaze_calibration(SCREEN)
        c.emergency.clear()
        with self.assertRaises(ValueError):c.activate_control(True,SCREEN)
        self.factory.assert_not_called()
        c.cancel_gaze_calibration()
        self.assertEqual(c.profile["absolute_calibration"],original)

    def test_missing_absolute_model_only_blocks_activation(self):
        self.controller.profile.pop("absolute_calibration")
        self.controller.start_diagnostic()
        self.controller.step()
        with self.assertRaises(ValueError):self.controller._require_tracking_calibration()
        self.factory.assert_not_called()

    def test_draft_profile_allows_raw_eye_diagnostic_without_backend(self):
        c=self.controller
        c.create_profile("Diagnóstico sin calibrar")
        c.start_diagnostic()
        c.step()
        self.assertTrue(c.snapshot()["detected"])
        self.assertIsNone(c.gesture)
        self.factory.assert_not_called()

    def test_failed_attempt_export_preserves_profile_and_never_creates_backend(self):
        c=self.controller
        before=deepcopy(c.profile)
        c.start_gaze_calibration(SCREEN)
        c.gaze_calibration=completed_session(wrong_validation=True)
        c.export_gaze_attempt()
        files=list((self.root/"calibration").glob("*.jsonl"))
        self.assertEqual(len(files),1)
        record=json.loads(files[0].read_text())
        self.assertFalse(record["approved_calibration"])
        self.assertFalse(record["authorizes_control"])
        self.assertEqual(before,c.profile)
        self.factory.assert_not_called()

    def test_conventional_mouse_experiment_needs_no_camera_or_control(self):
        c=self.controller
        notes={"lighting":"luz difusa", "distance_cm":60}
        c.start_experiment(mode="real",source="mouse",conditions=notes)
        notes["distance_cm"]=100
        self.assertIsNone(c.vision)
        self.assertIsNone(c.control)
        self.factory.assert_not_called()
        x,y=c.experiment.targets[0]
        c.experiment_input(x,y,click=True,absolute=True)
        record=c.experiment.results[0]
        self.assertTrue(record["completed"])
        self.assertEqual(record["conditions"]["operator"]["distance_cm"],60)
        self.assertIsNone(record["tracking_method"])
        self.assertIsNone(record["processing_ms_mean"])


class OcularSafetyTests(unittest.TestCase):
    def test_wink_freezes_movement_but_preserves_click_and_recovery_guard(self):
        now=[1.]
        engine=GestureEngine(None,calibration=calibration(),
            strategy=create_strategy("eye",TrackingCalibration().record(),EyeTrackingConfig(smoothing_alpha=0)),clock=lambda:now[0])
        events=[]
        for stamp in (1000,1100):
            now[0]=stamp/1000
            events=engine.update(replace(eye_face(.7,.5,stamp),eye_left_ratio=.01))
            self.assertFalse(any(e.type=="CURSOR_MOVE" for e in events))
        self.assertTrue(any(e.type=="LEFT_CLICK" for e in events))
        now[0]=1.2
        self.assertFalse(any(e.type=="CURSOR_MOVE" for e in engine.update(eye_face(.7,.5,1200))))
        now[0]=1.3
        self.assertFalse(any(e.type=="CURSOR_MOVE" for e in engine.update(eye_face(.7,.5,1300))))
        now[0]=1.35
        self.assertFalse(any(e.type=="CURSOR_MOVE" for e in engine.update(eye_face(.7,.5,1350))))
        now[0]=1.4
        self.assertTrue(any(e.type=="CURSOR_MOVE" for e in engine.update(eye_face(.7,.5,1400))))

    def test_fractional_deltas_survive_duplicate_ticks_and_reset_at_neutral(self):
        stamp=int(time.monotonic()*1000)-20
        vision=Mock()
        vision.get_face_data.return_value=eye_face(.7,.5,stamp)
        gesture=Mock(strategy=Mock(name="strategy"))
        gesture.strategy.name="eye"
        gesture.config=load_config().gesture
        gesture.update.side_effect=[[GestureEvent("CURSOR_MOVE",dx=.4)],[],[GestureEvent("CURSOR_MOVE",dx=.4)],[],[GestureEvent("CURSOR_MOVE",dx=.4)]]
        backend=Mock(); backend.size.return_value=(1920,1080)
        control=ControlEngine(vision,gesture,backend=backend)
        control.toggle_pause()
        for i in range(5):
            vision.get_face_data.return_value=eye_face(.7,.5,stamp+i//2)
            control._tick()
        backend.moveRel.assert_called_once_with(1,0,_pause=False)
        gesture.update.side_effect=None; gesture.update.return_value=[]
        vision.get_face_data.return_value=eye_face(.5,.5,stamp+3)
        control._tick()
        self.assertEqual(control._fraction,[0,0])

    def test_monocular_transition_stops_instead_of_jumping(self):
        engine=GestureEngine(None,calibration=calibration(),strategy=create_strategy("eye",TrackingCalibration().record()),clock=lambda:1.)
        mono=replace(eye_face(.7,.5),left_gaze_x=None,left_gaze_y=None,gaze_confidence=.5)
        self.assertFalse(any(e.type=="CURSOR_MOVE" for e in engine.update(mono)))
        self.assertIn("ambos iris",engine.tracking_diagnostic()["block_reason"])


if __name__ == "__main__": unittest.main()
