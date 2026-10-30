"""Mini cámara al controlar con la nariz: guía de centro y zona quieta, opcional."""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from application_controller import ApplicationController
from face_data import FaceData
from profile_manager import ProfileManager
from profiles import ProfileStore


class FakePrefs:
    def __init__(self): self.data = {}
    def get(self, key, default): return self.data.get(key, default)
    def set(self, key, value): self.data[key] = value


@unittest.skipUnless(importlib.util.find_spec("PySide6"), "requiere PySide6")
class MiniCameraTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def snapshot(self, **overrides):
        import numpy as np
        with tempfile.TemporaryDirectory() as temp:
            s = ApplicationController(ProfileManager(ProfileStore(Path(temp) / "p")), data_dir=temp).snapshot()
        s.update(dict(profiles=[], profile={"user_id": "a", "display_name": "Ana"}, camera=True, detected=True,
                      frame=np.zeros((480, 640, 3), dtype=np.uint8), face=FaceData(True, timestamp_ms=1, nose_x=.6, nose_y=.55),
                      diagnostic=dict(neutral_x=.5, neutral_y=.5, normalized_dx=.1, normalized_dy=.05,
                                      calibrated_neutral=(.5, .5), gates={}, signals={}, active={}, sources={},
                                      gesture_offsets={}, gesture_calibrations={})) | overrides)
        return s

    def window(self, s):
        from render_gui import ReviewBridge
        from desktop.window import MainWindow
        bridge = ReviewBridge(s)
        window = MainWindow(bridge)
        window.ui_prefs = FakePrefs()
        self.addCleanup(window.close)
        return window, bridge

    def test_zoom_keeps_guide_aligned(self):
        from desktop.widgets import zoom_snapshot
        z = zoom_snapshot(self.snapshot(), 2.0)
        self.assertEqual(z["frame"].shape[:2], (240, 320))                 # medio cuadro
        self.assertAlmostEqual(z["diagnostic"]["neutral_x"], .5)           # el centro queda al medio
        self.assertAlmostEqual(z["face"].nose_x, .7)                       # 0,1 a la derecha → 0,2 en el recorte
        self.assertAlmostEqual(z["settings"]["gesture"]["dead_zone"],
                               self.snapshot()["settings"]["gesture"]["dead_zone"] * 2)
        self.assertTrue(z["settings"]["ui"]["show_overlay"])
        edge = zoom_snapshot(self.snapshot(diagnostic=dict(neutral_x=.05, neutral_y=.95)), 2.0)
        self.assertEqual(edge["frame"].shape[:2], (240, 320))              # junto al borde no se sale del cuadro

    def test_shown_only_while_controlling_with_the_nose(self):
        window, bridge = self.window(self.snapshot(control_enabled=False))
        window.mini_camera_check.setChecked(True)
        window.refresh()
        self.assertFalse(window.mini_camera.isVisible())
        bridge.data = self.snapshot(control_enabled=True, paused=True)
        window.refresh()
        self.assertTrue(window.mini_camera.isVisible())                    # también en pausa: guía para recentrar
        eyes = self.snapshot(control_enabled=True)
        eyes["settings"] = dict(eyes["settings"], ui=dict(eyes["settings"]["ui"], tracking_method="eye"))
        bridge.data = eyes
        window.refresh()
        self.assertFalse(window.mini_camera.isVisible())

    def test_option_hides_it_and_both_checkboxes_stay_in_sync(self):
        window, bridge = self.window(self.snapshot(control_enabled=True))
        window.mini_camera_check.setChecked(True)
        window.refresh()
        self.assertTrue(window.mini_camera.isVisible())
        window.mini_camera_settings_check.setChecked(False)
        self.assertFalse(window.mini_camera.isVisible())
        self.assertFalse(window.mini_camera_check.isChecked())
        self.assertFalse(window.ui_prefs.data["mini_camera"])

    def test_does_not_take_focus_or_clicks(self):
        from PySide6.QtCore import Qt
        window, _ = self.window(self.snapshot())
        flags = window.mini_camera.windowFlags()
        self.assertTrue(flags & Qt.WindowType.WindowDoesNotAcceptFocus)
        self.assertTrue(flags & Qt.WindowType.WindowTransparentForInput)
        self.assertTrue(flags & Qt.WindowType.WindowStaysOnTopHint)

    def test_overlays_have_no_owner_so_minimizing_keeps_them(self):
        """2026-10-28: al minimizar HeadMouse la mini cámara (y el aviso de dictado) desaparecían."""
        window, _ = self.window(self.snapshot())
        self.assertIsNone(window.mini_camera.parent())
        self.assertIsNone(window.dictation_overlay.parent())

    def test_dispose_releases_ownerless_overlays(self):
        from shiboken6 import isValid
        from desktop.lifecycle import dispose_window
        from render_gui import ReviewBridge
        from desktop.window import MainWindow
        window = MainWindow(ReviewBridge(self.snapshot()))  # sin addCleanup: se destruye acá
        overlays = window.owned_overlays
        dispose_window(window)
        self.assertFalse(any(isValid(o) for o in overlays))  # no quedan ventanas huérfanas

    def test_status_indicator_reflects_paused_active_and_dragging(self):
        window, bridge = self.window(self.snapshot(control_enabled=True, paused=True))
        window.mini_camera_check.setChecked(True)
        window.refresh()
        self.assertEqual(window.mini_camera.state_kind, "paused")
        self.assertIn("EN PAUSA", window.mini_camera.status_badge.text())
        self.assertIn("Ambas cejas", window.mini_camera.status_hint.text())
        self.assertIn("#d4a843", window.mini_camera.styleSheet())

        bridge.data = self.snapshot(control_enabled=True, paused=False, dragging=False)
        window.refresh()
        self.assertEqual(window.mini_camera.state_kind, "active")
        self.assertIn("ACTIVO", window.mini_camera.status_badge.text())
        self.assertIn("Control activo", window.mini_camera.status_hint.text())
        self.assertIn("#57d4c3", window.mini_camera.styleSheet())

        bridge.data = self.snapshot(control_enabled=True, paused=False, dragging=True)
        window.refresh()
        self.assertEqual(window.mini_camera.state_kind, "dragging")
        self.assertIn("ARRASTRANDO", window.mini_camera.status_badge.text())
        self.assertIn("Soltá", window.mini_camera.status_hint.text())

        bridge.data = self.snapshot(control_enabled=True, paused=True, detected=False)
        window.refresh()
        self.assertIn("Sin rostro", window.mini_camera.status_hint.text())

    @unittest.skipUnless(__import__("sys").platform == "win32", "comprobación nativa de Windows")
    def test_windows_keeps_mini_camera_visible_when_minimized(self):
        import ctypes, time
        from PySide6.QtWidgets import QApplication
        if QApplication.platformName() != "windows":
            self.skipTest("requiere la plataforma nativa de Windows, no offscreen")
        window, _ = self.window(self.snapshot(control_enabled=True))
        window.mini_camera_check.setChecked(True)
        window.show()
        window.refresh()
        window.showMinimized()
        for _ in range(20):
            self.app.processEvents()
            time.sleep(.02)
        self.assertTrue(ctypes.windll.user32.IsWindowVisible(int(window.mini_camera.winId())))


if __name__ == "__main__": unittest.main()
