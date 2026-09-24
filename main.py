"""
main.py
HeadMouse — Punto de entrada principal
Tesis UNSTA 2026 — Bloj · Domfrocht · Petrelli · Valdez

Inicia los tres módulos en orden y muestra un overlay de estado
en la esquina superior derecha de la pantalla.

Uso:
    python main.py
    python main.py --camera 1     (si la webcam no es la 0)
    python main.py --no-overlay   (sin ventana de estado)

Controles:
    BOTH_BROWS (ambas cejas)  → pausar / reanudar
    Cursor a esquina sup-izq  → detener (failsafe de pyautogui)
    Ctrl+C en terminal        → detener
"""

import argparse
import time
import logging
from contextlib import ExitStack
from config import ROOT, load_config, configure_logging
from profiles import ProfileStore
from metrics import SessionMetrics
from action_mapping import ActionMapping

logger = logging.getLogger(__name__)


# ── Colores overlay ───────────────────────────────────────────────────────────
C_WHITE  = (255, 255, 255)
C_GRAY   = (150, 150, 150)
C_GREEN  = ( 40, 210,  80)
C_RED    = ( 50,  50, 220)
C_ORANGE = ( 30, 160, 255)
C_DARK   = ( 15,  15,  15)


def draw_overlay(stats):
    """Genera el frame del overlay de estado (230×185 px)."""
    import cv2
    import numpy as np
    w, h = 230, 185
    frame = np.zeros((h, w, 3), dtype=np.uint8)
    frame[:] = C_DARK

    font  = cv2.FONT_HERSHEY_SIMPLEX
    font2 = cv2.FONT_HERSHEY_PLAIN

    # Título
    cv2.putText(frame, "HeadMouse", (10, 26),
                font, 0.7, C_WHITE, 1, cv2.LINE_AA)

    # Estado principal
    if stats.paused:
        estado_txt = "[ PAUSADO ]"
        estado_col = C_ORANGE
    else:
        estado_txt = "[ ACTIVO  ]"
        estado_col = C_GREEN
    cv2.putText(frame, estado_txt, (10, 52),
                font, 0.7, estado_col, 2, cv2.LINE_AA)

    # Cara
    cara_txt = "Cara: SI" if stats.face_detected else "Cara: NO"
    cara_col = C_GREEN if stats.face_detected else C_RED
    cv2.putText(frame, cara_txt, (10, 80),
                font, 0.55, cara_col, 1, cv2.LINE_AA)

    # FPS
    cv2.putText(frame, f"FPS: {stats.fps:.0f}", (10, 104),
                font, 0.55, C_GRAY, 1, cv2.LINE_AA)

    # Último evento
    cv2.putText(frame, f"Ultimo: {stats.last_event}", (10, 128),
                font, 0.48, C_GRAY, 1, cv2.LINE_AA)

    # Contadores
    cv2.putText(frame, f"Clicks: {stats.clicks_total}   "
                       f"Scroll: {stats.scrolls_total}",
                (10, 152), font, 0.48, C_GRAY, 1, cv2.LINE_AA)

    # Instrucciones
    cv2.line(frame, (0, 162), (w, 162), (40, 40, 40), 1)
    cv2.putText(frame, "Amb.cejas=pausa  Esq.sup=stop",
                (6, 178), font2, 0.85, (80, 80, 80), 1, cv2.LINE_AA)

    return frame


def main(argv=None):
    parser = argparse.ArgumentParser(description="HEADMOUSE v0.2 — BASELINE Y CONSOLIDACIÓN")
    parser.add_argument("--camera", type=int, help="Índice de cámara; sobreescribe configuración")
    parser.add_argument("--user", default="default", help="Perfil en data/profiles")
    parser.add_argument("--config", help="Archivo JSON de configuración")
    parser.add_argument("--legacy-calibration", help="Leer calibration.json antiguo para el usuario indicado")
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    parser.add_argument("--no-overlay", action="store_true")
    parser.add_argument("--no-metrics", action="store_true")
    parser.add_argument("--check", action="store_true", help="Validar imports/config/perfil sin cámara ni control")
    parser.add_argument("--download-model", action="store_true", help="Preparar modelo con Internet y salir")
    args = parser.parse_args(argv)
    configure_logging(args.log_level or "INFO")
    try:
        config = load_config(args.config)
        if args.download_model:
            from vision_engine import VisionEngine
            path = ROOT / config.vision.model_path
            VisionEngine.download_model(path)
            return 0
        # Solo el usuario default puede buscar el archivo global automáticamente.
        legacy = args.legacy_calibration or (ROOT / "calibration.json" if args.user == "default" else None)
        profile = ProfileStore().load(args.user, legacy_path=legacy)
        if profile.get("status") == "draft":
            raise ValueError("Perfil pendiente de calibración")
        config = load_config(args.config, profile.get("settings", {}))
        if args.camera is not None:
            config.vision.camera_index = args.camera
            config.vision.__post_init__()
        if args.log_level:
            config.log_level = args.log_level
        logging.getLogger().setLevel(config.log_level)
        if args.no_metrics:
            config.metrics_enabled = False
        from vision_engine import VisionEngine
        from gesture_engine import GestureEngine
        from control_engine import ControlEngine
        import cv2
        import pyautogui  # verificar dependencia antes de abrir cámara
        if args.check:
            VisionEngine._ensure_model(ROOT / config.vision.model_path)
            logger.info("Imports, configuración, perfil y modelo local verificados; hardware no probado")
            return 0
        metrics = SessionMetrics(args.user, enabled=config.metrics_enabled)
        with ExitStack() as cleanup:
            cleanup.callback(metrics.close)
            cleanup.callback(cv2.destroyAllWindows)
            vision = VisionEngine(config=config.vision, metrics=metrics)
            cleanup.callback(vision.stop)
            vision.start()
            vision.wait_ready()
            gesture = GestureEngine(vision, config=config.gesture, calibration=profile)
            control = ControlEngine(vision, gesture, config.control, metrics=metrics,
                                    mapping=ActionMapping(config.actions.bindings))
            cleanup.callback(control.stop)
            control.start()
            logger.info("Inicio PAUSADO. Ambas cejas: activar/pausar; esquina: failsafe; Ctrl+C: salir")
            try:
                while control.get_stats().running:
                    if vision.error:
                        raise RuntimeError("Falló VisionEngine") from vision.error
                    if not vision.is_alive():
                        raise RuntimeError("VisionEngine terminó inesperadamente")
                    if not args.no_overlay:
                        cv2.imshow("HeadMouse — Estado", draw_overlay(control.get_stats()))
                        if cv2.waitKey(1) & 0xFF == ord("q"):
                            break
                    time.sleep(.05)
                if control.error:
                    raise RuntimeError("Falló ControlEngine") from control.error
            except KeyboardInterrupt:
                logger.info("Interrupción del usuario")
        logger.info("Sesión finalizada: %s", metrics.snapshot())
        return 0
    except (OSError, ValueError, RuntimeError, ImportError, TimeoutError) as exc:
        logger.error("No se pudo ejecutar HeadMouse: %s", exc)
        if isinstance(exc, FileNotFoundError):
            logger.error("Preparación: main.py --download-model; luego calibrate.py --user %s", args.user)
        return 1
    except KeyboardInterrupt:
        logger.info("Inicio cancelado por el usuario")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
