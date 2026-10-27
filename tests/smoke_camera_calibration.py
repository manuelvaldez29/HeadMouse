"""Opt-in: webcam REAL, worker Qt y neutral ocular, perfil temporal, sin mouse."""
import argparse
import json
import os
import sys
import tempfile
import time
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-camera-free",action="store_true")
    parser.add_argument("--source",choices=("both","left","right"),default="both")
    args=parser.parse_args(argv)
    if not args.confirm_camera_free:
        parser.error("Cerrá todas las otras capturas y agregá --confirm-camera-free")
    os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
    from PySide6.QtCore import QCoreApplication,QEvent
    from PySide6.QtWidgets import QApplication
    from config import configure_logging,load_config
    from runtime_diagnostics import install
    from application_controller import ApplicationController
    from desktop.bridge import DesktopBridge
    from profile_manager import ProfileManager
    from profiles import ProfileStore
    configure_logging("INFO")
    install(ROOT/"data"/"logs")
    app=QApplication.instance() or QApplication([])
    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path=ROOT/"data"/"logs"/f"camera-calibration-check-{stamp}.json"
    report=dict(mouse_backend="prohibited",eye_source=args.source,calibration_started=False,
                face_observed=False,neutral_ready=False,samples=0,closed=False)
    def forbidden_backend():raise AssertionError("Backend del mouse prohibido en prueba física de calibración")
    with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
        controller=ApplicationController(ProfileManager(ProfileStore(Path(tmp)/"profiles")),
            backend_factory=forbidden_backend,data_dir=tmp)
        controller.create_profile("Diagnóstico temporal C270")
        controller.config=load_config(overrides=dict(metrics_enabled=False,
            ui=dict(tracking_method="eye",eye_source=args.source),
            vision=dict(capture_backend="dshow",frame_width=640,frame_height=480,
                        target_fps=15,startup_timeout_s=20)))
        bridge=DesktopBridge(controller)
        try:
            bridge.request("start_eye_calibration")
            started=time.monotonic()
            calibration_at=None
            while time.monotonic()-started < 32:
                app.processEvents()
                snapshot=bridge.snapshot()
                if snapshot:
                    report["camera_status"]=snapshot.get("camera_status",{})
                    report["face_observed"] |= snapshot["detected"]
                    report["iris_available"]=snapshot.get("eye_availability",{})
                    if snapshot["state"]=="ERROR":
                        report["error"]=snapshot["message"]
                        break
                    if snapshot["state"]=="EYE_CALIBRATING":
                        report["calibration_started"]=True
                        calibration_at=calibration_at or time.monotonic()
                        session=snapshot.get("eye_calibration") or {}
                        report.update(neutral_ready=bool(session.get("can_save")),samples=session.get("samples",0),
                                      calibration_state=session.get("state"))
                        if report["neutral_ready"] or time.monotonic()-calibration_at > 8:
                            break
                time.sleep(.02)
            assert controller.control is None
            report["elapsed_s"]=time.monotonic()-started
            path.write_text(json.dumps(report,indent=2,allow_nan=False),encoding="utf-8")
        finally:
            bridge.shutdown()
            while bridge.thread.isRunning():
                app.processEvents()
                time.sleep(.02)
            app.processEvents()
            report["closed"]=controller.closed and controller.vision is None
            bridge.deleteLater()
            QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        # No se invoca guardar: las muestras y el perfil temporal se descartan.
    path.write_text(json.dumps(report,indent=2,allow_nan=False),encoding="utf-8")
    print(json.dumps(report,allow_nan=False),flush=True)
    print(f"Informe de calibración temporal: {path}",flush=True)
    return 0 if report["calibration_started"] and report["closed"] and not report.get("error") else 1


if __name__=="__main__":raise SystemExit(main())
