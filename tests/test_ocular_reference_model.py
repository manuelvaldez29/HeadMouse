import unittest
from dataclasses import replace
from copy import deepcopy
import numpy as np
from gaze_mapping import GazeCalibrationSession,GazeModel,features,TRAIN_TARGETS
from screen_mapping import target_in_viewport
from test_gaze_mapping import CONTEXT,completed_session
from test_eye_tracking import eye_face


def reference_face(target,stamp=1000):
    x,y=target
    # Párpados reproducibles pero dependientes de X; comisuras distinguen Y.
    return replace(eye_face(.25+.5*x,.45+.08*(x-.5)+.08*(x-.5)**2,stamp),
                   left_canthi_y=.5+.04*(y-.5),right_canthi_y=.5+.04*(y-.5))


def reference_session():
    now=[1.]
    s=GazeCalibrationSession(CONTEXT,clock=lambda:now[0],countdown_s=0,settle_s=0,duration_s=.2,min_samples=5)
    for _ in range(1000):
        if s.state in ('ready','invalid','error'):break
        now[0]+=.05
        s.update(reference_face(s.snapshot()['target'],round(now[0]*1000)))
    return s


class OcularReferenceTests(unittest.TestCase):
    def test_canthi_selected_from_training_then_validated_independently(self):
        s=reference_session()
        self.assertEqual(s.state,'ready',s.message)
        self.assertEqual(s.model.vertical_reference,'canthi')
        self.assertEqual(s.result()['schema_version'],3)
        self.assertEqual(len(s.validation_points),5)
        restored=GazeModel(s.result())
        np.testing.assert_allclose(restored.predict(reference_face((.3,.7))),(.3,.7),atol=.005)
        self.assertIsNone(restored.predict(eye_face(.4,.4))) # No comisuras: abstención.
        self.assertLess(s.model.scale[1],.025) # Escala por ancho, no apertura palpebral.

    def test_runtime_uses_saved_reference_and_abstains_on_missing_canthi(self):
        from tracking import create_strategy
        from gesture_engine import GestureEngine
        from test_core import calibration
        model=reference_session().result()
        strategy=create_strategy("eye_absolute",model)
        self.assertEqual(strategy.vertical_reference,"canthi")
        engine=GestureEngine(None,calibration=calibration(),strategy=strategy,clock=lambda:1.)
        engine.update(reference_face((.7,.3),1000))
        self.assertEqual(engine.tracking_diagnostic()["vertical_reference"],"canthi")
        events=engine.update(eye_face(.7,.3,1010))
        self.assertFalse(any(e.type=="CURSOR_ABSOLUTE" for e in events))

    def test_repeat_training_resets_reference_and_independent_validation(self):
        s=reference_session();s.review_training()
        self.assertEqual(s.vertical_reference,'eyelids')
        self.assertIsNone(s.model)
        self.assertEqual(s.validation_points,{})
        self.assertEqual(len(s.points),8)

    def test_legacy_model_stays_eyelids_and_unknown_reference_fails(self):
        record=completed_session().result()
        legacy=deepcopy(record);legacy.pop('vertical_reference',None)
        self.assertEqual(GazeModel(legacy).vertical_reference,'eyelids')
        with self.assertRaises(ValueError):GazeModel(legacy|dict(schema_version=3))
        with self.assertRaises(ValueError):GazeModel(legacy|dict(vertical_reference='canthi'))

    def test_canthi_requires_measured_noise_and_rejects_noise_only_signal(self):
        rows=[features(reference_face(t),vertical_reference='canthi') for t in TRAIN_TARGETS]
        with self.assertRaises(ValueError):GazeModel.fit(rows,TRAIN_TARGETS,CONTEXT,vertical_reference='canthi')
        with self.assertRaises(ValueError):GazeModel.fit(rows,TRAIN_TARGETS,CONTEXT,point_spreads=[[.1,.1]]*9,vertical_reference='canthi')

    def test_retina_overlay_offset_maps_to_exact_physical_target(self):
        context=CONTEXT|dict(width=2940,height=1912,dpr=2.)
        for target in TRAIN_TARGETS:
            x,y=target_in_viewport(target,context,(0,37),2.)
            self.assertAlmostEqual(x*2,target[0]*2939)
            self.assertAlmostEqual((y+37)*2,target[1]*1911)
            self.assertTrue(0<=x<1470 and 0<=y<919)
        with self.assertRaises(ValueError):target_in_viewport((.5,.5),context,(0,0),1.)

    def test_v3_roundtrip_in_personal_profile_preserves_reference(self):
        import tempfile
        from profiles import ProfileStore
        from test_core import calibration
        model=reference_session().result()
        with tempfile.TemporaryDirectory() as root:
            store=ProfileStore(root)
            profile=calibration();profile["absolute_calibration"]=model
            store.save(profile)
            restored=GazeModel(store.load(profile["user_id"])["absolute_calibration"])
            self.assertEqual(restored.vertical_reference,"canthi")
            np.testing.assert_allclose(restored.predict(reference_face((.7,.3))),(.7,.3),atol=.005)

    def test_diagnostic_export_never_becomes_approved_calibration(self):
        s=completed_session(wrong_validation=True);before=deepcopy(s.model.record)
        record=s.diagnostic_record()
        self.assertFalse(record['authorizes_control'])
        self.assertFalse(record['approved_calibration'])
        self.assertNotIn('validated',record)
        self.assertEqual(before,s.model.record)
        with self.assertRaises(ValueError):GazeModel(record)
        with self.assertRaises(ValueError):s.result()
