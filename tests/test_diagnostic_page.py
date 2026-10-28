"""Diagnóstico: estado en lenguaje simple arriba; los números técnicos, plegados."""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from application_controller import ApplicationController
from face_data import FaceData
from profile_manager import ProfileManager
from profiles import ProfileStore


@unittest.skipUnless(importlib.util.find_spec("PySide6"), "requiere PySide6")
class DiagnosticPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    GATES = {"LEFT_WINK": dict(activation={"eye_left_ratio": .05}, release={"eye_left_ratio": .055}, enabled=True),
             "MOUTH_OPEN": dict(activation={"mouth_open": .08}, release={"mouth_open": .05}, enabled=True),
             "BOTH_BROWS": dict(activation={"left": .24, "right": .24}, release={"left": .23, "right": .23}, enabled=True),
             "RIGHT_BROW": dict(activation={"right": .23}, release={"right": .22}, enabled=False)}
    CAL = {key: dict(enabled=True, source="GEOMETRIC", quality_score=1., repetitions_valid=3,
                     activation_threshold=gate["activation"], release_threshold=gate["release"], neutral_statistics=neutral)
           for key, gate, neutral in (
               ("LEFT_WINK", GATES["LEFT_WINK"], {"eye_left_ratio": {"median": .065}}),
               ("MOUTH_OPEN", GATES["MOUTH_OPEN"], {"mouth_open": {"median": .005}}),
               ("BOTH_BROWS", GATES["BOTH_BROWS"], {"left": {"median": .20}, "right": {"median": .20}}))}

    def window(self, **overrides):
        from render_gui import ReviewBridge
        from desktop.window import MainWindow
        with tempfile.TemporaryDirectory() as temp:
            snapshot = ApplicationController(ProfileManager(ProfileStore(Path(temp) / "p")), data_dir=temp).snapshot()
        snapshot.update(dict(profiles=[]) | overrides)
        window = MainWindow(ReviewBridge(snapshot))
        self.addCleanup(window.close)
        window.refresh()
        return window

    def diagnostic(self, dx=0., dy=0., **extra):
        return dict(normalized_dx=dx, normalized_dy=dy, neutral_x=.5, neutral_y=.5, calibrated_neutral=(.5, .5),
                    gates=self.GATES, gesture_calibrations=self.CAL, head_still=abs(dx) <= .03 and abs(dy) <= .03,
                    signals={"LEFT_WINK": (.035,), "MOUTH_OPEN": (.08,), "BOTH_BROWS": (.24, .21)},
                    active={"MOUTH_OPEN": True}, sources={}, gesture_offsets={}) | extra

    def test_progress_toward_activation(self):
        from desktop.widgets import gesture_progress
        self.assertAlmostEqual(gesture_progress((.035,), self.CAL["LEFT_WINK"], self.GATES["LEFT_WINK"], (-1,)), 2.)
        self.assertAlmostEqual(gesture_progress((.0425,), self.CAL["MOUTH_OPEN"], self.GATES["MOUTH_OPEN"], (1,)), .5)
        # Dos canales: avanza lo que avance el más atrasado.
        self.assertAlmostEqual(gesture_progress((.24, .21), self.CAL["BOTH_BROWS"], self.GATES["BOTH_BROWS"], (1, 1)), .25)
        self.assertIsNone(gesture_progress(None, {}, self.GATES["LEFT_WINK"], (-1,)))
        self.assertIsNone(gesture_progress((.05,), {}, self.GATES["LEFT_WINK"], (-1,)))  # sin reposo calibrado

    def test_plain_language_state(self):
        w = self.window(camera=False)
        self.assertEqual(w.diag_face.text(), "Cámara apagada")
        w = self.window(camera=True, detected=False, face=FaceData(False))
        self.assertIn("No te veo la cara", w.diag_face.text())
        w = self.window(camera=True, detected=True, fps=23, face=FaceData(True, timestamp_ms=1),
                        diagnostic=self.diagnostic(dx=.08, dy=-.06), gesture="LEFT_WINK", action="LEFT_CLICK")
        self.assertIn("Te veo la cara", w.diag_face.text())
        self.assertIn("→ derecha y ↑ arriba", w.diag_cursor.text())
        self.assertIn("cejas en pausa", w.diag_cursor.text())
        self.assertEqual(w.diag_last.text(), "Último gesto: Guiño izquierdo  →  Click izquierdo (sin ejecutar)")
        w = self.window(camera=True, detected=True, fps=23, face=FaceData(True, timestamp_ms=1),
                        diagnostic=self.diagnostic())
        self.assertIn("quieto", w.diag_cursor.text())

    def test_meters_and_technical_details(self):
        w = self.window(camera=True, detected=True, face=FaceData(True, timestamp_ms=1), diagnostic=self.diagnostic())
        rows = {label: (value, active, available) for label, value, active, available in w.gesture_meters.rows}
        self.assertAlmostEqual(rows["Boca abierta"][0], 1.)
        self.assertTrue(rows["Boca abierta"][1])
        self.assertFalse(rows["Ceja derecha"][2])  # desmarcado en la calibración
        self.assertTrue(w.diagnostic_values.parentWidget().isHidden())  # plegado por defecto
        self.assertIn("Facial X", w.diagnostic_values.text())  # el texto técnico se sigue generando
        w.diagnostic_details_toggle.setChecked(True)
        self.assertFalse(w.diagnostic_values.parentWidget().isHidden())


if __name__ == "__main__": unittest.main()
