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
import cv2
import numpy as np

from vision_engine  import VisionEngine
from gesture_engine import GestureEngine, GestureConfig
from control_engine import ControlEngine, ControlConfig


# ── Colores overlay ───────────────────────────────────────────────────────────
C_WHITE  = (255, 255, 255)
C_GRAY   = (150, 150, 150)
C_GREEN  = ( 40, 210,  80)
C_RED    = ( 50,  50, 220)
C_ORANGE = ( 30, 160, 255)
C_DARK   = ( 15,  15,  15)


def draw_overlay(stats) -> np.ndarray:
    """Genera el frame del overlay de estado (220×200 px)."""
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


def main():
    parser = argparse.ArgumentParser(description="HeadMouse — Control de PC por movimiento de cabeza")
    parser.add_argument("--camera",     type=int,  default=0,
                        help="Índice de cámara (default: 0)")
    parser.add_argument("--no-overlay", action="store_true",
                        help="No mostrar ventana de estado")
    args = parser.parse_args()

    print("══════════════════════════════════════════════════════════════")
    print("  HeadMouse — UNSTA 2026")
    print("  Bloj · Domfrocht · Petrelli · Valdez")
    print("══════════════════════════════════════════════════════════════")
    print()

    # ── Módulo 1: Vision Engine ───────────────────────────────────────────────
    print("[1/3] Iniciando Vision Engine...")
    vision = VisionEngine(camera_index=args.camera, target_fps=30)
    vision.start()
    time.sleep(1.2)

    # ── Módulo 2: Gesture Engine ──────────────────────────────────────────────
    print("[2/3] Iniciando Gesture Engine...")
    gesture_config = GestureConfig(
        sensitivity     = 80.0,
        acceleration    = 600.0,
        dead_zone       = 0.03,
        smoothing_alpha = 0.35,
    )
    gesture = GestureEngine(
        vision,
        calibration_path = "calibration.json",
        config           = gesture_config,
    )

    # ── Módulo 3: Control Engine ──────────────────────────────────────────────
    print("[3/3] Iniciando Control Engine...")
    control_config = ControlConfig(
        scroll_lines    = 3,
        face_timeout_s  = 2.0,
        max_cursor_delta= 60.0,
        loop_hz         = 60.0,
    )
    control = ControlEngine(vision, gesture, control_config)
    control.start()

    print()
    print("══════════════════════════════════════════════════════════════")
    print("  Sistema activo. Controlá el cursor con tu cabeza.")
    print("  Ambas cejas levantadas → pausar / reanudar")
    print("  Cursor a esquina sup-izq → detener (failsafe)")
    print("  Ctrl+C → detener")
    print("══════════════════════════════════════════════════════════════")
    print()

    # ── Overlay de estado ─────────────────────────────────────────────────────
    win_name = "HeadMouse — Estado"

    try:
        while True:
            time.sleep(0.1)

            if not args.no_overlay:
                stats = control.get_stats()
                overlay = draw_overlay(stats)
                cv2.imshow(win_name, overlay)

                key = cv2.waitKey(1) & 0xFF
                if key == ord("q"):
                    break

    except KeyboardInterrupt:
        print("\n[main] Ctrl+C detectado — deteniendo...")

    finally:
        control.stop()
        vision.stop()
        cv2.destroyAllWindows()
        print("[main] HeadMouse detenido.")

        # Resumen final
        stats = control.get_stats()
        print()
        print("── Resumen de sesión ────────────────────────────────────────")
        print(f"  Clicks totales : {stats.clicks_total}")
        print(f"  Scrolls totales: {stats.scrolls_total}")
        print(f"  Eventos totales: {stats.events_total}")


if __name__ == "__main__":
    main()
