import json
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import Mock

from action_mapping import ActionMapping, DEFAULT_MAPPING, gesture_identity
from application_controller import ApplicationController
from calibration_session import CalibrationSession
from config import ROOT, load_config
from experiment_engine import ExperimentEngine, JitterMeasurement, ResultStore
from face_data import FaceData
from gesture_engine import GestureEvent, GestureEngine
from profile_manager import ProfileManager
from profiles import ProfileStore
from tracking import TrackingStrategy, NoseTrackingStrategy, create_strategy
from test_core import calibration


class DesktopLogicTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.manager = ProfileManager(ProfileStore(self.root / "profiles"))

    def test_mapping_defaults_and_all_actions(self):
        from action_mapping import ACTIONS
        for gesture, expected in DEFAULT_MAPPING.items():
            self.assertEqual(ActionMapping().resolve(GestureEvent(gesture, gesture=gesture)).type, expected)
        for action in ACTIONS:
            mapping = DEFAULT_MAPPING | {"LEFT_WINK": action}
            self.assertEqual(ActionMapping(mapping).resolve(GestureEvent("LEFT_CLICK")).type, action)
        with self.assertRaises(ValueError):
            ActionMapping({"LEFT_WINK": "shell_command"})

    def test_nose_strategy_preserves_coordinates(self):
        strategy = create_strategy()
        self.assertIsInstance(strategy, TrackingStrategy)
        face = FaceData(True, nose_x=.23, nose_y=.71)
        self.assertEqual(strategy.position(face), (.23,.71))
        with self.assertRaises(ValueError):
            create_strategy("pose")

    def test_profiles_draft_rename_select_delete(self):
        p = self.manager.create("Julián")
        self.assertEqual(self.manager.status(p), "Sin calibrar")
        self.assertNotIn("thresholds", p)
        self.assertNotIn("calibrated_at", p)
        with self.assertRaises(ValueError):
            GestureEngine(None, calibration=p)
        renamed = self.manager.rename(p["user_id"], "Julián escritorio")
        self.assertEqual(renamed["user_id"], p["user_id"])
        self.assertEqual(len(self.manager.list_profiles()), 1)
        with self.assertRaises(ValueError):
            self.manager.delete(p["user_id"])
        self.manager.delete(p["user_id"], True)
        self.assertFalse(self.manager.list_profiles())

    def test_settings_shared_and_invalidate_hold_changes(self):
        p = calibration()
        p["validation"] = {"passed": True}
        self.manager.store.save(p)
        config = load_config()
        config.gesture.sensitivity_x = 120
        config.gesture.sensitivity_y = 60
        config.gesture.blink_hold_ms = 100
        result = self.manager.save_settings(p, asdict(config))
        self.assertEqual(load_config(overrides=result["settings"]).gesture.sensitivity_x, 120)
        self.assertFalse(result["validation"]["passed"])

    def test_axis_sensitivity_does_not_change_legacy_defaults(self):
        now = lambda: 1
        p = calibration()
        config = load_config().gesture
        config.smoothing_alpha = 0
        g = GestureEngine(None, config=config, calibration=p, clock=now)
        first = g.update(FaceData(True, nose_x=.7, nose_y=.7, timestamp_ms=1000))[0]
        self.assertEqual(first.dx, first.dy)
        config.sensitivity_x = 100
        g2 = GestureEngine(None, config=config, calibration=p, clock=now)
        second = g2.update(FaceData(True, nose_x=.7, nose_y=.7, timestamp_ms=1000))[0]
        self.assertEqual(first.dy, second.dy)
        self.assertGreater(second.dx, first.dx)

    def test_experiment_trajectory_clicks_overshoot_and_persistence(self):
        now = [1.]
        engine = ExperimentEngine("p", store=ResultStore(self.root), clock=lambda: now[0], targets=[(500,250)], radius=20)
        engine.click()
        engine.move(100,0,30,10)  # entra
        engine.move(30,0,30,10)   # sale: overshoot
        engine.move(-30,0,30,10)
        now[0] = 2
        engine.click()
        self.assertFalse(engine.active)
        record = json.loads(Path(engine.path).read_text())
        self.assertEqual(record["distance_px"], 160)
        self.assertEqual(record["failed_clicks"], 1)
        self.assertEqual(record["overshoots"], 1)
        self.assertEqual(record["duration_s"], 1)
        self.assertEqual(record["fps_mean"], 30)
        self.assertNotIn("face", record)

    def test_experiment_timeout_and_cancel(self):
        now = [1.]
        e = ExperimentEngine("p", store=ResultStore(self.root), clock=lambda:now[0], timeout_s=1)
        now[0] = 3
        e.tick()
        self.assertEqual(e.results[0]["reason"], "timeout")
        e.cancel()
        self.assertFalse(e.active)
        self.assertEqual(e.results[-1]["reason"], "cancelled")
        manual = ExperimentEngine("demo", source="keyboard", store=ResultStore(self.root))
        manual.move(10, 0)
        manual.cancel()
        self.assertIsNone(manual.results[0]["fps_mean"])
        self.assertIsNone(manual.results[0]["processing_ms_mean"])

    def test_jitter_known_values_and_unique_frames(self):
        now = [1.]
        j = JitterMeasurement(clock=lambda:now[0])
        for idx, x in enumerate((.5,.54,.55,.5,.54)):
            now[0] = 1 + idx*.05
            fd = FaceData(True,nose_x=x,timestamp_ms=int(now[0]*1000))
            j.add(fd)
            j.add(fd)
        summary=j.summary()
        self.assertEqual(summary["samples"], 5)
        self.assertEqual(summary["dead_zone_exits"], 2)
        self.assertAlmostEqual(summary["range_x"], .05)
        self.assertGreater(summary["jitter_rms"], 0)
        self.assertAlmostEqual(summary["mean_deviation"], .026)
        self.assertAlmostEqual(summary["jitter_rms"], (.00145)**.5)

    def test_controller_start_safe_and_diagnostic_never_constructs_backend(self):
        now = [1.]
        vision=Mock(error=None)
        vision.get_face_data.return_value=FaceData(True,timestamp_ms=1000)
        vision.get_fps.return_value=30
        backend_factory=Mock()
        c=ApplicationController(self.manager,Mock(return_value=vision),backend_factory,self.root,lambda:now[0])
        self.assertTrue(c.emergency.is_set())
        p=calibration()
        self.manager.store.save(p)
        c.select_profile("julian")
        c.start_diagnostic()
        c.step()
        backend_factory.assert_not_called()
        with self.assertRaises(ValueError):
            c.activate_control()
        c.shutdown()
        vision.stop.assert_called_once()

    def test_controller_activation_requires_validation_and_can_stop(self):
        import time
        vision=Mock(error=None)
        vision.get_face_data.return_value=FaceData(True,timestamp_ms=int(time.monotonic()*1000))
        backend=Mock()
        backend.size.return_value=(1920,1080)
        c=ApplicationController(self.manager,Mock(return_value=vision),lambda:backend,self.root)
        p=calibration()
        p["validation"]={"passed":True}
        self.manager.store.save(p)
        c.select_profile("julian")
        c.emergency.clear()  # autorización enviada por UI confirmada
        c.activate_control(True)
        self.assertIsNotNone(c.control)
        c.emergency_stop()
        self.assertFalse(c.control.output_allowed.is_set())
        c.step()
        self.assertIsNone(c.control)
        c.shutdown()

    def test_wizard_requires_validation_and_reuses_statistics(self):
        now=[1.]
        cc=load_config()
        cc.calibration.countdown_s=.1
        cc.calibration.measuring_s=.2
        cc.calibration.min_samples=3
        session=CalibrationSession({"user_id":"julian"},cc,lambda:now[0])
        session.start()
        values=[{}, {"eye_left_ratio":.02},{"eye_right_ratio":.03},
                {"brow_left_lift":.4},{"brow_right_lift":.5},{"mouth_open":.3}]
        for phase in range(6):
            count=0
            while session.phase==phase and session.state!="error":
                count+=1
                self.assertLess(count,50)
                now[0]+=.03
                face=replace(FaceData(True,timestamp_ms=int(now[0]*1000),eye_left_ratio=.1,
                                      eye_right_ratio=.12,brow_left_lift=.2,brow_right_lift=.22,mouth_open=.01),**values[phase])
                session.update(face)
        self.assertEqual(session.state,"measured")
        self.assertEqual(session.candidate["thresholds"],calibration()["thresholds"])
        with self.assertRaises(ValueError): session.result()
        session.validate()
        self.assertEqual(session.state,"validation")
        session.repeat()
        self.assertFalse(session.validator.passed)
        def feed(seconds, overrides=None):
            for _ in range(round(seconds/.05)):
                now[0]+=.05
                face=replace(FaceData(True,timestamp_ms=int(now[0]*1000),eye_left_ratio=.1,
                                      eye_right_ratio=.12,brow_left_lift=.2,brow_right_lift=.22,mouth_open=.01),
                             **(overrides or {}))
                session.update(face)
        feed(2.2)
        for overrides in values[1:]+[{"brow_left_lift":.4,"brow_right_lift":.5}]:
            feed(.3,overrides)
            feed(2.2)
        self.assertEqual(session.state,"validated")
        controller=ApplicationController(self.manager,data_dir=self.root,clock=lambda:now[0])
        controller.wizard=session
        controller.save_calibration()
        self.assertEqual(controller.state,"PREVIEW")
        self.assertTrue(controller.profile["validation"]["passed"])
        self.assertTrue(self.manager.store.load("julian")["validation"]["passed"])

    def test_control_all_new_actions_and_none_use_mock(self):
        from control_engine import ControlEngine
        backend=Mock()
        backend.size.return_value=(1000,800)
        control=ControlEngine(Mock(),Mock(),backend=backend)
        for action in ("DOUBLE_CLICK","KEY_ENTER","KEY_ESCAPE","KEY_SPACE","OPEN_START_MENU","NONE"):
            control._execute(GestureEvent(action))
        backend.doubleClick.assert_called_once_with(interval=.1,_pause=False)
        self.assertEqual([call.args[0] for call in backend.press.call_args_list],["enter","esc","space"])
        backend.hotkey.assert_called_once_with("win",_pause=False)
        backend.click.assert_not_called()

    def test_stop_during_startup_prevents_backend_construction(self):
        vision=Mock(error=None)
        backend=Mock()
        c=ApplicationController(self.manager,Mock(return_value=vision),backend,self.root)
        p=calibration(); p["validation"]={"passed":True}
        self.manager.store.save(p)
        c.select_profile("julian")
        c.emergency.clear()
        vision.wait_ready.side_effect=c.emergency_stop
        c.activate_control(True)
        backend.assert_not_called()
        self.assertIsNone(c.control)
        c.shutdown()

    def test_cleanup_attempts_metrics_even_if_camera_stop_fails(self):
        c=ApplicationController(self.manager,data_dir=self.root)
        c.vision=Mock()
        c.vision.stop.side_effect=RuntimeError("driver blocked")
        metrics=Mock()
        c.metrics=metrics
        with self.assertRaises(RuntimeError): c.stop_camera()
        metrics.close.assert_called_once()
        self.assertTrue(c.emergency.is_set())


if __name__=="__main__":
    unittest.main()
