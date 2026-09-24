"""
debug_cursor.py
HeadMouse — Diagnóstico del cursor
Muestra en tiempo real los valores de la nariz y el delta calculado
SIN mover el cursor real. Sirve para verificar que los valores son
correctos antes de activar el control.

Uso:
    python debug_cursor.py

Controles:
    Q → salir
"""

import time
import argparse
import logging
from contextlib import ExitStack
from config import ROOT, load_config, configure_logging
from profiles import ProfileStore
from gesture_engine import GestureEngine

C_WHITE  = (255, 255, 255)
C_GRAY   = (150, 150, 150)
C_GREEN  = ( 40, 210,  80)
C_CYAN   = (  0, 210, 210)
C_ORANGE = ( 30, 160, 255)
C_RED    = ( 50,  50, 220)
C_DARK   = ( 20,  20,  20)


def put_bg(frame, text, pos, scale=0.6, color=C_WHITE, thickness=1):
    font = cv2.FONT_HERSHEY_SIMPLEX
    (tw, th), bl = cv2.getTextSize(text, font, scale, thickness)
    x, y = pos
    cv2.rectangle(frame, (x-4, y-th-4), (x+tw+4, y+bl+4), C_DARK, -1)
    cv2.putText(frame, text, (x, y), font, scale, color, thickness, cv2.LINE_AA)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Diagnóstico nasal sin controlar el SO")
    parser.add_argument("--user", default="default")
    parser.add_argument("--config")
    parser.add_argument("--camera", type=int)
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], default="INFO")
    args = parser.parse_args(argv)
    configure_logging(args.log_level)
    global cv2
    import cv2
    from vision_engine import VisionEngine
    profile = ProfileStore().load(args.user, ROOT / "calibration.json" if args.user == "default" else None)
    config = load_config(args.config, profile.get("settings", {}))
    if args.camera is not None:
        config.vision.camera_index = args.camera
        config.vision.__post_init__()
    neutral_x = profile.get("neutral_nose_x", config.gesture.neutral_x)
    neutral_y = profile.get("neutral_nose_y", config.gesture.neutral_y)
    with ExitStack() as cleanup:
        cleanup.callback(cv2.destroyAllWindows)
        vision = VisionEngine(config=config.vision)
        cleanup.callback(vision.stop)
        vision.start()
        vision.wait_ready()
        gesture = GestureEngine(vision, config=config.gesture, calibration=profile)
        logging.info("Diagnóstico: no mueve el cursor; Q para salir")
        _preview(vision, gesture, neutral_x, neutral_y)
    return 0


def _preview(vision, gesture, neutral_x, neutral_y):
    while True:
        if vision.error or not vision.is_alive():
            raise RuntimeError("Captura detenida") from vision.error
        frame = vision.get_frame()
        if frame is None:
            time.sleep(0.01)
            continue

        fd = vision.get_face_data()
        h, w = frame.shape[:2]

        events = gesture.update(fd)
        if fd.fresh(gesture.config.stale_after_s):
            cursor = next((e for e in events if e.type == "CURSOR_MOVE"), None)
            px, py = (cursor.dx, cursor.dy) if cursor else (0., 0.)
            dx_raw = gesture._smooth_x - neutral_x
            dy_raw = gesture._smooth_y - neutral_y
            dz = gesture.config.dead_zone
            dx = 0 if abs(dx_raw) <= dz else dx_raw

            # Dibujar punto de la nariz en el frame
            nx = int(fd.nose_x * w)
            ny = int(fd.nose_y * h)
            cv2.circle(frame, (nx, ny), 8, C_CYAN, -1)
            cv2.circle(frame, (int(neutral_x * w), int(neutral_y * h)), 8, C_ORANGE, 2)

            # Dibujar zona muerta
            dz_px_x = int(dz * w)
            dz_px_y = int(dz * h)
            cv2.rectangle(frame,
                (int(neutral_x*w) - dz_px_x, int(neutral_y*h) - dz_px_y),
                (int(neutral_x*w) + dz_px_x, int(neutral_y*h) + dz_px_y),
                C_ORANGE, 1)

            # Vector de movimiento
            if abs(px) > 0.5 or abs(py) > 0.5:
                ex = int(neutral_x*w + dx_raw * w * 2)
                ey = int(neutral_y*h + dy_raw * h * 2)
                cv2.arrowedLine(frame, (int(neutral_x*w), int(neutral_y*h)),
                                (ex, ey), C_GREEN, 2, tipLength=0.3)

            # Panel de datos
            cv2.rectangle(frame, (0, 0), (340, 250), C_DARK, -1)
            items = [
                (f"Nariz X     : {fd.nose_x:.3f}", C_CYAN),
                (f"Nariz Y     : {fd.nose_y:.3f}", C_CYAN),
                (f"Neutral X   : {neutral_x:.3f}", C_ORANGE),
                (f"Neutral Y   : {neutral_y:.3f}", C_ORANGE),
                (f"dx raw      : {dx_raw:+.3f}", C_WHITE),
                (f"dy raw      : {dy_raw:+.3f}", C_WHITE),
                (f"dx en zona muerta: {'SI' if dx==0 else 'NO'}", C_GRAY),
                (f"delta cursor: ({px:+.1f}, {py:+.1f}) px/frame", C_GREEN),
            ]
            for i, (txt, col) in enumerate(items):
                cv2.putText(frame, txt, (10, 28 + i*27),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.58, col, 1, cv2.LINE_AA)

            # Advertencia si el delta es muy grande
            if abs(px) > 30 or abs(py) > 30:
                put_bg(frame, f"⚠ Delta muy alto ({px:.0f}, {py:.0f}) — ajustar neutral",
                       (10, h-20), scale=0.55, color=C_RED)
            else:
                put_bg(frame, "✓ Delta en rango normal",
                       (10, h-20), scale=0.55, color=C_GREEN)

            cv2.rectangle(frame, (0, 0), (w-1, h-1), C_GREEN, 2)
        else:
            cv2.rectangle(frame, (0, 0), (w-1, h-1), C_RED, 3)
            put_bg(frame, "SIN CARA DETECTADA", (w//2-130, h//2),
                   scale=1.0, color=C_RED, thickness=2)

        cv2.putText(frame, "MODO DIAGNOSTICO — cursor NO se mueve",
                    (10, h - 45), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, C_ORANGE, 1, cv2.LINE_AA)
        cv2.putText(frame, "Nariz (cian) | Neutral (naranja) | Q=salir",
                    (10, h - 25), cv2.FONT_HERSHEY_SIMPLEX,
                    0.48, C_GRAY, 1, cv2.LINE_AA)

        cv2.imshow("HeadMouse — Diagnostico cursor  (Q = salir)", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        pass
    except (OSError, ValueError, RuntimeError, ImportError) as exc:
        logging.error("Diagnóstico detenido: %s", exc)
        raise SystemExit(1)
