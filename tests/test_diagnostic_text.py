"""Diagnóstico: umbrales vigentes de la señal que usa cada gesto, no los genéricos."""
import importlib.util
import unittest
from face_data import FaceData
from gesture_engine import GestureEngine
from test_core import calibration


@unittest.skipUnless(importlib.util.find_spec("PySide6"), "requiere PySide6")
class DiagnosticTextTests(unittest.TestCase):
    def diagnostic(self, **overrides):
        d = dict(
            sources=dict(LEFT_WINK="GEOMETRIC", RIGHT_WINK="GEOMETRIC", LEFT_BROW="GEOMETRIC_3D",
                         RIGHT_BROW="GEOMETRIC_3D", BOTH_BROWS="GEOMETRIC_3D", MOUTH_OPEN="GEOMETRIC"),
            signals=dict(LEFT_WINK=(.064,), RIGHT_WINK=(.065,), LEFT_BROW=(.218,), RIGHT_BROW=(.215,),
                         BOTH_BROWS=(.218, .215), MOUTH_OPEN=(.006,)),
            gates={k: dict(activation=a, release=r, enabled=True) for k, a, r in (
                ("LEFT_WINK", {"eye_left_ratio": .0499}, {"eye_left_ratio": .0553}),
                ("RIGHT_WINK", {"eye_right_ratio": .0502}, {"eye_right_ratio": .0554}),
                ("LEFT_BROW", {"left": .2338}, {"left": .2277}),
                ("RIGHT_BROW", {"right": .2351}, {"right": .2255}),
                ("BOTH_BROWS", {"left": .2482, "right": .2383}, {"left": .2349, "right": .2269}),
                ("MOUTH_OPEN", {"mouth_open": .0825}, {"mouth_open": .0555}))},
            active={}, gesture_offsets={})
        d.update(overrides)
        return d

    def test_shows_profile_signal_and_its_thresholds(self):
        from desktop.window import gesture_threshold_lines
        text = gesture_threshold_lines(self.diagnostic())
        self.assertIn("Cejas izq/der · Geométrica 3D: 0.2180 / 0.2150", text)
        self.assertIn("activación 0.2338 / 0.2351", text)
        self.assertIn("Boca · Geométrica: 0.0060", text)
        self.assertNotIn("0.2900", text)  # umbral genérico de compatibilidad

    def test_disabled_active_and_recentered_gestures(self):
        from desktop.window import gesture_threshold_lines
        d = self.diagnostic(active={"LEFT_BROW": True}, gesture_offsets={"LEFT_BROW": {"left": .004}})
        d["gates"]["MOUTH_OPEN"]["enabled"] = False
        d["gates"]["RIGHT_WINK"]["enabled"] = False
        text = gesture_threshold_lines(d)
        self.assertIn("Boca: no disponible", text)
        self.assertIn("guiño derecho no disponible", text)
        self.assertIn("gesto activo: ceja izquierda", text)
        self.assertIn("ajuste por recentrado (ceja izquierda): +0.0040", text)

    def test_engine_gates_reflect_recentering(self):
        from desktop.window import gesture_threshold_lines
        ms = [1000]
        engine = GestureEngine(None, calibration=calibration(), clock=lambda: ms[0] / 1000)
        engine.update(FaceData(True, timestamp_ms=ms[0]))
        d = engine.diagnostic()
        self.assertEqual(d["gates"]["MOUTH_OPEN"]["activation"], {"mouth_open": calibration()["thresholds"]["mouth_open"]})
        self.assertIn("Boca · Geométrica", gesture_threshold_lines(d))


if __name__ == "__main__": unittest.main()
