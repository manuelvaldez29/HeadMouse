"""Virtual joystick unit, course, and offscreen Qt integration tests."""
from dataclasses import asdict, replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from direction_diagnostic import DirectionClassifier
from ocular_joystick import GazeDirection, HEIGHT, WIDTH, JoystickOptions, VirtualJoystick
from ocular_lab import JoystickCourse
from ocular_simulation import IDEAL, SCENARIOS, SyntheticVision, write_report
import test_gui


CENTERS = dict(center=[(.5, .5)], up=[(.5, .3)], down=[(.5, .7)], left=[(.3, .5)], right=[(.7, .5)])


class JoystickTests(unittest.TestCase):
    def test_every_direction_dwell_and_steps(self):
        x, y = WIDTH / 2, HEIGHT / 2
        expected = dict(up=(x, y-20), down=(x, y+20), left=(x-20, y), right=(x+20, y))
        for direction, position in expected.items():
            joystick = VirtualJoystick(JoystickOptions(pixels=20))
            joystick.update(1., direction, .95)
            joystick.update(1.25, direction, .95)
            self.assertEqual(joystick.position, (x, y))
            joystick.update(1.31, direction, .95)
            self.assertEqual(joystick.position, position)
            joystick.update(1.9, direction, .95)
            self.assertEqual(joystick.position, position)
            joystick.update(2., "center", 1.)
            self.assertEqual(joystick.state, "neutral")
            self.assertIsNone(joystick.active)

    def test_continuous_accelerates_hysteresis_and_loss_stop(self):
        joystick = VirtualJoystick(JoystickOptions(mode="continuous"))
        joystick.update(0., "right", .96)
        joystick.update(.3, "right", .96)
        joystick.update(.4, "right", .4)  # between engage and release thresholds
        slow = joystick.speed
        joystick.update(.5, "right", .4)
        self.assertGreater(joystick.speed, slow)
        position = joystick.position
        joystick.update(.6, None, 0)
        self.assertEqual(joystick.position, position)
        self.assertEqual(joystick.speed, 0.)
        self.assertEqual(joystick.stops, 1)
        joystick.update(.7, "left", .95)
        joystick.update(.9, "right", .95)  # neither direction dwelled
        self.assertEqual(joystick.position, position)
        joystick.update(1.3, "right", .95)
        for index in range(1, 300):
            joystick.update(1.3 + .1 * index, "right", .95)
        self.assertEqual(joystick.position[0], WIDTH)
        self.assertEqual(joystick.speed, 0.)
        self.assertEqual(joystick.state, "boundary")

    def test_estimator_has_no_target_input_and_rejects_weak_vertical_and_missing_faces(self):
        classifier = DirectionClassifier.fit(CENTERS)
        control = GazeDirection(classifier, (.004, .004))
        config = replace(IDEAL, noise=0., head=0., blink=0., loss=0., natural=0., offset=0., invalid=0.)
        face = SyntheticVision(config, 4)
        for frame in range(35):
            observed = face.capture(100000 + frame * 33, "right")
            label, confidence, _ = control.read(observed, observed.timestamp_ms / 1000)
        self.assertEqual(label, "right")
        self.assertGreater(confidence, .8)
        self.assertIsNone(control.read(observed, observed.timestamp_ms / 1000 + .5)[0])
        self.assertIsNone(control.read(None, 110.)[0])
        weak = DirectionClassifier.fit(CENTERS | dict(up=[(.5, .494)], down=[(.5, .506)]))
        estimator = GazeDirection(weak, (.005, .007))
        self.assertFalse({"up", "down"} & estimator.reliable)

    def test_courses_use_independent_training_and_reach_targets(self):
        for mode in ("step", "continuous"):
            course = JoystickCourse(IDEAL, 42, "ideal", JoystickOptions(mode=mode))
            while not course.done:
                course.step()
            result = course.record()
            self.assertNotEqual(result["training_seed"], result["seed"])
            self.assertEqual(result["metrics"]["targets_reached"], 6, (mode, result["metrics"]))
            self.assertGreater(result["metrics"]["distance_px"], 400)
            self.assertTrue(all(0 <= x <= WIDTH and 0 <= y <= HEIGHT for x, y in result["trajectory"]))
            self.assertEqual(result["source"], "synthetic")
        noisy = JoystickCourse(SCENARIOS["vertical"][1], 42, "vertical", JoystickOptions())
        while not noisy.done:
            noisy.step()
        self.assertLess(noisy.record()["metrics"]["targets_reached"], 6)

    def test_explicit_release_discards_delayed_directions(self):
        config = replace(IDEAL, delay_ms=180)
        course = JoystickCourse(config, 42, "custom", JoystickOptions(dwell=.12), automatic=False)
        for _ in range(8):
            course.vision.tick(100., "right")
        self.assertTrue(course.vision.queue)
        course.command("neutral")
        self.assertFalse(course.vision.queue)
        self.assertEqual(course.vision.gaze, [0., 0.])
        self.assertEqual(course.manual_intent, "center")
        self.assertIsNone(course.joystick.active)

    def test_options_round_trip_and_mode_change(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "options.json"
            options = JoystickOptions(mode="continuous", pixels=50, dwell=.65, position="top_right")
            write_report(path, asdict(options))
            stored = JoystickOptions(**json.loads(path.read_text(encoding="utf-8")))
            self.assertEqual(options, stored)
            new = VirtualJoystick(replace(stored, mode="step"))
            new.select("left")
            new.update(1., None, 0)
            self.assertEqual(new.position, (WIDTH / 2 - 50, HEIGHT / 2))
            new.release()
            self.assertIsNone(new.active)

    def test_worker_failure_revokes_active_virtual_motion(self):
        from desktop.ocular_lab import LabWorker

        with tempfile.TemporaryDirectory() as temp:
            worker = LabWorker(Path(temp))
            worker.timer = Mock()
            worker.run = JoystickCourse(IDEAL, 2, "ideal", JoystickOptions(mode="continuous"))
            worker.run.joystick.select("right")
            worker.run.joystick.update(1., None, 0)
            worker.run.step = Mock(side_effect=RuntimeError("error simulado"))
            worker.tick()
            worker.timer.stop.assert_called_once()
            self.assertIsNone(worker.run.joystick.active)
            self.assertEqual(worker.state, "error")


@unittest.skipUnless(test_gui.QT_AVAILABLE, "Requiere PySide6")
class JoystickGuiTests(unittest.TestCase):
    setUpClass = classmethod(test_gui.GUITests.setUpClass.__func__)
    setUp = test_gui.GUITests.setUp
    wait = test_gui.GUITests.wait
    tearDown = test_gui.GUITests.tearDown
    select_calibrated = test_gui.GUITests.select_calibrated

    def test_laboratory_can_start_without_webcam_and_f8_stops(self):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QKeySequence, QShortcut
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QBoxLayout

        self.select_calibrated()
        profile = next((self.root / "profiles").glob("*.json"))
        before = profile.read_bytes()
        self.controller.vision_factory = Mock(side_effect=AssertionError("No abrir la cámara"))
        self.window.show_page(3)
        self.window.open_ocular_lab()
        lab = self.window.ocular_lab
        self.assertTrue(self.controller.synthetic_lab.is_set())
        with self.assertRaisesRegex(ValueError, "laboratorio"):
            self.controller.start_camera()
        with self.assertRaisesRegex(ValueError, "laboratorio"):
            self.controller.activate_control(confirmed=True)
        lab.automatic.setChecked(False)
        lab.start("joystick")
        self.wait(lambda: (lab.canvas.data.get("joystick") or {}).get("elapsed_s", 0.) > .1)
        lab.resize(650, 515)
        self.wait(lambda: lab.body.direction() == QBoxLayout.Direction.TopToBottom)
        self.assertTrue(lab.stop.isVisible())
        QTest.mouseClick(lab.directions["right"], Qt.MouseButton.LeftButton)
        self.wait(lambda: lab.canvas.data["joystick"]["joystick"]["position"][0] == WIDTH / 2 + 10)
        lab.pause.click()
        self.wait(lambda: lab.canvas.data["state"] == "paused")
        lab.stop.click()
        self.wait(lambda: lab.canvas.data["state"] == "stopped")
        lab.export.click()
        self.wait(lambda: "guardado" in lab.note.text())
        files = list((self.root / "experiments" / "ocular-simulation").glob("*.json"))
        self.assertEqual(len(files), 2)
        competing_shortcut = QShortcut(QKeySequence("F8"), lab)
        competing_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        QTest.keyClick(lab, Qt.Key.Key_F8)
        self.wait(lambda: self.window.ocular_lab is None)
        self.assertFalse(self.controller.synthetic_lab.is_set())
        self.assertIsNone(self.controller.vision)
        self.controller.vision_factory.assert_not_called()
        self.backend_factory.assert_not_called()
        self.assertEqual(profile.read_bytes(), before)
        self.assertEqual(self.controller.config.ui.tracking_method, "nose")

    def test_closing_window_joins_running_simulation(self):
        self.window.open_ocular_lab()
        lab = self.window.ocular_lab
        lab.start("diagnostic")
        self.wait(lambda: lab.canvas.data.get("diagnostic") is not None)
        self.window.close()
        self.wait(lambda: self.window.ocular_lab is None and not self.bridge.thread.isRunning())
        self.assertFalse(self.controller.synthetic_lab.is_set())
