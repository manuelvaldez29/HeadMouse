"""Revisión visual reproducible exclusivamente con fijaciones sintéticas."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from desktop.gaze_overlay import GazeOverlay
from desktop.style import apply_style
from test_gaze_mapping import completed_session


def main():
    app=QApplication.instance() or QApplication([])
    apply_style(app)
    output=Path(__file__).resolve().parents[1]/"docs"/"screenshots"
    output.mkdir(exist_ok=True)
    overlay=GazeOverlay()
    overlay.resize(1280,800)
    session=completed_session()
    session.repeat(3)
    overlay.present(session.snapshot(),None)
    overlay.show()
    app.processEvents()
    assert overlay.grab().save(str(output/"gaze-calibration-synthetic.png"))
    overlay.present(None,(.7,.3))
    app.processEvents()
    assert overlay.grab().save(str(output/"gaze-diagnostic-synthetic.png"))
    overlay.close()
    overlay.deleteLater()
    app.processEvents()
    print("Capturas sintéticas guardadas; sin cámara/entrada SO")


if __name__=="__main__": main()
