"""Capturas de revisión: una fuente monocular sintética, sin webcam ni mouse."""
import os
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
import sys
import tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from desktop.style import apply_style
from desktop.window import MainWindow
from desktop.lifecycle import dispose_window
from application_controller import ApplicationController
from profile_manager import ProfileManager
from profiles import ProfileStore
from config import ROOT
from test_core import calibration
from test_eye_sources import completed_source_session
from test_eye_source_gui import LeftOnlyVision
from ocular_profiles import with_calibration
from render_gui import ReviewBridge


def main():
    app=QApplication.instance() or QApplication([])
    apply_style(app)
    with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
        manager=ProfileManager(ProfileStore(Path(tmp)/"profiles"))
        profile=with_calibration(calibration(),completed_source_session("left").result())
        profile.update(display_name="Revisión sintética",validation={"passed":True},
            settings={"ui":{"tracking_method":"eye_absolute","eye_source":"left"}})
        manager.store.save(profile)
        controller=ApplicationController(manager,vision_factory=LeftOnlyVision,data_dir=tmp)
        controller.start_diagnostic()
        controller.step()
        snapshot=controller.snapshot()
        snapshot["message"]="DATOS SINTÉTICOS · Ojo izquierdo seleccionado; iris derecho ausente. Sin control real."
        snapshot["profiles"]=manager.list_profiles()
        window=MainWindow(ReviewBridge(snapshot))
        window.resize(1240,900)
        window.show()
        directory=ROOT/"docs"/"screenshots"
        window.show_page(4)
        window.refresh()
        window.settings_scroll.ensureWidgetVisible(window.eye_source_combo,0,90)
        app.processEvents()
        assert window.grab().save(str(directory/"eye-source-settings-synthetic.png"))
        window.show_page(3)
        window.refresh()
        app.processEvents()
        assert window.grab().save(str(directory/"eye-source-diagnostic-synthetic.png"))
        window.close()
        dispose_window(window)
        controller.shutdown()
    print("Capturas sintéticas de fuente ocular guardadas; sin entradas SO")


if __name__=="__main__":main()
