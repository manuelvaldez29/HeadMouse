"""Precisión independiente y recuperación de calibración; sólo datos sintéticos."""
import math
import unittest
from copy import deepcopy
import numpy as np
from gaze_mapping import (GazeCalibrationSession, GazeModel, TRAIN_TARGETS,
                          VALIDATION_TARGETS, position_errors, precision_summary, features)
from test_gaze_mapping import CONTEXT, completed_session, target_face


class ValidationPrecisionTests(unittest.TestCase):
    def test_28_stable_samples_can_have_exactly_400px_error(self):
        context=CONTEXT|dict(width=2940,height=1912,dpr=2.)
        prediction=(.7,.7-400.5/1911)
        result=position_errors([prediction]*28,(.7,.7),context)
        self.assertAlmostEqual(result['error_mean_px'],400.5)
        self.assertAlmostEqual(result['error_y_px'],400.5)
        self.assertEqual(result['error_x_px'],0.)
        self.assertEqual(result['target_px'],[.7*2939,.7*1911])
        self.assertAlmostEqual(result['signed_bias_px'][1],-400.5)

    def test_normalized_pixels_use_physical_extent_once_at_any_dpi(self):
        for dpr in (1.,1.5,2.):
            r=position_errors([[.7,.2]],(.3,.7),CONTEXT|dict(dpr=dpr))
            self.assertAlmostEqual(r['error_x_px'],.4*1919)
            self.assertAlmostEqual(r['error_y_px'],.5*1079)
            self.assertAlmostEqual(r['error_mean_px'],math.hypot(.4*1919,.5*1079))

    def test_global_400px_error_fails_without_changing_limits(self):
        points=[dict(error_mean_px=e) for e in (477.976782,332.340763,335.497241,446.292522,410.391247)]
        r=precision_summary(points,CONTEXT|dict(width=2940,height=1912))
        self.assertAlmostEqual(r['error_mean_px'],400.499711,places=5)
        self.assertAlmostEqual(r['worst_error_px'],477.976782)
        self.assertFalse(r['passed'])

    def test_training_report_preserves_canonical_target_association(self):
        s=completed_session()
        report=s.model.record['training_report']
        for index,p in enumerate(report['points']):
            self.assertEqual(p['point_index'],index)
            self.assertEqual(tuple(p['target']),TRAIN_TARGETS[index])
            self.assertLess(p['error_mean_px'],10)
        self.assertTrue(report['passed'])
        for p in s.validation_points.values():
            self.assertEqual(tuple(p['target']),VALIDATION_TARGETS[p['point_index']])
            self.assertNotIn(tuple(p['target']),TRAIN_TARGETS)
            self.assertIn('ocular_median',p)
            self.assertIn('predicted_mean_px',p)

    def test_incoherent_vertical_signal_blocks_before_validation(self):
        s=completed_session()
        s.phase='training';s.validation_points.clear()
        # Hay rango Y y señal estable, pero su patrón no codifica la fila objetivo.
        ys=(.3,.65,.4,.7,.3,.6,.45,.66,.3)
        for i,y in enumerate(ys):
            s.points[i]['features']=features(target_face((TRAIN_TARGETS[i][0],y))).tolist()
            # También corromper comisuras: ninguna referencia debe codificar Y.
            for source in ('left','right','both'):
                s.points[i]['reference_comparison'][source+'_canthi']['median']=.5+.2*(y-.5)
        s._advance()
        self.assertEqual(s.state,'invalid')
        self.assertEqual(s.outcome,'training_rejected')
        self.assertEqual(s.phase,'training')
        self.assertEqual(s.validation_points,{})
        with self.assertRaises(ValueError):s.result()

    def test_failed_fourth_repeat_keeps_other_measurements_and_reports_complete(self):
        s=completed_session(wrong_validation=True)
        previous=deepcopy(s.validation_points)
        training=deepcopy(s.points)
        s.repeat(3)
        self.assertEqual(s.state,'countdown')
        self.assertEqual(len(s.validation_points),4)
        self.assertNotIn(3,s.validation_points)
        # Captura de 28 frames estables sintéticos, con sesgo real de predicción.
        s.countdown_s=s.settle_s=0;s.duration_s=.2;s.min_samples=28
        now=s.clock()
        s.clock=lambda:now
        s.started=now
        for i in range(28):
            now+=.01
            s.update(target_face((.5,.5),round(now*1000)))
        self.assertEqual(s.state,'invalid')
        self.assertEqual(s.index,3)
        self.assertEqual(s.outcome,'validation_rejected')
        self.assertTrue(s.snapshot()['validation_complete'])
        self.assertIn('completa 5/5',s.message)
        self.assertEqual(s.validation_points[3]['samples'],28)
        self.assertEqual(s.points,training)  # validar no reentrena
        for i in (0,1,2,4):self.assertEqual(s.validation_points[i],previous[i])
        s.review_training()
        self.assertEqual(s.phase,'training')
        self.assertEqual(s.state,'countdown')
        self.assertEqual(len(s.points),8)
        self.assertEqual(s.validation_points,{})
        self.assertIsNone(s.model)
        self.assertFalse(s.snapshot()['can_save'])

    def test_validation_bias_is_not_used_to_retrain(self):
        good=completed_session();bad=completed_session(wrong_validation=True)
        self.assertEqual(good.model.record['coefficients'],bad.model.record['coefficients'])
        self.assertTrue(good.model.record['validated'])
        self.assertFalse(bad.model.record['validated'])
