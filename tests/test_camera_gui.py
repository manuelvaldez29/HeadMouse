"""QThread/Qt reales con cámara pendiente simulada y mouse prohibido."""
import unittest
from unittest.mock import patch
import test_gui
from test_camera_startup import PendingVision


@unittest.skipUnless(test_gui.QT_AVAILABLE,"Requiere PySide6")
class CameraGUITests(unittest.TestCase):
    setUpClass=classmethod(test_gui.GUITests.setUpClass.__func__)
    setUp=test_gui.GUITests.setUp
    tearDown=test_gui.GUITests.tearDown
    wait=test_gui.GUITests.wait
    select_calibrated=test_gui.GUITests.select_calibrated

    def test_stop_button_turns_off_camera_in_preview_without_control(self):
        from PySide6.QtWidgets import QPushButton
        self.select_calibrated()
        self.bridge.request("start_diagnostic")
        self.wait(lambda:self.bridge.snapshot()["camera"])
        vision=self.controller.vision
        self.window.refresh()
        self.assertIsNotNone(self.window.preview.image)
        self.assertIsNone(self.controller.control)
        before=self.manager.store.path("julian").read_bytes()
        stop=next(b for b in self.window.findChildren(QPushButton) if b.text()=="DETENER CONTROL · F8")
        stop.click()
        self.wait(lambda:not self.bridge.snapshot()["camera"])
        self.window.refresh()
        self.assertFalse(vision.is_alive())
        self.assertIsNone(self.window.preview.image)
        self.assertIsNone(self.bridge.snapshot()["frame"])
        self.assertEqual(self.bridge.snapshot()["state"],"HOME")
        self.assertEqual(self.manager.store.path("julian").read_bytes(),before)
        self.backend_factory.assert_not_called()

    def test_f8_stops_camera_and_pending_calibration_start(self):
        from PySide6.QtTest import QTest
        from PySide6.QtCore import Qt
        self.select_calibrated();self.controller.vision_factory=PendingVision
        self.bridge.request("start_calibration")
        self.wait(lambda:self.bridge.snapshot()["state"]=="CAMERA_STARTING")
        vision=self.controller.vision
        self.window.activateWindow();self.app.processEvents()
        QTest.keyClick(self.window,Qt.Key.Key_F8)
        self.wait(lambda:not self.bridge.snapshot()["camera"])
        self.assertTrue(vision.cancelled)
        self.assertIsNone(self.bridge.worker.pending_camera)
        self.assertIsNone(self.controller.wizard)
        self.backend_factory.assert_not_called()

    def test_home_stop_closes_active_control_and_camera(self):
        from PySide6.QtWidgets import QMessageBox
        self.select_calibrated();self.window.refresh()
        with patch.object(QMessageBox,"question",return_value=QMessageBox.StandardButton.Yes):
            self.window.activate()
        self.wait(lambda:self.bridge.snapshot()["control_enabled"])
        vision=self.controller.vision
        self.window.refresh();self.window.home_action.click()
        self.wait(lambda:not self.bridge.snapshot()["camera"])
        self.assertFalse(vision.is_alive())
        self.assertIsNone(self.controller.control)
        self.assertTrue(self.controller.emergency.is_set())

    def test_stop_is_processed_while_camera_waits_for_mediapipe(self):
        self.select_calibrated()
        self.controller.vision_factory=PendingVision
        self.bridge.request("start_calibration")
        self.wait(lambda:self.bridge.snapshot()["state"]=="CAMERA_STARTING")
        self.window.refresh()
        self.assertFalse(self.window.activate_button.isEnabled())
        self.assertEqual(self.bridge.snapshot()["camera_status"]["stage"],"MEDIAPIPE_INITIALIZING")
        vision=self.controller.vision
        self.bridge.stop()
        self.wait(lambda:self.controller.vision is None)
        self.assertTrue(vision.cancelled)
        self.assertIsNone(self.controller.wizard)
        self.backend_factory.assert_not_called()

    def test_usb_camera_preset_only_applies_on_save(self):
        self.select_calibrated()
        self.window.refresh()
        previous=self.controller.config.vision.target_fps
        self.window.usb_camera_preset()
        self.assertEqual(self.controller.config.vision.target_fps,previous)
        self.assertEqual(self.window.fields["vision.frame_width"].value(),640)
        self.assertEqual(self.window.capture_backend_combo.currentData(),"dshow")
        self.window.save_settings()
        self.wait(lambda:self.bridge.snapshot()["settings"]["vision"]["target_fps"]==15)
        settings=self.bridge.snapshot()["settings"]["vision"]
        self.assertEqual(settings["frame_height"],480)
        self.assertEqual(settings["capture_backend"],"dshow")
        self.assertEqual(settings["startup_timeout_s"],20)
        self.backend_factory.assert_not_called()
