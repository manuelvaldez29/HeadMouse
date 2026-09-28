"""Calibración de señales sintéticas; no cámara, Qt ni entradas del SO."""
import json
import unittest
from dataclasses import replace
from types import SimpleNamespace

from adaptive_calibration import GestureCalibration, HysteresisGate
from config import CalibrationConfig
from face_data import FaceData
from gesture_signals import get_signal, GESTURE_SIGNALS, extract_blendshapes, BROW_BLENDSHAPES
from gesture_arbitration import BrowArbiter
from gesture_engine import GestureEngine
from profiles import validate_profile
from test_core import calibration


class AdaptiveCalibrationTests(unittest.TestCase):
    def make_model(self, gesture_id="LEFT_BROW", source="GEOMETRIC"):
        signal=get_signal(gesture_id)
        return GestureCalibration(gesture_id,signal.channels,signal.directions,source)

    def fit(self, neutral, active, model=None):
        model = model or self.make_model()
        for _ in range(3): model.add_repetition(neutral,active)
        return model.fit(CalibrationConfig())

    def test_strong_signal_adaptive_threshold_and_export(self):
        model=self.fit([(.2,)]*20,[(.4,)]*20)
        self.assertTrue(model.usable)
        self.assertEqual(model.quality_score,1)
        self.assertEqual(model.quality_label,"BUENA")
        self.assertGreater(model.activation_threshold["left"],.2)
        self.assertLess(model.activation_threshold["left"],.4)
        self.assertLess(model.release_threshold["left"],model.activation_threshold["left"])
        record=model.to_record()
        self.assertEqual(record["repetitions_valid"],3)
        self.assertEqual(record["neutral_statistics"]["left"]["mad"],0)
        encoded=json.dumps(record,allow_nan=False)
        self.assertNotIn("neutral_samples",encoded)
        self.assertNotIn("active_samples",encoded)

    def test_weak_signal_requires_repeat_without_silent_acceptance(self):
        model=self.fit([(.2,)]*20,[(.201,)]*20)
        self.assertFalse(model.usable)
        self.assertEqual(model.validation_state,"repeat")
        self.assertTrue(model.reasons)
        self.assertEqual(model.to_record()["repetitions_captured"],3)

    def test_noisy_neutral_rejected(self):
        model=self.fit([(.1,),(.2,),(.4,),(.5,)]*5,[(.45,)]*20)
        self.assertFalse(model.usable)
        self.assertGreater(model.neutral_noise["left"],0)

    def test_single_outlier_does_not_set_extreme_threshold(self):
        clean=self.fit([(.2,)]*20,[(.4,)]*20)
        noisy=self.fit([(.2,)]*19+[(9.,)],[(.4,)]*19+[(-9.,)])
        self.assertTrue(noisy.usable)
        self.assertAlmostEqual(clean.activation_threshold["left"],noisy.activation_threshold["left"])
        self.assertAlmostEqual(noisy.quality_score,.95)

    def test_repetitions_required_and_bad_repetition_not_hidden(self):
        model=self.make_model()
        for _ in range(2): model.add_repetition([(.2,)]*20,[(.4,)]*20)
        model.fit(CalibrationConfig())
        self.assertFalse(model.usable)
        model.add_repetition([(.2,)]*20,[(.201,)]*20)
        model.fit(CalibrationConfig())
        self.assertFalse(model.usable)

    def test_same_algorithm_for_decreasing_and_future_signal(self):
        wink=self.fit([(.1,)]*20,[(.02,)]*20,self.make_model("LEFT_WINK"))
        self.assertTrue(wink.usable)
        self.assertLess(wink.activation_threshold["eye_left_ratio"],wink.release_threshold["eye_left_ratio"])
        future=GestureCalibration("FUTURE_SMILE",("new_signal",),(1,))
        future=self.fit([(.1,)]*20,[(.7,)]*20,future)
        self.assertTrue(future.usable)
        self.assertEqual(future.gesture_id,"FUTURE_SMILE")

    def test_both_brows_uses_own_two_channel_capture(self):
        both=self.fit([(.2,.3)]*20,[(.3,.42)]*20,self.make_model("BOTH_BROWS"))
        self.assertTrue(both.usable)
        self.assertLess(both.activation_threshold["left"],.3)
        self.assertLess(both.activation_threshold["right"],.42)
        gate=HysteresisGate(both.channels,both.directions,both.activation_threshold,both.release_threshold)
        self.assertFalse(gate.update((.4,.3)))
        self.assertTrue(gate.update((.3,.42)))

    def test_hysteresis_prevents_oscillation_for_both_directions(self):
        for direction in (-1,1):
            gate=HysteresisGate(("x",),(direction,),{"x":direction*.6},{"x":direction*.4})
            states=[gate.update((direction*v,)) for v in (.5,.61,.59,.6,.41,.39,.59)]
            self.assertEqual(states,[False,True,True,True,True,False,False])
            self.assertFalse(gate.update(None))

    def test_single_threshold_fallback_retains_comparison(self):
        gate=HysteresisGate(("x",),(1,),{"x":.3},{"x":.3})
        self.assertTrue(gate.update((.31,)))
        self.assertFalse(gate.update((.3,)))

    def test_disabled_gesture_requires_no_samples(self):
        model=self.make_model("MOUTH_OPEN")
        model.disable()
        model.fit(CalibrationConfig())
        self.assertTrue(model.usable)
        self.assertEqual(model.validation_state,"disabled")
        self.assertEqual(model.activation_threshold,{})

    def test_all_current_adapters_and_blendshape_missing(self):
        face=FaceData(True,eye_left_ratio=.1,eye_right_ratio=.2,brow_left_lift=.3,brow_right_lift=.4,mouth_open=.5)
        expected={"LEFT_WINK":(.1,),"RIGHT_WINK":(.2,),"LEFT_BROW":(.3,),"RIGHT_BROW":(.4,),"MOUTH_OPEN":(.5,),"BOTH_BROWS":(.3,.4)}
        for key,signal in GESTURE_SIGNALS.items(): self.assertEqual(signal.extract(face),expected[key])
        self.assertIsNone(get_signal("BOTH_BROWS").extract(face,"BLENDSHAPE"))
        blends=(("browInnerUp",.4),("browOuterUpLeft",.8),("browOuterUpRight",.6),("browDownLeft",.2),("browDownRight",.1))
        face=replace(face,blendshapes=blends)
        left=get_signal("LEFT_BROW")
        self.assertAlmostEqual(left.extract(face,"BLENDSHAPE")[0],.5)
        self.assertAlmostEqual(left.extract(face,"HYBRID")[0],(.3/.25+.5)/2)
        self.assertEqual(left.extract(face,"GEOMETRIC"),(.3,))

    def test_invalid_samples_and_hysteresis_rejected(self):
        model=self.make_model()
        for bad in ([],[(float("nan"),)],[(1,2)]):
            with self.assertRaises(ValueError): model.add_repetition(bad,[(.4,)])
        with self.assertRaises(ValueError): HysteresisGate(("x",),(1,),{"x":.2},{"x":.3})

    def test_mediapipe_categories_use_names_and_reject_invalid_scores(self):
        categories=[SimpleNamespace(category_name=name,score=.4) for name in BROW_BLENDSHAPES]
        categories.extend([SimpleNamespace(category_name="jawOpen",score=.9),
                           SimpleNamespace(category_name="browInnerUp",score=float("nan"))])
        scores=dict(extract_blendshapes(categories))
        self.assertEqual(set(scores),set(BROW_BLENDSHAPES))
        self.assertEqual(scores["browInnerUp"],.4)
        self.assertEqual(extract_blendshapes([]),())

    def test_brow_arbitration_temporal_sequences(self):
        for first,delay in (("left",.08),("right",.12)):
            arb=BrowArbiter(200)
            self.assertIsNone(arb.update(first=="left",first=="right",False,1))
            self.assertEqual(arb.update(True,True,True,1+delay),"both")
            self.assertEqual(arb.update(True,True,True,1.4),"both")
            self.assertIsNone(arb.update(False,False,False,1.5))
        for side in ("left","right"):
            arb=BrowArbiter(200)
            self.assertIsNone(arb.update(side=="left",side=="right",False,1))
            self.assertEqual(arb.update(side=="left",side=="right",False,1.2),side)
            self.assertEqual(arb.update(True,True,True,1.3),side)
        arb=BrowArbiter(200)
        self.assertEqual(arb.update(True,True,True,1),"both")

    def test_arbitration_release_cancels_pending(self):
        arb=BrowArbiter(200)
        self.assertIsNone(arb.update(True,False,False,1))
        self.assertIsNone(arb.update(False,False,False,1.1))
        self.assertIsNone(arb.update(False,True,False,1.2))
        self.assertEqual(arb.update(False,True,False,1.4),"right")

    def test_detector_emits_only_resolved_brow_event(self):
        cases=((0,None,"SCROLL_UP"),(None,0,"SCROLL_DOWN"),(0,0,"BOTH_BROWS"),
               (0,.08,"BOTH_BROWS"),(.12,0,"BOTH_BROWS"),(0,.3,"SCROLL_UP"),(.3,0,"SCROLL_DOWN"))
        for left_start,right_start,expected in cases:
            with self.subTest(left=left_start,right=right_start):
                now=[1.]
                engine=GestureEngine(None,calibration=calibration(),clock=lambda:now[0])
                emitted=[]
                for frame in range(30):
                    elapsed=frame*.02
                    timestamp=1000+frame*20
                    now[0]=timestamp/1000
                    face=FaceData(True,timestamp_ms=timestamp,eye_left_ratio=.1,eye_right_ratio=.12,
                                  brow_left_lift=.4 if left_start is not None and elapsed>=left_start else .2,
                                  brow_right_lift=.5 if right_start is not None and elapsed>=right_start else .22,mouth_open=.01)
                    emitted += [e.type for e in engine.update(face)]
                self.assertEqual(emitted,[expected])

    def adaptive_profile(self):
        profile=calibration()
        neutral=FaceData(True,eye_left_ratio=.1,eye_right_ratio=.12,brow_left_lift=.2,brow_right_lift=.22,mouth_open=.01)
        variants={"LEFT_WINK":{"eye_left_ratio":.02},"RIGHT_WINK":{"eye_right_ratio":.03},
                  "LEFT_BROW":{"brow_left_lift":.4},"RIGHT_BROW":{"brow_right_lift":.5},
                  "MOUTH_OPEN":{"mouth_open":.3},"BOTH_BROWS":{"brow_left_lift":.3,"brow_right_lift":.33}}
        records={}
        for key,spec in GESTURE_SIGNALS.items():
            model=self.make_model(key)
            for _ in range(3): model.add_repetition([spec.extract(neutral)]*20,[spec.extract(replace(neutral,**variants[key]))]*20)
            model.fit(CalibrationConfig())
            records[key]=model.to_record()
        profile["gesture_calibrations"]=records
        return profile

    def test_runtime_uses_explicit_bilateral_profile_and_disabled_gesture(self):
        profile=self.adaptive_profile()
        model=self.make_model("LEFT_WINK")
        model.disable()
        profile["gesture_calibrations"]["LEFT_WINK"]=model.to_record()
        validate_profile(profile)
        now=[1.]
        engine=GestureEngine(None,calibration=profile,clock=lambda:now[0])
        events=[]
        for i in range(20):
            timestamp=1000+i*20
            now[0]=timestamp/1000
            events += engine.update(FaceData(True,timestamp_ms=timestamp,eye_left_ratio=.02,eye_right_ratio=.12,
                                            brow_left_lift=.3,brow_right_lift=.33,mouth_open=.01))
        self.assertEqual([e.type for e in events],["BOTH_BROWS"])
        self.assertNotIn("LEFT_WINK",engine.enabled_gestures)

    def test_profile_rejects_mismatched_signal_or_reversed_hysteresis(self):
        profile=self.adaptive_profile()
        profile["gesture_calibrations"]["LEFT_WINK"]["source"]="BLENDSHAPE"
        with self.assertRaises(ValueError): validate_profile(profile)
        profile=self.adaptive_profile()
        profile["gesture_calibrations"]["LEFT_BROW"]["release_threshold"]["left"]=.9
        with self.assertRaises(ValueError): validate_profile(profile)


if __name__=="__main__": unittest.main()
