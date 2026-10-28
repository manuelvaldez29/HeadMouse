"""Activación Qt sostenida y paridad facial: cámara y entrada del SO simuladas."""
from copy import deepcopy
from dataclasses import asdict, replace
import json
import unittest
from unittest.mock import Mock, patch

import test_gui
import test_gaze_save
import test_adaptive_session
from test_eye_gui import EyeVision
from test_gaze_mapping import completed_session, CONTEXT
from test_core import calibration
from calibration_session import CalibrationSession
from config import load_config
from face_data import FaceData
from profiles import gesture_profile, save_gesture_mode


def measured_pair():
    """Misma secuencia facial completa en ambas modalidades; iris ausente."""
    fixture=test_adaptive_session.AdaptiveSessionTests()
    fixture.setUp()
    configs=[deepcopy(fixture.config),deepcopy(fixture.config)]
    configs[1].ui.tracking_method="eye_absolute"
    configs[1].ui.unified_eyes=True
    sessions=[CalibrationSession({"user_id":"synthetic"},c,fixture.clock) for c in configs]
    for s in sessions:s.start()
    for _ in range(1200):
        first=sessions[0]
        if first.state in ("measured","error"):break
        values=test_adaptive_session.ACTIVE.get(first.gesture_id,{}) if first.stage=="active" else {}
        face=fixture.face(values)
        # Se mueven párpados/cejas sin una fijación ocular utilizable.
        assert not face.gaze_available
        for s in sessions:s.update(face)
        assert sessions[0]._state_key()==sessions[1]._state_key()
    assert all(s.state=="measured" for s in sessions),[s.snapshot() for s in sessions]
    for s in sessions:s.validate()
    for _ in range(1600):
        v=sessions[0].validator
        if v.passed or v.error:break
        key=next((k for k,spec in test_adaptive_session.GESTURE_SIGNALS.items()
                  if not v.neutral and spec.event_type==v.gestures[v.index][0]),None)
        face=fixture.face(test_adaptive_session.ACTIVE.get(key,{}))
        for s in sessions:s.update(face)
    assert all(s.state=="validated" for s in sessions),[s.snapshot() for s in sessions]
    return sessions


class GestureModeAuditTests(unittest.TestCase):
    def fixture(self):
        f=test_gaze_save.SaveControllerRegressionTests()
        f.setUp();self.addCleanup(f.doCleanups)
        return f

    def test_identical_winks_brows_and_validation_without_iris_for_both_methods(self):
        nose,eyes=measured_pair()
        self.assertEqual(nose.result()["gesture_calibrations"],eyes.result()["gesture_calibrations"])
        self.assertEqual(nose.result()["thresholds"],eyes.result()["thresholds"])
        self.assertEqual(nose.validator.recognized,eyes.validator.recognized)
        self.assertEqual(len(eyes.validator.recognized),6)
        self.assertEqual(eyes.diagnostic()["result"],"validated")
        self.assertFalse(eyes.diagnostic()["iris_required"])
        self.assertGreater(eyes.diagnostic()["accepted_samples"],0)

    def test_eye_gesture_save_reload_restart_and_failed_save_preserve_nose_and_models(self):
        f=self.fixture();c=f.c;c.select_control_method("eyes")
        before=deepcopy(c.profile)
        candidate=measured_pair()[1].result()
        candidate["user_id"]=c.profile["user_id"]
        candidate["settings"]=asdict(c.config)
        c.wizard=Mock();c.wizard.result.return_value=candidate
        path=f.store.path(c.profile["user_id"]);original=path.read_bytes()
        with patch("profiles.replace_with_retry",side_effect=PermissionError("archivo ocupado")),self.assertLogs(level="ERROR"):
            with self.assertRaisesRegex(RuntimeError,"gestos de Ojos.*archivo ocupado"):
                c.save_calibration()
        self.assertEqual(path.read_bytes(),original)
        self.assertEqual(c.profile,before)
        self.assertIsNotNone(c.wizard)
        c.save_calibration()
        self.assertTrue(c._actions_ready())
        saved=f.store.load(c.profile["user_id"])
        from profiles import GESTURE_PROFILE_KEYS
        for key in GESTURE_PROFILE_KEYS:
            self.assertEqual(gesture_profile(saved,"nose").get(key),gesture_profile(before,"nose").get(key))
        for key in ("tracking_calibrations","absolute_calibration"):
            self.assertEqual(saved[key],before[key])
        c.stop_camera();c.select_profile(saved["user_id"])
        self.assertTrue(c._actions_ready())
        self.assertEqual(gesture_profile(c.profile,"eyes")["thresholds"],candidate["thresholds"])
        f.factory.assert_not_called()

    def test_pending_eye_actions_allow_movement_but_cannot_click_or_type(self):
        from gesture_engine import GestureEvent
        f=self.fixture();c=f.c;c.select_control_method("eyes");c.start_diagnostic()
        self.assertFalse(c._actions_ready())
        with self.assertRaises(ValueError):c.activate_control(False)
        f.factory.assert_not_called()
        c.emergency.clear();c.activate_control(True)
        self.assertTrue(c.control.movement_only)
        self.assertFalse(c.gesture.enabled_gestures)
        c.gesture.update=Mock(return_value=[GestureEvent("LEFT_CLICK"),GestureEvent("RIGHT_CLICK"),GestureEvent("MOUTH_OPEN"),GestureEvent("CURSOR_MOVE",5,0)])
        with patch("control_engine.time.monotonic",return_value=f.now):c.step()
        f.backend.moveRel.assert_called()
        f.backend.click.assert_not_called();f.backend.hotkey.assert_not_called()
        c.emergency_stop();c.step();self.assertIsNone(c.control)

    def test_each_wink_can_be_detected_without_iris_and_motion_waits_for_stable_recovery(self):
        from gesture_engine import GestureEngine
        from tracking import create_strategy
        from tracking_calibration import TrackingCalibration
        from test_eye_tracking import eye_face
        absolute=completed_session().result()
        for method,record in (("eye",TrackingCalibration().record()),("eye_absolute",absolute)):
            for side,event in (("left","LEFT_CLICK"),("right","RIGHT_CLICK")):
                with self.subTest(method=method,side=side):
                    now=[1.]
                    engine=GestureEngine(None,calibration=calibration(),strategy=create_strategy(method,record),clock=lambda:now[0])
                    observed=[]
                    for stamp in (1000,1100):
                        now[0]=stamp/1000
                        face=replace(eye_face(.7,.5,stamp),**{f"eye_{side}_ratio":.01,f"{side}_gaze_x":None,f"{side}_gaze_y":None})
                        events=engine.update(face);observed += [e.type for e in events]
                        self.assertFalse(any(e.type in ("CURSOR_MOVE","CURSOR_ABSOLUTE") for e in events))
                    self.assertIn(event,observed)
                    for stamp in (1200,1300,1350):
                        now[0]=stamp/1000
                        events=engine.update(eye_face(.7,.5,stamp))
                        self.assertFalse(any(e.type in ("CURSOR_MOVE","CURSOR_ABSOLUTE") for e in events))
                    now[0]=1.4
                    self.assertTrue(any(e.type in ("CURSOR_MOVE","CURSOR_ABSOLUTE") for e in engine.update(eye_face(.7,.5,1400))))

    def test_camera_resolution_and_other_host_are_not_reported_as_ready(self):
        f=self.fixture();c=f.c;c.config.ui.tracking_method="eye_absolute"
        c.config.ui.unified_eyes=True
        record=c._tracking_record()
        record["context"]["capture_host"]="a"*64
        self.assertFalse(c.snapshot(False)["tracking_calibrated"])
        self.assertTrue(any("equipo" in r for r in c.snapshot(False)["activation_blockers"]))
        record["context"]["capture_host"]=CONTEXT["capture_host"]
        record["context"]["frame_width"]=1280
        self.assertFalse(c.snapshot(False)["tracking_calibrated"])
        f.factory.assert_not_called()

    def test_telemetry_identifies_method_bank_rejections_and_signal_without_images(self):
        f=self.fixture();c=f.c;c.select_control_method("eyes");c.start_calibration()
        c.wizard.state="measuring"
        f.now=round(f.now+.05,3)
        c.wizard.update(FaceData(False,timestamp_ms=round(f.now*1000)))
        c._flush_calibration_telemetry()
        records=[json.loads(line) for line in next((f.root/"calibration").glob("*.jsonl")).read_text(encoding="utf-8").splitlines()]
        d=next(r for r in records if r["experiment"]=="gesture_diagnostic")
        self.assertEqual(d["gesture_bank"],"eyes");self.assertEqual(d["public_method"],"eyes")
        self.assertEqual(d["rejected_samples"],1);self.assertTrue(d["rejection_reasons"])
        for field in ("landmarks","image","frame","iris_points"):self.assertNotIn(field,d)
        f.factory.assert_not_called()


@unittest.skipUnless(test_gui.QT_AVAILABLE,"Requiere PySide6")
class ActivationGUIAuditTests(unittest.TestCase):
    setUpClass=classmethod(test_gui.GUITests.setUpClass.__func__)
    setUp=test_gui.GUITests.setUp
    tearDown=test_gui.GUITests.tearDown
    wait=test_gui.GUITests.wait
    select_calibrated=test_gui.GUITests.select_calibrated

    def prepare_eyes(self):
        self.select_calibrated();self.controller.vision_factory=EyeVision
        self.bridge.request("select_control_method",method="eyes")
        self.wait(lambda:self.bridge.snapshot().get("public_method")=="eyes")
        model=completed_session().result()
        screen=self.window.screen_context()
        model["context"]={k:v for k,v in screen.items() if k in ("width","height","dpr","screen","display")}
        model["context"].update({k:CONTEXT[k] for k in ("camera_index","frame_width","frame_height","capture_host")})
        model["context"].update(frame_width=320,frame_height=240)
        from ocular_profiles import with_calibration
        self.controller.profile=with_calibration(self.controller.profile,model)
        self.controller.profiles.store.save(self.controller.profile)
        self.backend.size.return_value=(model["context"]["width"],model["context"]["height"])
        self.backend.position.return_value=(model["context"]["width"]/2,model["context"]["height"]/2)
        self.bridge.request("start_diagnostic")
        self.wait(lambda:self.bridge.snapshot().get("state")=="DIAGNOSTIC")

    def test_confirmed_eye_activation_survives_repeated_refresh_and_stops_on_real_context_change(self):
        from PySide6.QtWidgets import QMessageBox
        from PySide6.QtTest import QTest
        self.prepare_eyes();self.window.refresh()
        self.assertIn("listo para confirmar",self.window.home_state.text())
        self.assertIn("Sólo movimiento",self.window.home_hint.text())
        with patch.object(QMessageBox,"question",return_value=QMessageBox.StandardButton.No):self.window.activate()
        self.backend_factory.assert_not_called()
        with patch.object(QMessageBox,"question",return_value=QMessageBox.StandardButton.Yes):self.window.home_primary()
        self.wait(lambda:self.bridge.snapshot().get("control_enabled"))
        for _ in range(12):
            self.window.refresh();QTest.qWait(30);self.app.processEvents()
            self.assertTrue(self.bridge.snapshot()["control_enabled"])
        self.assertIn("ACTIVO",self.window.home_state.text())
        screen=self.window.screen_context()
        with patch.object(self.window,"screen_context",return_value=screen|dict(dpr=2.)):
            self.window.refresh()
            self.wait(lambda:not self.bridge.snapshot()["control_enabled"])
        self.assertIn("control detenido",self.bridge.snapshot()["message"])

    def test_camera_and_iris_requirements_are_visible_in_home(self):
        self.prepare_eyes()
        self.controller.vision_factory=test_gui.FakeVision
        self.bridge.request("stop_camera")
        self.wait(lambda:not self.bridge.snapshot()["camera"])
        self.window.refresh()
        self.assertIn("requisitos pendientes",self.window.home_state.text())
        self.assertIn("Cámara",self.window.home_hint.text())
        self.backend_factory.assert_not_called()

    def test_nose_confirmed_activation_is_unchanged_and_f8_revokes(self):
        from PySide6.QtWidgets import QMessageBox
        self.select_calibrated();self.window.refresh()
        with patch.object(QMessageBox,"question",return_value=QMessageBox.StandardButton.Yes):self.window.activate()
        self.wait(lambda:self.bridge.snapshot().get("control_enabled"))
        self.assertEqual(self.bridge.snapshot()["public_method"],"nose")
        self.window.stop_immediately()
        self.wait(lambda:not self.bridge.snapshot()["control_enabled"])
