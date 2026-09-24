"""Qt real/offscreen, webcam y backend simulados. Nunca entrada real del SO."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock

try:
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    QT_AVAILABLE = True
except ImportError:
    QT_AVAILABLE = False

from config import ROOT
from face_data import FaceData
from profile_manager import ProfileManager
from profiles import ProfileStore
from application_controller import ApplicationController
from test_core import calibration


class FakeVision:
    def __init__(self, config=None, metrics=None):
        self.error = None
        self.ready = threading.Event()
        self.alive = False
        self.metrics = metrics

    def start(self): self.alive = True; self.ready.set()
    def wait_ready(self): pass
    def stop(self): self.alive = False
    def is_alive(self): return self.alive
    def get_fps(self): return 30
    def get_face_data(self):
        return FaceData(True, timestamp_ms=int(time.monotonic()*1000), processing_ms=12,
                        detected_at=time.monotonic(), eye_left_ratio=.1,eye_right_ratio=.12,
                        brow_left_lift=.2,brow_right_lift=.22,mouth_open=.01,
                        landmarks=((.5,.5),(.4,.4),(.6,.4)))
    def get_frame(self):
        import numpy as np
        return np.zeros((240,320,3), dtype=np.uint8)


@unittest.skipUnless(QT_AVAILABLE,"Instalar PySide6 para pruebas de interfaz")
class GUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import numpy  # preparar fixture sintético antes de medir tiempos de señales
        cls.app=QApplication.instance() or QApplication([])
        from desktop.style import apply_style
        apply_style(cls.app)

    def setUp(self):
        from desktop.bridge import DesktopBridge
        from desktop.window import MainWindow
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT)
        self.root=Path(self.tmp.name)
        self.manager=ProfileManager(ProfileStore(self.root/"profiles"))
        self.backend=Mock()
        self.backend.size.return_value=(1920,1080)
        self.backend_factory=Mock(return_value=self.backend)
        self.controller=ApplicationController(self.manager,FakeVision,self.backend_factory,self.root)
        self.bridge=DesktopBridge(self.controller)
        self.window=MainWindow(self.bridge)
        self.window.show()
        self.wait(lambda:bool(self.bridge.snapshot()))

    def wait(self,predicate,timeout=20000):
        end=time.monotonic()+timeout/1000
        while time.monotonic()<end:
            self.app.processEvents()
            if predicate(): return
            QTest.qWait(20)
        self.fail("Qt no llegó al estado esperado")

    def tearDown(self):
        self.window.close()
        self.wait(lambda:not self.bridge.thread.isRunning())
        self.app.processEvents()
        self.window.deleteLater()
        self.app.processEvents()
        self.tmp.cleanup()

    def select_calibrated(self):
        p=calibration()
        p["validation"]={"passed":True}
        self.manager.store.save(p)
        self.bridge.request("select_profile",user_id="julian")
        self.wait(lambda:self.bridge.snapshot().get("profile") is not None)

    def test_window_pages_safe_start_and_no_backend(self):
        self.assertEqual(self.window.stack.count(),8)
        for index in range(8):
            self.window.show_page(index)
            self.window.refresh()
            self.app.processEvents()
            self.assertEqual(self.window.stack.currentIndex(),index)
        self.assertIn("DESACTIVADO",self.window.control_status.text())
        self.backend_factory.assert_not_called()

    def test_create_profile_from_controller_updates_ui(self):
        self.bridge.request("create_profile",name="Perfil accesible")
        self.wait(lambda:bool(self.bridge.snapshot().get("profile")))
        self.window.refresh()
        self.assertIn("Perfil accesible",self.window.home_profile.text())
        self.assertFalse(self.window.activate_button.isEnabled())
        self.assertFalse(self.window.save_calibration_button.isEnabled())

    def test_preview_and_diagnostic_without_real_mouse(self):
        self.select_calibrated()
        self.window.show_page(3)
        self.bridge.request("start_diagnostic")
        self.wait(lambda:self.bridge.snapshot().get("state")=="DIAGNOSTIC")
        self.window.refresh()
        self.assertIsNotNone(self.window.diagnostic_preview.image)
        self.assertIn("Facial X",self.window.diagnostic_values.text())
        self.backend_factory.assert_not_called()

    def test_settings_and_mapping_persist_from_widgets(self):
        self.select_calibrated()
        self.window.refresh()
        self.window.fields["gesture.sensitivity_x"].setValue(150)
        self.window.save_settings()
        self.wait(lambda:self.bridge.snapshot()["settings"]["gesture"]["sensitivity_x"]==150)
        self.window.refresh()
        combo=self.window.mapping_fields["LEFT_WINK"]
        combo.setCurrentIndex(combo.findData("DOUBLE_CLICK"))
        self.window.save_mapping()
        self.wait(lambda:self.bridge.snapshot()["settings"]["actions"]["bindings"]["LEFT_WINK"]=="DOUBLE_CLICK")
        self.assertEqual(self.manager.store.load("julian")["settings"]["gesture"]["sensitivity_x"],150)

    def test_calibration_start_and_stop_button_revoke_output(self):
        self.select_calibrated()
        self.bridge.request("start_calibration")
        self.wait(lambda:self.bridge.snapshot().get("state")=="CALIBRATING")
        self.window.refresh()
        self.assertIn("Relajá",self.window.wizard_instruction.text())
        self.backend_factory.assert_not_called()
        self.bridge.request("stop_camera")
        self.wait(lambda:self.bridge.snapshot().get("state")=="HOME")
        self.bridge.activate()  # equivale a confirmación positiva, backend simulado
        self.wait(lambda:self.bridge.snapshot().get("control_enabled"))
        self.bridge.stop()
        self.assertTrue(self.controller.emergency.is_set())
        self.wait(lambda:not self.bridge.snapshot().get("control_enabled"))

    def test_experiment_simulation_through_qt_without_camera(self):
        self.bridge.request("start_experiment",mode="simulation",source="keyboard")
        self.wait(lambda:self.bridge.snapshot().get("experiment") is not None)
        for index,target in enumerate(((640,120),(160,380),(650,380),(150,120),(400,250))):
            snapshot=self.bridge.snapshot()["experiment"]
            x,y=snapshot["cursor"]
            self.bridge.request("experiment_input",x=target[0]-x,y=target[1]-y,click=True)
            self.wait(lambda:self.bridge.snapshot()["experiment"]["completed"]==index+1)
        self.assertFalse(self.bridge.snapshot()["experiment"]["active"])
        self.assertEqual(len(list((self.root/"experiments").glob("*.jsonl"))),1)
        self.backend_factory.assert_not_called()


if __name__=="__main__": unittest.main()
