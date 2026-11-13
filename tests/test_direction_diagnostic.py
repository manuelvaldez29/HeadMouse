"""Synthetic acquisition and Qt integration; no camera, cursor, or participant data."""
import json
import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from application_controller import ApplicationController
from direction_diagnostic import DIRECTIONS, DirectionDiagnostic
from face_data import FaceData
from profile_manager import ProfileManager
from profiles import ProfileStore
import test_gui


POINTS = dict(center=(.5, .5), up=(.5, .35), down=(.5, .65), left=(.3, .5), right=(.7, .5))


class Clock:
    now = 100.

    def __call__(self):
        return self.now


def frame(clock, position=(.5, .5), **changes):
    x, y = position
    data = dict(detected=True, timestamp_ms=int(clock.now * 1000), eye_left_ratio=.12,
                eye_right_ratio=.13, processing_ms=12., left_gaze_x=x, left_gaze_y=y,
                right_gaze_x=x+.01, right_gaze_y=y, left_canthi_y=.5+(y-.5)/2,
                right_canthi_y=.5+(y-.5)/2, head_pitch=1.,
                ocular_geometry=(("left", 11., 12., 11., 10., 11., 14., 6., 12., 16., 12., 10., 40., y, .5),),
                landmarks=((.2, .9),))
    return FaceData(**(data | changes))


class DirectionTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.session = DirectionDiagnostic(self.clock, rng=random.Random(3), rounds=3,
                                           settle_s=.2, fixation_s=.6, max_age=.1, min_samples=3)

    def trial(self, position, changes=None):
        session = self.session
        start = self.clock.now
        session.acknowledge(*session.token)
        for offset in (.08, .25, .35, .45, .55, .65):
            self.clock.now = start + offset
            face = frame(self.clock, position, **(changes or {}))
            session.update(face, 30.)
            session.update(face, 30.)  # same mailbox result, not another measurement
        self.clock.now = start + 1
        session.update(FaceData(False), 30.)

    def test_signal_metrics_validate_only_on_independent_rounds(self):
        session = self.session
        for index, target in enumerate(session.schedule):
            self.assertEqual(session.snapshot()["target"], target)
            # Third round mimics someone looking at center when cued to look up.
            position = POINTS["center" if index >= 10 and target == "up" else target]
            self.trial(position, {"nose_x": .55, "head_pitch": 10.} if index >= 10 else {})
        self.assertEqual(session.state, "ready")
        for offset in range(0, len(session.schedule), 5):
            self.assertCountEqual(session.schedule[offset:offset+5], DIRECTIONS)
        self.assertTrue(all(a != b for a, b in zip(session.schedule, session.schedule[1:])))
        report = session.report
        channel = report["channels"]["canthi_both"]
        self.assertEqual(report["valid_percent"], 100.)
        self.assertEqual(report["transition_samples"], 15)
        self.assertEqual(report["processing_ms_median"], 12.)
        self.assertEqual(report["capture_fps_median"], 30.)
        self.assertAlmostEqual(report["binocular_disagreement"]["eyelids"]["mean_abs_x"], .01)
        self.assertEqual(channel["confusion"]["up"]["center"], 1)
        self.assertEqual(channel["confusion"]["up"]["up"], 2)
        self.assertEqual(channel["evaluated_trials"], 15)
        self.assertLess(channel["accuracy_percent"], 100.)
        self.assertGreater(channel["separation"]["up:down"]["signed_gap"], 0.)
        self.assertEqual(channel["fixation"]["up"]["fixation_sd"], (0., 0.))
        self.assertEqual(report["head_motion_samples"], 25)
        self.assertEqual(channel["head_groups"]["moved"]["samples"], 25)
        for fold in channel["folds"]:
            self.assertNotIn(fold["validation_round"], fold["training_rounds"])

    def test_invalid_attempt_retry_skip_stale_and_single_eye(self):
        session = self.session
        token = session.token
        session.acknowledge("old-session", *token[1:])
        self.assertEqual(session.state, "await_target")
        session.acknowledge(*token)
        self.clock.now += .5
        session.update(frame(self.clock, timestamp_ms=100_000), 30.)
        self.assertEqual(session.samples[0]["rejected"], "stale_or_invalid")
        self.clock.now += .6
        session.update(FaceData(False), 30.)
        self.assertEqual(session.state, "retry")
        session.retry()
        self.assertEqual(session.token[1:], (0, 1))
        session.acknowledge(*token)
        self.assertEqual(session.state, "await_target")
        self.trial((.4, .5), {"left_gaze_x": None, "right_gaze_x": None})
        self.assertEqual(session.samples[-1]["rejected"], "iris_missing_or_invalid")
        session.retry()
        self.trial((.4, .5), {"eye_left_ratio": .001, "eye_right_ratio": .002})
        self.assertEqual(session.samples[-1]["rejected"], "blink_or_closed")
        session.retry()
        self.trial((.4, .5), {"eye_left_ratio": .001, "right_gaze_x": None})
        self.assertEqual(session.state, "retry")
        session.retry(skip=True)
        self.trial((.5, .5), {"eye_left_ratio": .001})
        row = session.trials[-1]["samples"][-1]
        self.assertTrue(row["eyes"]["left"]["blink"])
        self.assertIn("eyelids_right", row["signals"])
        self.assertNotIn("eyelids_left", row["signals"])
        self.assertNotIn("eyelids_both", row["signals"])
        self.assertEqual(row["eyes"]["left"]["geometry"]["iris_x_px"], 11.)
        self.assertEqual(session.trials[0]["index"], 0)
        self.assertFalse(session.trials[0]["used"])

    def test_empty_session_has_no_invented_scores(self):
        session = self.session
        for _ in session.schedule:
            session.acknowledge(*session.token)
            self.clock.now += 1
            session.update(frame(self.clock, detected=False, timestamp_ms=round((self.clock.now-.4)*1000)), 0.)
            self.assertEqual(session.samples[-1]["rejected"], "face_missing")
            session.retry(skip=True)
        report = session.report
        self.assertEqual(report["rejected_percent"], 100.)
        self.assertIsNone(report["channels"]["eyelids_left"]["accuracy_percent"])
        self.assertFalse(report["channels"]["eyelids_left"]["folds"])
