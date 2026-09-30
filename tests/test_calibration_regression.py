"""Regresión: tiempo virtual, señales continuas y recuperación humana no instantánea."""
import tempfile
import unittest
from pathlib import Path
from calibration_session import CalibrationSession
from application_controller import ApplicationController
from profile_manager import ProfileManager
from profiles import ProfileStore
from config import ROOT, load_config
from face_data import FaceData
from gesture_signals import GESTURE_SIGNALS
from test_adaptive_session import NEUTRAL, ACTIVE


class CalibrationRegressionTests(unittest.TestCase):
    def setUp(self):
        self.ms=1000
        self.config=load_config()
        self.config.calibration.countdown_s=.1
        self.session=CalibrationSession({"user_id":"regression"},self.config,self.clock)
        self.session.start()

    def clock(self): return self.ms/1000

    def feed(self, values=None, detected=True, step=50, blends=()):
        self.ms+=step
        face=FaceData(detected,timestamp_ms=self.ms,blendshapes=blends,**(NEUTRAL | (values or {})))
        self.session.update(face)
        return face

    def capture(self, holes=False, step=50, weak=None):
        completed={key:[] for key in GESTURE_SIGNALS}
        for frame in range(4000):
            s=self.session
            if s.state in ("error","measured"): break
            values=ACTIVE.get(s.gesture_id,{}) if s.stage=="active" and s.gesture_id!=weak else {}
            # Una pérdida de 50 ms cada 650 ms no debe borrar todo el progreso.
            self.feed(values,detected=not holes or frame%13!=12,step=step)
            for key,model in s.models.items():
                n=len(model.active_samples)
                if n and (not completed[key] or completed[key][-1]!=n): completed[key].append(n)
        return completed

    def test_complete_calibration_session_advances_all_phases(self):
        for holes in (False,True):
            with self.subTest(temporary_loss=holes):
                self.setUp()
                completed=self.capture(holes)
                s=self.session
                self.assertEqual(s.state,"measured",s.snapshot())
                for key in GESTURE_SIGNALS: self.assertEqual(completed[key],[1,2,3])
                s.validate()
                for _ in range(45): self.feed()
                for key in GESTURE_SIGNALS:
                    self.assertFalse(s.validator.neutral)
                    # El humano sigue sosteniendo 1.2 s; no suelta al recibir el evento.
                    for _ in range(24): self.feed(ACTIVE[key])
                    self.assertIsNone(s.validator.error,(key,s.snapshot()))
                    # Retorno gradual de 0.6 s, sin exigir liberación instantánea.
                    for frame in range(12):
                        values={channel:NEUTRAL[channel]+(value-NEUTRAL[channel])*(11-frame)/12
                                for channel,value in ACTIVE[key].items()}
                        self.feed(values)
                    for _ in range(45): self.feed()
                    self.assertIsNone(s.validator.error,(key,s.snapshot()))
                self.assertEqual(s.state,"validated")
                with tempfile.TemporaryDirectory(dir=ROOT) as temp:
                    manager=ProfileManager(ProfileStore(Path(temp)/"profiles"))
                    controller=ApplicationController(manager,data_dir=temp,clock=self.clock)
                    controller.wizard=s
                    controller.save_calibration()
                    self.assertEqual(controller.state,"PREVIEW")
                    saved=manager.store.load("regression")
                    self.assertTrue(saved["validation"]["passed"])
                    self.assertEqual(len(saved["validation"]["recognized"]),6)

    def test_valid_five_fps_waits_for_minimum_samples(self):
        completed=self.capture(step=200)
        self.assertEqual(self.session.state,"measured",self.session.snapshot())
        for key in GESTURE_SIGNALS: self.assertEqual(completed[key],[1,2,3])

    def test_isolated_loss_does_not_restart_baseline(self):
        self.config.calibration.measuring_s=1
        self.session=CalibrationSession({"user_id":"regression"},self.config,self.clock)
        self.session.start()
        for frame in range(50):
            self.feed(detected=frame%10!=9)
            if self.session.gesture_id: break
        self.assertEqual(self.session.gesture_id,"LEFT_WINK")

    def test_timeout_retry_and_optional_gesture_recover(self):
        for _ in range(680): self.feed(detected=False)
        self.assertEqual(self.session.state,"error")
        self.assertIn("Tiempo agotado",self.session.snapshot()["error"])
        self.session.repeat()
        self.session.set_enabled("RIGHT_BROW",False)
        self.capture()
        self.assertEqual(self.session.state,"measured")
        self.assertEqual(self.session.candidate["settings"]["actions"]["bindings"]["RIGHT_BROW"],"NONE")

    def test_missing_blendshapes_have_explicit_timeout_and_recover(self):
        self.config.calibration.brow_signal_source="BLENDSHAPE"
        self.session=CalibrationSession({"user_id":"regression"},self.config,self.clock,
            enabled={key:key=="BOTH_BROWS" for key in GESTURE_SIGNALS})
        self.session.start()
        for _ in range(680): self.feed()
        self.assertEqual(self.session.state,"error")
        self.assertIn("BLENDSHAPE",self.session.snapshot()["error"])
        self.session.repeat()
        for _ in range(1000):
            if self.session.state in ("measured","error"): break
            active=self.session.stage=="active"
            blends=(("browInnerUp",.1),("browOuterUpLeft",.7 if active else .1),
                    ("browOuterUpRight",.7 if active else .1),("browDownLeft",0.),("browDownRight",0.))
            self.feed(ACTIVE["BOTH_BROWS"] if active else {},blends=blends)
        self.assertEqual(self.session.state,"measured",self.session.snapshot())

    def test_weak_gesture_retries_without_losing_previous(self):
        self.capture(weak="RIGHT_BROW")
        self.assertEqual(self.session.state,"error")
        previous=self.session.models["LEFT_BROW"].to_record()
        self.session.repeat()
        self.capture()
        self.assertEqual(self.session.state,"measured")
        self.assertEqual(previous,self.session.models["LEFT_BROW"].to_record())

    def test_validation_wrong_gesture_and_never_released_timeout(self):
        self.capture()
        s=self.session
        s.validate()
        for _ in range(45): self.feed()
        for _ in range(24): self.feed(ACTIVE["LEFT_WINK"])
        self.assertIsNone(s.validator.error)
        self.feed(ACTIVE["LEFT_WINK"] | ACTIVE["MOUTH_OPEN"])
        self.assertIsNone(s.validator.error)  # El tiempo de retorno no cuenta como gesto incorrecto.
        for _ in range(4): self.feed(ACTIVE["LEFT_WINK"])
        for _ in range(15): self.feed(ACTIVE["MOUTH_OPEN"])
        self.assertIsNotNone(s.validator.error)
        s.repeat()
        for _ in range(45): self.feed()
        for _ in range(650): self.feed(ACTIVE["LEFT_WINK"])
        self.assertIn("Tiempo agotado",s.snapshot()["error"])

    def test_duplicates_do_not_advance_and_still_timeout(self):
        face=self.feed()
        for _ in range(650):
            self.ms+=50
            self.session.update(face)
        self.assertEqual(self.session.state,"error")
        self.assertIsNone(self.session.baseline)

    def test_debug_trace_reports_transitions_without_frame_spam(self):
        with self.assertLogs("calibration_session",level="DEBUG") as logs:
            self.capture()
        self.assertTrue(any("activation_threshold=" in row and "neutral_reference=" in row for row in logs.output))
        self.assertTrue(any("'measured'" in row for row in logs.output))
        self.assertLess(len(logs.output),300)

    def test_noisy_signals_and_brief_neutral_excursions_advance(self):
        s=self.session
        for frame in range(4000):
            if s.state in ("measured","error"): break
            values=NEUTRAL | (ACTIVE.get(s.gesture_id,{}) if s.stage=="active" else {})
            # Ruido continuo pequeño, más una excursión aislada durante retorno.
            values={key:value+(.0004 if frame%2 else -.0004) for key,value in values.items()}
            if s.stage=="neutral" and frame%13==12:
                values.update(ACTIVE[s.gesture_id])
            self.feed(values)
        self.assertEqual(s.state,"measured",s.snapshot())
        for model in s.models.values():
            self.assertEqual(len(model.active_samples),3)
            self.assertTrue(model.usable)


if __name__=="__main__": unittest.main()
