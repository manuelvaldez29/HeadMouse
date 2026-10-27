"""Arranque y limpieza de scripts usando solo dobles de cámara/SO."""
import importlib
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from test_core import calibration


class EntryPointTests(unittest.TestCase):
    def test_cli_does_not_turn_nasal_approval_into_ocular_click_permission(self):
        import main
        from tracking_calibration import TrackingCalibration
        profile=calibration()|dict(validation={"passed":True},settings={"ui":{"tracking_method":"eye"}},
            tracking_calibration=TrackingCalibration().record())
        vision_class,control_class=Mock(),Mock()
        with patch.object(main,"ProfileStore") as store,patch.dict(sys.modules,{
            "vision_engine":SimpleNamespace(VisionEngine=vision_class),
            "control_engine":SimpleNamespace(ControlEngine=control_class),"pyautogui":Mock()}),self.assertLogs(level="ERROR"):
            store.return_value.load.return_value=profile
            self.assertEqual(main.main(["--user","julian"]),1)
        vision_class.assert_not_called();control_class.assert_not_called()

    def test_relative_cli_rejects_incompatible_source_camera_before_backend(self):
        import main
        import numpy as np
        from tracking_calibration import TrackingCalibration
        profile=calibration()
        from profiles import save_gesture_mode
        profile=save_gesture_mode(profile,calibration()|dict(validation={"passed":True}),"eye")
        profile["settings"]={"ui":{"tracking_method":"eye","eye_source":"left"}}
        profile["tracking_calibrations"]={"left":TrackingCalibration(eye_source="left",
            camera_context=dict(camera_index=0,frame_width=640,frame_height=480)).record()}
        for camera in (None,1):
            vision=Mock(error=None)
            vision.get_frame.return_value=np.zeros((240,320,3),dtype=np.uint8)
            vision_class,control_class=Mock(return_value=vision),Mock()
            with patch.object(main,"ProfileStore") as store, \
                 patch.object(main,"SessionMetrics"), \
                 patch.dict(sys.modules,{"vision_engine":SimpleNamespace(VisionEngine=vision_class),
                     "control_engine":SimpleNamespace(ControlEngine=control_class),"cv2":Mock(),"pyautogui":Mock()}), \
                 self.assertLogs(level="ERROR"):
                store.return_value.load.return_value=profile
                args=["--user","julian"]+(["--camera",str(camera)] if camera is not None else [])
                self.assertEqual(main.main(args),1)
            control_class.assert_not_called()
            if camera is not None:
                vision_class.assert_not_called()
            else:
                vision.stop.assert_called_once()

    def test_cli_gesture_save_preserves_both_eye_models(self):
        import calibrate
        import calibration_session
        from config import load_config
        from profiles import validate_profile
        from test_gaze_mapping import completed_session
        from tracking_calibration import TrackingCalibration
        from dataclasses import asdict
        original=calibration()
        original["tracking_calibration"]=TrackingCalibration().record()
        original["absolute_calibration"]=completed_session().result()
        candidate=calibration()
        candidate["settings"]=asdict(load_config())
        candidate["validation"]={"passed":True}
        vision=Mock(error=None)
        session=Mock(state="validated",telemetry=[])
        session.result.return_value=candidate
        cv2=Mock()
        cv2.waitKey.return_value=32
        with patch.dict(sys.modules,{"cv2":cv2,"vision_engine":SimpleNamespace(VisionEngine=Mock(return_value=vision))}), \
             patch.object(calibration_session,"CalibrationSession",return_value=session), \
             patch.object(calibrate,"draw_adaptive_calibration"), patch.object(calibrate,"ProfileStore") as store:
            store.return_value.load.return_value=original
            calibrate.run("julian")
            saved=store.return_value.save.call_args.args[0]
        self.assertEqual(saved["tracking_calibration"],original["tracking_calibration"])
        self.assertEqual(saved["absolute_calibration"],original["absolute_calibration"])
        validate_profile(saved)
        vision.stop.assert_called_once()

    def test_imports_and_help_without_native_dependencies(self):
        # Fallaría si importar los entrypoints intentara usar bibliotecas nativas.
        with patch.dict(sys.modules, {"cv2": None, "numpy": None, "mediapipe": None,
                                     "pyautogui": None}):
            for name in ("main", "calibrate", "debug_cursor"):
                module = importlib.import_module(name)
                with self.subTest(name=name), patch("sys.stdout"), self.assertRaises(SystemExit) as exc:
                    module.main(["--help"])
                self.assertEqual(exc.exception.code, 0)

    def test_main_success_and_initialization_failures_cleanup(self):
        import main
        for failure in (None, "vision", "control"):
            with self.subTest(failure=failure):
                vision = Mock(error=None)
                vision.is_alive.return_value = True
                vision_class = Mock(return_value=vision)
                control = Mock(error=None)
                control.get_stats.return_value = SimpleNamespace(running=False)
                control_class = Mock(return_value=control)
                if failure == "vision":
                    vision.wait_ready.side_effect = RuntimeError("camera failed")
                elif failure == "control":
                    control_class.side_effect = RuntimeError("backend failed")
                metrics = Mock()
                cv2 = Mock()
                modules = {"vision_engine": SimpleNamespace(VisionEngine=vision_class),
                           "control_engine": SimpleNamespace(ControlEngine=control_class),
                           "cv2": cv2, "pyautogui": Mock()}
                with patch.dict(sys.modules, modules), \
                        patch.object(main, "ProfileStore") as store, \
                        patch.object(main, "SessionMetrics", return_value=metrics), \
                        self.assertLogs(level="INFO"):
                    store.return_value.load.return_value = calibration()
                    result = main.main(["--user", "julian", "--no-overlay"])
                self.assertEqual(result, 0 if failure is None else 1)
                vision.stop.assert_called_once()
                metrics.close.assert_called_once()
                cv2.destroyAllWindows.assert_called_once()
                if failure is None:
                    control.stop.assert_called_once()

    def test_calibrate_startup_failure_cleanup(self):
        import calibrate
        vision = Mock()
        vision.wait_ready.side_effect = RuntimeError("camera failed")
        cv2 = Mock()
        with patch.dict(sys.modules, {"cv2": cv2, "numpy": Mock(),
                                      "vision_engine": SimpleNamespace(VisionEngine=Mock(return_value=vision))}):
            with self.assertRaises(RuntimeError):
                calibrate.run("test")
        vision.stop.assert_called_once()
        cv2.destroyAllWindows.assert_called_once()

    def test_main_check_never_constructs_camera_or_control(self):
        import main
        vision_class, control_class = Mock(), Mock()
        with patch.dict(sys.modules, {
            "vision_engine": SimpleNamespace(VisionEngine=vision_class),
            "control_engine": SimpleNamespace(ControlEngine=control_class),
            "cv2": Mock(), "pyautogui": Mock()}), patch.object(main, "ProfileStore") as store:
            store.return_value.load.return_value = calibration()
            with self.assertLogs(level="INFO"):
                self.assertEqual(main.main(["--user", "julian", "--check"]), 0)
        vision_class.assert_not_called()
        control_class.assert_not_called()


if __name__ == "__main__":
    unittest.main()
