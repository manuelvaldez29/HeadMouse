"""Tracking ocular sintético: sin cámara, persona ni entrada real al sistema."""
import math
import tempfile
import unittest
from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from application_controller import ApplicationController
from config import ROOT, EyeTrackingConfig, GestureConfig, load_config
from control_engine import ControlEngine
from eye_geometry import EYES, extract_gaze
from face_data import FaceData
from gesture_engine import GestureEngine
from profile_manager import ProfileManager
from profiles import ProfileStore, validate_profile
from tracking import EyeGazeTrackingStrategy, NoseTrackingStrategy, TrackingStrategy, create_strategy
from tracking_calibration import EyeTrackingCalibrationSession, TrackingCalibration
from experiment_engine import ExperimentEngine, JitterMeasurement, ResultStore
from test_core import calibration


def eye_landmarks(x=.5, y=.5, scale=1., tx=0., ty=0., roll=0., mirror=False):
    """Ojos sintéticos con aspecto 640x480; iris dentro del paralelogramo ocular."""
    points=[SimpleNamespace(x=.5,y=.5,z=0.) for _ in range(478)]
    coords={234:(.2,.55),454:(.8,.55),1:(.5,.6)}
    for side,(a,b,upper,lower,center,ring) in EYES.items():
        cx=.35 if side=="left" else .65
        coords.update({a:(cx-.08,.4), b:(cx+.08,.4), upper:(cx,.37), lower:(cx,.43),
                       center:(cx-.08+.16*x,.37+.06*y)})
        for k,index in enumerate(ring):
            angle=k*math.pi/2
            coords[index]=(coords[center][0]+.01*math.cos(angle),coords[center][1]+.01*math.sin(angle))
    for i,(px,py) in coords.items():
        a,b=(px-.5)*640,(py-.5)*480
        c,s=math.cos(roll),math.sin(roll)
        px=.5+scale*(a*c-b*s)/640+tx
        py=.5+scale*(a*s+b*c)/480+ty
        points[i]=SimpleNamespace(x=1-px if mirror else px,y=py,z=0.)
    return points


def eye_face(x=.5, y=.5, timestamp_ms=1000, **kwargs):
    return FaceData(True,timestamp_ms=timestamp_ms,**extract_gaze(eye_landmarks(x,y),640,480),**kwargs)


class EyeGeometryTests(unittest.TestCase):
    def test_neutral_and_all_directions(self):
        for x,y in ((.5,.5),(.2,.5),(.8,.5),(.5,.2),(.5,.8)):
            with self.subTest(x=x,y=y):
                face=eye_face(x,y)
                self.assertTrue(face.gaze_available)
                self.assertAlmostEqual(face.gaze_x,x)
                self.assertAlmostEqual(face.gaze_y,y)
                self.assertEqual(face.gaze_confidence,1)
                self.assertEqual(len(face.iris_points),2)

    def test_translation_distance_and_roll_invariance(self):
        for scale,tx,ty,roll in ((.6,.1,.1,0),(1.2,-.05,0,0),(1.,0,0,.2)):
            gaze=extract_gaze(eye_landmarks(.65,.35,scale,tx,ty,roll),640,480)
            self.assertAlmostEqual(gaze["gaze_x"],.65)
            self.assertAlmostEqual(gaze["gaze_y"],.35)

    def test_horizontal_mirror_contract(self):
        normal=extract_gaze(eye_landmarks(.7,.4),640,480,mirrored=False)
        mirrored=extract_gaze(eye_landmarks(.7,.4,mirror=True),640,480,mirrored=True)
        self.assertAlmostEqual(normal["gaze_x"],mirrored["gaze_x"])
        self.assertAlmostEqual(normal["gaze_y"],mirrored["gaze_y"])

    def test_single_eye_and_no_eyes(self):
        for missing in ("left","right"):
            points=eye_landmarks(.7,.3)
            points[EYES[missing][4]]=SimpleNamespace(x=float("nan"),y=.4)
            face=FaceData(True,timestamp_ms=1,**extract_gaze(points,640,480))
            self.assertTrue(face.gaze_available)
            self.assertEqual(face.gaze_confidence,.5)
            self.assertIsNone(getattr(face,f"{missing}_gaze_x"))
            self.assertAlmostEqual(face.gaze_x,.7)
        self.assertEqual(extract_gaze([],640,480)["gaze_confidence"],0)

    def test_bad_landmarks_closed_eye_and_out_of_range_iris(self):
        for bad in (None,float("nan"),float("inf"),2.):
            points=eye_landmarks()
            for spec in EYES.values(): points[spec[4]]=SimpleNamespace(x=bad,y=.4)
            self.assertIsNone(extract_gaze(points,640,480)["gaze_x"])
        points=eye_landmarks()
        for spec in EYES.values(): points[spec[3]]=points[spec[2]]
        self.assertIsNone(extract_gaze(points,640,480)["gaze_x"])
        for size in ((0,480),(640,float("nan"))):
            self.assertEqual(extract_gaze(points,*size)["gaze_confidence"],0)
        self.assertIsNone(extract_gaze(eye_landmarks(1.5,.5),640,480)["gaze_x"])

    def test_invalid_optional_gaze_does_not_break_nose_data(self):
        face=eye_face()
        for field,value in (("gaze_x",float("nan")),("gaze_y",float("inf")),
                            ("gaze_confidence",True),("left_gaze_y",None)):
            bad=replace(face,**{field:value})
            self.assertFalse(bad.gaze_available)
            self.assertTrue(bad.valid())
        self.assertFalse(replace(face,detected=False).gaze_available)
        self.assertFalse(replace(face,nose_x=float("nan")).gaze_available)

    def test_vision_extracts_iris_without_native_camera(self):
        # Reutiliza la carga aislada de VisionEngine con dependencias nativas mock.
        import test_safety
        fixture=test_safety.VisionLifecycleTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        engine=fixture.engine()
        engine._frame_size=(640,480)
        fixture.module.np.isfinite.side_effect=math.isfinite
        fixture.module.np.mean.side_effect=lambda values:sum(values)/len(values)
        result=SimpleNamespace(face_landmarks=[eye_landmarks(.65,.35)],face_blendshapes=[])
        face=engine._extract(result,1000)
        self.assertTrue(face.gaze_available)
        self.assertAlmostEqual(face.gaze_x,.65)
        result.face_landmarks[0][468].x=float("nan")
        mono=engine._extract(result,1001)
        self.assertTrue(mono.detected)
        self.assertEqual(mono.gaze_confidence,.5)
        result.face_landmarks[0]=result.face_landmarks[0][:468]
        legacy=engine._extract(result,1002)
        self.assertTrue(legacy.detected)
        self.assertFalse(legacy.gaze_available)


class EyeStrategyTests(unittest.TestCase):
    def setUp(self):
        self.now=1.
        self.strategy=EyeGazeTrackingStrategy(TrackingCalibration(),EyeTrackingConfig(smoothing_alpha=0))
        self.engine=GestureEngine(None,calibration=calibration(),strategy=self.strategy,clock=lambda:self.now)

    def move(self,x,y):
        self.now+=.05
        events=self.engine.update(eye_face(x,y,int(self.now*1000)))
        return next((e for e in events if e.type=="CURSOR_MOVE"),None)

    def test_contract_default_nose_and_eye(self):
        self.assertIsInstance(self.strategy,TrackingStrategy)
        self.assertIsInstance(create_strategy(),NoseTrackingStrategy)
        self.assertIsInstance(create_strategy("eye"),EyeGazeTrackingStrategy)
        self.assertEqual(create_strategy().position(FaceData(True,nose_x=.23,nose_y=.71)),(.23,.71))
        self.assertEqual(load_config().ui.tracking_method,"nose")

    def test_joystick_neutral_deadzone_and_direction(self):
        self.assertIsNone(self.move(.5,.5))
        self.assertIsNone(self.move(.51,.49))
        for x,y,axis,sign in ((.3,.5,"dx",-1),(.7,.5,"dx",1),(.5,.3,"dy",-1),(.5,.7,"dy",1)):
            event=self.move(x,y)
            self.assertGreater(sign*getattr(event,axis),0)
            self.assertLessEqual(max(abs(event.dx),abs(event.dy)),self.strategy.config.max_delta)

    def test_speed_increases_and_stays_bounded(self):
        small=self.move(.57,.5)
        large=self.move(.9,.5)
        self.assertGreater(large.dx,small.dx)
        self.assertLessEqual(large.dx,20)

    def test_smoothing_and_invalid_signal_immediate_stop(self):
        self.strategy.config.smoothing_alpha=.5
        self.move(.7,.5)
        first=self.engine._eye_smooth_x
        self.move(.7,.5)
        self.assertGreater(self.engine._eye_smooth_x,first)
        self.now+=.05
        events=self.engine.update(FaceData(True,timestamp_ms=int(self.now*1000)))
        self.assertFalse(any(e.type=="CURSOR_MOVE" for e in events))
        self.assertEqual(self.engine._eye_smooth_x,0)
        self.assertIsNone(self.move(.5,.5))

    def test_missing_calibration_invalid_face_stale_duplicate(self):
        self.assertIsNone(EyeGazeTrackingStrategy().position(eye_face(.7,.5)))
        for face in (FaceData(False),eye_face(.7,.5,1),replace(eye_face(),nose_x=float("nan"))):
            self.assertEqual(self.engine.update(face),[])
        self.move(.7,.5)
        self.assertEqual(self.engine.update(eye_face(.7,.5,int(self.now*1000))),[])

    def test_single_eye_strategy(self):
        for side in ("left","right"):
            face=eye_face(.7,.5)
            face=replace(face,**{f"{side}_gaze_x":None,f"{side}_gaze_y":None,"gaze_confidence":.5})
            self.assertIsNone(self.strategy.position(face))  # binocular nunca hace fallback
            selected = "right" if side == "left" else "left"
            strategy=EyeGazeTrackingStrategy(TrackingCalibration(eye_source=selected),eye_source=selected)
            self.assertGreater(strategy.position(face)[0],0)

    def test_eye_recenter_never_modifies_gesture_thresholds_or_neutral(self):
        old=deepcopy(self.engine.diagnostic())
        self.assertFalse(self.engine.recenter(1000)["ok"])
        self.assertEqual(self.engine.diagnostic(),old)

    def test_eye_motion_does_not_gate_brows_when_head_is_still(self):
        self.move(.8,.5)
        self.assertTrue(self.engine.head_still)
        self.now+=.05
        self.engine.update(eye_face(.8,.5,int(self.now*1000),nose_x=.8))
        self.assertFalse(self.engine.head_still)

    def test_nose_cursor_formula_unchanged(self):
        engine=GestureEngine(None,calibration=calibration(),config=GestureConfig(smoothing_alpha=.5),clock=lambda:1)
        ev=engine.update(FaceData(True,timestamp_ms=1000,nose_x=.7))[0]
        d=.5*.5+.5*.7-.5-.03
        self.assertAlmostEqual(ev.dx,d*80+d*d*600)


class EyeCalibrationTests(unittest.TestCase):
    def setUp(self): self.now=1.

    def session(self): return EyeTrackingCalibrationSession(clock=lambda:self.now)

    def feed(self,session,n=70,step=33,x=.52,y=.48):
        for _ in range(n):
            self.now+=step/1000
            session.update(eye_face(x,y,int(self.now*1000)))

    def test_neutral_capture_30fps_and_result(self):
        s=self.session()
        self.feed(s)
        self.assertEqual(s.state,"ready")
        self.assertAlmostEqual(s.result()["neutral_x"],.52)
        self.assertFalse(s.result()["ranges_measured"])
        self.assertNotIn("samples",s.result())

    def test_low_fps_can_finish_with_enough_samples(self):
        for step in (100,200):
            with self.subTest(step=step):
                s=self.session()
                self.feed(s,n=11,step=step)
                self.assertLess(s.snapshot()["progress"],1)
                self.feed(s,n=39,step=step)
                self.assertEqual(s.state,"ready")

    def test_duplicate_loss_unstable_timeout_and_no_early_save(self):
        s=self.session()
        with self.assertRaises(ValueError): s.result()
        face=eye_face()
        for _ in range(50): s.update(face)
        self.assertEqual(len(s.samples),1)
        s.update(FaceData(False))
        self.assertEqual(len(s.samples),0)
        for k in range(80): self.feed(s,n=1,x=.3 if k%2 else .7)
        self.assertEqual(s.state,"capturing")
        self.now+=21
        s.update(FaceData(False))
        self.assertEqual(s.state,"error")

    def test_tracking_record_validation(self):
        for record in ({},{"method":"nose"},TrackingCalibration().record()|{"neutral_x":float("nan")},
                       TrackingCalibration().record()|{"left_range":0},
                       TrackingCalibration().record()|{"schema_version":True}):
            with self.assertRaises(ValueError): TrackingCalibration.from_record(record)


class EyeControllerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.manager=ProfileManager(ProfileStore(self.root/"profiles"))
        self.now=1.
        self.face=eye_face()
        self.vision=Mock(error=None)
        self.vision.get_face_data.side_effect=lambda:self.face
        self.vision.get_fps.return_value=30
        self.backend=Mock()
        self.backend.size.return_value=(1920,1080)
        self.factory=Mock(return_value=self.backend)
        self.controller=ApplicationController(self.manager,Mock(return_value=self.vision),self.factory,
                                              self.root,lambda:self.now)
        self.addCleanup(self.controller.shutdown)
        self.profile=calibration()|{"validation":{"passed":True}}
        self.manager.store.save(self.profile)
        self.controller.select_profile("julian")

    def select_eye(self,calibrated=False):
        p=deepcopy(self.profile)
        p["settings"]={"ui":{"tracking_method":"eye"}}
        if calibrated: p["tracking_calibration"]=TrackingCalibration().record()
        self.manager.store.save(p)
        self.controller.select_profile("julian")

    def test_old_profile_default_and_switch_both_directions(self):
        c=self.controller
        c.start_camera()
        self.assertEqual(c.gesture.strategy.name,"nose")
        for method in ("eye","nose"):
            settings=asdict(c.config)
            settings["ui"]["tracking_method"]=method
            c.save_settings(settings)
            self.assertIsNone(c.vision)
            c.start_camera()
            self.assertEqual(c.gesture.strategy.name,method)
            self.assertEqual(c.gesture._eye_smooth_x,0)
            self.assertTrue(c.emergency.is_set())

    def test_uncalibrated_eye_blocks_activation_and_experiment(self):
        self.select_eye()
        c=self.controller
        c.emergency.clear()
        with self.assertRaisesRegex(ValueError,"tracking ocular"): c.activate_control(True)
        with self.assertRaises(ValueError): c.start_experiment()
        self.factory.assert_not_called()

    def test_eye_diagnostic_and_full_calibration_save_are_safe(self):
        self.select_eye()
        c=self.controller
        original=deepcopy(c.profile)
        c.start_eye_calibration()
        with self.assertRaises(ValueError): c.activate_control(True)
        for _ in range(70):
            self.now+=.033
            self.face=eye_face(.52,.48,int(self.now*1000))
            c.step()
        self.assertTrue(c.snapshot(False)["eye_calibration"]["can_save"])
        c.save_eye_calibration()
        self.assertEqual(c.state,"DIAGNOSTIC")
        self.assertAlmostEqual(c.profile["tracking_calibration"]["neutral_y"],.48)
        for key,value in original.items(): self.assertEqual(c.profile[key],value)
        c.start_diagnostic()
        c.step()
        self.factory.assert_not_called()
        self.assertTrue(c.snapshot(False)["tracking_calibrated"])
        self.assertEqual(c.gesture.diagnostic()["tracking"]["method"],"eye")

    def test_cancel_preserves_old_eye_calibration(self):
        self.select_eye(True)
        c=self.controller
        old=deepcopy(c.profile)
        c.start_eye_calibration()
        c.cancel_eye_calibration()
        self.assertEqual(c.profile,old)
        with self.assertRaises(ValueError): c.save_eye_calibration()

    def test_saving_gesture_calibration_preserves_independent_eye_record(self):
        self.select_eye(True)
        c=self.controller
        old=deepcopy(c.profile["tracking_calibration"])
        facial=deepcopy(self.profile)
        facial["settings"]=asdict(c.config)
        c.wizard=Mock()
        c.wizard.result.return_value=facial
        c.save_calibration()
        self.assertEqual(c.profile["tracking_calibration"],old)
        self.assertEqual(c.profile["thresholds"],facial["thresholds"])

    def test_main_uses_selected_strategy_and_blocks_missing_neutral(self):
        import main
        import sys
        self.select_eye(True)
        for with_neutral in (True,False):
            p=deepcopy(self.controller.profile)
            from profiles import save_gesture_mode
            p=save_gesture_mode(p,p,"eye")  # esta prueba requiere gestos oculares medidos/aprobados
            if not with_neutral: p.pop("tracking_calibration")
            vision=Mock(error=None)
            control=Mock(error=None)
            control.get_stats.return_value=SimpleNamespace(running=False)
            control_factory=Mock(return_value=control)
            modules={"vision_engine":SimpleNamespace(VisionEngine=Mock(return_value=vision)),
                     "control_engine":SimpleNamespace(ControlEngine=control_factory),
                     "cv2":Mock(),"pyautogui":Mock()}
            with patch.dict(sys.modules,modules), patch.object(main,"ProfileStore") as store, \
                 patch.object(main,"SessionMetrics"), patch("gesture_engine.GestureEngine") as engine, \
                 self.assertLogs(level="INFO"):
                store.return_value.load.return_value=p
                result=main.main(["--user","julian","--no-overlay"])
            self.assertEqual(result,0 if with_neutral else 1)
            if with_neutral:
                self.assertEqual(engine.call_args.kwargs["strategy"].name,"eye")
            else:
                control_factory.assert_not_called()

    def test_eye_results_identify_method_and_jitter_signal(self):
        self.select_eye(True)
        c=self.controller
        c.start_experiment()
        c.experiment.cancel()
        self.assertEqual(c.experiment.results[-1]["tracking_method"],"eye")
        c.start_jitter()
        for k in range(5):
            self.now+=.05
            self.face=eye_face(.5+k*.005,.5,int(self.now*1000))
            c.step()
        summary=c.jitter.summary()
        self.assertEqual(summary["units"],"comfortable_eye_range")
        self.assertGreater(summary["range_x"],0)

    def test_control_mock_stops_on_lost_iris_and_keeps_limits(self):
        self.select_eye(True)
        c=self.controller
        c.start_camera()
        control=ControlEngine(self.vision,c.gesture,backend=self.backend)
        self.addCleanup(control.stop)
        control.toggle_pause()
        self.face=eye_face(.9,.1)
        with patch("control_engine.time.monotonic",return_value=self.now): control._tick()
        self.assertTrue(self.backend.moveRel.called)
        for call in self.backend.moveRel.call_args_list:
            self.assertLessEqual(max(abs(v) for v in call.args),20)
        self.backend.moveRel.reset_mock()
        self.now+=.05
        self.face=FaceData(True,timestamp_ms=1050)
        with patch("control_engine.time.monotonic",return_value=self.now): control._tick()
        self.backend.moveRel.assert_not_called()

    def test_malformed_eye_profile_rejected_and_old_profile_supported(self):
        validate_profile(self.profile)
        self.assertEqual(load_config(overrides=self.profile.get("settings",{})).ui.tracking_method,"nose")
        with self.assertRaises(ValueError): validate_profile(self.profile|{"tracking_calibration":{}})


if __name__=="__main__": unittest.main()
