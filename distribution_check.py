"""Verificación instalada con imagen sintética en RAM: sin webcam ni salida al SO."""
import os
import sys
from app_paths import RESOURCE_ROOT,data_root,face_model_path,VERSION


def voice_check():
    """Load the voice stack without opening a microphone or sending input."""
    import numpy as np
    import ctranslate2,faster_whisper,sounddevice
    from faster_whisper.vad import get_speech_timestamps
    from dictation import UIAFocusProbe,WhisperTranscriber,installed_model
    from config import VoiceConfig,WHISPER_MODELS
    assert get_speech_timestamps(np.zeros(16000,dtype=np.float32))==[]  # onnxruntime + silero_vad.onnx
    UIAFocusProbe().init_thread()                                        # comtypes genera UIAutomationCore
    frozen=getattr(sys,"frozen",False)
    fixture=os.environ.get("HEADMOUSE_VERIFY_AUDIO")
    audio=np.zeros(16000,dtype=np.float32)
    if fixture:
        import wave
        with wave.open(fixture,"rb") as wav:
            assert (wav.getnchannels(),wav.getsampwidth(),wav.getframerate())==(1,2,16000)
            audio=np.frombuffer(wav.readframes(wav.getnframes()),dtype="<i2").astype(np.float32)/32768
    models={}
    for model in WHISPER_MODELS if frozen else (VoiceConfig().model,):
        directory=RESOURCE_ROOT/"models/whisper" if frozen else None
        if frozen or installed_model(model) is not None:
            result=WhisperTranscriber(model,directory).transcribe(audio)
            models[model]=result
    if fixture:
        assert "prueba" in models[VoiceConfig().model].lower(), models
    import sherpa_onnx
    from speaker import MODEL_NAME,SpeakerModel,model_path as speaker_path
    speaker=RESOURCE_ROOT/"models/speaker"/MODEL_NAME if frozen else speaker_path()
    if speaker:
        assert speaker.is_file()
        embedding=SpeakerModel(speaker).embed(audio if fixture else np.sin(np.arange(16000,dtype=np.float32)/8))
        assert len(embedding)==256 and np.isfinite(embedding).all()
    return dict(faster_whisper=faster_whisper.__version__,ctranslate2=ctranslate2.__version__,
                sherpa_onnx=sherpa_onnx.__version__,speaker_model=bool(speaker),
                portaudio=sounddevice.get_portaudio_version()[1],ui_automation=True,
                model_installed=bool(models),model_transcribed=bool(models),models=models,
                microphone_opened=False,fixture_used=bool(fixture))


def run():
    def deny_network(event,args):
        if event in ("socket.connect","socket.getaddrinfo"):
            raise RuntimeError("La verificación de distribución debe funcionar sin red")
    sys.addaudithook(deny_network)
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
        facial_model=path.is_file(),camera_opened=False,physical_actions=0,
        python_network_blocked=True,voice=voice_check())
    from user_storage import write_json
    write_json(data_root()/"logs"/"distribution-check.json",report)
    return 0
