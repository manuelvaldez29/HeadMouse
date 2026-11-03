"""Verificación instalada con imagen sintética en RAM: sin webcam ni salida al SO."""
import json
from app_paths import data_root,face_model_path,VERSION


def voice_check():
    """Motor de dictado completo sin grabar ni escribir: VAD con audio sintético,
    UI Automation creado y PortAudio cargado. El modelo Whisper es opcional."""
    import numpy as np
    import ctranslate2,faster_whisper,sounddevice
    from faster_whisper.vad import get_speech_timestamps
    from dictation import UIAFocusProbe,installed_model
    from config import VoiceConfig
    assert get_speech_timestamps(np.zeros(16000,dtype=np.float32))==[]  # onnxruntime + silero_vad.onnx
    UIAFocusProbe().init_thread()                                        # comtypes genera UIAutomationCore
    model=VoiceConfig().model
    installed=installed_model(model) is not None
    if installed:  # CTranslate2 carga el modelo y transcribe 1 s de silencio
        from dictation import WhisperTranscriber
        WhisperTranscriber(model).transcribe(np.zeros(16000,dtype=np.float32))
    import sherpa_onnx
    from speaker import SpeakerModel,model_path as speaker_path
    if speaker_path():  # huella de 1 s de un tono: 256 números
        assert len(SpeakerModel().embed(np.sin(np.arange(16000,dtype=np.float32)/8))) == 256
    return dict(faster_whisper=faster_whisper.__version__,ctranslate2=ctranslate2.__version__,
                sherpa_onnx=sherpa_onnx.__version__,speaker_model=bool(speaker_path()),
                portaudio=sounddevice.get_portaudio_version()[1],ui_automation=True,
                model_installed=installed,model_transcribed=installed)


def run():
    import cv2,numpy as np,pyautogui
    from PySide6.QtCore import qVersion
    from vision_engine import mp,mp_python,mp_vision
    path=face_model_path()
    options=mp_vision.FaceLandmarkerOptions(base_options=mp_python.BaseOptions(model_asset_path=str(path)),
        running_mode=mp_vision.RunningMode.IMAGE,num_faces=1,output_face_blendshapes=True)
    with mp_vision.FaceLandmarker.create_from_options(options) as detector:
        result=detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB,data=np.zeros((256,256,3),dtype=np.uint8)))
        assert not result.face_landmarks
    report=dict(result="passed",version=VERSION,qt=qVersion(),opencv=cv2.__version__,numpy=np.__version__,
        facial_model=path.is_file(),camera_opened=False,physical_actions=0,voice=voice_check())
    from user_storage import write_json
    write_json(data_root()/"logs"/"distribution-check.json",report)
    return 0
