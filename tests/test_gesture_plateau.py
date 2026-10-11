"""Segmentación del tramo sostenido del gesto y repetición selectiva de intentos.

Reproduce la falla física del 2026-10-11: el guiño derecho tenía buena señal
(neutral ~0.062, cerrado ~0.014) pero el usuario abrió el ojo antes de que
terminara la ventana activa fija, y esos frames anulaban el gesto completo.
"""
import unittest
from adaptive_calibration import GestureCalibration, gesture_plateau
from calibration_session import CalibrationSession
from config import load_config
from face_data import FaceData
from gesture_signals import GESTURE_SIGNALS
from test_adaptive_session import NEUTRAL, ACTIVE

OPEN, CLOSED, REOPENED = .062, .014, .066


class GesturePlateauTests(unittest.TestCase):
    def setUp(self):
        self.cc = load_config().calibration

    def test_excludes_onset_and_release_frames(self):
        neutral = [(OPEN + (.001 if i % 2 else -.001),) for i in range(40)]
        active = [(OPEN,)] * 5 + [(CLOSED,)] * 12 + [(REOPENED,)] * 20
        self.assertEqual(gesture_plateau(neutral, active, (-1,), self.cc), tuple(range(5, 17)))

    def test_old_fixed_window_failed_but_plateau_is_separable(self):
        neutral = [(OPEN + (.001 if i % 2 else -.001),) for i in range(40)]
        contaminated = [(CLOSED,)] * 34 + [(REOPENED,)] * 7  # 17% del final con el ojo abierto
        clean = [(CLOSED + .004,)] * 40
        for rows, usable in ((contaminated, False), ([contaminated[i] for i in
                             gesture_plateau(neutral, contaminated, (-1,), self.cc)], True)):
            model = GestureCalibration("RIGHT_WINK", ("eye_right_ratio",), (-1,))
            model.add_repetition(neutral, rows)
            for _ in range(2): model.add_repetition(neutral, clean)
            self.assertEqual(model.fit(self.cc).usable, usable)

    def test_tolerates_brief_gaps_and_picks_longest_run(self):
        neutral = [(.2,)] * 20
        active = [(.2,)] * 3 + [(.4,)] * 9 + [(.2,)] * 5 + [(.4,)] * 4 + [(.2,)] + [(.4,)] * 4
        self.assertEqual(gesture_plateau(neutral, active, (1,), self.cc), tuple(range(3, 12)))
        merged = gesture_plateau(neutral, active[12:], (1,), self.cc)
        self.assertEqual(merged, tuple(i for i in range(5, 14) if i != 9))

    def test_no_plateau_for_noise_or_short_gestures(self):
        neutral = [(.2 + (.003 if i % 3 else -.003),) for i in range(30)]
        noise = [(.2 + (.003 if i % 2 else -.004),) for i in range(60)]
        self.assertEqual(gesture_plateau(neutral, noise, (1,), self.cc), ())
        short = [(.2,)] * 10 + [(.4,)] * (self.cc.min_window_samples - 1) + [(.2,)] * 10
        self.assertEqual(gesture_plateau(neutral, short, (1,), self.cc), ())

    def test_composite_gesture_requires_all_channels(self):
        neutral = [(.2, .22)] * 20
        one_side = [(.4, .22)] * 15
        self.assertEqual(gesture_plateau(neutral, one_side, (1, 1), self.cc), ())
        both = [(.2, .22)] * 2 + [(.3, .33)] * 10
        self.assertEqual(gesture_plateau(neutral, both, (1, 1), self.cc), tuple(range(2, 12)))


class PlateauSessionTests(unittest.TestCase):
    """Configuración por defecto salvo esperas neutrales, a 20 FPS virtuales."""

    def setUp(self):
        self.ms = 1000
        self.config = load_config()
        cc = self.config.calibration
        cc.countdown_s = cc.measuring_s = cc.transition_s = cc.neutral_window_s = .5
        self.session = CalibrationSession({"user_id": "plateau"}, self.config, self.clock,
                                          {key: key == "RIGHT_WINK" for key in GESTURE_SIGNALS})
        self.session.start()

    def clock(self): return self.ms / 1000

    def feed(self, eye):
        self.ms += 50
        values = dict(NEUTRAL, eye_right_ratio=eye, eye_left_ratio=OPEN)
        self.session.update(FaceData(True, timestamp_ms=self.ms, **values))

    def wait_active(self):
        for _ in range(200):
            if self.session.stage == "active" or self.session.state in ("measured", "error"): return
            self.feed(OPEN)
        self.fail("No llegó a la ventana activa")

    def wink(self, closed_frames, reaction=4):
        """Reacción, guiño breve y reapertura; devuelve frames hasta terminar el intento."""
        model = self.session.models["RIGHT_WINK"]
        before = (len(model.active_samples), model.rejected)
        frames = [OPEN] * reaction + [CLOSED] * closed_frames + [REOPENED] * 40
        for count, eye in enumerate(frames, 1):
            self.feed(eye)
            if (len(model.active_samples), model.rejected) != before or self.session.state != "measuring":
                return count
        return None

    def test_brief_wink_completes_on_release_without_holding(self):
        durations = []
        for _ in range(3):
            self.wait_active()
            durations.append(self.wink(closed_frames=10))  # 0.5 s, guiño natural
        self.assertEqual(self.session.state, "measured", self.session.snapshot())
        # Termina pocos frames después de soltar; no exige sostener una ventana fija.
        self.assertTrue(all(d <= 4 + 10 + 4 for d in durations), durations)
        record = self.session.candidate["gesture_calibrations"]["RIGHT_WINK"]
        self.assertEqual(record["quality_label"], "BUENA")
        self.assertTrue(CLOSED < record["activation_threshold"]["eye_right_ratio"] < OPEN)
        self.assertEqual(record["active_statistics"]["eye_right_ratio"]["p90"], CLOSED)

    def test_long_hold_is_capped_by_active_window(self):
        self.wait_active()
        frames = self.wink(closed_frames=200)
        cap = self.config.calibration.active_window_s / .05
        self.assertLessEqual(frames, 4 + cap + 2)
        self.assertEqual(len(self.session.models["RIGHT_WINK"].active_samples), 1)

    def test_inconsistent_attempt_is_recaptured_alone(self):
        model = self.session.models["RIGHT_WINK"]
        self.wait_active()
        self.wink(10)
        self.wait_active()
        self.wink(10)
        # Tercer intento con neutral desplazado (ojo más abierto) y guiño mínimo:
        # separable por sí solo, incompatible con los otros dos.
        for _ in range(200):
            if self.session.stage == "active": break
            self.feed(.2)
        for _ in range(4): self.feed(.2)
        for _ in range(12): self.feed(.19)
        for _ in range(5): self.feed(.2)
        self.assertEqual(model.rejected, 1)
        self.assertEqual(len(model.active_samples), 2)
        self.assertIn("intento 3", self.session.capture_message)
        self.assertNotEqual(self.session.state, "error")
        self.wait_active()
        self.wink(10)
        self.assertEqual(self.session.state, "measured", self.session.snapshot())
        record = self.session.candidate["gesture_calibrations"]["RIGHT_WINK"]
        self.assertEqual((record["repetitions_captured"], record["rejected"]), (3, 1))

    def test_no_gesture_times_out_with_failed_telemetry(self):
        self.wait_active()
        for _ in range(round(self.config.calibration.validation_timeout_s / .05) + 2): self.feed(OPEN)
        self.assertEqual(self.session.state, "error")
        self.assertIn("Esperando el gesto", self.session.error)
        self.assertEqual(self.session.telemetry[-1]["quality_label"], "DÉBIL")


if __name__ == "__main__": unittest.main()
