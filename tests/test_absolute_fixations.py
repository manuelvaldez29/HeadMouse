"""Regresiones sintéticas del umbral cruzado; sin cámara ni mouse real."""
import unittest
import numpy as np
from gaze_mapping import GazeCalibrationSession, GazeModel, TRAIN_TARGETS, features
from test_gaze_mapping import CONTEXT, target_face


class AbsoluteFixationTests(unittest.TestCase):
    def point(self, x, y, spread=0.):
        return dict(features=features(target_face((x,y))).tolist(),
                    target=[x,y], spread=spread, last_timestamp_ms=1000)

    def test_reported_values_have_traceable_components_but_no_absolute_gate(self):
        session=GazeCalibrationSession(CONTEXT)
        center=self.point(.5,.5,.089158)
        session.points[4]=center
        point=self.point(.1,.1,.002)
        point['features'][1]=point['features'][3]=.5-.008967
        self.assertIsNone(session._point_problem(0,point))
        check=point['direction_check']
        self.assertAlmostEqual(-check['delta'][1],.008967)
        self.assertEqual(check['minimum'],.089158)
        self.assertEqual(check['threshold_components']['center_spread'],.089158)
        self.assertFalse(check['threshold_applied'])
        self.assertFalse(session.snapshot()['can_save'])

    def test_missing_center_is_rejected_and_new_session_has_no_saved_neutral(self):
        session=GazeCalibrationSession(CONTEXT)
        self.assertEqual(session.index,4)
        self.assertEqual(session.snapshot()['capture_number'],1)
        self.assertIn('Falta el neutral',session._point_problem(0,self.point(.1,.1)))
        self.assertEqual(session.points,{})

    def test_relative_gate_is_preserved(self):
        session=GazeCalibrationSession(CONTEXT,relative=True)
        session.points[0]=self.point(.5,.5,.089158)
        point=self.point(.5,.1)
        point['features'][1]=point['features'][3]=.5-.008967
        self.assertIn('arriba insuficiente',session._point_problem(3,point))
        self.assertTrue(point['direction_check']['threshold_applied'])

    def test_complete_spatial_variation_must_exceed_noise_on_each_axis(self):
        rows=[features(target_face(p)) for p in TRAIN_TARGETS]
        model=GazeModel.fit(rows,TRAIN_TARGETS,CONTEXT,point_spreads=[[.01,.01]]*9)
        self.assertFalse(model.record['validated'])
        with self.assertRaisesRegex(ValueError,'ruido'):
            GazeModel.fit(rows,TRAIN_TARGETS,CONTEXT,point_spreads=[[.01,.5]]*9)

    def test_collinear_and_small_vertical_coverage_still_fail(self):
        rows=[features(target_face((x,x))) for x,y in TRAIN_TARGETS]
        with self.assertRaisesRegex(ValueError,'degeneradas'):
            GazeModel.fit(rows,TRAIN_TARGETS,CONTEXT)
        rows=[features(target_face((x,.5+.01*(y-.5)))) for x,y in TRAIN_TARGETS]
        with self.assertRaisesRegex(ValueError,'Rango ocular insuficiente'):
            GazeModel.fit(rows,TRAIN_TARGETS,CONTEXT)

    def test_other_host_legacy_context_and_changed_camera_are_incompatible(self):
        from screen_mapping import same_context
        self.assertTrue(same_context(CONTEXT,CONTEXT))
        for change in (dict(capture_host="a"*64),dict(camera_index=1),dict(frame_width=1280)):
            self.assertFalse(same_context(CONTEXT,CONTEXT|change))
        legacy={k:v for k,v in CONTEXT.items() if k!="capture_host"}
        self.assertFalse(same_context(legacy,CONTEXT))
        # Se conserva el registro; sólo se bloquea activación en entorno nuevo.
        self.assertEqual(GazeModel.fit([features(target_face(p)) for p in TRAIN_TARGETS],
                                     TRAIN_TARGETS,legacy).record["context"],legacy)

    def test_head_change_still_blocks_absolute_capture(self):
        session=GazeCalibrationSession(CONTEXT)
        session.points[4]=self.point(.5,.5)
        point=self.point(.1,.1)
        point['features'][4]=.9
        self.assertIn('cabeza cambió',session._point_problem(0,point))
