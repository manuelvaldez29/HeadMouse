"""Línea de estado: un indicador y un solo mensaje (error > aviso reciente > próximo paso)."""
import importlib.util
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from application_controller import ApplicationController
from profile_manager import ProfileManager
from profiles import ProfileStore

NOT_BLOCKING = ["Cámara no iniciada o todavía no lista", "Falta confirmación explícita de activación"]


@unittest.skipUnless(importlib.util.find_spec("PySide6"), "requiere PySide6")
class StatusMessageTests(unittest.TestCase):
    def message(self, **s):
        from desktop.window import status_message
        base = dict(state="HOME", message="", control_enabled=False, paused=True, camera=False,
                    profile={"user_id": "a"}, activation_conditions=[])
        return status_message(base | s)

    def test_first_real_blocker_in_plain_words(self):
        self.assertEqual(self.message(profile=None, activation_conditions=["Seleccioná un perfil"] + NOT_BLOCKING),
                         ("Elegí un perfil en Perfiles para empezar.", False))
        text, _ = self.message(activation_conditions=["Gestos pendientes de validar para este método"] + NOT_BLOCKING)
        self.assertIn("andá a Calibración", text)
        text, _ = self.message(activation_conditions=["Gestos pendientes de validar para este método; sólo movimiento, sin clics"])
        self.assertTrue(text.startswith("Ojos: sólo movimiento"))

    def test_non_blocking_conditions_mean_ready(self):
        self.assertEqual(self.message(activation_conditions=NOT_BLOCKING),
                         ("Listo para empezar: tocá «Iniciar HeadMouse» en Inicio.", False))

    def test_iris_only_matters_with_camera_on_and_unknown_pass_through(self):
        iris = ["Iris seleccionado no detectado o frame vencido"]
        self.assertIn("Listo", self.message(activation_conditions=iris)[0])
        self.assertIn("No se ven tus ojos", self.message(activation_conditions=iris, camera=True)[0])
        self.assertEqual(self.message(activation_conditions=["Condición nueva"])[0], "Condición nueva")

    def test_precedence_error_event_control(self):
        self.assertEqual(self.message(state="ERROR", message="Se cortó la cámara"), ("Se cortó la cámara", True))
        self.assertEqual(self.message(activation_conditions=["Seleccioná un perfil"]) [0][:5], "Elegí")
        from desktop.window import status_message
        self.assertEqual(status_message(dict(state="HOME", control_enabled=False), ("Centro ajustado.", 0, False)),
                         ("Centro ajustado.", False))
        self.assertIn("Levantá ambas cejas", self.message(control_enabled=True, paused=True)[0])
        self.assertIn("F8", self.message(control_enabled=True, paused=False)[0])


@unittest.skipUnless(importlib.util.find_spec("PySide6"), "requiere PySide6")
class StatusBarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from render_gui import ReviewBridge
        from desktop.window import MainWindow
        with tempfile.TemporaryDirectory() as temp:
            snapshot = ApplicationController(ProfileManager(ProfileStore(Path(temp) / "p")), data_dir=temp).snapshot()
        snapshot.update(profiles=[], profile={"user_id": "a", "display_name": "Ana"}, activation_conditions=NOT_BLOCKING)
        self.bridge = ReviewBridge(snapshot)
        self.window = MainWindow(self.bridge)
        self.addCleanup(self.window.close)
        self.window.refresh()

    def test_single_line_with_indicator_and_hidden_full_list(self):
        w = self.window
        self.assertEqual(w.control_status.text(), "●  DESACTIVADO")
        self.assertTrue(w.activation_requirements.isHidden())
        self.assertIn("Falta confirmación explícita", w.activate_button.toolTip())  # la lista sigue disponible
        self.assertIn("Listo para empezar", w.banner.text())

    def test_new_message_shows_for_eight_seconds_then_next_step(self):
        w = self.window
        start = time.monotonic()
        self.bridge.data = dict(self.bridge.data, message="Centro ajustado a tu postura actual.")
        with patch("desktop.window.time.monotonic", return_value=start):
            w.refresh()
        self.assertEqual(w.banner.text(), "Centro ajustado a tu postura actual.")
        with patch("desktop.window.time.monotonic", return_value=start + 9):
            w.refresh()
        self.assertIn("Listo para empezar", w.banner.text())

    def test_gui_errors_are_red_and_temporary(self):
        w = self.window
        w.show_error("Primero elegí un perfil")
        self.assertEqual((w.banner.text(), w.banner.objectName()), ("Primero elegí un perfil", "StatusError"))
        w.refresh()
        self.assertEqual(w.banner.text(), "Primero elegí un perfil")  # sigue durante 8 s
        self.window._status_event = ("x", 0, True)
        w.refresh()
        self.assertEqual(w.banner.objectName(), "StatusMessage")


if __name__ == "__main__": unittest.main()
