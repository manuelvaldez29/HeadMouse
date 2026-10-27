"""Regresiones de cierre y excepciones; sin cámara ni backend del SO."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from application_controller import ApplicationController
from profile_manager import ProfileManager
from profiles import ProfileStore
from config import ROOT


class RuntimeStabilityTests(unittest.TestCase):
    def test_disposal_refuses_to_destroy_widgets_before_worker_finishes(self):
        from PySide6.QtCore import QThread
        from desktop.lifecycle import dispose_window
        window=Mock()
        window.bridge.thread=QThread.currentThread()
        with self.assertRaisesRegex(RuntimeError,"worker"):
            dispose_window(window)
        window.deleteLater.assert_not_called()
    def controller(self):
        tmp=tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(tmp.cleanup)
        root=Path(tmp.name)
        return ApplicationController(ProfileManager(ProfileStore(root/"profiles")),data_dir=root)

    def test_timed_out_vision_is_retained_for_retry_and_control_revoked(self):
        c=self.controller()
        vision=Mock()
        vision.stop.side_effect=[RuntimeError("driver no respondió"),None]
        c.vision=vision
        control=Mock()
        c.control=control
        with self.assertRaises(RuntimeError):c.stop_camera()
        self.assertIs(c.vision,vision)
        self.assertTrue(c.emergency.is_set())
        control.output_allowed.clear.assert_called()
        self.assertIsNone(c.control)
        c.shutdown()
        self.assertIsNone(c.vision)
        self.assertEqual(vision.stop.call_count,2)
        self.assertTrue(c.closed)

    def test_worker_catches_snapshot_exception_and_revokes_output(self):
        from desktop.bridge import ControllerWorker,Mailbox
        c=Mock()
        c.snapshot.side_effect=RuntimeError("snapshot failure")
        worker=ControllerWorker(c,Mailbox())
        with self.assertLogs("desktop.bridge",level="ERROR"):
            worker.tick()
        c.emergency_stop.assert_called_once()
        c.fail.assert_called_once_with("snapshot failure")

    def test_shutdown_failure_does_not_emit_finished_or_destroy_worker(self):
        from desktop.bridge import ControllerWorker,Mailbox
        from unittest.mock import patch
        c=Mock()
        c.shutdown.side_effect=RuntimeError("native driver still alive")
        worker=ControllerWorker(c,Mailbox())
        worker.timer=Mock()
        finished=Mock()
        worker.finished.connect(finished)
        with patch("desktop.bridge.QTimer.singleShot") as retry,self.assertLogs("desktop.bridge",level="ERROR"):
            worker.command("shutdown",{})
        finished.assert_not_called()
        self.assertTrue(worker.stopping)
        worker.timer.stop.assert_called()
        retry.assert_called_once()

    def test_uncaught_exception_handler_revokes_before_logging(self):
        import runtime_diagnostics
        from unittest.mock import patch
        handler=Mock()
        with patch.object(runtime_diagnostics,"_emergency_handler",handler):
            runtime_diagnostics.revoke_output()
        handler.assert_called_once()


if __name__=="__main__":unittest.main()
