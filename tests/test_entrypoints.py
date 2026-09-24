"""Arranque y limpieza de scripts usando solo dobles de cámara/SO."""
import importlib
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from test_core import calibration


class EntryPointTests(unittest.TestCase):
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
