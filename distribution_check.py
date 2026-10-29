"""Verificación instalada con imagen sintética en RAM: sin webcam ni salida al SO."""
import json
from app_paths import data_root,face_model_path,VERSION


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
        facial_model=path.is_file(),camera_opened=False,physical_actions=0)
    from user_storage import write_json
    write_json(data_root()/"logs"/"distribution-check.json",report)
    return 0
