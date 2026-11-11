"""Bounded virtual control and offline replay without desktop or camera I/O."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from ocular_joystick import JoystickOptions, VirtualJoystick, WIDTH, HEIGHT
from ocular_lab import JoystickCourse
from ocular_replay import ReplayComparison, load_record
from ocular_simulation import IDEAL, run_simulation, write_report


class FineControlTests(unittest.TestCase):
    def test_manual_steps_are_single_and_have_separate_counters(self):
        joystick = VirtualJoystick(JoystickOptions(pixels=50))
        for direction in ("left", "right", "up", "down"):
            joystick.select(direction)
            joystick.update(100. + joystick.activations, None, 0., fine=True)
            joystick.update(100.5 + joystick.activations, None, 0., fine=True)
            joystick.release()
        self.assertEqual(joystick.position, (WIDTH/2, HEIGHT/2))
        self.assertEqual(joystick.distance, 20.)
        self.assertEqual((joystick.manual_operations, joystick.eye_operations), (4, 0))

    def test_continuous_cap_blocks_same_direction_and_reversals_until_neutral(self):
        options = JoystickOptions(mode="continuous", dwell=.12, max_duration=.4)
        joystick = VirtualJoystick(options)
        for i in range(35):
            joystick.update(100+i*.04, "right", .95)
        self.assertTrue(joystick.locked)
        self.assertEqual(joystick.speed, 0)
        position = joystick.position
        for i in range(20):
            joystick.update(102+i*.04, "left" if i % 2 else None, .95)
        self.assertEqual(joystick.position, position)
        for i in range(10):
            joystick.update(103+i*.04, "center", 1.)
        self.assertFalse(joystick.locked)
        for i in range(10):
            joystick.update(104+i*.04, "left", .95)
        self.assertLess(joystick.position[0], position[0])

    def test_pulse_and_immediate_loss(self):
        options = JoystickOptions(mode="continuous", continuous_policy="pulse", pulse_seconds=.24)
        joystick = VirtualJoystick(options)
        joystick.select("right")
        for i in range(24):
            joystick.update(100+i*.03, None, 0.)
        self.assertTrue(joystick.locked)
        self.assertLess(joystick.distance, 20.)
        self.assertEqual(joystick.manual_operations, 1)
        joystick.release()
        for i in range(15):
            joystick.update(102+i*.03, "up", .95)
        self.assertEqual(joystick.active, "up")
        position = joystick.position
        joystick.update(102.46, None, 0)
        self.assertEqual(joystick.position, position)
        self.assertEqual(joystick.speed, 0)
        self.assertEqual(joystick.eye_operations, 1)

    def test_optional_repeat_starts_after_delay_and_does_not_catch_up(self):
        joystick = VirtualJoystick(JoystickOptions(step_repeat=True))
        joystick.select("right")
        joystick.update(100, None, 0)
        joystick.update(100.64, None, 0)
        self.assertEqual(joystick.manual_operations, 1)
        joystick.update(101.44, None, 0)
        self.assertEqual(joystick.manual_operations, 2)
        joystick.update(101.72, None, 0)
        self.assertEqual(joystick.manual_operations, 2)
        joystick.release()
        self.assertEqual(joystick.distance, 20)

    def test_manual_tap_runs_one_pulse_without_holding(self):
        options = JoystickOptions(selection="manual", mode="continuous", continuous_policy="pulse", pulse_seconds=.24)
        course = JoystickCourse(IDEAL, 43, "ideal", options, automatic=False)
        course.command("press", "right")
        course.command("release")
        for _ in range(30):
            course.step()
        self.assertGreater(course.joystick.position[0], WIDTH / 2)
        self.assertLess(course.joystick.position[0], WIDTH / 2 + 20)
        self.assertEqual(course.joystick.manual_operations, 1)
        self.assertEqual(course.joystick.speed, 0.)

    def test_precision_task_requires_stable_virtual_confirmation(self):
        course = JoystickCourse(IDEAL, 43, "ideal", JoystickOptions(selection="manual", task_set="precision"),
                                automatic=False)
        course.command("confirm")
        self.assertEqual(course.rejected_confirms, 1)
        course.joystick.position = course.target[:2]
        for _ in range(12):
            course.step()
        self.assertTrue(course.snapshot()["ready_to_confirm"])
        self.assertEqual(course.target_index, 0)
        course.command("confirm")
        self.assertEqual(course.target_index, 1)
        self.assertEqual(course.record()["reached"][0]["confirmation"], "manual")
        self.assertEqual(course.record()["metrics"]["eye_operations"], 0)


class ReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.recording = run_simulation(IDEAL, 61, "ideal").record()

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "input.json"

    def replay(self, record, options=None):
        write_report(self.path, record)
        replay = ReplayComparison(self.path, options or JoystickOptions(mode="continuous"))
        while not replay.done:
            replay.step()
        return replay.record()

    def test_replay_is_deterministic_and_held_out_labels_only_change_scoring(self):
        first = self.replay(self.recording)
        self.assertEqual(first, self.replay(self.recording))
        altered = deepcopy(self.recording)
        for trial in altered["trials"]:
            if trial["round"] > first["training_round"]:
                trial["target"] = "center"
        second = self.replay(altered)
        self.assertNotIn(first["training_round"], first["evaluation_rounds"])
        self.assertEqual(first["origin"], "synthetic")
        for name, a in first["methods"].items():
            b = second["methods"][name]
            self.assertEqual(a["distance_px"], b["distance_px"])
            self.assertEqual(a["operations"], b["operations"])
            self.assertNotEqual(a["confusion"], b["confusion"])
            self.assertEqual(a["invalid_motion_ticks"], 0)

    def test_replay_retains_rejections_and_detects_bad_schema(self):
        sample = deepcopy(self.recording)
        sample.pop("source")
        row = next(trial["samples"][0] for trial in sample["trials"] if trial["round"] == 1 and trial["samples"])
        row["rejected"] = "blink_or_closed"
        write_report(self.path, sample)
        origin, _, _, _, events = load_record(self.path, "eyelids_both")
        self.assertEqual(origin, "unmarked")
        self.assertIsNone(events[0].sample.point)
        sample["schema_version"] = 2
        write_report(self.path, sample)
        with self.assertRaises(ValueError):
            load_record(self.path, "eyelids_both")

    def test_worker_replay_exports_only_numeric_summary(self):
        from desktop.ocular_lab import LabWorker

        write_report(self.path, self.recording | {"participant": "private-metadata"})
        worker = LabWorker(self.path.parent / "export")
        worker.timer = Mock()
        worker.command("start", ("replay", "", 0, self.path, JoystickOptions(), False))
        while worker.state == "running":
            worker.tick()
        self.assertEqual(worker.state, "complete")
        worker.export()
        output, = [p for p in (self.path.parent / "export").glob("*.json") if p.name != "options.json"]
        raw = output.read_text(encoding="utf-8")
        self.assertNotIn("private-metadata", raw)
        self.assertNotIn("input.json", raw)
        self.assertEqual(json.loads(raw)["origin"], "synthetic")
