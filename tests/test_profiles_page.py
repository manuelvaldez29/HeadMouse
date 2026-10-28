"""Perfiles: una tarjeta por perfil con estado de Nariz/Ojos, fecha legible y acciones."""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from application_controller import ApplicationController
from profile_manager import ProfileManager
from profiles import ProfileStore

ENTRIES = [dict(user_id="user_b", display_name="Julián", status="Sin calibrar", calibrated_at="—", error="",
                eyes="Movimiento calibrado"),
           dict(user_id="user_a", display_name="Manu", status="Listo para comenzar",
                calibrated_at="2026-10-11T23:48:20+00:00", error="", eyes="Sin calibrar"),
           dict(user_id="user_c", display_name="user_c", status="Necesita reparación", calibrated_at="—",
                error="JSON inválido", eyes="—")]


class EyesStatusTests(unittest.TestCase):
    def test_eyes_summary(self):
        self.assertEqual(ProfileManager.eyes_status({}), "Sin calibrar")
        self.assertEqual(ProfileManager.eyes_status({"tracking_calibrations": {"both": {}}}), "Sin calibrar")
        self.assertEqual(ProfileManager.eyes_status({"absolute_calibration": {"method": "eye_absolute"}}),
                         "Movimiento calibrado")

    def test_listing_includes_eyes(self):
        with tempfile.TemporaryDirectory() as temp:
            manager = ProfileManager(ProfileStore(Path(temp)))
            manager.create("Ana")
            self.assertEqual(manager.list_profiles()[0]["eyes"], "Sin calibrar")


@unittest.skipUnless(importlib.util.find_spec("PySide6"), "requiere PySide6")
class ProfilesPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def window(self, profile, entries):
        from render_gui import ReviewBridge
        from desktop.window import MainWindow
        with tempfile.TemporaryDirectory() as temp:
            snapshot = ApplicationController(ProfileManager(ProfileStore(Path(temp) / "p")), data_dir=temp).snapshot()
        snapshot.update(profile=profile, profiles=entries)
        bridge = ReviewBridge(snapshot)
        bridge.request = Mock()
        window = MainWindow(bridge)
        window.refresh()
        self.addCleanup(window.close)
        return window, bridge

    def cards(self, window):
        from PySide6.QtWidgets import QFrame
        layout = window.profile_cards
        return [layout.itemAt(i).widget() for i in range(layout.count() - 1)]

    def texts(self, card):
        from PySide6.QtWidgets import QLabel, QPushButton
        return ([l.text() for l in card.findChildren(QLabel)], [b.text() for b in card.findChildren(QPushButton)])

    def test_current_profile_first_with_its_actions(self):
        window, bridge = self.window({"user_id": "user_a", "display_name": "Manu"}, ENTRIES)
        cards = self.cards(window)
        self.assertEqual(len(cards), 3)
        labels, buttons = self.texts(cards[0])
        self.assertIn("●  Manu", labels)
        self.assertIn("Nariz: Listo para comenzar   ·   Ojos: Sin calibrar", labels)
        self.assertTrue(any(l.startswith("Última calibración: 11/10/2026") or l.startswith("Última calibración: 12/10/2026")
                            for l in labels))
        self.assertEqual(buttons, ["Calibrar", "Renombrar", "Eliminar"])
        self.assertEqual(cards[0].objectName(), "ProfileCardActive")

    def test_other_profiles_offer_use_and_broken_ones_explain(self):
        from PySide6.QtWidgets import QPushButton
        window, bridge = self.window({"user_id": "user_a", "display_name": "Manu"}, ENTRIES)
        cards = self.cards(window)
        labels, buttons = self.texts(cards[1])
        self.assertEqual(buttons, ["Usar este perfil"])
        cards[1].findChildren(QPushButton)[0].click()
        bridge.request.assert_called_with("select_profile", user_id="user_b")
        labels, buttons = self.texts(cards[2])
        self.assertEqual(buttons, [])
        self.assertIn("No se pudo leer este perfil: JSON inválido", labels)

    def test_empty_state(self):
        window, _ = self.window(None, [])
        labels, buttons = self.texts(self.cards(window)[0])
        self.assertIn("Todavía no hay perfiles", labels)

    def test_friendly_date(self):
        from desktop.window import friendly_date
        self.assertEqual(friendly_date("—"), "pendiente")
        self.assertEqual(friendly_date(None), "pendiente")
        self.assertEqual(friendly_date("2026-10-11T20:48:00"), "11/10/2026 20:48")


if __name__ == "__main__": unittest.main()
