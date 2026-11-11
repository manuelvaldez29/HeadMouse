"""Experiments exercise the real geometry and round-based diagnostic without hardware."""
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from direction_diagnostic import DIRECTIONS
from gaze_source import gaze_position
from ocular_simulation import IDEAL, SCENARIOS, STEP, SyntheticVision, replay_metrics, run_simulation, write_report


class OcularSimulationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reports = {name: run_simulation(config, 42, name).record() for name, (_, config) in SCENARIOS.items()}

    def test_reproducibility_and_latency(self):
        a, b = SyntheticVision(IDEAL, 21), SyntheticVision(IDEAL, 21)
        frames = [a.tick(100 + index * STEP, "up") for index in range(100)]
        self.assertEqual(frames, [b.tick(100 + index * STEP, "up") for index in range(100)])
        self.assertIsNone(frames[0])
        self.assertIsNone(frames[1])
        self.assertEqual(frames[2].timestamp_ms, 100000)
        self.assertNotEqual(frames[2:], [SyntheticVision(IDEAL, 22).capture(100000, "up")] * 98)

    def test_five_directions_use_valid_geometry(self):
        config = replace(IDEAL, noise=0, natural=0, head=0, blink=0, loss=0, invalid=0, offset=0, asymmetry=0)
        signals = {}
        for target in DIRECTIONS:
            source = SyntheticVision(config, 2)
            for index in range(100):
                face = source.capture(100000 + index * 33, target)
            self.assertTrue(face.valid())
            self.assertEqual(len(face.ocular_geometry), 2)
            signals[target] = gaze_position(face, "both", "eyelids")
        self.assertAlmostEqual(signals["center"][0], .5)
        self.assertLess(signals["up"][1], signals["center"][1])
        self.assertGreater(signals["down"][1], signals["center"][1])
        self.assertLess(signals["left"][0], signals["center"][0])
        self.assertGreater(signals["right"][0], signals["center"][0])

    def test_scenarios_and_round_independence(self):
        metrics = {name: value["metrics"] for name, value in self.reports.items()}
        channels = {name: value["channels"]["eyelids_both"] for name, value in metrics.items()}
        ideal = channels["ideal"]
        self.assertEqual(ideal["accuracy_percent"], 100.)
        self.assertLess(channels["vertical"]["accuracy_percent"], ideal["accuracy_percent"])
        self.assertGreater(channels["noisy"]["fixation"]["center"]["fixation_sd"][0],
                           ideal["fixation"]["center"]["fixation_sd"][0])
        self.assertLess(channels["vertical"]["separation"]["up:down"]["signed_gap"],
                        ideal["separation"]["up:down"]["signed_gap"] / 3)
        self.assertGreater(metrics["head"]["head_motion_samples"], metrics["ideal"]["head_motion_samples"])
        self.assertGreater(metrics["loss"]["tracking_loss_percent"], metrics["ideal"]["tracking_loss_percent"])
        self.assertGreater(metrics["asymmetry"]["binocular_disagreement"]["eyelids"]["mean_abs_y"],
                           metrics["ideal"]["binocular_disagreement"]["eyelids"]["mean_abs_y"])
        self.assertIsNone(metrics["ideal"]["capture_fps_median"])
        self.assertEqual(metrics["ideal"]["artificial_delay_ms"], IDEAL.delay_ms)
        self.assertEqual(len(ideal["folds"]), 4)
        for fold in ideal["folds"]:
            self.assertNotIn(fold["validation_round"], fold["training_rounds"])
        for direction in DIRECTIONS:
            self.assertEqual(ideal["per_direction"][direction], dict(precision=1., sensitivity=1.))

    def test_loss_has_missing_face_iris_and_blinks(self):
        rows = [row for trial in self.reports["loss"]["trials"] for row in trial["samples"]]
        self.assertIn("face_missing", {row["rejected"] for row in rows})
        self.assertTrue(any(row["eyes"]["left"]["blink"] for row in rows))
        self.assertTrue(any(row["face_detected"] and row["rejected"] is None
                            and not row["eyes"]["left"]["available"] for row in rows))

    def test_json_and_compatible_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.json"
            report = self.reports["moderate"]
            write_report(path, report)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["source"], "synthetic")
            replay = replay_metrics(path)
            self.assertEqual(replay["original_source"], "synthetic")
            self.assertEqual(replay["metrics"]["channels"], report["metrics"]["channels"])
            write_report(path, dict(schema_version=2))
            with self.assertRaises(ValueError):
                replay_metrics(path)
