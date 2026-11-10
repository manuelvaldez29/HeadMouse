"""Umbrales con margen desde el reposo (2026-11-09).

Calibración de un perfil nuevo el 2026-11-08: cejas en reposo 0,245 y levantadas 0,303,
pero activación en 0,258 (22 % del recorrido) y liberación 0,0015 por debajo. El p10
del gesto incluye la subida, y el hueco robusto quedaba pegado a la cara relajada.
"""
import random
import unittest

from adaptive_calibration import GestureCalibration
from config import CalibrationConfig


def brow_rows(rng, rest=.245, raised=.303):
    neutral = [(rng.gauss(rest, .002),) for _ in range(46)]
    rise = [(rest + (raised - rest) * k / 6,) for k in range(1, 4)]  # la subida también se mide
    active = rise + [(rng.gauss(raised, .003),) for _ in range(14)]
    return neutral, active


class CalibrationMarginTests(unittest.TestCase):
    def fit(self, fraction):
        rng = random.Random(4)
        model = GestureCalibration("BOTH_BROWS", ("left",), (1,), "GEOMETRIC")
        for _ in range(3):
            model.add_repetition(*brow_rows(rng))
        return model.fit(CalibrationConfig(min_activation_fraction=fraction))

    def test_activation_keeps_at_least_forty_percent_from_rest(self):
        old, new = self.fit(0), self.fit(.4)
        travel = lambda m: (m.activation_threshold["left"] - .245) / (.303 - .245)
        self.assertLess(travel(old), .35)          # así quedaba
        self.assertGreaterEqual(travel(new), .39)  # ahora
        gap = new.activation_threshold["left"] - new.release_threshold["left"]
        self.assertGreater(gap, 2 * (old.activation_threshold["left"] - old.release_threshold["left"]))
        self.assertTrue(new.usable)
        self.assertGreaterEqual(new.quality_score, .85)  # el gesto sostenido se sigue detectando

    def test_works_for_decreasing_signals_too(self):
        rng = random.Random(8)
        model = GestureCalibration("RIGHT_WINK", ("eye_right_ratio",), (-1,), "GEOMETRIC")
        for _ in range(3):
            neutral = [(rng.gauss(.06, .002),) for _ in range(46)]
            active = [(.06 - .03 * k / 6,) for k in range(1, 4)] + [(rng.gauss(.028, .002),) for _ in range(14)]
            model.add_repetition(neutral, active)
        model.fit(CalibrationConfig())
        rest = model.neutral_statistics["eye_right_ratio"]["median"]
        closed = model.active_statistics["eye_right_ratio"]["median"]
        self.assertLessEqual(model.activation_threshold["eye_right_ratio"], rest - .4 * (rest - closed) + 1e-9)
        self.assertTrue(model.usable)

    def test_a_repetition_with_idle_lips_does_not_drag_the_threshold_to_rest(self):
        # 2026-11-10: "labios a la derecha" quedó en 0,011 (gesto 0,206, reposo 0,000) porque
        # en una repetición los labios estuvieron quietos un rato, y saltó 41 veces en la prueba.
        rng = random.Random(10)
        model = GestureCalibration("MOUTH_RIGHT", ("mouth_right",), (1,), "GEOMETRIC")
        for attempt in range(3):
            neutral = [(abs(rng.gauss(0, .0005)),) for _ in range(46)]
            idle = 5 if attempt == 1 else 0  # ~30 % del tiempo con los labios apenas corridos (~0,011)
            active = [(rng.gauss(.011, .001),) for _ in range(idle)] + [(rng.gauss(.206, .01),) for _ in range(17 - idle)]
            model.add_repetition(neutral, active)
        model.fit(CalibrationConfig())
        self.assertGreaterEqual(model.activation_threshold["mouth_right"], .4 * .2)
        self.assertTrue(model.usable)  # el gesto sostenido se sigue detectando

    def test_setting_is_bounded(self):
        for value in (-.1, .9):
            with self.assertRaises(ValueError):
                CalibrationConfig(min_activation_fraction=value)
        self.assertEqual(CalibrationConfig().validation_strikes, 3)


if __name__ == "__main__":
    unittest.main()
