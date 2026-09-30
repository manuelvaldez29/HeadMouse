"""Publicación real del worker y widgets Qt; reloj/cámara sintéticos, sin SO."""
import os
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
import tempfile
import unittest
from pathlib import Path
from test_gui import QT_AVAILABLE, FakeVision
from test_adaptive_session import NEUTRAL, ACTIVE
from face_data import FaceData
from config import ROOT
from application_controller import ApplicationController
from profile_manager import ProfileManager
from profiles import ProfileStore


@unittest.skipUnless(QT_AVAILABLE,"Instalar PySide6 para pruebas de interfaz")
class CalibrationGUIRegressionTests(unittest.TestCase):
    def test_backend_transitions_are_published_and_displayed(self):
        from PySide6.QtCore import QObject, Signal
        from PySide6.QtWidgets import QApplication
        from desktop.bridge import ControllerWorker, Mailbox
        from desktop.window import MainWindow
        app=QApplication.instance() or QApplication([])
        mailbox=Mailbox()
        class Bridge(QObject):
            error=Signal(str)
            closed=Signal()
            def snapshot(self): return mailbox.get()
            def request(self,*args,**kwargs): raise AssertionError("refresh no debe mandar comandos")
            def stop(self): pass
            def activate(self): raise AssertionError("Sin control real")
            def shutdown(self): self.closed.emit()
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            ms=[1000]
            manager=ProfileManager(ProfileStore(Path(temp)/"profiles"))
            c=ApplicationController(manager,vision_factory=FakeVision,data_dir=temp,clock=lambda:ms[0]/1000)
            c.profile=manager.create("Regresión sintética")
            cc=c.config.calibration
            cc.countdown_s=cc.transition_s=.1
            cc.measuring_s=cc.neutral_window_s=cc.active_window_s=.3
            cc.min_samples=cc.min_window_samples=4
            c.start_calibration()
            face=[FaceData(False)]
            c.vision.get_face_data=lambda:face[0]
            worker=ControllerWorker(c,mailbox)
            failures=[]
            worker.error.connect(failures.append)
            worker.publish()
            bridge=Bridge()
            window=MainWindow(bridge)
            window.timer.stop()
            window.show_page(2)
            def tick(values=None):
                ms[0]+=50
                face[0]=FaceData(True,timestamp_ms=ms[0],**(NEUTRAL | (values or {})))
                worker.tick()
                before=c.wizard._state_key()
                window.refresh()
                self.assertEqual(before,c.wizard._state_key())
                snap=mailbox.get()["wizard"]
                self.assertEqual(window.wizard_instruction.text(),snap["instruction"])
                self.assertEqual(window.wizard_progress.value(),int(snap["progress"]*100))
                self.assertFalse(failures,failures)
                return snap
            try:
                attempts=set()
                for _ in range(1500):
                    s=c.wizard
                    if s.state in ("measured","error"): break
                    snap=tick(ACTIVE.get(s.gesture_id,{}) if s.stage=="active" else {})
                    if snap["gesture_id"]:
                        attempts.add((snap["gesture_id"],snap["attempt"]))
                        self.assertIn(f"Intento {snap['attempt']}/3",window.wizard_status.text())
                self.assertEqual(c.wizard.state,"measured")
                self.assertEqual(len(attempts),18)
                c.validate_calibration()
                snap=tick()
                self.assertEqual(snap["phase"],1)
                self.assertEqual(snap["attempt"],0)
                self.assertNotIn("Intento",window.wizard_status.text())
                for _ in range(45): tick()
                self.assertIn("Esperando gesto",window.wizard_instruction.text())
                for _ in range(24): snap=tick(ACTIVE["LEFT_WINK"])
                self.assertIn("Detectado",window.capture_feedback.text())
                self.assertEqual(snap["gesture_id"],"LEFT_WINK")
                for _ in range(45): snap=tick()
                self.assertEqual(snap["phase"],2)
                self.assertEqual(snap["gesture_id"],"RIGHT_WINK")
                self.assertIn("derecho",window.wizard_instruction.text())
                c.stop_camera()
                self.assertIsNone(c.vision)
                self.assertIsNone(c.control)
            finally:
                c.shutdown()
                window.close()
                window.deleteLater()
                app.processEvents()


if __name__=="__main__": unittest.main()
