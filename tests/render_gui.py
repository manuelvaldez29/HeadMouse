"""Capturas de revisión exclusivamente de UI vacía/sintética, nunca webcam."""
import os
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
import sys
import tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from desktop.window import MainWindow
from desktop.style import apply_style
from PySide6.QtCore import QObject, Signal
from application_controller import ApplicationController
from profile_manager import ProfileManager
from profiles import ProfileStore
from config import ROOT
from face_data import FaceData
import numpy as np


class ReviewBridge(QObject):
    error=Signal(str)
    closed=Signal()
    def __init__(self,snapshot): super().__init__(); self.data=snapshot
    def snapshot(self): return self.data
    def request(self,*args,**kwargs): pass
    def stop(self): pass
    def activate(self): raise RuntimeError("No hay control real en revisión visual")
    def shutdown(self): self.closed.emit()


def main():
    app=QApplication([])
    apply_style(app)
    with tempfile.TemporaryDirectory(dir=ROOT) as temp:
        c=ApplicationController(ProfileManager(ProfileStore(Path(temp)/"profiles")),data_dir=temp)
        snapshot=c.snapshot()
        snapshot["profiles"]=[]
        bridge=ReviewBridge(snapshot)
        window=MainWindow(bridge)
        window.show()
        directory=ROOT/"docs"/"screenshots"
        directory.mkdir(exist_ok=True)
        for index,name in enumerate(("home","profiles","calibration","diagnostic","settings","actions","experiments","metrics")):
            window.show_page(index)
            window.refresh()
            app.processEvents()
            window.grab().save(str(directory/f"v03-{name}.png"))
        # Datos explícitamente sintéticos para revisar textos largos y overlays.
        snapshot.update(message="REVISIÓN VISUAL · Datos sintéticos, sin cámara ni control",
                        camera=True, detected=True, mediapipe="Preparado", fps=30,
                        processing_ms=12.5, frame=np.zeros((480,640,3),dtype=np.uint8),
                        face=FaceData(True,nose_x=.54,nose_y=.48,eye_left_ratio=.3,
                                      eye_right_ratio=.3,brow_left_lift=.08,brow_right_lift=.08,
                                      mouth_open=.02,landmarks=((.54,.48),(.4,.4),(.6,.4))),
                        profile={"user_id":"visual_demo","display_name":"Perfil de demostración visual",
                                 "validation":{"passed":True},"calibrated_at":"2026-09-23"},
                        profile_status="Listo para comenzar",
                        diagnostic={"normalized_dx":.04,"normalized_dy":-.02,
                                    "thresholds":{"blink_left":.2,"blink_right":.2,
                                                  "brow_left":.1,"brow_right":.1,"mouth_open":.08}},
                        wizard={"instruction":"Volvé a posición neutral antes del siguiente gesto.",
                                "progress":.8,"state":"validation","phase":6,"samples":120,
                                "countdown":0,"error":"","recognized":["LEFT_CLICK","RIGHT_CLICK","SCROLL_UP"],
                                "can_save":False},
                        experiment={"active":True,"index":1,"total":5,"cursor":(400,250),
                                    "target":(640,120),"radius":35,"completed":0,"path":"",
                                    "elapsed_s":1,"mode":"simulation","source":"keyboard"})
        for index,name in ((0,"home"),(2,"calibration"),(3,"diagnostic"),(6,"experiments")):
            window.show_page(index)
            window.refresh()
            app.processEvents()
            window.grab().save(str(directory/f"v03-{name}-synthetic.png"))
        window.close()
        app.processEvents()
        print("Pantallas vacías y sintéticas renderizadas en",directory)


if __name__=="__main__": main()
