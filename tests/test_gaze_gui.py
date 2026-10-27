"""Qt real/offscreen, objetivos sintéticos; mouse y webcam siempre simulados."""
import unittest
from unittest.mock import Mock
import test_gui
from test_eye_gui import EyeVision
from test_gaze_mapping import completed_session
import test_gaze_save


@unittest.skipUnless(test_gui.QT_AVAILABLE,"Requiere PySide6")
class GazeGUITests(unittest.TestCase):
    setUpClass=classmethod(test_gui.GUITests.setUpClass.__func__)
    setUp=test_gui.GUITests.setUp
    tearDown=test_gui.GUITests.tearDown
    wait=test_gui.GUITests.wait
    select_calibrated=test_gui.GUITests.select_calibrated

    def test_absolute_selector_blocks_uncalibrated_control_and_keeps_diagnostic(self):
        self.select_calibrated()
        self.window.refresh()
        self.window.tracking_combo.setCurrentIndex(self.window.tracking_combo.findData("eyes"))
        self.window.save_settings()
        self.wait(lambda:self.bridge.snapshot()["settings"]["ui"]["tracking_method"]=="eye_absolute")
        self.window.refresh()
        self.assertFalse(self.window.activate_button.isEnabled())
        self.assertEqual(self.window.home_action.text(),"Calibrar Ojos")
        self.bridge.request("start_diagnostic")
        self.wait(lambda:self.bridge.snapshot()["state"]=="DIAGNOSTIC")
        self.backend_factory.assert_not_called()

    def test_fullscreen_targets_repeat_and_escape_preserve_profile(self):
        from PySide6.QtTest import QTest
        from PySide6.QtCore import Qt
        self.select_calibrated()
        self.controller.vision_factory=EyeVision
        self.window.start_absolute_calibration()
        self.wait(lambda:self.bridge.snapshot()["state"]=="GAZE_CALIBRATING")
        self.window.refresh()
        overlay=self.window.gaze_overlay
        self.assertTrue(overlay.isVisible())
        self.assertEqual(overlay.session["total"],9)
        self.assertFalse(overlay.save_button.isEnabled())
        overlay.points.setCurrentIndex(3)
        overlay.repeat_button.click()
        self.wait(lambda:self.bridge.snapshot()["gaze_calibration"]["index"]==3)
        QTest.keyClick(overlay,Qt.Key.Key_Escape)
        self.wait(lambda:self.bridge.snapshot()["state"]=="PREVIEW")
        self.assertNotIn("absolute_calibration",self.controller.profile)
        self.backend_factory.assert_not_called()

    def test_overlay_displays_validation_errors_and_predicted_point_without_mouse(self):
        from desktop.gaze_overlay import GazeOverlay
        overlay=GazeOverlay(self.window)
        # La ventana es el propietario Qt y lo destruye en tearDown.
        session=completed_session()
        overlay.present(session.snapshot(),(.3,.7))
        self.assertTrue(overlay.save_button.isEnabled())
        self.assertIn("Error medio",overlay.info.text())
        overlay.resize(1000,700)
        overlay.show()
        self.app.processEvents()
        self.assertFalse(overlay.grab().isNull())
        overlay.present(None,(.3,.7))
        self.assertIn("DIAGNÓSTICO SEGURO",overlay.info.text())
        self.assertTrue(overlay.save_button.isHidden())
        self.backend_factory.assert_not_called()

    def test_failed_vertical_capture_displays_reason_disables_save_and_repeats_that_point(self):
        from desktop.gaze_overlay import GazeOverlay
        capture=test_gaze_save.CaptureRegressionTests()
        session=capture.completed()
        session.repeat(4)
        capture.capture(session,.5,.5-.017683836886550786)
        overlay=GazeOverlay(self.window)
        repeat=Mock()
        overlay.repeat.connect(repeat)
        overlay.present(session.snapshot(),None)
        self.assertIn("abajo no coincide",overlay.info.text())
        self.assertIn("-0.017684",overlay.info.text())
        self.assertIn("Ojos",overlay.info.text())
        self.assertFalse(overlay.save_button.isEnabled())
        self.assertEqual(overlay.points.currentData(),4)
        overlay.repeat_button.click()
        repeat.assert_called_once_with(4)
        session.repeat(4)
        capture.capture(session,.5,.7)
        overlay.present(session.snapshot(),None)
        self.assertTrue(overlay.save_button.isEnabled())
        self.backend_factory.assert_not_called()

    def test_activation_requirements_are_visible_on_main_window(self):
        from unittest.mock import patch
        self.select_calibrated()
        snapshot=dict(self.bridge.snapshot())
        reasons=["Gestos pendientes de validar para este método",
                 "Sin calibración para el método y fuente seleccionados",
                 "Iris seleccionado no detectado o frame vencido",
                 "Cámara no iniciada o todavía no lista",
                 "Falta confirmación explícita de activación"]
        snapshot.update(activation_conditions=reasons,tracking_calibrated=False)
        with patch.object(self.bridge,"snapshot",return_value=snapshot):
            self.window.refresh()
        for reason in reasons:
            self.assertIn(reason,self.window.activation_requirements.text())
        self.assertFalse(self.window.activate_button.isEnabled())
        self.backend_factory.assert_not_called()


if __name__=="__main__":unittest.main()
