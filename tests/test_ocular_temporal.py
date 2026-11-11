"""Causal temporal decisions and virtual-only safety using recorded-style FaceData."""
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from direction_diagnostic import DirectionClassifier
from face_data import FaceData
from ocular_comparison import BASE_PROTOCOL, STRESS, CourseComparison, evaluate_stream, fixed_stream
from ocular_joystick import JoystickOptions, VirtualJoystick
from ocular_simulation import BASE_TIME, IDEAL, STEP, run_simulation
from ocular_temporal import TemporalGaze, filtered_point


CENTERS = dict(center=[(.5, .5)], up=[(.5, .28)], down=[(.5, .72)], left=[(.28, .5)], right=[(.72, .5)])


def face(t, x=.5, y=.28, blink=False):
    return FaceData(True, timestamp_ms=round(t*1000), detected_at=t, eye_left_ratio=.01 if blink else .25,
                    eye_right_ratio=.01 if blink else .25, left_gaze_x=x, left_gaze_y=y,
                    right_gaze_x=x, right_gaze_y=y, left_canthi_y=y, right_canthi_y=y)


class TemporalOcularTests(unittest.TestCase):
    def setUp(self):
        self.model = DirectionClassifier.fit(CENTERS)
        self.options = JoystickOptions(algorithm="weighted", window=.24, mode="continuous")
        self.estimator = TemporalGaze(self.model, (.006, .006), window=self.options.window)
        self.joystick = VirtualJoystick(self.options)

    def step(self, index, x=.5, y=.28, blink=False, missing=False):
        now = round((BASE_TIME + index * STEP) * 1000) / 1000
        frame = None if missing else face(now, x, y, blink)
        label, confidence, _ = self.estimator.read(frame, now)
        self.joystick.update(now, label, confidence)
        return label

    def test_window_uses_distinct_present_samples_and_discards_old_and_future(self):
        start = face(BASE_TIME)
        self.assertIsNone(self.estimator.read(start, BASE_TIME)[0])
        for i in range(1, 5):
            self.assertIsNone(self.estimator.read(start, BASE_TIME + i * .01)[0])
        self.assertEqual(len(self.estimator.samples), 1)
        self.assertIsNone(self.estimator.read(face(BASE_TIME + .3), BASE_TIME + .25)[0])
        self.assertFalse(self.estimator.samples)
        self.assertEqual(filtered_point([(0., .2), (.5, .4), (.6, .5)], "median"), (.5, .4))

    def test_sustained_direction_survives_a_single_outlier_and_stops_on_neutral(self):
        for i in range(30):
            self.step(i, y=.72 if i % 9 == 6 else .28)
        self.assertEqual(self.joystick.active, "up")
        self.assertEqual(self.joystick.activations, 1)
        self.assertLess(self.joystick.position[1], 210)
        for i in range(30, 42):
            self.step(i, y=.5)
        self.assertIsNone(self.joystick.active)
        self.assertEqual(self.joystick.speed, 0)
        self.assertEqual(self.joystick.activations, 1)

    def test_blink_and_loss_stop_same_tick_then_require_new_evidence_and_dwell(self):
        for i in range(26):
            self.step(i)
        self.assertEqual(self.joystick.active, "up")
        position = self.joystick.position
        self.assertIsNone(self.step(26, blink=True))
        self.assertIsNone(self.joystick.active)
        self.assertEqual(self.joystick.position, position)
        for i in range(27, 40):
            self.step(i, missing=True)
        self.assertEqual(self.joystick.position, position)
        for i in range(40, 49):
            self.step(i)
        self.assertIsNone(self.joystick.active)
        for i in range(49, 65):
            self.step(i)
        self.assertEqual(self.joystick.active, "up")

    def test_short_reversals_and_neutral_do_not_arm_movement(self):
        for i in range(72):
            self.step(i, y=(.28, .72, .5)[(i // 3) % 3])
        self.assertEqual(self.joystick.activations, 0)

    def test_weak_vertical_is_unreliable_even_when_smoothed(self):
        model = DirectionClassifier.fit(CENTERS | dict(up=[(.5, .494)], down=[(.5, .506)]))
        self.estimator = TemporalGaze(model, (.008, .01), window=.24)
        for i in range(45):
            self.step(i, y=.494)
        self.assertFalse({"up", "down"} & self.estimator.reliable)
        self.assertEqual(self.joystick.activations, 0)

    def test_held_out_stress_comparison_reports_physical_free_stop(self):
        config, stress = STRESS["outage"]
        seed = 307
        training = run_simulation(config, seed ^ 0x512AC, "outage").session
        frames = tuple(fixed_stream(config, seed, BASE_PROTOCOL + stress))
        prior = evaluate_stream(frames, training, replace(self.options, algorithm="previous"))
        temporal = evaluate_stream(frames, training, self.options)
        self.assertEqual(prior["scored_frames"], temporal["scored_frames"])
        self.assertEqual(temporal["invalid_movement_ticks"], 0)
        self.assertGreater(temporal["invalid_delivery_stop_ms"]["n"], 0)
        self.assertEqual(temporal["invalid_delivery_stop_ms"]["maximum"], 0)
        self.assertTrue(all("unavailable" in row for row in temporal["confusion"].values()))

    def test_exported_comparison_retains_seed_configuration_and_virtual_metrics(self):
        from desktop.ocular_lab import LabWorker
        import json

        with tempfile.TemporaryDirectory() as temp:
            worker = LabWorker(Path(temp))
            worker.timer = Mock()
            worker.command("start", ("comparison", "ideal", 42, IDEAL, self.options, True))
            self.assertIsInstance(worker.run, CourseComparison)
            while worker.state == "running":
                worker.tick()
            self.assertEqual(worker.state, "complete")
            worker.export()
            report, = [p for p in Path(temp).glob("*.json") if p.name != "options.json"]
            data = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(data["source"], "synthetic")
            self.assertEqual(data["seed"], 42)
            self.assertEqual(set(data["runs"]), {"previous", "weighted"})
            self.assertTrue(all(run["metrics"]["targets_reached"] == 6 for run in data["runs"].values()))
