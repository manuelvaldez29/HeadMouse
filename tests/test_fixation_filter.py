"""Filtro de fijaciones del cursor por mirada (2026-10-28: "no se queda quieto aunque
mire un punto fijo; falla más arriba/abajo que a los costados")."""
import math
import random
import unittest

from gaze_filter import FixationFilter

W, H = 1920, 1080


def to_norm(x, y):
    return x/(W-1), y/(H-1)


def noisy_fixation(rng, x, y, frames, start_ms=0, sx=15., sy=40.):
    """Ruido de webcam: el vertical es el más grande (σ 40 px contra 15 px)."""
    return [(start_ms+i*33, to_norm(rng.gauss(x, sx), rng.gauss(y, sy))) for i in range(frames)]


def path_px(filter_, samples):
    out = []
    for ts, p in samples:
        x, y = filter_.update(ts, p)
        out.append((x*(W-1), y*(H-1)))
    return out


def travel(points):
    return sum(math.hypot(b[0]-a[0], b[1]-a[1]) for a, b in zip(points, points[1:]))


class FixationFilterTests(unittest.TestCase):
    def test_cursor_stays_still_while_looking_at_a_fixed_point(self):
        rng = random.Random(7)
        samples = noisy_fixation(rng, 900, 500, 90)  # 3 s mirando el mismo punto
        out = path_px(FixationFilter(W, H), samples)[15:]
        # Suavizado anterior (EMA .65) con el mismo ruido, para comparar.
        ema, previous = [], None
        for _, p in samples:
            previous = p if previous is None else tuple(.65*a+.35*b for a, b in zip(previous, p))
            ema.append((previous[0]*(W-1), previous[1]*(H-1)))
        ema = ema[15:]
        self.assertLess(travel(out), 60)                 # prácticamente quieto
        self.assertGreater(travel(ema), 10*travel(out) + 500)
        x, y = out[-1]
        self.assertLess(math.hypot(x-900, y-500), 40)    # y quieto en el lugar mirado

    def test_saccade_jumps_within_a_few_frames(self):
        rng = random.Random(3)
        f = FixationFilter(W, H)
        path_px(f, noisy_fixation(rng, 400, 300, 20))
        after = path_px(f, noisy_fixation(rng, 1500, 800, 6, start_ms=20*33))
        reached = next(i for i, (x, y) in enumerate(after) if math.hypot(x-1500, y-800) < 80)
        self.assertLessEqual(reached, 3)                 # ~100 ms, no un deslizamiento lento
        self.assertEqual(f.state, "fijación")

    def test_single_spike_does_not_move_the_cursor(self):
        f = FixationFilter(W, H)
        for i in range(10):
            f.update(i*33, to_norm(900, 500))
        before = f.anchor
        f.update(330, to_norm(900, 900))                 # párpado abriéndose: lectura suelta muy abajo
        f.update(363, to_norm(900, 500))
        self.assertEqual(f.anchor, before)

    def test_vertical_tolerates_more_than_horizontal(self):
        def jumped(dx, dy):
            f = FixationFilter(W, H)
            for i in range(10):
                f.update(i*33, to_norm(900, 500))
            for i in range(10, 14):
                f.update(i*33, to_norm(900+dx, 500+dy))
            return f.state == "salto" or abs(f.anchor[0]-900) > 50 or abs(f.anchor[1]-500) > 50
        self.assertTrue(jumped(90, 0))
        self.assertFalse(jumped(0, 90))

    def test_small_sustained_shift_is_followed(self):
        f = FixationFilter(W, H)
        for i in range(15):
            f.update(i*33, to_norm(900, 500))
        for i in range(15, 60):                          # mirar 40 px a la derecha (dentro del radio)
            f.update(i*33, to_norm(940, 500))
        self.assertLess(abs(f.anchor[0]-940), 10)

    def test_blink_keeps_anchor_but_long_loss_restarts(self):
        f = FixationFilter(W, H)
        for i in range(10):
            f.update(i*33, to_norm(900, 500))
        f.interrupt()
        x, y = f.update(500, to_norm(930, 530))          # misma mirada, lectura algo corrida
        self.assertAlmostEqual(x*(W-1), 900, delta=1)
        self.assertAlmostEqual(y*(H-1), 500, delta=1)
        x, y = f.update(5000, to_norm(1500, 200))        # varios segundos sin datos: se reinicia
        self.assertAlmostEqual(x*(W-1), 1500, delta=1)


class EngineFixationTests(unittest.TestCase):
    def test_losing_the_iris_does_not_restart_from_the_raw_reading(self):
        from dataclasses import replace
        from test_eye_sources import SourceCursorTests, source_face
        now = [1.]
        engine = SourceCursorTests.engine(None, "eye_absolute", "left", now)
        stamp = 1000
        for _ in range(10):
            now[0] = stamp/1000
            events = engine.update(source_face("left", .7, .5, stamp))
            stamp += 33
        anchored = next(e for e in events if e.type == "CURSOR_ABSOLUTE")
        now[0] = stamp/1000
        engine.update(source_face("right", .7, .5, stamp))   # se pierde el iris elegido
        resumed = None
        for _ in range(20):                                   # recuperación del motor: unos cuadros estables
            stamp += 33
            now[0] = stamp/1000
            events = engine.update(source_face("left", .705, .505, stamp))
            resumed = next((e for e in events if e.type == "CURSOR_ABSOLUTE"), None)
            if resumed:
                break
        self.assertIsNotNone(resumed)
        self.assertAlmostEqual(resumed.dx, anchored.dx, places=6)
        self.assertAlmostEqual(resumed.dy, anchored.dy, places=6)
        self.assertEqual(engine.tracking_diagnostic()["fixation"]["state"], "fijación")

    def test_config_rejects_out_of_range_radius(self):
        from config import load_config
        self.assertEqual(load_config().absolute.fixation_radius_px, 70.)
        for value in (0, 5, 1000, True):
            with self.assertRaises(ValueError):
                load_config(overrides={"absolute": {"fixation_radius_px": value}})


if __name__ == "__main__":
    unittest.main()
