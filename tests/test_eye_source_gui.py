"""Selector Qt real con iris sintéticos y backend prohibido."""
import unittest
from dataclasses import replace
import test_gui
from test_eye_sources import source_face, completed_source_session
from ocular_profiles import with_calibration


class LeftOnlyVision(test_gui.FakeVision):
    def get_face_data(self):
        face=super().get_face_data()
        signal=source_face("left",stamp=face.timestamp_ms)
        return replace(signal,eye_left_ratio=.1,eye_right_ratio=.12,detected_at=face.detected_at)


@unittest.skipUnless(test_gui.QT_AVAILABLE,"Requiere PySide6")
class SourceGUITests(unittest.TestCase):
    setUpClass=classmethod(test_gui.GUITests.setUpClass.__func__)
    setUp=test_gui.GUITests.setUp
    tearDown=test_gui.GUITests.tearDown
    wait=test_gui.GUITests.wait
    select_calibrated=test_gui.GUITests.select_calibrated

    def test_overlays_have_the_main_window_as_native_owner(self):
        self.assertIs(self.window.dictation_overlay.parent(),self.window)
        self.window._open_gaze_overlay()
        self.assertIs(self.window.gaze_overlay.parent(),self.window)
        self.window.gaze_overlay.close()

    def test_default_source_is_both_and_selector_visible_for_both_eye_methods(self):
        self.select_calibrated()
        self.window.refresh()
        self.assertEqual(self.window.eye_source_combo.currentData(),"both")
        self.assertTrue(self.window.eye_source_combo.isHidden())
        self.assertEqual(self.window.tracking_combo.count(),2)
        self.assertEqual(self.window.eye_source_combo.count(),3)
        for method in ("eyes",):
            self.window.tracking_combo.setCurrentIndex(self.window.tracking_combo.findData(method))
            self.assertFalse(self.window.eye_source_combo.isHidden())
        self.backend_factory.assert_not_called()

    def test_source_selection_persists_and_diagnostic_uses_only_available_selected_eye(self):
        self.select_calibrated()
        self.controller.vision_factory=LeftOnlyVision
        self.window.refresh()
        self.window.tracking_combo.setCurrentIndex(self.window.tracking_combo.findData("eyes"))
        self.window.eye_source_combo.setCurrentIndex(self.window.eye_source_combo.findData("left"))
        self.window.save_settings()
        self.wait(lambda:self.bridge.snapshot()["settings"]["ui"]["eye_source"]=="left")
        self.window.refresh()
        self.assertFalse(self.window.activate_button.isEnabled())
        self.bridge.request("start_diagnostic")
        self.wait(lambda:self.bridge.snapshot()["state"]=="DIAGNOSTIC")
        self.window.refresh()
        text=self.window.eye_diagnostic.text()
        self.assertIn("Fuente ocular: Ojo izquierdo",text)
        self.assertIn("Iris izquierdo: True",text)
        self.assertIn("Iris derecho: False",text)
        self.assertIsNotNone(self.bridge.snapshot()["used_gaze"])
        persisted=self.manager.store.load("julian")
        self.assertEqual(persisted["settings"]["ui"]["eye_source"],"left")
        self.backend_factory.assert_not_called()

    def test_neutral_calibration_announces_source_and_saves_without_other_iris(self):
        self.select_calibrated()
        self.controller.vision_factory=LeftOnlyVision
        settings=dict(self.bridge.snapshot()["settings"])
        settings["ui"]=dict(settings["ui"],tracking_method="eye")
        self.bridge.request("save_settings",settings=settings)
        self.wait(lambda:self.bridge.snapshot()["settings"]["ui"]["tracking_method"]=="eye")
        self.window.refresh()
        self.window.tracking_combo.setCurrentIndex(self.window.tracking_combo.findData("eyes"))
        self.window.eye_source_combo.setCurrentIndex(self.window.eye_source_combo.findData("left"))
        self.window.save_settings()
        self.wait(lambda:self.bridge.snapshot()["settings"]["ui"]["eye_source"]=="left")
        self.window.eye_start.click()
        self.wait(lambda:bool((self.bridge.snapshot().get("eye_calibration") or {}).get("can_save")))
        self.window.refresh()
        self.assertEqual(self.bridge.snapshot()["eye_calibration"]["eye_source"],"left")
        self.window.eye_save.click()
        self.wait(lambda:self.bridge.snapshot()["state"]=="DIAGNOSTIC")
        self.window.refresh()
        self.assertTrue(self.window.activate_button.isEnabled())
        self.assertEqual(self.controller.profile["tracking_calibrations"]["left"]["eye_source"],"left")
        self.assertNotIn("tracking_calibration",self.controller.profile)
        self.backend_factory.assert_not_called()
