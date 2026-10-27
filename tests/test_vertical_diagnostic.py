"""Referencia vertical y motor real sobre backend en memoria; nunca mouse SO."""
import unittest
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch
from eye_geometry import EYES,extract_gaze
from gaze_source import gaze_position
from tracking_calibration import TrackingCalibration
from config import EyeTrackingConfig,load_config
from tracking import create_strategy
from vertical_diagnostic import VerticalDiagnosticSession,DiagnosticMovementTrace
from gaze_mapping import GazeCalibrationSession
from ocular_profiles import with_calibration,calibration_for
from profiles import save_gesture_mode,gesture_profile
from test_core import calibration
from test_eye_tracking import eye_face,eye_landmarks
from test_gaze_mapping import CONTEXT
import test_gaze_save


class VerticalReferenceTests(unittest.TestCase):
    def test_moving_lids_do_not_invert_canthi_reference_or_change_horizontal(self):
        before=extract_gaze(eye_landmarks(.7,.5),640,480)
        points=eye_landmarks(.7,.5)
        for _,_,upper,lower,iris,_ in EYES.values():
            points[upper]=SimpleNamespace(x=points[upper].x,y=.36)
            points[lower]=SimpleNamespace(x=points[lower].x,y=.41)
            points[iris]=SimpleNamespace(x=points[iris].x,y=.398)
        after=extract_gaze(points,640,480)
        for side in ("left","right"):
            self.assertGreater(after[side+"_gaze_y"],before[side+"_gaze_y"])
            self.assertLess(after[side+"_canthi_y"],before[side+"_canthi_y"])
            self.assertAlmostEqual(after[side+"_gaze_x"],before[side+"_gaze_x"])

    def test_all_sources_up_down_roll_scale_and_mirror_preserve_signed_y(self):
        for mirror in (False,True):
            for scale,roll in ((1.,0),(.6,.2),(1.2,-.2)):
                for source in ("both","left","right"):
                    signals=[]
                    for y in (.3,.5,.7):
                        geometry=extract_gaze(eye_landmarks(.5,y,mirror=mirror,scale=scale,roll=roll),640,480,mirrored=mirror)
                        signals.append(gaze_position(replace(eye_face(),**geometry),source,"canthi")[1])
                    self.assertLess(signals[0],signals[1]);self.assertLess(signals[1],signals[2])

    def test_partially_closed_eye_does_not_gain_false_iris_validity(self):
        points=eye_landmarks()
        for _,_,top,bottom,_,_ in EYES.values():points[bottom]=SimpleNamespace(x=points[top].x,y=points[top].y+.001)
        face=replace(eye_face(),**extract_gaze(points,640,480))
        self.assertIsNone(gaze_position(face,"both","canthi"))
        self.assertEqual(len(face.ocular_geometry),2)

    def test_relative_ranges_measure_new_reference_without_altering_absolute(self):
        for source in ("both","left","right"):
            now=[1.]
            session=GazeCalibrationSession(CONTEXT,clock=lambda:now[0],relative=True,eye_source=source,
                vertical_reference="canthi",countdown_s=0,settle_s=0,duration_s=.2,min_samples=5)
            for _ in range(250):
                if session.state in ("ready","invalid","error"):break
                x,y=session.snapshot()["target"];now[0]=round(now[0]+.05,3)
                session.update(eye_face(.25+.5*x,.25+.5*y,round(now[0]*1000)))
            self.assertEqual(session.state,"ready",session.message)
            record=session.result()
            self.assertEqual(record["vertical_reference"],"canthi")
            self.assertGreaterEqual(record["up_range"],.02)
            strategy=create_strategy("eye",record,EyeTrackingConfig(vertical_reference="canthi"),source)
            self.assertLess(strategy.position(eye_face(.5,.3))[1],0)
            self.assertGreater(strategy.position(eye_face(.5,.7))[1],0)
        absolute=GazeCalibrationSession(CONTEXT,vertical_reference="canthi")
        self.assertEqual(absolute.vertical_reference,"eyelids")

    def test_legacy_reference_is_compatible_but_changed_reference_needs_new_model(self):
        record=TrackingCalibration().record();record.pop("vertical_reference")
        self.assertEqual(TrackingCalibration.from_record(record).vertical_reference,"eyelids")
        self.assertIsNone(create_strategy("eye",record,EyeTrackingConfig(vertical_reference="canthi")).position(eye_face()))
        with self.assertRaises(ValueError):TrackingCalibration(vertical_reference="inverted")

    def test_observed_neutral_drift_and_dead_zone_explain_zero_up_delta(self):
        stored=.3884752227042749;observed_up=.3960577;observed_center=.4116041
        self.assertGreater(observed_up-stored,0)  # nunca puede producir Y negativa con ese neutral
        self.assertLess((observed_up-stored)/.2,.15)
        self.assertLess(abs((observed_up-observed_center)/.2),.15)  # nominal aún insuficiente
        with self.assertRaises(ValueError):TrackingCalibration(up_range=.0262898388,down_range=.0148150049)

    def test_actual_control_engine_sends_negative_y_only_to_memory_backend(self):
        for source in ("both","left","right"):
            cfg=load_config(overrides={"ui":{"tracking_method":"eye","eye_source":source},
                                      "eye":{"vertical_reference":"canthi","smoothing_alpha":0}})
            p=with_calibration(calibration(),TrackingCalibration(eye_source=source,vertical_reference="canthi",
                up_range=.06,down_range=.06,ranges_measured=True).record())
            now=[1.]
            trace=DiagnosticMovementTrace(p,cfg,clock=lambda:now[0])
            for stamp in (1000,1050,1100):
                now[0]=stamp/1000
                with patch("control_engine.time.monotonic",return_value=now[0]):result=trace.feed(eye_face(.5,.3,stamp))
            self.assertLess(result["computed_dy"],0)
            self.assertLess(result["would_send_dy"],0)

    def test_three_point_diagnostic_repeat_preserves_other_measurements(self):
        now=[1.]
        session=VerticalDiagnosticSession(clock=lambda:now[0],settle_s=0,duration_s=.2,min_samples=5)
        for _ in range(50):
            if session.state=="ready":break
            _,y=session.targets[session.index];now[0]=round(now[0]+.05,3)
            session.update(eye_face(.5,.25+.5*y,round(now[0]*1000)),dict(computed_dy=-2 if y<.5 else 2))
        report=session.report()
        self.assertTrue(report["comparison"]["both_canthi"]["signs_match"])
        self.assertFalse(report["calibration_saved"])
        saved=deepcopy(session.points[0]);session.repeat(1)
        self.assertEqual(session.points[0],saved)
        self.assertIn(2,session.points)
        self.assertNotIn(1,session.points)

    def test_ocular_movement_waits_for_mouth_gesture_then_recovers_stably(self):
        from gesture_engine import GestureEngine
        now=[1.]
        engine=GestureEngine(None,calibration=calibration(),clock=lambda:now[0],
            strategy=create_strategy("eye",TrackingCalibration().record()))
        self.assertTrue(any(e.type=="CURSOR_MOVE" for e in engine.update(eye_face(.7,.5,1000))))
        for stamp in (1050,1100):
            now[0]=stamp/1000
            events=engine.update(replace(eye_face(.7,.5,stamp),mouth_open=.4))
            self.assertFalse(any(e.type=="CURSOR_MOVE" for e in events))
        for stamp in (1500,1550,1600):
            now[0]=stamp/1000;events=engine.update(eye_face(.7,.5,stamp))
        self.assertTrue(any(e.type=="CURSOR_MOVE" for e in events))

    def test_axis_specific_dead_zone_changes_only_y_when_explicitly_set(self):
        from gesture_engine import GestureEngine
        records=[]
        for zone in (None,.4):
            now=[1.]
            engine=GestureEngine(None,calibration=calibration(),clock=lambda:now[0],
                strategy=create_strategy("eye",TrackingCalibration().record(),
                    EyeTrackingConfig(smoothing_alpha=0,dead_zone_y=zone)))
            engine.update(eye_face(.6,.56,1000))
            records.append(engine.tracking_diagnostic()["cursor_delta"])
        self.assertEqual(records[0][0],records[1][0])
        self.assertGreater(records[0][1],0)
        self.assertEqual(records[1][1],0)
        with self.assertRaises(ValueError):EyeTrackingConfig(dead_zone_y=-.1)

    def test_low_vertical_amplitude_report_does_not_claim_noise_separation(self):
        session=VerticalDiagnosticSession()
        for index,(value,noise) in enumerate(((.46,.0032),(.4337,.0017),(.4748,.0064))):
            session.points[index]=dict(target=session.names[index],samples=31,
                median={"both_canthi":value},spread_p10_p90={"both_canthi":noise},quality=.8)
        result=session.report()["comparison"]["both_canthi"]
        self.assertTrue(result["signs_match"])
        self.assertFalse(result["relative_ranges_at_least_002"])
        self.assertFalse(result["exceeds_three_spreads"])
        self.assertLess(result["amplitude_over_noise_down"],3)

    def test_position_diagnostic_uses_current_model_and_never_falls_back_to_direction(self):
        from test_gaze_mapping import completed_session
        p=with_calibration(calibration(),completed_session().result())
        p=with_calibration(p,TrackingCalibration().record())
        cfg=load_config(overrides={"ui":{"tracking_method":"eye_absolute"}})
        trace=DiagnosticMovementTrace(p,cfg,clock=lambda:1.)
        with patch("control_engine.time.monotonic",return_value=1.):result=trace.feed(eye_face(.5,.35,1000))
        self.assertEqual(result["method"],"eye_absolute")
        self.assertLess(result["would_send_dy"],0)
        p.pop("absolute_calibration");p.pop("absolute_calibrations")
        missing=DiagnosticMovementTrace(p,cfg)
        self.assertIsNone(missing.control)
        self.assertIn("no se cambia",missing.feed(eye_face())["block_reason"])


class OcularIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.fixture=test_gaze_save.SaveControllerRegressionTests()
        self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.c=self.fixture.c

    def test_nasal_validation_is_not_silently_authorized_for_ocular_actions(self):
        self.assertTrue(self.c.profile["validation"]["passed"])
        self.assertFalse(self.c._actions_ready())
        self.c.emergency.clear();self.c.activate_control(True)
        self.assertTrue(self.c.control.movement_only)
        self.c.control._execute(__import__('gesture_engine').GestureEvent("LEFT_CLICK"))
        self.fixture.backend.click.assert_not_called()

    def test_measured_gestures_save_in_selected_bank_without_replacing_nose(self):
        original=deepcopy(gesture_profile(self.c.profile,"nose"))
        candidate=calibration()|dict(validation={"passed":True})
        saved=save_gesture_mode(self.c.profile,candidate,"eye")
        self.c.profiles.store.save(saved)
        self.c.profile=self.c.profiles.store.load(saved["user_id"])
        self.assertTrue(self.c._actions_ready())
        self.assertEqual(gesture_profile(self.c.profile,"nose")["thresholds"],original["thresholds"])
        self.assertNotIn("eye_absolute",self.c.profile["gesture_mode_origin"])

    def test_canthi_neutral_alone_or_reference_mismatch_cannot_activate(self):
        self.c.config.eye.vertical_reference="canthi"
        with self.assertRaisesRegex(ValueError,"referencia vertical"):self.c._require_tracking_calibration()
        self.c.profile=with_calibration(self.c.profile,TrackingCalibration(vertical_reference="canthi").record())
        with self.assertRaisesRegex(ValueError,"cinco rangos"):self.c._require_tracking_calibration()
        self.fixture.factory.assert_not_called()

    def test_vertical_diagnostic_does_not_change_profiles_or_create_real_backend(self):
        before=deepcopy(self.c.profile)
        self.c.start_vertical_diagnostic()
        self.assertEqual(self.c.state,"VERTICAL_DIAGNOSTIC")
        self.c.step()
        self.assertIsNotNone(self.c.snapshot(False)["vertical_trace"])
        self.c.emergency.clear()
        with self.assertRaises(ValueError):self.c.activate_control(True)
        self.c.cancel_vertical_diagnostic()
        self.assertEqual(self.c.profile,before)
        self.fixture.factory.assert_not_called()


if __name__=="__main__":unittest.main()
