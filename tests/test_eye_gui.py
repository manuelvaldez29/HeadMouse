"""Interfaz Qt real con iris sintético; sin webcam ni backend del SO."""
import unittest
from dataclasses import replace
import test_gui
from test_eye_tracking import eye_landmarks
from eye_geometry import extract_gaze


class EyeVision(test_gui.FakeVision):
    def get_face_data(self):
        return replace(super().get_face_data(),**extract_gaze(eye_landmarks(),640,480))


@unittest.skipUnless(test_gui.QT_AVAILABLE,"Instalar PySide6 para pruebas de interfaz")
class EyeGUITests(unittest.TestCase):
    setUpClass=classmethod(test_gui.GUITests.setUpClass.__func__)
    setUp=test_gui.GUITests.setUp
    tearDown=test_gui.GUITests.tearDown
    wait=test_gui.GUITests.wait
    select_calibrated=test_gui.GUITests.select_calibrated

    def test_select_eye_requires_calibration_and_switch_back_to_nose(self):
        self.select_calibrated()
        self.window.refresh()
        self.window.tracking_combo.setCurrentIndex(self.window.tracking_combo.findData("eyes"))
        self.assertFalse(self.window.eye_warning.isHidden())
        self.window.save_settings()
        self.wait(lambda:self.bridge.snapshot()["settings"]["ui"]["tracking_method"]=="eye_absolute")
        self.window.refresh()
        self.assertFalse(self.window.activate_button.isEnabled())
        self.assertIn("Calibrar Ojos",self.window.home_action.text())
        self.assertFalse(self.window.eye_save.isEnabled())
        self.assertIsNotNone(self.window._home_step(self.bridge.snapshot())[2])
        self.window.tracking_combo.setCurrentIndex(self.window.tracking_combo.findData("nose"))
        self.window.save_settings()
        self.wait(lambda:self.bridge.snapshot()["settings"]["ui"]["tracking_method"]=="nose")
        self.window.refresh()
        self.assertTrue(self.window.activate_button.isEnabled())
        self.backend_factory.assert_not_called()

    def test_worker_capture_save_diagnostic_and_preview(self):
        self.select_calibrated()
        self.controller.vision_factory=EyeVision
        settings=dict(self.bridge.snapshot()["settings"])
        settings["ui"]=dict(settings["ui"],tracking_method="eye")
        self.bridge.request("save_settings",settings=settings)
        self.wait(lambda:self.bridge.snapshot()["settings"]["ui"]["tracking_method"]=="eye")
        self.window.refresh()
        self.window.tracking_combo.setCurrentIndex(self.window.tracking_combo.findData("eyes"))
        self.window.save_settings()
        self.wait(lambda:self.bridge.snapshot()["settings"]["ui"]["tracking_method"]=="eye")
        original=self.controller.profile["thresholds"].copy()
        self.window.show_page(4)
        self.window.eye_start.click()
        self.app.processEvents()
        self.assertEqual(self.window.stack.currentIndex(),2)
        self.assertEqual(self.window.calibration_tabs.currentIndex(),1)
        self.wait(lambda:bool((self.bridge.snapshot().get("eye_calibration") or {}).get("can_save")))
        self.window.refresh()
        self.assertTrue(self.window.eye_save.isEnabled())
        self.assertIsNotNone(self.window.eye_preview.image)
        self.window.eye_save.click()
        self.wait(lambda:self.bridge.snapshot().get("state")=="DIAGNOSTIC")
        self.window.show_page(3)
        self.window.refresh()
        self.assertIn("Estrategia activa: eye",self.window.eye_diagnostic.text())
        self.assertIn("left_gaze_x/y",self.window.eye_diagnostic.text())
        self.assertIn("Neutral gaze:",self.window.eye_diagnostic.text())
        self.assertEqual(self.controller.profile["thresholds"],original)
        self.assertTrue(self.window.activate_button.isEnabled())
        self.backend_factory.assert_not_called()


if __name__=="__main__": unittest.main()
