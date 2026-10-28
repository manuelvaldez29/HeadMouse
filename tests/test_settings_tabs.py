"""Configuración en pestañas: lo básico primero; cada campo en un solo lugar."""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from application_controller import ApplicationController
from profile_manager import ProfileManager
from profiles import ProfileStore


@unittest.skipUnless(importlib.util.find_spec("PySide6"), "requiere PySide6")
class SettingsTabsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from render_gui import ReviewBridge
        from desktop.window import MainWindow
        with tempfile.TemporaryDirectory() as temp:
            snapshot = ApplicationController(ProfileManager(ProfileStore(Path(temp) / "p")), data_dir=temp).snapshot()
        snapshot["profiles"] = []
        self.window = MainWindow(ReviewBridge(snapshot))
        self.window.refresh()
        self.addCleanup(self.window.close)

    def tab_of(self, widget):
        tabs = self.window.settings_tabs
        for index in range(tabs.count()):
            if tabs.widget(index).isAncestorOf(widget):
                return tabs.tabText(index).split(" ·")[0]
        return None

    def test_five_tabs_and_basic_holds_what_users_change(self):
        tabs = self.window.settings_tabs
        self.assertEqual([tabs.tabText(i).split(" ·")[0] for i in range(tabs.count())],
                         ["Básico", "Gestos y scroll", "Ojos", "Cámara", "Modelos"])
        w = self.window
        for widget in (w.tracking_combo, w.fields["gesture.sensitivity_x"], w.fields["vision.camera_index"],
                       w.voice_check, w.overlay_check):
            self.assertEqual(self.tab_of(widget), "Básico")
        self.assertEqual(self.tab_of(w.fields["gesture.blink_hold_ms"]), "Gestos y scroll")
        self.assertEqual(self.tab_of(w.fields["eye.sensitivity"]), "Ojos")
        self.assertEqual(self.tab_of(w.capture_backend_combo), "Cámara")
        self.assertEqual(self.tab_of(w.prepare_voice_button), "Modelos")

    def test_every_field_lives_in_exactly_one_tab(self):
        tabs = self.window.settings_tabs
        for key, widget in self.window.fields.items():
            owners = [i for i in range(tabs.count()) if tabs.widget(i).isAncestorOf(widget)]
            self.assertEqual(len(owners), 1, key)

    def test_eyes_tab_explains_when_unused(self):
        w = self.window
        index = w.settings_tab_index["Ojos"]
        w.tracking_combo.setCurrentIndex(w.tracking_combo.findData("nose"))
        self.assertFalse(w.eye_unused_note.isHidden())
        self.assertIn("sin usar", w.settings_tabs.tabText(index))
        w.tracking_combo.setCurrentIndex(w.tracking_combo.findData("eyes"))
        self.assertTrue(w.eye_unused_note.isHidden())
        self.assertEqual(w.settings_tabs.tabText(index), "Ojos")


if __name__ == "__main__": unittest.main()
