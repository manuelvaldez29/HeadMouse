r"""Opt-in: dependencias/modelo reales, imagen negra en RAM, sin cámara ni SO.

Ejecutar desde raíz: .venv\Scripts\python.exe tests/smoke_runtime.py
Requiere preparar antes el modelo con main.py --download-model.
"""
import json
import sys
import tempfile
import time
from contextlib import ExitStack
from importlib.metadata import version
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run():
    import numpy as np
    import pyautogui
    import main
    import calibrate
    from vision_engine import VisionEngine, mp, mp_python, mp_vision
    from config import DEFAULT_THRESHOLDS

    with ExitStack() as cleanup:
        for action in ("moveRel", "moveTo", "click", "rightClick", "scroll", "hotkey", "press", "keyDown", "keyUp"):
            cleanup.enter_context(patch.object(pyautogui, action, side_effect=AssertionError("Acción SO prohibida en smoke")))
        directory = Path(cleanup.enter_context(tempfile.TemporaryDirectory(dir=ROOT)))
        legacy = directory / "synthetic-profile.json"
        legacy.write_text(json.dumps({"user_id": "__runtime_smoke__", "thresholds": DEFAULT_THRESHOLDS}), encoding="utf-8")
        assert main.main(["--user", "__runtime_smoke__", "--legacy-calibration", str(legacy), "--check"]) == 0
        assert calibrate.main(["--check"]) == 0
        engine = VisionEngine()  # constructor no abre cámara ni descarga modelo
        cleanup.callback(engine.stop)
        options = mp_vision.FaceLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=str(engine.model_path)),
            running_mode=mp_vision.RunningMode.LIVE_STREAM,
            num_faces=1, output_face_blendshapes=True, result_callback=engine._on_result)
        with mp_vision.FaceLandmarker.create_from_options(options) as detector:
            image = mp.Image(image_format=mp.ImageFormat.SRGB,
                             data=np.zeros((256, 256, 3), dtype=np.uint8))
            detector.detect_async(image, int(time.monotonic() * 1000))
            assert engine.first_result.wait(20), "MediaPipe no entregó resultado"
            assert engine.error is None
            face = engine.get_face_data()
            assert not face.detected
            assert face.timestamp_ms > 0 and face.processing_ms >= 0
        # Ejecutar también el ciclo revisado de VisionEngine con una cámara
        # sintética y detector nativo real. No se llama a VideoCapture físico.
        import threading
        import vision_engine
        from config import VisionConfig
        class SyntheticCapture:
            released_by=None
            def isOpened(self):return True
            def getBackendName(self):return "SYNTHETIC_NO_WEBCAM"
            def set(self,*args):return True
            def get(self,prop):return 15. if prop==vision_engine.cv2.CAP_PROP_FPS else 256.
            def read(self):return True,np.zeros((256,256,3),dtype=np.uint8)
            def release(self):self.released_by=threading.get_ident()
        capture=SyntheticCapture()
        with patch.object(vision_engine.cv2,"VideoCapture",return_value=capture):
            pipeline=VisionEngine(config=VisionConfig(capture_backend="auto",target_fps=15))
            cleanup.callback(pipeline.stop)
            pipeline.start()
            pipeline.wait_ready(20)
            status=pipeline.diagnostics()
            assert status["ready"] and status["captured_frames"]>=2 and status["processed_results"]>=1
            pipeline.stop()
            assert capture.released_by==pipeline.ident and not pipeline.is_alive()
            assert not pipeline.diagnostics()["ready"]
        assert main.draw_overlay(__import__("control_engine").ControlStats()).shape == (185, 230, 3)
    print("PASS: imports, entrypoints --check, overlay, callback y ciclo VisionEngine con MediaPipe real/captura sintética; sin webcam/acciones SO")
    print({name: version(name) for name in ("mediapipe", "opencv-contrib-python", "numpy", "pyautogui")})


if __name__ == "__main__":
    run()
