import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from calibration_logic import Samples, compute_thresholds, validate_calibration, build_calibration
from config import DEFAULT_THRESHOLDS, GestureConfig, load_config
from control_engine import ControlEngine
from face_data import FaceData
from gesture_engine import GestureEngine, GestureEvent, SingleGestureDetector
from metrics import SessionMetrics
from profiles import ProfileStore


def calibration():
    data = dict(user_id="julian", neutral_nose_x=0.5, neutral_nose_y=0.5,
                neutral=dict(eye_left=.1, eye_right=.12, brow_left=.2, brow_right=.22, mouth=.01),
                gesture_extremes=dict(eye_left_min=.02, eye_right_min=.03,
                                      brow_left_max=.4, brow_right_max=.5, mouth_max=.3))
    data["thresholds"] = compute_thresholds(data)
    return data


class CoreTests(unittest.TestCase):
    def test_config_validation(self):
        for override in ({"gesture": {"smoothing_alpha": 1}}, {"control": {"loop_hz": 0}},
                         {"vision": {"camera_index": True}}, {"typo": 3},
                         {"gesture": {"sensitivity": float("nan")}}):
            with self.subTest(override=override), self.assertRaises(ValueError):
                load_config(overrides=override)

    def test_config_precedence(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory:
            path = Path(directory) / "config.json"
            path.write_text('{"gesture": {"sensitivity": 20, "dead_zone": 0.04}}')
            config = load_config(path, {"gesture": {"sensitivity": 30}})
            self.assertEqual(config.gesture.sensitivity, 30)
            self.assertEqual(config.gesture.dead_zone, .04)

    def test_thresholds_and_noise(self):
        data = calibration()
        self.assertAlmostEqual(data["thresholds"]["blink_left"], .052)
        self.assertFalse(validate_calibration(data))
        data["neutral_variability"] = {"eye_left": .1}
        self.assertTrue(validate_calibration(data))

    def test_invalid_thresholds(self):
        for value in (.1, float("nan"), -.1):
            data = calibration()
            data["thresholds"]["blink_left"] = value
            self.assertTrue(validate_calibration(data))

    def test_profiles_roundtrip(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory:
            store = ProfileStore(directory)
            path = store.save(calibration())
            first = store.load("julian")
            store.save(first)
            self.assertEqual(store.load("julian")["created_at"], first["created_at"])
            self.assertEqual(json.loads(path.read_text())["schema_version"], 2)
            with self.assertRaises(FileNotFoundError):
                store.load("otro")
            for bad in ("../escape", "CON", "a/b", ""):
                with self.assertRaises(ValueError):
                    store.path(bad)

    def test_atomic_save_failure_preserves_previous_profile(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory:
            store = ProfileStore(directory)
            path = store.save(calibration())
            previous = path.read_bytes()
            data = calibration()
            data["neutral_nose_x"] = .6
            with patch("profiles.os.replace", side_effect=OSError("disk error")):
                with self.assertRaises(OSError):
                    store.save(data)
            self.assertEqual(path.read_bytes(), previous)
            self.assertEqual(len(list(Path(directory).iterdir())), 1)

    def test_recalibration_replaces_corrupt_profile_only_on_save(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory:
            store = ProfileStore(directory)
            store.path("julian").write_text("broken json")
            with self.assertLogs("profiles", level="WARNING"):
                store.save(calibration())
            self.assertEqual(store.load("julian")["user_id"], "julian")

    def test_malformed_calibration_structure(self):
        data = calibration()
        data["neutral_variability"] = []
        self.assertTrue(validate_calibration(data))

    def test_legacy_and_corrupt_profile(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory:
            store = ProfileStore(Path(directory) / "profiles")
            legacy = Path(directory) / "calibration.json"
            legacy.write_text(json.dumps(calibration()))
            self.assertEqual(store.load("julian", legacy)["user_id"], "julian")
            with self.assertRaises(ValueError):
                store.load("otro", legacy)
            legacy.write_text('{"thresholds": {}}')
            with self.assertRaises(ValueError):
                store.load("julian", legacy)

    def test_samples_unique_finite_and_robust(self):
        samples = Samples()
        face = FaceData(True, timestamp_ms=1000)
        self.assertTrue(samples.add(face, now=1))
        self.assertFalse(samples.add(face, now=1))
        self.assertFalse(samples.add(replace(face, nose_x=float("nan"), timestamp_ms=1001), now=1.01))
        self.assertFalse(samples.add(replace(face, timestamp_ms=1), now=2))
        samples.eye_left = [.1] * 19 + [999]
        self.assertEqual(samples.median("eye_left"), .1)
        self.assertEqual(samples.mad("eye_left"), 0)
        with self.assertRaises(ValueError):
            Samples().median("mouth")

    def test_build_calibration_requires_samples_and_retains_bilateral_values(self):
        with self.assertRaises(ValueError):
            build_calibration("julian", {})
        phases = {}
        variants = {"neutral": {}, "wink_left": {"eye_left_ratio": .02},
                    "wink_right": {"eye_right_ratio": .03},
                    "brow_left": {"brow_left_lift": .4},
                    "brow_right": {"brow_right_lift": .5}, "mouth": {"mouth_open": .3}}
        for phase, values in variants.items():
            samples = Samples()
            for index in range(25):
                face = replace(FaceData(True, timestamp_ms=1000 + index * 30,
                                        eye_left_ratio=.1, eye_right_ratio=.12,
                                        brow_left_lift=.2, brow_right_lift=.22, mouth_open=.01), **values)
                samples.add(face, now=face.timestamp_ms/1000)
            phases[phase] = samples
        result = build_calibration("julian", phases)
        self.assertEqual(result["thresholds"], calibration()["thresholds"])
        self.assertEqual(result["sample_counts"]["neutral"], 25)
        self.assertEqual(result["neutral_variability"]["nose_x"], 0)
        self.assertNotEqual(result["thresholds"]["blink_left"], result["thresholds"]["blink_right"])

    def test_hold_cooldown_release(self):
        now = [1.0]
        detector = SingleGestureDetector("TEST", 60, 600, clock=lambda: now[0])
        self.assertIsNone(detector.update(True))
        now[0] += .03
        self.assertIsNone(detector.update(True))
        now[0] += .04
        self.assertEqual(detector.update(True).type, "TEST")
        now[0] += 1
        self.assertIsNone(detector.update(True))  # no repetición sostenida
        detector.update(False)
        self.assertEqual(detector.state, "IDLE")
        detector.update(True)
        detector.update(False)
        self.assertEqual(detector.state, "IDLE")

    def make_gesture(self, **kwargs):
        self.now = 1.0
        self.vision = Mock()
        return GestureEngine(self.vision, calibration={"thresholds": DEFAULT_THRESHOLDS.copy()},
                             config=GestureConfig(**kwargs), clock=lambda: self.now)

    def test_cursor_smoothing_dead_zone(self):
        engine = self.make_gesture(smoothing_alpha=.5)
        self.assertEqual(engine.update(FaceData(True, timestamp_ms=1000, nose_x=.52)), [])
        self.now = 1.1
        events = engine.update(FaceData(True, timestamp_ms=1100, nose_x=.7))
        delta = (.5 * .51 + .5 * .7) - .5 - .03
        self.assertAlmostEqual(events[0].dx, delta * 80 + delta * delta * 600)
        self.assertEqual(events[0].source_timestamp_ms, 1100)

    def test_stale_duplicate_lost_invalid_cancel_hold(self):
        engine = self.make_gesture()
        face = FaceData(True, timestamp_ms=1000, eye_left_ratio=.01)
        engine.update(face)
        self.now = 1.1
        self.assertEqual(engine.update(face), [])
        self.assertEqual(engine.update(FaceData(False)), [])
        self.assertEqual(engine.get_detector_states()["blink_left"], "IDLE")
        self.assertEqual(engine.update(replace(face, timestamp_ms=1100)), [])
        self.now = 2
        self.assertEqual(engine.update(face), [])
        self.assertEqual(engine.get_detector_states()["blink_left"], "IDLE")
        self.assertEqual(engine.update(FaceData(True, timestamp_ms=2000, nose_x=float("inf"))), [])

    def test_bilateral_blink_suppressed_and_wink_emitted(self):
        engine = self.make_gesture()
        engine.update(FaceData(True, timestamp_ms=1000, eye_left_ratio=.01, eye_right_ratio=.01))
        self.now = 1.1
        self.assertEqual(engine.update(FaceData(True, timestamp_ms=1100, eye_left_ratio=.01, eye_right_ratio=.01)), [])
        self.now = 1.2
        engine.update(FaceData(True, timestamp_ms=1200, eye_left_ratio=.01))
        self.now = 1.3
        events = engine.update(FaceData(True, timestamp_ms=1300, eye_left_ratio=.01))
        self.assertEqual([e.type for e in events], ["LEFT_CLICK"])

    def test_consumer_stall_does_not_complete_hold(self):
        engine = self.make_gesture()
        engine.update(FaceData(True, timestamp_ms=1000, eye_left_ratio=.01))
        self.now = 2
        events = engine.update(FaceData(True, timestamp_ms=2000, eye_left_ratio=.01))
        self.assertEqual(events, [])
        self.assertEqual(engine.get_detector_states()["blink_left"], "HOLDING")

    def test_both_brows_suppress_scroll(self):
        engine = self.make_gesture()
        engine.update(FaceData(True, timestamp_ms=1000, brow_left_lift=.4, brow_right_lift=.4))
        self.now = 1.2
        events = engine.update(FaceData(True, timestamp_ms=1200, brow_left_lift=.4, brow_right_lift=.4))
        self.assertEqual([e.type for e in events], ["BOTH_BROWS"])

    def test_control_mock_only(self):
        backend = Mock()
        backend.size.return_value = (1920, 1080)
        control = ControlEngine(Mock(), Mock(), backend=backend)
        self.assertTrue(control.paused)
        control._execute(GestureEvent("CURSOR_MOVE", dx=999, dy=-999))
        backend.moveRel.assert_called_once_with(60, -60, _pause=False)
        control._execute(GestureEvent("LEFT_CLICK"))
        backend.click.assert_called_once()
        with self.assertRaises(ValueError):
            control._execute(GestureEvent("CURSOR_MOVE", dx=float("nan")))
        control.stop()  # también funciona si nunca se inició

    def test_metrics_no_biometrics(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory:
            now = [1.]
            metrics = SessionMetrics("julian", Path(directory), clock=lambda: now[0])
            metrics.frame(FaceData(True, processing_ms=10))
            metrics.tracking(True)
            metrics.tracking(False)
            metrics.tracking(False)
            event = GestureEvent("LEFT_CLICK", detected_at=1)
            metrics.generated([event])
            now[0] = 1.05
            metrics.action(event)
            data = metrics.snapshot()
            self.assertEqual(data["tracking_losses"], 1)
            self.assertEqual(data["clicks"], 1)
            self.assertAlmostEqual(data["detection_to_action_ms_mean"], 50)
            path = metrics.close()
            self.assertEqual(path, metrics.close())
            self.assertNotIn("nose", path.read_text())
            self.assertNotIn("image", path.read_text())

    def test_disabled_metrics_write_nothing(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory:
            metrics = SessionMetrics("test", Path(directory), enabled=False)
            metrics.frame(FaceData(True))
            metrics.generated([GestureEvent("LEFT_CLICK")])
            metrics.action(GestureEvent("LEFT_CLICK"))
            self.assertIsNone(metrics.close())
            self.assertFalse(list(Path(directory).iterdir()))


if __name__ == "__main__":
    unittest.main()
