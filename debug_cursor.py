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
import json
import cv2
import numpy as np
from vision_engine  import VisionEngine
from gesture_engine import GestureEngine, GestureConfig

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


def main():
    # Cargar calibración para ver el neutral real
    try:
        with open("calibration.json") as f:
            cal = json.load(f)
        neutral_x = cal.get("neutral_nose_x", 0.5)
        neutral_y = cal.get("neutral_nose_y", 0.5)
        print(f"Neutral nariz cargado: x={neutral_x:.3f}, y={neutral_y:.3f}")
    except FileNotFoundError:
        neutral_x, neutral_y = 0.5, 0.5
        print("calibration.json no encontrado — usando neutral=0.5")

    vision = VisionEngine(camera_index=0, target_fps=30)
    vision.start()
    time.sleep(1.0)

    SENSITIVITY  = 80.0
    ACCELERATION = 600.0
    DEAD_ZONE    = 0.03
    ALPHA        = 0.35

    smooth_x = neutral_x
    smooth_y = neutral_y

    print("\nMostrando diagnóstico del cursor (sin mover el cursor real).")
    print("Presioná Q para salir.\n")

    while True:
        frame = vision.get_frame()
        if frame is None:
            time.sleep(0.01)
            continue

        fd = vision.get_face_data()
        h, w = frame.shape[:2]

        if fd.detected:
            # Suavizado
            smooth_x = ALPHA * smooth_x + (1 - ALPHA) * fd.nose_x
            smooth_y = ALPHA * smooth_y + (1 - ALPHA) * fd.nose_y

            # Delta desde neutral
            dx_raw = smooth_x - neutral_x
            dy_raw = smooth_y - neutral_y

            # Zona muerta
            dz = DEAD_ZONE
            dx = 0.0 if abs(dx_raw) < dz else dx_raw - dz * (1 if dx_raw > 0 else -1)
            dy = 0.0 if abs(dy_raw) < dz else dy_raw - dz * (1 if dy_raw > 0 else -1)

            # Delta en píxeles — curva lineal + cuadrática
            px = dx * SENSITIVITY + (dx * abs(dx)) * ACCELERATION
            py = dy * SENSITIVITY + (dy * abs(dy)) * ACCELERATION

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

    vision.stop()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
