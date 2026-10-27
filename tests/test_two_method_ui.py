"""Dos métodos públicos y webcam compartida visible en calibración."""
import unittest
from unittest.mock import Mock,patch
from PySide6.QtCore import QThread,QPoint
import test_gui
from test_eye_gui import EyeVision


@unittest.skipUnless(test_gui.QT_AVAILABLE,"Requiere PySide6")
class TwoMethodGUITests(unittest.TestCase):
    setUpClass=classmethod(test_gui.GUITests.setUpClass.__func__)
    setUp=test_gui.GUITests.setUp
    tearDown=test_gui.GUITests.tearDown
    wait=test_gui.GUITests.wait
    select_calibrated=test_gui.GUITests.select_calibrated

    def test_home_and_calibration_have_exactly_nose_and_eyes(self):
        self.select_calibrated();self.window.refresh()
        for selector in (self.window.home_method,self.window.tracking_combo):
            self.assertEqual(selector.count(),2)
            self.assertEqual([selector.itemText(i) for i in range(2)],["Nariz","Ojos"])
        self.assertEqual(self.window.calibration_tabs.count(),2)
        self.window.home_method.setCurrentIndex(1)
        self.window.home_method.activated.emit(1)
        self.wait(lambda:self.bridge.snapshot()["public_method"]=="eyes")
        self.window.refresh()
        self.assertEqual(self.window.calibration_tabs.currentIndex(),1)
        self.assertEqual(self.window.home_action.text(),"Calibrar Ojos")
        self.assertEqual(self.bridge.snapshot()["profile"]["user_id"],"julian")
        self.assertFalse(hasattr(self.window,"eye_setup_dialog"))
        self.backend_factory.assert_not_called()

    def test_fullscreen_calibration_receives_frames_by_qt_signal_from_one_vision(self):
        self.select_calibrated()
        factory=Mock(side_effect=EyeVision)
        self.controller.vision_factory=factory
        self.window.open_eye_calibration()
        self.wait(lambda:self.bridge.snapshot()["public_method"]=="eyes")
        self.window.refresh()
        errors=[];threads=[]
        self.bridge.snapshot_ready.connect(lambda:threads.append(QThread.currentThread()))
        with patch("sys.excepthook",lambda k,e,t:errors.append(str(e))):
            self.window.start_public_ocular_movement()
            self.wait(lambda:self.bridge.snapshot()["state"]=="GAZE_CALIBRATING")
            self.wait(lambda:self.window.gaze_overlay.camera_preview.image is not None)
            overlay=self.window.gaze_overlay
            self.assertIn("Iris I/D",overlay.camera_caption.text())
            for index in (0,2,4,6,8):
                self.bridge.request("repeat_gaze_point",index=index)
                self.wait(lambda:self.bridge.snapshot()["gaze_calibration"]["index"]==index)
                self.window.refresh();self.app.processEvents()
                x,y=overlay.session["target"]
                target=QPoint(round(x*(overlay.width()-1)),round(y*(overlay.height()-1)))
                occupied=overlay.camera_preview.geometry().united(overlay.camera_caption.geometry())
                self.assertFalse(occupied.adjusted(-25,-25,25,25).contains(target))
            self.assertTrue(all(thread==self.app.thread() for thread in threads))
            self.assertEqual(factory.call_count,1)
            overlay.close()
            self.wait(lambda:self.bridge.snapshot()["state"]=="PREVIEW")
        self.assertEqual(errors,[])
        self.backend_factory.assert_not_called()

    def test_ocular_gestures_reuse_original_widgets_inside_eye_tab(self):
        self.select_calibrated();self.controller.vision_factory=EyeVision
        original=self.window.gesture_calibration_scroll
        self.window.start_ocular_gestures()
        self.wait(lambda:self.bridge.snapshot()["state"]=="CALIBRATING")
        self.window.refresh()
        self.assertEqual(self.window.calibration_tabs.currentIndex(),1)
        self.assertEqual(self.window.ocular_content.currentIndex(),1)
        self.assertIs(self.window.gesture_calibration_scroll,original)
        self.assertTrue(self.window.calibration_preview.isVisible())
        self.assertIsNotNone(self.window.calibration_preview.image)
        self.backend_factory.assert_not_called()

    def test_calibration_marks_iris_without_changing_saved_overlay_preferences(self):
        from desktop.gaze_overlay import GazeOverlay
        from copy import deepcopy
        self.select_calibrated()
        s=deepcopy(self.bridge.snapshot())
        s["settings"]["ui"].update(show_landmarks=False,show_overlay=False)
        overlay=GazeOverlay(self.window)
        overlay.present_camera(s)
        self.assertTrue(overlay.camera_preview.snapshot["settings"]["ui"]["show_landmarks"])
        self.assertFalse(s["settings"]["ui"]["show_landmarks"])
        self.assertFalse(s["settings"]["ui"]["show_overlay"])
        self.backend_factory.assert_not_called()


if __name__=="__main__":unittest.main()
