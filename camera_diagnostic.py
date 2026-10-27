"""Diagnóstico serial OpenCV y MediaPipe. Sin perfiles, ControlEngine ni mouse."""
import argparse
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from config import ROOT, VisionConfig, configure_logging


def run_cycle(config, duration_s, engine_factory=None, clock=time.monotonic):
    if engine_factory is None:
        from vision_engine import VisionEngine
        engine_factory=VisionEngine
    engine=engine_factory(config=config)
    error=None
    try:
        engine.start()
        engine.wait_ready()
        started=clock()
        while clock()-started < duration_s:
            if engine.error or not engine.is_alive():
                raise RuntimeError(f"Motor interrumpido: {engine.error or engine.diagnostics()}")
            time.sleep(.05)
    except (Exception,KeyboardInterrupt) as exc:
        error=f"{type(exc).__name__}: {exc}"
        logging.getLogger(__name__).exception("Diagnóstico interrumpido")
    before=engine.diagnostics()
    try:
        engine.stop()
    except Exception as exc:
        # Nunca abrir el siguiente ciclo mientras este propietario siga vivo.
        logging.getLogger(__name__).error("%s. No se reabrirá la cámara",exc)
        return dict(success=False,error=error or str(exc),before_close=before,
                    after_close=engine.diagnostics()),engine
    return dict(success=error is None,error=error,before_close=before,
                after_close=engine.diagnostics()),None


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--camera",type=int,default=0)
    parser.add_argument("--backend",choices=("auto","dshow","msmf"),default="dshow")
    parser.add_argument("--width",type=int,default=640)
    parser.add_argument("--height",type=int,default=480)
    parser.add_argument("--fps",type=int,default=15)
    parser.add_argument("--startup-timeout",type=float,default=20)
    parser.add_argument("--duration",type=float,default=5)
    parser.add_argument("--cycles",type=int,default=3)
    parser.add_argument("--confirm-camera-free",action="store_true",
        help="Confirmar que HeadMouse, Cámara de Windows y otras capturas están cerradas")
    args=parser.parse_args(argv)
    if not args.confirm_camera_free:
        parser.error("Cerrá las otras aplicaciones de cámara y agregá --confirm-camera-free")
    if not 1 <= args.cycles <= 20 or not .1 <= args.duration <= 120:
        parser.error("Usar 1–20 ciclos de 0,1–120 segundos")
    config=VisionConfig(camera_index=args.camera,capture_backend=args.backend,
        frame_width=args.width,frame_height=args.height,target_fps=args.fps,startup_timeout_s=args.startup_timeout)
    configure_logging("INFO")
    from runtime_diagnostics import install
    install(ROOT/"data"/"logs")
    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path=ROOT/"data"/"logs"/f"camera-diagnostic-{stamp}.json"
    results=[]
    retained=None
    for index in range(args.cycles):
        result,retained=run_cycle(config,args.duration)
        results.append(dict(cycle=index+1,**result))
        path.write_text(json.dumps(dict(mouse_backend="never_created",cycles=results),
            indent=2,ensure_ascii=False,allow_nan=False),encoding="utf-8")
        print(json.dumps(results[-1],ensure_ascii=False,allow_nan=False),flush=True)
        if retained is not None or not result["success"]:
            break
    print(f"Informe local: {path}",flush=True)
    # No destruir referencias/callbacks durante una operación nativa no cancelable.
    # El informe ya está escrito para permitir investigar el cierre pendiente.
    while retained is not None and retained.is_alive():
        try:
            retained.stop()
        except KeyboardInterrupt:
            retained.request_stop()
        except Exception as exc:
            logging.getLogger(__name__).error("Cierre aún pendiente, sin otra apertura: %s",exc)
            time.sleep(.5)
    if retained is not None:
        results[-1]["after_close"]=retained.diagnostics()
        path.write_text(json.dumps(dict(mouse_backend="never_created",cycles=results),
            indent=2,ensure_ascii=False,allow_nan=False),encoding="utf-8")
    return 0 if len(results)==args.cycles and all(r["success"] for r in results) else 1


if __name__=="__main__":raise SystemExit(main())
