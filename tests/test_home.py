"""Inicio: último perfil recordado y un botón principal que hace el próximo paso."""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from application_controller import ApplicationController
from config import ROOT
from profile_manager import ProfileManager
from profiles import ProfileStore
from test_core import calibration


ENTRY = [dict(user_id="julian", display_name="Manu", status="Listo para comenzar", calibrated_at="", error="")]


class LastProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT)
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def controller(self):
        return ApplicationController(ProfileManager(ProfileStore(self.root / "profiles")), data_dir=self.root)

    def test_last_selected_profile_is_restored_on_start(self):
        c = self.controller()
        c.create_profile("Ana")
        c.create_profile("Beto")
        ana = next(p["user_id"] for p in c.profiles.list_profiles() if p["display_name"] == "Ana")
        c.select_profile(ana)
        self.assertEqual(self.controller().profile["user_id"], ana)

    def test_single_profile_is_selected_without_memory(self):
        c = self.controller()
        c.create_profile("Única")
        (self.root / "last_profile.json").unlink()
        self.assertEqual(self.controller().profile["display_name"], "Única")

    def test_no_choice_when_several_profiles_and_no_memory(self):
        c = self.controller()
        c.create_profile("Ana")
        c.create_profile("Beto")
        (self.root / "last_profile.json").unlink()
        self.assertIsNone(self.controller().profile)

    def test_deleted_or_broken_memory_is_ignored(self):
        c = self.controller()
        c.create_profile("Ana")
        c.delete_profile(confirmed=True)
        self.assertFalse((self.root / "last_profile.json").exists())
        (self.root / "last_profile.json").write_text("{roto", encoding="utf-8")
        self.assertIsNone(self.controller().profile)
        (self.root / "last_profile.json").write_text('{"user_id": "no_existe"}', encoding="utf-8")
        self.assertIsNone(self.controller().profile)


@unittest.skipUnless(importlib.util.find_spec("PySide6"), "requiere PySide6")
class HomeButtonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def window(self, **overrides):
        from render_gui import ReviewBridge
        from desktop.window import MainWindow
        with tempfile.TemporaryDirectory() as temp:
            snapshot = ApplicationController(ProfileManager(ProfileStore(Path(temp) / "p")), data_dir=temp).snapshot()
        snapshot.update(dict(profiles=[]) | overrides)
        bridge = ReviewBridge(snapshot)
        bridge.activate, bridge.stop = Mock(), Mock()
        window = MainWindow(bridge)
        window.refresh()
        self.addCleanup(window.close)
        return window, bridge

    def ready_profile(self):
        p = calibration()
        p.update(display_name="Manu", status="calibrated", validation={"passed": True})
        return p

    def test_button_follows_next_step(self):
        cases = ((dict(profile=None), "Crear mi perfil"),
                 (dict(profile=dict(calibration(), status="draft"), profiles=ENTRY), "Calibrar mis gestos"),
                 (dict(profile=dict(calibration(), validation={"passed": False}), profiles=ENTRY), "Validar mi calibración"),
                 (dict(profile=self.ready_profile(), profiles=ENTRY), "▶  Iniciar HeadMouse"),
                 (dict(profile=self.ready_profile(), profiles=ENTRY, control_enabled=True, paused=True), "■  Detener HeadMouse"))
        for overrides, text in cases:
            with self.subTest(text=text):
                window, _ = self.window(**overrides)
                self.assertEqual(window.home_action.text(), text)

    def test_start_is_one_click_and_stop_uses_emergency_path(self):
        window, bridge = self.window(profile=self.ready_profile(), profiles=ENTRY)
        window.home_action.click()
        bridge.activate.assert_called_once()  # sin diálogo extra: arranca en pausa
        window, bridge = self.window(profile=self.ready_profile(), profiles=ENTRY, control_enabled=True, paused=False)
        self.assertEqual(window.home_state.text(), "ACTIVO")
        window.home_action.click()
        bridge.stop.assert_called_once()

    def test_duplicate_navigation_buttons_are_gone(self):
        from PySide6.QtWidgets import QPushButton
        window, _ = self.window(profile=self.ready_profile(), profiles=ENTRY)
        home = window.stack.widget(0)
        texts = {b.text() for b in home.findChildren(QPushButton)}
        self.assertEqual(texts, {"▶  Iniciar HeadMouse"})



@unittest.skipUnless(importlib.util.find_spec("PySide6"), "requiere PySide6")
class CalibrationButtonTests(HomeButtonTests):
    def wizard(self, state, **extra):
        base = dict(state=state, stage="active", phase=2, total_phases=7, gesture_id="RIGHT_WINK",
                    instruction="Guiñá el ojo derecho", countdown=0, progress=0, samples=0, attempt=1,
                    repetitions=3, feedback="", capture_message="", recognized=[], meter=[], error="",
                    enabled={k: True for k in ("LEFT_WINK", "RIGHT_WINK", "LEFT_BROW", "RIGHT_BROW",
                                               "MOUTH_OPEN", "BOTH_BROWS")},
                    quality={"LEFT_WINK": dict(label="BUENA", score=1, retries=0)}, can_save=False)
        return base | extra

    def calibrating(self, wizard):
        window, bridge = self.window(profile=self.ready_profile(), profiles=ENTRY, state="CALIBRATING", wizard=wizard)
        bridge.request = Mock()
        return window, bridge

    def test_primary_follows_wizard_state(self):
        cases = (("measuring", "Midiendo…", False), ("validation", "Probando tus gestos…", False),
                 ("error", "Repetir este gesto", True))
        for state, text, enabled in cases:
            with self.subTest(state=state):
                window, _ = self.calibrating(self.wizard(state))
                self.assertEqual(window.calibration_primary.text(), text)
                self.assertEqual(window.calibration_primary.isEnabled(), enabled)

    def test_error_offers_repeat_or_skip_the_gesture(self):
        window, bridge = self.calibrating(self.wizard("error", error="Tiempo agotado."))
        self.assertFalse(window.calibration_secondary.isHidden())
        window.calibration_primary.click()
        bridge.request.assert_called_with("repeat_calibration", gesture_id=None)
        window.calibration_secondary.click()
        bridge.request.assert_called_with("set_calibration_gesture", gesture_id="RIGHT_WINK", enabled=False)
        self.assertIn("✗", window.calibration_steps.text())

    def test_validation_error_retries_and_validated_saves(self):
        window, bridge = self.calibrating(self.wizard("validation", stage="gesture", error="Gesto incorrecto."))
        self.assertEqual(window.calibration_primary.text(), "Reintentar la prueba")
        window, bridge = self.calibrating(self.wizard("validated", can_save=True,
                                                      recognized=["LEFT_CLICK", "RIGHT_CLICK"]))
        self.assertTrue(window.calibration_primary.isHidden())
        self.assertFalse(window.save_calibration_button.isHidden())
        self.assertTrue(window.save_calibration_button.isEnabled())
        self.assertEqual(window.calibration_steps.text().count("detectado"), 6)


class CalibrationOrderTests(unittest.TestCase):
    def test_checklist_follows_capture_order(self):
        if not importlib.util.find_spec("PySide6"):
            self.skipTest("requiere PySide6")
        from desktop.window import CALIBRATION_ORDER
        from gesture_signals import GESTURE_SIGNALS
        self.assertEqual(CALIBRATION_ORDER, tuple(GESTURE_SIGNALS))


if __name__ == "__main__": unittest.main()
