"""Fuentes oculares explícitas. No cámara, PyAutoGUI ni entradas del SO."""
import json
import math
import tempfile
import unittest
from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import Mock, patch
import numpy as np

from config import ROOT, EyeTrackingConfig, load_config
from gaze_source import eye_coordinates, gaze_position, channels, iris_markers
from gaze_mapping import features, GazeCalibrationSession, GazeModel, TRAIN_TARGETS, VALIDATION_TARGETS
from tracking_calibration import TrackingCalibration, EyeTrackingCalibrationSession
from tracking import create_strategy
from gesture_engine import GestureEngine
from ocular_profiles import calibration_for, with_calibration
from profiles import ProfileStore, validate_profile
from profile_manager import ProfileManager
from application_controller import ApplicationController
from test_core import calibration
from test_eye_tracking import eye_face
from test_gaze_mapping import CONTEXT, SCREEN


def source_face(source, x=.5, y=.5, stamp=1000, missing_other=True):
    face=eye_face(x,y,stamp)
    if source != "both" and missing_other:
        other="right" if source=="left" else "left"
        face=replace(face,iris_points=(face.iris_points[0 if source=="left" else 1],),
            **{f"{other}_gaze_x":None,f"{other}_gaze_y":None,"gaze_confidence":.5})
    return face


def completed_source_session(source, relative=False):
    now=[1.]
    session=GazeCalibrationSession(CONTEXT,clock=lambda:now[0],countdown_s=.1,settle_s=.1,
        duration_s=.2,min_samples=5,eye_source=source,relative=relative)
    for _ in range(1500):
        if session.state in ("ready","invalid","error"):
            break
        x,y=session.snapshot()["target"]
        now[0]+=.05
        session.update(source_face(source,.25+.5*x,.25+.5*y,round(now[0]*1000)))
    if session.state!="ready":
        raise AssertionError(session.message)
    return session


class SourceContractTests(unittest.TestCase):
    def test_default_and_unknown_source(self):
        self.assertEqual(load_config().ui.eye_source,"both")
        for value in ("", "auto", None, True, 1):
            with self.assertRaises(ValueError):load_config(overrides={"ui":{"eye_source":value}})

    def test_anatomical_channel_mapping_accounts_for_input_mirror(self):
        face=replace(eye_face(),left_gaze_x=.3,right_gaze_x=.7)
        self.assertEqual(channels("left",True),("left",))
        self.assertAlmostEqual(gaze_position(face,"left")[0],.3)
        self.assertAlmostEqual(gaze_position(replace(face,gaze_mirrored=False),"left")[0],.7)
        self.assertAlmostEqual(gaze_position(replace(face,gaze_mirrored=False),"right")[0],.3)
        self.assertEqual([m[0] for m in iris_markers(face,"left")],["left","right"])

    def test_binocular_average_and_no_silent_fallback(self):
        face=replace(eye_face(),left_gaze_x=.2,right_gaze_x=.8,gaze_x=.1)
        self.assertAlmostEqual(gaze_position(face,"both")[0],.5)
        self.assertIsNone(gaze_position(source_face("left"),"both"))
        self.assertIsNone(gaze_position(source_face("right"),"both"))

    def test_unselected_invalid_or_absent_iris_is_irrelevant(self):
        for source in ("left","right"):
            face=source_face(source,.65,.35)
            self.assertAlmostEqual(gaze_position(face,source)[0],.65)
            other="right" if source=="left" else "left"
            corrupt=replace(face,**{f"{other}_gaze_x":float("nan"),f"{other}_gaze_y":float("nan")})
            self.assertEqual(gaze_position(face,source),gaze_position(corrupt,source))
            self.assertEqual(features(corrupt,source).shape,(8,))
            self.assertIsNone(eye_coordinates(corrupt,"both"))

    def test_selected_missing_and_wrong_calibration_are_rejected(self):
        for source in ("left","right"):
            other="right" if source=="left" else "left"
            strategy=create_strategy("eye",TrackingCalibration(eye_source=source).record(),eye_source=source)
            self.assertIsNone(strategy.position(source_face(other)))
            self.assertIsNone(create_strategy("eye",TrackingCalibration().record(),eye_source=source).position(eye_face()))


class SourceCalibrationTests(unittest.TestCase):
    def test_neutral_accepts_only_selected_source(self):
        for source in ("both","left","right"):
            now=[1.]
            session=EyeTrackingCalibrationSession(clock=lambda:now[0],eye_source=source)
            for _ in range(80):
                now[0]+=.033
                session.update(source_face(source,.54,.46,int(now[0]*1000)))
            self.assertTrue(session.snapshot()["can_save"],source)
            self.assertEqual(session.result()["eye_source"],source)
            self.assertAlmostEqual(session.result()["neutral_x"],.54)

    def test_missing_selected_never_completes_neutral(self):
        for source in ("left","right"):
            now=[1.]
            session=EyeTrackingCalibrationSession(clock=lambda:now[0],eye_source=source)
            other="right" if source=="left" else "left"
            for _ in range(80):
                now[0]+=.033
                session.update(source_face(other,stamp=int(now[0]*1000)))
            self.assertFalse(session.snapshot()["can_save"])

    def test_ranges_independent_of_unselected_eye(self):
        for source in ("both","left","right"):
            record=completed_source_session(source,relative=True).result()
            self.assertEqual(record["eye_source"],source)
            self.assertTrue(record["ranges_measured"])
            self.assertAlmostEqual(record["left_range"],.2)
            self.assertEqual(record["camera_context"]["frame_width"],640)

    def test_all_sources_complete_nine_points_and_five_independent_targets(self):
        for source in ("both","left","right"):
            with self.subTest(source=source):
                session=completed_source_session(source)
                self.assertEqual(len(session.points),9)
                self.assertEqual(len(session.validation_points),5)
                record=session.result()
                model=GazeModel(json.loads(json.dumps(record)))
                self.assertEqual(model.feature_count,10 if source=="both" else 8)
                self.assertEqual(record["eye_source"],source)
                for target in VALIDATION_TARGETS:
                    face=source_face(source,.25+.5*target[0],.25+.5*target[1])
                    self.assertLess(math.dist(model.predict(face),target),.005)
                for wrong in ({"eye_source":"left" if source=="both" else "both"}, {"schema_version":1,"eye_source":"left"}):
                    with self.assertRaises(ValueError):GazeModel(record|wrong)

    def test_source_specific_strategy_rejects_other_models(self):
        record=completed_source_session("both").result()
        for source in ("left","right"):
            strategy=create_strategy("eye_absolute",record,eye_source=source)
            self.assertIsNone(strategy.position(eye_face()))

    def test_historical_models_are_read_only_and_binocular(self):
        record=completed_source_session("both").result()
        record["schema_version"]=1
        record.pop("eye_source")
        original=deepcopy(record)
        model=GazeModel(record)
        self.assertEqual(model.eye_source,"both")
        self.assertEqual(record,original)
        self.assertIsNone(model.predict(source_face("left")))

    def test_persisting_monocular_keeps_both_models_and_other_source(self):
        profile=calibration()
        profile["tracking_calibration"]=TrackingCalibration().record()
        profile["absolute_calibration"]=completed_source_session("both").result()
        original=deepcopy(profile)
        for source in ("left","right"):
            profile=with_calibration(profile,completed_source_session(source).result())
            profile=with_calibration(profile,completed_source_session(source,relative=True).result())
        validate_profile(profile)
        self.assertEqual(profile["absolute_calibration"],original["absolute_calibration"])
        self.assertEqual(profile["tracking_calibration"],original["tracking_calibration"])
        for source in ("both","left","right"):
            self.assertEqual(calibration_for(profile,"eye_absolute",source).get("eye_source","both"),source)
            self.assertEqual(calibration_for(profile,"eye",source).get("eye_source","both"),source)
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            store=ProfileStore(tmp)
            store.save(profile)
            self.assertEqual(store.load("julian")["absolute_calibrations"],profile["absolute_calibrations"])

    def test_bank_rejects_source_mismatch_and_legacy_never_fills_mono(self):
        profile=calibration()|{"tracking_calibration":TrackingCalibration().record()}
        self.assertIsNone(calibration_for(profile,"eye","left"))
        profile["tracking_calibrations"]={"left":TrackingCalibration().record()}
        with self.assertRaises(ValueError):validate_profile(profile)


class SourceCursorTests(unittest.TestCase):
    def engine(self,method,source,now):
        record=(TrackingCalibration(eye_source=source).record() if method=="eye" else completed_source_session(source).result())
        return GestureEngine(None,calibration=calibration(),strategy=create_strategy(method,record,eye_source=source),clock=lambda:now[0])

    def test_both_methods_move_with_other_iris_absent_and_stop_when_selected_lost(self):
        for method in ("eye","eye_absolute"):
            for source in ("left","right"):
                now=[1.]
                engine=self.engine(method,source,now)
                self.assertTrue(any(e.type.startswith("CURSOR_") for e in engine.update(source_face(source,.7,.5))))
                now[0]=1.05
                other="right" if source=="left" else "left"
                self.assertFalse(any(e.type.startswith("CURSOR_") for e in engine.update(source_face(other,.7,.5,1050))))
                self.assertIsNone(getattr(engine,"_absolute_smooth",None))
                for stamp in (1100,1150):
                    now[0]=stamp/1000
                    self.assertFalse(any(e.type.startswith("CURSOR_") for e in engine.update(source_face(source,.7,.5,stamp))))
                now[0]=1.2
                self.assertTrue(any(e.type.startswith("CURSOR_") for e in engine.update(source_face(source,.7,.5,1200))))

    def test_unstable_recovery_remains_blocked_then_resumes(self):
        now=[1.]
        engine=self.engine("eye","left",now)
        engine.update(source_face("right"))
        for stamp,x in ((1050,.3),(1100,.7),(1150,.3),(1200,.7),(1250,.3)):
            now[0]=stamp/1000
            self.assertFalse(any(e.type=="CURSOR_MOVE" for e in engine.update(source_face("left",x,.5,stamp))))
        for stamp in (1300,1350,1400,1450):
            now[0]=stamp/1000
            events=engine.update(source_face("left",.7,.5,stamp))
        self.assertTrue(any(e.type=="CURSOR_MOVE" for e in events))


class SourceControllerTests(unittest.TestCase):
    engine=SourceCursorTests.engine
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.store=ProfileStore(self.root/"profiles")
        self.profile=calibration()|{"validation":{"passed":True}}
        for source in ("both","left","right"):
            self.profile=with_calibration(self.profile,completed_source_session(source).result())
            self.profile=with_calibration(self.profile,completed_source_session(source,relative=True).result())
        self.store.save(self.profile)
        self.now=1.
        self.face=source_face("both")
        self.vision=Mock(error=None)
        self.vision.get_frame.return_value=np.zeros((480,640,3),dtype=np.uint8)
        self.vision.get_face_data.side_effect=lambda:self.face
        self.vision.get_fps.return_value=30
        self.vision._frame_size=(640,480)
        self.backend=Mock()
        self.backend.size.return_value=(1920,1080)
        self.backend.position.return_value=(960,540)
        self.backend_factory=Mock(return_value=self.backend)
        self.controller=ApplicationController(ProfileManager(self.store),Mock(return_value=self.vision),
            self.backend_factory,self.root,clock=lambda:self.now)
        self.addCleanup(self.controller.shutdown)

    def select(self,method,source):
        config=asdict(self.controller.config)
        config["ui"].update(tracking_method=method,eye_source=source)
        self.controller.save_settings(config)
        self.face=source_face(source,.7,.5,int(self.now*1000))

    def test_switching_sources_loads_corresponding_calibration_and_resets_filters(self):
        for method in ("eye","eye_absolute"):
            for source in ("both","left","right","both"):
                self.select(method,source)
                c=self.controller
                self.assertIsNone(c.vision)
                c.start_diagnostic()
                c.step()
                snap=c.snapshot(False)
                self.assertEqual(c.gesture.strategy.eye_source,source)
                self.assertTrue(snap["tracking_calibrated"])
                self.assertIsNotNone(snap["used_gaze"])
                self.assertEqual(snap["profile"]["tracking_calibration"]["eye_source"],source)
                self.assertEqual(snap["profile"]["absolute_calibration"]["eye_source"],source)
                self.assertEqual(c.profile["tracking_calibration"]["eye_source"],"both")
        self.backend_factory.assert_not_called()

    def test_absolute_monocular_control_uses_move_to_only_with_confirmation(self):
        for source in ("left","right"):
            self.select("eye_absolute",source)
            c=self.controller
            with self.assertRaises(ValueError):c.activate_control(False,SCREEN)
            c.emergency.clear()
            c.activate_control(True,SCREEN)
            with patch("control_engine.time.monotonic",return_value=self.now):
                c.step()
            self.backend.moveTo.assert_called()
            self.backend.click.assert_not_called()
            c.stop_control()

    def test_missing_source_blocks_activation_but_keeps_raw_diagnostic(self):
        self.controller.profile.pop("absolute_calibrations")
        self.select("eye_absolute","left")
        c=self.controller
        c.start_diagnostic()
        c.step()
        self.assertFalse(c.snapshot(False)["tracking_calibrated"])
        with self.assertRaises(ValueError):c._require_tracking_calibration()
        self.backend_factory.assert_not_called()

    def test_neutral_save_cannot_overwrite_binocular_or_other_source(self):
        self.select("eye","left")
        c=self.controller
        before=deepcopy(c.profile)
        c.start_eye_calibration()
        for _ in range(80):
            self.now+=.033
            self.face=source_face("left",.54,.46,int(self.now*1000))
            c.step()
        c.save_eye_calibration()
        self.assertAlmostEqual(calibration_for(c.profile,"eye","left")["neutral_x"],.54)
        self.assertEqual(calibration_for(c.profile,"eye","right"),calibration_for(before,"eye","right"))
        self.assertEqual(c.profile["tracking_calibration"],before["tracking_calibration"])
        self.assertEqual(c.profile["absolute_calibrations"],before["absolute_calibrations"])
        self.backend_factory.assert_not_called()

    def test_relative_camera_mismatch_blocks_before_mouse_backend(self):
        self.select("eye","left")
        self.vision.get_frame.return_value=np.zeros((240,320,3),dtype='uint8')
        c=self.controller
        c.emergency.clear()
        with self.assertRaisesRegex(ValueError,"resolución"):c.activate_control(True)
        self.backend_factory.assert_not_called()

    def test_winks_preserve_actions_without_jumps_for_any_source(self):
        for method in ("eye","eye_absolute"):
            for source in ("both","left","right"):
                for wink in ("left","right"):
                    now=[1.]
                    engine=self.engine(method,source,now)
                    for stamp in (1000,1100):
                        now[0]=stamp/1000
                        face=replace(source_face(source,.7,.5,stamp),**{f"eye_{wink}_ratio":.01})
                        events=engine.update(face)
                        self.assertFalse(any(e.type.startswith("CURSOR_") for e in events))
                    self.assertTrue(any(e.type==("LEFT_CLICK" if wink=="left" else "RIGHT_CLICK") for e in events))

    def test_unselected_sustained_closure_does_not_require_its_iris(self):
        now=[1.]
        engine=self.engine("eye","left",now)
        events=[]
        for stamp in range(1000,1800,50):
            now[0]=stamp/1000
            events=engine.update(replace(source_face("left",.7,.5,stamp),eye_right_ratio=.01))
        self.assertTrue(any(e.type=="CURSOR_MOVE" for e in events))


if __name__=="__main__":unittest.main()
