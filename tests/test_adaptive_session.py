"""Flujos de calibración/validación adaptativa con reloj y rostro sintéticos."""
import unittest
import json
import tempfile
from pathlib import Path
from copy import deepcopy
from dataclasses import replace
from calibration_session import CalibrationSession
from calibration_validation import CalibrationValidation
from config import load_config
from face_data import FaceData
from gesture_engine import GestureEngine
from gesture_signals import GESTURE_SIGNALS
from profiles import validate_profile
from test_core import calibration

NEUTRAL=dict(eye_left_ratio=.1,eye_right_ratio=.12,brow_left_lift=.2,brow_right_lift=.22,mouth_open=.01)
ACTIVE={"LEFT_WINK":{"eye_left_ratio":.02},"RIGHT_WINK":{"eye_right_ratio":.03},
        "LEFT_BROW":{"brow_left_lift":.4},"RIGHT_BROW":{"brow_right_lift":.5},
        "MOUTH_OPEN":{"mouth_open":.3},"BOTH_BROWS":{"brow_left_lift":.3,"brow_right_lift":.33}}


class AdaptiveSessionTests(unittest.TestCase):
    def setUp(self):
        self.timestamp=1000
        self.config=load_config()
        cc=self.config.calibration
        cc.countdown_s=.1
        cc.measuring_s=.2
        cc.min_samples=3
        cc.min_window_samples=3
        cc.active_window_s=cc.neutral_window_s=.15
        cc.transition_s=.05

    def clock(self): return self.timestamp/1000

    def face(self,values=None,detected=True):
        self.timestamp+=50
        return FaceData(detected,timestamp_ms=self.timestamp,**(NEUTRAL | (values or {})))

    def session(self,enabled=None):
        s=CalibrationSession({"user_id":"synthetic"},self.config,self.clock,enabled)
        s.start()
        return s

    def capture(self,session,variants=None):
        variants=ACTIVE if variants is None else variants
        for _ in range(1000):
            if session.state in ("measured","error"): return
            values=variants.get(session.gesture_id,{}) if session.stage=="active" else {}
            session.update(self.face(values))
        self.fail("La captura no terminó")

    def feed(self,target,seconds,values=None):
        for _ in range(round(seconds/.05)): target.update(self.face(values))

    def test_three_repetitions_explicit_both_and_no_transition_samples(self):
        s=self.session()
        self.capture(s)
        self.assertEqual(s.state,"measured")
        self.assertEqual(len(s.telemetry),6)
        for record in s.candidate["gesture_calibrations"].values():
            self.assertEqual(record["repetitions_valid"],3)
            self.assertEqual(record["quality_score"],1)
        both=s.candidate["gesture_calibrations"]["BOTH_BROWS"]
        self.assertEqual(both["active_statistics"]["left"]["median"],.3)
        self.assertLess(both["activation_threshold"]["left"],s.candidate["thresholds"]["brow_left"])
        validate_profile(s.candidate)

    def test_disabled_gestures_map_none_and_are_not_required(self):
        s=self.session({key:key=="MOUTH_OPEN" for key in GESTURE_SIGNALS})
        self.capture(s)
        self.assertEqual(s.state,"measured")
        for key in GESTURE_SIGNALS:
            if key!="MOUTH_OPEN": self.assertEqual(s.candidate["settings"]["actions"]["bindings"][key],"NONE")
        s.validate()
        self.assertEqual([v[0] for v in s.validator.gestures],["MOUTH_OPEN"])
        self.feed(s,2.2)
        self.feed(s,.3,ACTIVE["MOUTH_OPEN"])
        self.feed(s,2.2)
        result=s.result()
        self.assertTrue(result["validation"]["passed"])
        self.assertEqual(result["gesture_calibrations"]["LEFT_BROW"]["validation_state"],"disabled")

    def test_retry_only_failed_gesture_preserves_others(self):
        s=self.session()
        self.capture(s,ACTIVE | {"RIGHT_WINK":{"eye_right_ratio":.12}})
        self.assertEqual(s.state,"error")
        self.assertEqual(s.gesture_id,"RIGHT_WINK")
        left=deepcopy(s.models["LEFT_WINK"].to_record())
        s.repeat()
        self.capture(s)
        self.assertEqual(s.state,"measured")
        self.assertEqual(s.models["LEFT_WINK"].to_record(),left)
        self.assertEqual(s.models["RIGHT_WINK"].retries,1)
        self.assertEqual(len(s.telemetry),7)

    def test_disable_failed_gesture_continues_without_restart(self):
        s=self.session()
        self.capture(s,ACTIVE | {"RIGHT_WINK":{"eye_right_ratio":.12}})
        s.set_enabled("RIGHT_WINK",False)
        self.capture(s)
        self.assertEqual(s.state,"measured")
        self.assertEqual(s.candidate["settings"]["actions"]["bindings"]["RIGHT_WINK"],"NONE")
        self.assertEqual(s.models["LEFT_WINK"].quality_score,1)

    def test_loss_resets_capture_and_duplicate_frames_do_not_count(self):
        s=self.session()
        while s.state!="measuring": s.update(self.face())
        face=self.face()
        s.update(face)
        s.update(face)
        self.assertEqual(len(s.samples.nose_x),1)
        s.update(self.face(detected=False))
        self.assertEqual(len(s.samples.nose_x),0)
        self.capture(s)
        self.assertEqual(s.state,"measured")

    def test_validation_tolerates_isolated_noise_but_rejects_sustained_wrong(self):
        engine=GestureEngine(None,calibration=calibration(),clock=self.clock)
        v=CalibrationValidation(engine,clock=self.clock)
        self.feed(v,1.2)
        self.feed(v,.05,ACTIVE["RIGHT_WINK"])
        self.feed(v,1.2)
        self.assertIsNone(v.error)
        self.assertFalse(v.neutral)
        self.feed(v,.15,ACTIVE["RIGHT_WINK"])
        self.feed(v,.2)
        self.assertIsNone(v.error)
        self.assertEqual(v.recognized,[])
        self.feed(v,.2,ACTIVE["LEFT_WINK"])
        self.feed(v,2.2)
        self.assertEqual(v.recognized,["LEFT_CLICK"])
        self.feed(v,.5,ACTIVE["MOUTH_OPEN"])
        self.assertIsNotNone(v.error)

    def test_experimental_sources_capture_and_detect_in_same_units(self):
        for source in ("BLENDSHAPE","HYBRID"):
            with self.subTest(source=source):
                self.config.calibration.brow_signal_source=source
                s=self.session()
                def blend_face(values=None):
                    f=self.face(values)
                    return replace(f,blendshapes=(("browInnerUp",.1),("browDownLeft",0.),("browDownRight",0.),
                        ("browOuterUpLeft",max(0.,2*(f.brow_left_lift-.2))),
                        ("browOuterUpRight",max(0.,2*(f.brow_right_lift-.22)))))
                for _ in range(1000):
                    if s.state in ("measured","error"): break
                    s.update(blend_face(ACTIVE.get(s.gesture_id,{}) if s.stage=="active" else {}))
                self.assertEqual(s.state,"measured")
                validate_profile(s.candidate)
                self.assertEqual(s.candidate["gesture_calibrations"]["BOTH_BROWS"]["source"],source)
                engine=GestureEngine(None,calibration=s.candidate,clock=self.clock)
                events=[]
                for _ in range(15): events.extend(engine.update(blend_face(ACTIVE["BOTH_BROWS"])))
                self.assertEqual([e.type for e in events if e.type!="CURSOR_MOVE"],["BOTH_BROWS"])
                # Sin blendshapes no se sustituyen por geometría con otra escala.
                for _ in range(15):
                    self.assertFalse([e for e in engine.update(self.face(ACTIVE["BOTH_BROWS"])) if e.type!="CURSOR_MOVE"])

    def test_telemetry_writes_aggregates_once_and_keeps_failed_attempt(self):
        from application_controller import ApplicationController
        from profile_manager import ProfileManager
        from profiles import ProfileStore
        from config import ROOT
        s=self.session()
        self.capture(s,ACTIVE | {"RIGHT_WINK":{"eye_right_ratio":.12}})
        s.repeat()
        self.capture(s)
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            c=ApplicationController(ProfileManager(ProfileStore(Path(temp)/"profiles")),data_dir=temp)
            c.profile={"user_id":"synthetic"}
            c.wizard=s
            c._calibration_session_id="a"*32
            c._flush_calibration_telemetry()
            c._flush_calibration_telemetry()
            records=[json.loads(line) for line in (Path(temp)/"calibration"/("a"*32+".jsonl")).read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(records),7)
            self.assertEqual(records[1]["quality_label"],"DÉBIL")
            self.assertEqual(records[2]["retries"],1)
            for record in records:
                self.assertIn("neutral_statistics",record)
                for name in ("neutral_samples","active_samples","frame","face","landmarks"):
                    self.assertNotIn(name,record)

    def test_existing_profile_revalidation_requires_fresh_capture_to_remeasure(self):
        s=CalibrationSession(calibration(),self.config,self.clock)
        s.candidate=calibration()
        s.validate()
        with self.assertRaisesRegex(ValueError,"nueva calibración"):
            s.repeat("LEFT_BROW")
        self.assertEqual(s.state,"validation")

    def test_single_available_wink_preserves_bilateral_blink_suppression(self):
        for available in ("LEFT_WINK","RIGHT_WINK"):
            s=self.session({key:key==available for key in GESTURE_SIGNALS})
            neutral=dict(eye_left_ratio=.03,eye_right_ratio=.025)
            channel=GESTURE_SIGNALS[available].channels[0]
            for _ in range(1000):
                if s.state in ("measured","error"): break
                values=neutral | ({channel:.006} if s.stage=="active" else {})
                s.update(self.face(values))
            self.assertEqual(s.state,"measured")
            engine=GestureEngine(None,calibration=s.candidate,clock=self.clock)
            bilateral=[]
            for _ in range(10): bilateral+=engine.update(self.face(dict(eye_left_ratio=.006,eye_right_ratio=.006)))
            self.assertFalse(bilateral)
            for _ in range(15): engine.update(self.face(neutral))
            events=[]
            for _ in range(10): events+=engine.update(self.face(neutral | {channel:.006}))
            self.assertEqual([e.type for e in events],[GESTURE_SIGNALS[available].event_type])


if __name__=="__main__": unittest.main()
