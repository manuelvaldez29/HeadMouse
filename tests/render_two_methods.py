"""Revisión visual Nariz/Ojos con rostro dibujado; nunca usa webcam/mouse."""
import os
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
import sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
import cv2
from PySide6.QtWidgets import QApplication
from desktop.style import apply_style
from desktop.window import MainWindow
from desktop.gaze_overlay import GazeOverlay
from desktop.lifecycle import dispose_window
from application_controller import ApplicationController
from profile_manager import ProfileManager
from profiles import ProfileStore
from ocular_profiles import with_calibration
from test_core import calibration
from test_eye_gui import EyeVision
from test_gaze_mapping import completed_session
from render_gui import ReviewBridge


class DrawnFaceVision(EyeVision):
    def get_frame(self):
        image=np.full((480,640,3),45,dtype=np.uint8)
        cv2.ellipse(image,(320,240),(180,210),0,0,360,(145,175,195),-1)
        for x in (224,416):
            cv2.ellipse(image,(x,192),(52,15),0,0,360,(235,235,235),-1)
            cv2.circle(image,(x,192),11,(65,90,100),-1)
        cv2.line(image,(320,205),(310,280),(85,100,115),3)
        cv2.ellipse(image,(320,330),(55,15),0,0,180,(80,80,130),3)
        cv2.putText(image,"DATOS SINTETICOS",(150,455),cv2.FONT_HERSHEY_SIMPLEX,.7,(255,255,255),2)
        return image


def main():
    app=QApplication.instance() or QApplication([]);apply_style(app)
    output=Path('docs/screenshots');output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        manager=ProfileManager(ProfileStore(Path(tmp)/'profiles'))
        p=with_calibration(calibration()|dict(display_name="Persona de demostración",validation={"passed":True},
            settings={"ui":{"tracking_method":"eye_absolute"}}),completed_session().result())
        manager.store.save(p)
        controller=ApplicationController(manager,vision_factory=DrawnFaceVision,data_dir=tmp)
        controller.select_control_method('eyes');controller.start_diagnostic();controller.step()
        snapshot=controller.snapshot();snapshot['profiles']=manager.list_profiles()
        snapshot['message']='REVISIÓN SINTÉTICA · Sin webcam ni control del sistema'
        window=MainWindow(ReviewBridge(snapshot));window.resize(1240,850);window.show();window.refresh();app.processEvents()
        for index,name in ((0,'two-methods-home-synthetic.png'),(2,'two-methods-calibration-synthetic.png')):
            window.show_page(index);window.refresh();app.processEvents();assert window.grab().save(str(output/name))
        overlay=GazeOverlay(window);overlay.resize(1280,900)
        session=completed_session();session.repeat(2)
        overlay.present(session.snapshot(),None);overlay.present_camera(snapshot);overlay.show();app.processEvents()
        assert overlay.grab().save(str(output/'two-methods-live-preview-synthetic.png'))
        overlay.blockSignals(True);overlay.close()
        window.close();dispose_window(window);app.processEvents();controller.shutdown()
    print('Tres capturas sintéticas generadas; sin webcam ni acciones del SO')


if __name__=='__main__':main()
