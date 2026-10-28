"""Infraestructura de cámara con dispositivos/detectores simulados; sin SO."""
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import numpy as np

from config import ROOT, VisionConfig, load_config
from face_data import FaceData
from application_controller import ApplicationController
from profiles import ProfileStore
from profile_manager import ProfileManager
from test_core import calibration
import test_safety


class CameraEngineTests(unittest.TestCase):
    def setUp(self):
        self.fixture=test_safety.VisionLifecycleTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.module=self.fixture.module
        self.cv=self.fixture.cv
        self.cap=self.cv.VideoCapture.return_value
        self.cap.isOpened.return_value=True
        self.cap.getBackendName.return_value="DSHOW"
        self.cap.get.return_value=15.
        self.frame=np.zeros((480,640,3),dtype=np.uint8)
        self.cap.read.side_effect=lambda:(True,self.frame)
        self.cv.flip.side_effect=lambda frame,axis:frame
        self.cv.cvtColor.side_effect=lambda frame,code:frame
        self.detector=Mock()
        self.fixture.mp.FaceLandmarker.create_from_options.return_value=self.detector
        self.engines=[]
        self.gates=[]
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.model=Path(self.tmp.name)/"fake.task"
        self.model.write_bytes(b"simulated detector only")
        # Limpiar antes de restaurar los módulos simulados, siempre en su dueño.
        self.addCleanup(self.cleanup_engines)

    def cleanup_engines(self):
        for gate in self.gates:gate.set()
        for engine in self.engines:
            engine.stop()

    def engine(self,**kwargs):
        config=VisionConfig(model_path=str(self.model),startup_timeout_s=.5,
            shutdown_timeout_s=.05,target_fps=60,**kwargs)
        engine=self.module.VisionEngine(config=config)
        self.engines.append(engine)
        self.detector.detect_async.side_effect=lambda image,stamp:engine._on_result(
            SimpleNamespace(face_landmarks=[]),None,stamp)
        return engine

    def gate(self):
        value=threading.Event()
        self.gates.append(value)
        return value

    def await_stage(self,engine,stage,timeout=1):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            if engine.diagnostics()["stage"]==stage:return
            time.sleep(.002)
        self.fail(engine.diagnostics())

    def test_ready_requires_capture_detector_and_published_result_then_owner_closes(self):
        engine=self.engine(frame_width=640,frame_height=480)
        owners={}
        self.cap.release.side_effect=lambda:owners.update(camera=threading.get_ident())
        self.detector.close.side_effect=lambda:owners.update(detector=threading.get_ident())
        engine.start()
        engine.wait_ready(1)
        status=engine.diagnostics()
        self.assertTrue(status["ready"])
        self.assertGreater(status["captured_frames"],0)
        self.assertGreater(status["processed_results"],0)
        self.assertGreater(engine.get_face_data().timestamp_ms,0)
        self.assertFalse(engine.get_face_data().detected)  # no exige cara para readiness
        for stage in ("CAMERA_OPENING","CAMERA_OPEN","FIRST_FRAME","MEDIAPIPE_INITIALIZING","MEDIAPIPE_READY","FIRST_SUBMISSION","FIRST_RESULT","READY"):
            self.assertIn(stage,status["timeline"])
        engine.stop()
        self.assertEqual(owners,{"camera":engine.ident,"detector":engine.ident})
        self.assertFalse(engine.diagnostics()["ready"])
        self.assertTrue(engine.diagnostics()["stopped"])
        self.assertIsNone(engine.get_frame())

    def test_first_frame_delayed_does_not_initialize_detector_or_claim_ready(self):
        gate=self.gate()
        engine=self.engine()
        self.cap.read.side_effect=lambda:(gate.wait(1) and True,self.frame)
        engine.start()
        self.await_stage(engine,"CAMERA_OPEN")
        self.assertFalse(engine.ready.is_set())
        self.assertEqual(engine.diagnostics()["operation"],"camera_read")
        self.fixture.mp.FaceLandmarker.create_from_options.assert_not_called()
        gate.set()
        engine.wait_ready(1)

    def test_slow_detector_is_identified_and_late_creation_only_closes(self):
        gate=self.gate()
        engine=self.engine()
        self.fixture.mp.FaceLandmarker.create_from_options.side_effect=lambda options:(gate.wait(1),self.detector)[1]
        engine.start()
        self.await_stage(engine,"MEDIAPIPE_INITIALIZING")
        self.assertTrue(engine.first_frame.is_set())
        with self.assertRaisesRegex(TimeoutError,"detector_init"):
            engine.wait_ready(.02)
        with self.assertRaisesRegex(RuntimeError,"detector_init"):
            engine.stop()
        self.assertTrue(engine.is_alive())
        self.cap.release.assert_not_called()
        gate.set()
        engine.join(1)
        self.detector.detect_async.assert_not_called()
        self.detector.close.assert_called_once()
        self.cap.release.assert_called_once()
        self.assertFalse(engine.diagnostics()["ready"])

    def test_delayed_callback_not_is_opened_controls_readiness(self):
        engine=self.engine()
        submitted=self.gate()
        stamps=[]
        self.detector.detect_async.side_effect=lambda image,stamp:(stamps.append(stamp),submitted.set())
        engine.start()
        self.assertTrue(submitted.wait(1))
        self.assertFalse(engine.ready.is_set())
        engine._on_result(SimpleNamespace(face_landmarks=[]),None,stamps[-1])
        engine.wait_ready(.5)
        self.assertTrue(engine.diagnostics()["ready"])

    def test_never_arriving_or_late_callback_after_timeout_cannot_reauthorize(self):
        engine=self.engine()
        self.detector.detect_async.side_effect=None
        engine.start()
        with self.assertRaisesRegex(TimeoutError,"resultados=0"):
            engine.wait_ready(.08)
        engine.stop()
        engine._on_result(SimpleNamespace(face_landmarks=[]),None,int(time.monotonic()*1000))
        self.assertFalse(engine.diagnostics()["ready"])
        self.assertEqual(engine.diagnostics()["processed_results"],0)
        self.assertFalse(engine.get_face_data().detected)

    def test_cancellation_during_native_open_does_not_open_detector(self):
        gate=self.gate()
        engine=self.engine()
        self.cv.VideoCapture.side_effect=lambda *args:(gate.wait(1),self.cap)[1]
        engine.start()
        self.await_stage(engine,"CAMERA_OPENING")
        engine.request_stop()
        with self.assertRaises(InterruptedError):engine.wait_ready(.01)
        gate.set()
        engine.join(1)
        self.fixture.mp.FaceLandmarker.create_from_options.assert_not_called()
        self.cap.release.assert_called_once()

    def test_blocked_read_never_released_from_foreign_thread(self):
        gate=self.gate()
        engine=self.engine()
        entered=threading.Event()
        def read():
            entered.set()
            return gate.wait(1),self.frame
        self.cap.read.side_effect=read
        engine.start()
        self.assertTrue(entered.wait(1),"La captura simulada no entró a read")
        with self.assertRaisesRegex(RuntimeError,"camera_read"):
            engine.stop()
        self.cap.release.assert_not_called()
        self.assertTrue(engine.is_alive())
        gate.set()
        engine.join(1)
        self.cap.release.assert_called_once()

    def test_read_failures_recover_without_switching_backend(self):
        engine=self.engine(capture_failure_limit=1)
        reads=[False,False,True]
        self.cap.read.side_effect=lambda:(reads.pop(0) if reads else True,self.frame)
        engine.start()
        engine.wait_ready(1)
        self.assertIn("RECOVERABLE_ERROR",engine.diagnostics()["timeline"])
        self.cv.VideoCapture.assert_called_once()

    def test_read_failure_after_ready_invalidates_signal_and_reports_terminal_error(self):
        engine=self.engine(capture_failure_limit=1)
        engine.start()
        engine.wait_ready(1)
        self.cap.read.side_effect=lambda:(False,None)
        with self.assertLogs("isolated_vision",level="ERROR"):
            engine.join(1)
        self.assertFalse(engine.is_alive())
        self.assertIn("dejó de entregar",str(engine.error))
        self.assertFalse(engine.diagnostics()["ready"])
        self.assertFalse(engine.get_face_data().detected)

    def test_detector_initialization_failure_preserves_cause_and_releases(self):
        engine=self.engine()
        self.fixture.mp.FaceLandmarker.create_from_options.side_effect=RuntimeError("graph failed")
        with self.assertLogs("isolated_vision",level="ERROR"):
            engine.start()
            with self.assertRaisesRegex(RuntimeError,"graph failed"):engine.wait_ready(1)
            engine.join(1)
        self.cap.release.assert_called_once()
        self.assertEqual(str(engine.error),"graph failed")

    def test_backend_selection_is_explicit_and_no_fallback(self):
        for backend,api in (("dshow",self.cv.CAP_DSHOW),("msmf",self.cv.CAP_MSMF),("auto",self.cv.CAP_ANY)):
            engine=self.engine(capture_backend=backend)
            self.cv.VideoCapture.reset_mock()
            with patch.object(self.module.sys, "platform", "win32"):
                cap=engine._open_capture()
            self.cv.VideoCapture.assert_called_once_with(0,api)
            self.assertIs(cap,self.cap)
        with self.assertRaises(ValueError):load_config(overrides={"vision":{"capture_backend":"guess"}})
        with self.assertRaises(ValueError):load_config(overrides={"vision":{"frame_width":640,"frame_height":0}})

    def test_callback_already_extracting_when_cancelled_cannot_publish(self):
        engine=self.engine()
        entered=self.gate();release=self.gate()
        engine._extract=Mock(side_effect=lambda result,stamp:(entered.set(),release.wait(1),FaceData(True,timestamp_ms=stamp))[-1])
        callback=threading.Thread(target=engine._on_result,args=(None,None,int(time.monotonic()*1000)))
        callback.start()
        self.assertTrue(entered.wait(1))
        engine.request_stop()
        release.set()
        callback.join(1)
        self.assertFalse(callback.is_alive())
        self.assertFalse(engine.get_face_data().detected)
        self.assertEqual(engine.diagnostics()["processed_results"],0)

    def test_raw_missing_extraction_rejected_and_invalid_signal_are_distinguished(self):
        for status,raw,detected,bad in (("NO_LANDMARKS",False,False,False),
            ("EXTRACTION_REJECTED",True,False,False),("INVALID_FACE_DATA",True,True,True),
            ("VALID_FACE",True,True,False)):
            with self.subTest(status=status):
                engine=self.engine()
                stamp=int(time.monotonic()*1000)
                engine._extract=Mock(return_value=FaceData(detected,timestamp_ms=stamp,
                    nose_x=float("nan") if bad else .5))
                engine._on_result(SimpleNamespace(face_landmarks=[[object()]] if raw else []),None,stamp)
                diagnostics=engine.diagnostics()
                self.assertEqual(diagnostics["face_status"],status)
                self.assertEqual(diagnostics["raw_face_results"],int(raw))
                self.assertEqual(diagnostics["valid_face_results"],int(status=="VALID_FACE"))
                self.assertEqual(diagnostics["rejected_face_results"],int(raw and status!="VALID_FACE"))


class PendingVision:
    def __init__(self,config=None,metrics=None):
        self.ready=threading.Event()
        self.error=None
        self.alive=False
        self.cancelled=False
        self.block_close=False
    def start(self):self.alive=True
    def is_alive(self):return self.alive
    def request_stop(self):self.cancelled=True;self.ready.set()
    def wait_ready(self,timeout=None):
        if self.cancelled:raise InterruptedError("cancelled")
        if not self.ready.is_set():raise TimeoutError("not ready")
    def stop(self):
        self.request_stop()
        if self.block_close:raise RuntimeError("detector_init still active")
        self.alive=False
    def diagnostics(self):return dict(stage="MEDIAPIPE_INITIALIZING",operation="detector_init",
        ready=self.ready.is_set() and not self.cancelled,stop_requested=self.cancelled,captured_frames=1,processed_results=0)
    def get_face_data(self):return FaceData(False)
    def get_frame(self):return None
    def get_fps(self):return 0


class ControllerStartupTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name)
        manager=ProfileManager(ProfileStore(root/"profiles"))
        manager.store.save(calibration()|{"validation":{"passed":True}})
        self.now=1.
        self.vision=PendingVision()
        self.factory=Mock(return_value=self.vision)
        self.backend=Mock()
        self.c=ApplicationController(manager,self.factory,self.backend,root,clock=lambda:self.now)
        self.addCleanup(self.cleanup)
    def cleanup(self):
        self.vision.block_close=False
        self.c.shutdown()
    def worker(self):
        from desktop.bridge import ControllerWorker,Mailbox
        worker=ControllerWorker(self.c,Mailbox())
        worker.timer=Mock()
        return worker

    def test_worker_returns_during_startup_and_defers_calibration_until_ready(self):
        worker=self.worker()
        worker.command("start_calibration",{})
        self.assertEqual(self.c.state,"CAMERA_STARTING")
        self.assertIsNone(self.c.wizard)
        worker.tick()
        self.assertEqual(self.c.state,"CAMERA_STARTING")
        self.vision.ready.set()
        worker.tick()
        self.assertEqual(self.c.state,"CALIBRATING")
        self.assertIsNotNone(self.c.wizard)
        self.backend.assert_not_called()

    def test_cancellation_prevents_pending_activation_or_calibration(self):
        for name in ("start_calibration","activate_control"):
            worker=self.worker()
            self.c.emergency.clear()
            worker.command(name,{"confirmed":True} if name=="activate_control" else {})
            self.c.emergency_stop()
            worker.command("stop_camera",{})
            self.vision.ready.set()
            worker.tick()
            self.assertIsNone(self.c.control)
            self.assertIsNone(self.c.vision)
            self.assertIsNone(self.c.wizard)
        self.backend.assert_not_called()

    def test_duplicate_start_never_opens_another_capture(self):
        worker=self.worker()
        worker.command("start_calibration",{})
        worker.command("start_camera",{})
        self.factory.assert_called_once()
        self.assertFalse(self.vision.cancelled)
        with self.assertRaisesRegex(RuntimeError,"iniciándose"):
            self.c.start_camera()
        self.assertIsNone(self.c.wizard)

    def test_failed_close_discards_pending_command_before_any_retry(self):
        worker=self.worker()
        worker.command("start_calibration",{})
        self.vision.block_close=True
        with self.assertLogs("desktop.bridge",level="ERROR"):
            worker.command("stop_control",{})
        self.assertIsNone(worker.pending_camera)
        self.assertTrue(self.vision.cancelled)
        self.assertEqual(self.c.state,"ERROR")
        worker.tick()
        self.assertIsNone(self.c.wizard)
        self.backend.assert_not_called()

    def test_timeout_retains_blocked_engine_and_original_stage_then_can_recover(self):
        worker=self.worker()
        self.vision.block_close=True
        self.c.config.vision.startup_timeout_s=.1
        worker.command("start_calibration",{})
        self.now=2.
        with self.assertLogs("desktop.bridge",level="ERROR"):worker.tick()
        self.assertEqual(self.c.state,"ERROR")
        self.assertIn("detector_init",self.c.message)
        self.assertIs(self.c.vision,self.vision)
        self.assertTrue(self.c.emergency.is_set())
        with self.assertRaises(RuntimeError):self.c.start_camera()
        self.factory.assert_called_once()
        self.vision.block_close=False
        self.c.stop_camera()
        self.assertIsNone(self.c.vision)
        replacement=PendingVision()
        replacement.ready.set()
        self.factory.return_value=replacement
        self.c.start_calibration()
        self.assertEqual(self.c.state,"CALIBRATING")
        self.backend.assert_not_called()

    def test_camera_restart_starts_new_calibration_session(self):
        self.vision.ready.set()
        self.c.start_calibration()
        old=self.c.wizard
        self.c.stop_camera()
        replacement=PendingVision();replacement.ready.set()
        self.factory.return_value=replacement
        self.c.start_calibration()
        self.assertIsNot(old,self.c.wizard)
        self.backend.assert_not_called()

    def test_diagnostic_report_failure_never_opens_another_cycle(self):
        from camera_diagnostic import run_cycle
        engine=Mock(error=None)
        engine.wait_ready.side_effect=TimeoutError("detector_init")
        engine.stop.side_effect=RuntimeError("still alive")
        engine.diagnostics.return_value=dict(stage="MEDIAPIPE_INITIALIZING",ready=False)
        with self.assertLogs("camera_diagnostic",level="ERROR"):
            report,retained=run_cycle(VisionConfig(),.1,engine_factory=Mock(return_value=engine))
        self.assertFalse(report["success"])
        self.assertIs(retained,engine)
        self.backend.assert_not_called()


if __name__=="__main__":unittest.main()
