"""Pruebas de fallos y ciclo de vida: nunca abrir cámara ni importar PyAutoGUI."""
import importlib.util
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from calibration_validation import CalibrationValidation, GESTURES
from config import GestureConfig, VisionConfig
from control_engine import ControlEngine
from face_data import FaceData
from gesture_engine import GestureEvent, GestureEngine
from test_core import calibration


class FailSafe(Exception):
    pass


class SafetyTests(unittest.TestCase):
    def setup_control(self):
        backend = Mock()
        backend.FailSafeException = FailSafe
        backend.size.return_value = (1920, 1080)
        vision, gesture = Mock(), Mock()
        gesture.config = GestureConfig()
        vision.get_fps.return_value = 30
        vision.get_face_data.return_value = FaceData(True, timestamp_ms=int(time.monotonic()*1000))
        gesture.update.return_value = [GestureEvent("LEFT_CLICK")]
        control = ControlEngine(vision, gesture, backend=backend)
        backend.reset_mock()
        return control, vision, gesture, backend

    def test_pause_and_toggle_priority(self):
        control, vision, gesture, backend = self.setup_control()
        control._tick()
        backend.click.assert_not_called()
        gesture.update.return_value = [GestureEvent("LEFT_CLICK"), GestureEvent("BOTH_BROWS")]
        control._tick()
        self.assertFalse(control.paused)
        backend.click.assert_not_called()
        gesture.update.return_value = [GestureEvent("LEFT_CLICK")]
        control._tick()
        backend.click.assert_called_once()
        self.assertEqual(vision.get_face_data.call_count, 3)  # un snapshot por tick

    def test_stale_and_missing_face_block_actions_immediately(self):
        for face in (FaceData(False), FaceData(True, timestamp_ms=1)):
            control, vision, gesture, backend = self.setup_control()
            control.toggle_pause()
            vision.get_face_data.return_value = face
            control._tick()
            backend.click.assert_not_called()
            control._face_last_ok = time.monotonic() - 3
            control._tick()
            self.assertTrue(control.paused)

    def test_failsafe_and_unexpected_errors_stop_loop(self):
        for error in (FailSafe(), RuntimeError("backend failed")):
            control, vision, gesture, backend = self.setup_control()
            control.toggle_pause()
            backend.click.side_effect = error
            control._running = True
            with self.assertLogs("control_engine", level="INFO"):
                control._loop()
            self.assertFalse(control.get_stats().running)
            if isinstance(error, RuntimeError):
                self.assertIs(control.error, error)

    def test_validation_recognizes_all_with_real_gesture_engine(self):
        now = [10.]
        engine = GestureEngine(Mock(), calibration=calibration(), clock=lambda: now[0])
        validation = CalibrationValidation(engine, clock=lambda: now[0])

        def feed(duration, **values):
            for _ in range(int(duration / .05)):
                now[0] += .05
                validation.update(FaceData(True, timestamp_ms=int(now[0]*1000),
                                           eye_left_ratio=values.get("eye_left_ratio", .1),
                                           eye_right_ratio=values.get("eye_right_ratio", .12),
                                           brow_left_lift=values.get("brow_left_lift", .2),
                                           brow_right_lift=values.get("brow_right_lift", .22),
                                           mouth_open=values.get("mouth_open", .01)))
        feed(2.2)
        for values in (dict(eye_left_ratio=.02), dict(eye_right_ratio=.03),
                       dict(brow_left_lift=.4), dict(brow_right_lift=.5),
                       dict(mouth_open=.3), dict(brow_left_lift=.4, brow_right_lift=.5)):
            feed(.3, **values)
            feed(2.2)
        self.assertIsNone(validation.error)
        self.assertTrue(validation.passed)
        self.assertEqual(validation.recognized, [key for key, _ in GESTURES])

    def test_validation_timeout_and_wrong_event(self):
        now = [1.]
        gesture = Mock(config=GestureConfig())
        gesture.update.return_value = []
        validation = CalibrationValidation(gesture, clock=lambda: now[0])
        now[0] = 32
        validation.update(FaceData(False))
        self.assertIsNotNone(validation.error)
        validation = CalibrationValidation(gesture, clock=lambda: now[0])
        validation.neutral = False
        gesture.update.return_value = [GestureEvent("RIGHT_CLICK")]
        validation.update(FaceData(True, timestamp_ms=32000))
        self.assertFalse(validation.passed)
        self.assertIsNotNone(validation.error)


class VisionLifecycleTests(unittest.TestCase):
    def setUp(self):
        names = ("cv2", "numpy", "mediapipe", "mediapipe.tasks", "mediapipe.tasks.python",
                 "mediapipe.tasks.python.vision")
        self.modules = {name: MagicMock() for name in names}
        self.modules["mediapipe.tasks"].python = self.modules["mediapipe.tasks.python"]
        self.modules["mediapipe.tasks.python"].vision = self.modules["mediapipe.tasks.python.vision"]
        self.patcher = patch.dict(sys.modules, self.modules)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        spec = importlib.util.spec_from_file_location("isolated_vision", Path(__file__).parents[1]/"vision_engine.py")
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.cv = self.modules["cv2"]
        self.mp = self.module.mp_vision

    def engine(self):
        with patch.object(self.module.VisionEngine, "_ensure_model"):
            return self.module.VisionEngine(config=VisionConfig(capture_failure_limit=1))

    def test_camera_open_failure_releases(self):
        engine = self.engine()
        cap = self.cv.VideoCapture.return_value
        cap.isOpened.return_value = False
        with self.assertLogs("isolated_vision", level="ERROR"):
            engine.run()
        cap.release.assert_called_once()
        self.assertTrue(engine._stopped.is_set())
        with self.assertRaises(RuntimeError):
            engine.wait_ready()

    def test_detector_failure_and_read_failure_release(self):
        for detector_fails in (True, False):
            engine = self.engine()
            cap = self.cv.VideoCapture.return_value
            cap.reset_mock()
            cap.isOpened.return_value = True
            cap.read.return_value = (False, None)
            self.mp.FaceLandmarker.create_from_options.side_effect = RuntimeError("detector") if detector_fails else None
            with self.assertLogs("isolated_vision", level="ERROR"):
                engine.run()
            cap.release.assert_called_once()
            self.assertFalse(engine.get_face_data().detected)
            self.assertTrue(engine.ready.is_set())

    def test_invalid_extraction_and_callback_error(self):
        engine = self.engine()
        self.assertFalse(engine._extract(SimpleNamespace(face_landmarks=[]), 100).detected)
        self.assertFalse(engine._extract(SimpleNamespace(face_landmarks=[[1]]), 100).detected)
        engine._extract = Mock(side_effect=ValueError("bad landmarks"))
        with self.assertLogs("isolated_vision", level="ERROR"):
            engine._on_result(None, None, 100)
        self.assertIsInstance(engine.error, ValueError)
        self.assertTrue(engine._stop_requested.is_set())

    def test_stop_before_start_and_startup_timeout(self):
        engine = self.engine()
        with self.assertRaises(TimeoutError):
            engine.wait_ready(.001)
        engine.stop()
        self.assertTrue(engine._stop_requested.is_set())


if __name__ == "__main__":
    unittest.main()
