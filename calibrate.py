"""
calibrate.py
HeadMouse — Calibración automática por usuario
Tesis UNSTA 2026 — Bloj · Domfrocht · Petrelli · Valdez

Mide los valores neutros y extremos de cada gesto para cada usuario
y calcula los umbrales óptimos automáticamente. Guarda el resultado
en calibration.json, que el Gesture Engine carga al arrancar.

Uso:
    python calibrate.py
    python calibrate.py --user ivan1

Controles:
    SPACE → avanzar a la siguiente fase
    Q     → salir sin guardar
"""

import argparse
import json
import os
import time
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime

import cv2
import numpy as np
from vision_engine import VisionEngine, FaceData


# ══════════════════════════════════════════════════════════════════════════════
# COLORES Y CONSTANTES
# ══════════════════════════════════════════════════════════════════════════════

C_WHITE  = (255, 255, 255)
C_BLACK  = (  0,   0,   0)
C_GREEN  = ( 40, 210,  80)
C_RED    = ( 50,  50, 220)
C_CYAN   = (  0, 220, 220)
C_ORANGE = ( 30, 160, 255)
C_PURPLE = (200,  80, 220)
C_GRAY   = (160, 160, 160)
C_DARK   = ( 20,  20,  20)

OUTPUT_PATH = "calibration.json"

# Duración de cada fase en segundos
COUNTDOWN_SECS  = 3    # cuenta regresiva antes de medir
MEASURING_SECS  = 4    # tiempo de medición


# ══════════════════════════════════════════════════════════════════════════════
# DEFINICIÓN DE FASES
# ══════════════════════════════════════════════════════════════════════════════

PHASES = [
    {
        "id":          "neutral",
        "title":       "POSICIÓN NEUTRAL",
        "instruction": "Mirá la cámara\ncon la cara relajada",
        "sub":         "No hagas ningún gesto — esta es tu línea base",
        "icon":        "😐",
        "color":       C_GREEN,
    },
    {
        "id":          "wink_left",
        "title":       "GUIÑO OJO IZQUIERDO",
        "instruction": "Guiñá tu ojo\nIZQUIERDO",
        "sub":         "Cerrá y abrí varias veces durante la medición",
        "icon":        "😉",
        "color":       C_CYAN,
    },
    {
        "id":          "wink_right",
        "title":       "GUIÑO OJO DERECHO",
        "instruction": "Guiñá tu ojo\nDERECHO",
        "sub":         "Cerrá y abrí varias veces durante la medición",
        "icon":        "😉",
        "color":       C_CYAN,
    },
    {
        "id":          "brow_left",
        "title":       "CEJA IZQUIERDA",
        "instruction": "Levantá tu\nceja IZQUIERDA",
        "sub":         "Subila y bajala varias veces durante la medición",
        "icon":        "🤨",
        "color":       C_ORANGE,
    },
    {
        "id":          "brow_right",
        "title":       "CEJA DERECHA",
        "instruction": "Levantá tu\nceja DERECHA",
        "sub":         "Subila y bajala varias veces durante la medición",
        "icon":        "🤨",
        "color":       C_ORANGE,
    },
    {
        "id":          "mouth",
        "title":       "BOCA ABIERTA",
        "instruction": "Abrí la boca\nbien grande",
        "sub":         "Abrí y cerrá varias veces durante la medición",
        "icon":        "😮",
        "color":       C_PURPLE,
    },
]


# ══════════════════════════════════════════════════════════════════════════════
# RECOLECTOR DE MUESTRAS
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class Samples:
    eye_left:   list = field(default_factory=list)
    eye_right:  list = field(default_factory=list)
    brow_left:  list = field(default_factory=list)
    brow_right: list = field(default_factory=list)
    mouth:      list = field(default_factory=list)
    nose_x:     list = field(default_factory=list)
    nose_y:     list = field(default_factory=list)

    def add(self, fd: FaceData):
        if not fd.detected:
            return
        self.eye_left.append(fd.eye_left_ratio)
        self.eye_right.append(fd.eye_right_ratio)
        self.brow_left.append(fd.brow_left_lift)
        self.brow_right.append(fd.brow_right_lift)
        self.mouth.append(fd.mouth_open)
        self.nose_x.append(fd.nose_x)
        self.nose_y.append(fd.nose_y)

    def median(self, key: str) -> float:
        vals = getattr(self, key)
        return float(np.median(vals)) if vals else 0.0

    def percentile(self, key: str, p: float) -> float:
        vals = getattr(self, key)
        return float(np.percentile(vals, p)) if vals else 0.0


# ══════════════════════════════════════════════════════════════════════════════
# CÁLCULO DE UMBRALES
# ══════════════════════════════════════════════════════════════════════════════

def compute_thresholds(data: dict) -> dict:
    """
    Calcula umbrales óptimos para cada gesto.

    Estrategia: el umbral se coloca al 60% del recorrido desde el valor
    neutral hacia el extremo del gesto. Esto lo aleja del neutral (menos
    falsos positivos) sin exigir un gesto excesivo al usuario.

    Para ojos: el extremo es el mínimo (ojo cerrado → ratio pequeño)
    Para cejas y boca: el extremo es el máximo (levantado/abierto → ratio grande)
    """
    n = data["neutral"]
    g = data["gesture_extremes"]

    def thresh_low(neutral, extreme):
        # Para gestos donde el valor BAJA (guiños)
        return neutral - (neutral - extreme) * 0.6

    def thresh_high(neutral, extreme):
        # Para gestos donde el valor SUBE (cejas, boca)
        return neutral + (extreme - neutral) * 0.6

    return {
        "blink_left":  round(thresh_low( n["eye_left"],  g["eye_left_min"]),  4),
        "blink_right": round(thresh_low( n["eye_right"], g["eye_right_min"]), 4),
        "brow_left":   round(thresh_high(n["brow_left"], g["brow_left_max"]), 4),
        "brow_right":  round(thresh_high(n["brow_right"],g["brow_right_max"]),4),
        "mouth_open":  round(thresh_high(n["mouth"],     g["mouth_max"]),     4),
    }


# ══════════════════════════════════════════════════════════════════════════════
# VISUALIZACIÓN
# ══════════════════════════════════════════════════════════════════════════════

def overlay_dark(frame, alpha=0.55):
    """Aplica overlay oscuro semitransparente."""
    dark = np.zeros_like(frame)
    return cv2.addWeighted(frame, 1 - alpha, dark, alpha, 0)


def put_centered(frame, text, y, font_scale, color, thickness=1):
    h, w = frame.shape[:2]
    font = cv2.FONT_HERSHEY_SIMPLEX
    (tw, th), _ = cv2.getTextSize(text, font, font_scale, thickness)
    x = (w - tw) // 2
    cv2.putText(frame, text, (x, y), font, font_scale, color, thickness, cv2.LINE_AA)


def put_bg_text(frame, text, pos, font_scale=0.65, color=C_WHITE, thickness=1):
    font = cv2.FONT_HERSHEY_SIMPLEX
    (tw, th), bl = cv2.getTextSize(text, font, font_scale, thickness)
    x, y = pos
    cv2.rectangle(frame, (x-4, y-th-4), (x+tw+4, y+bl+4), C_DARK, -1)
    cv2.putText(frame, text, (x, y), font, font_scale, color, thickness, cv2.LINE_AA)


def draw_progress_bar(frame, pct, color, y_offset=0):
    h, w = frame.shape[:2]
    bx, by = 40, h - 40 + y_offset
    bw, bh = w - 80, 18
    cv2.rectangle(frame, (bx, by), (bx+bw, by+bh), (60, 60, 60), -1)
    filled = int(bw * pct)
    if filled > 0:
        cv2.rectangle(frame, (bx, by), (bx+filled, by+bh), color, -1)
    cv2.rectangle(frame, (bx, by), (bx+bw, by+bh), (120, 120, 120), 1)


def draw_live_values(frame, fd: FaceData):
    """Panel con valores en tiempo real (esquina sup izq)."""
    if not fd.detected:
        return
    items = [
        (f"Ojo izq  : {fd.eye_left_ratio:.3f}",  C_CYAN),
        (f"Ojo der  : {fd.eye_right_ratio:.3f}",  C_CYAN),
        (f"Ceja izq : {fd.brow_left_lift:.3f}",   C_ORANGE),
        (f"Ceja der : {fd.brow_right_lift:.3f}",  C_ORANGE),
        (f"Boca     : {fd.mouth_open:.3f}",        C_PURPLE),
    ]
    for i, (txt, col) in enumerate(items):
        put_bg_text(frame, txt, (10, 28 + i * 26),
                    font_scale=0.55, color=col)


def draw_step_indicator(frame, current: int, total: int):
    h, w = frame.shape[:2]
    step_txt = f"Paso {current} de {total}"
    put_bg_text(frame, step_txt, (w - 160, 26),
                font_scale=0.6, color=C_GRAY)


def draw_welcome(frame):
    frame = overlay_dark(frame, 0.6)
    h, w = frame.shape[:2]
    put_centered(frame, "HeadMouse", h//2 - 100, 2.0, C_WHITE, 3)
    put_centered(frame, "Calibracion automatica", h//2 - 40, 0.9, C_GRAY)
    put_centered(frame, "El sistema va a medir tus gestos faciales", h//2 + 20, 0.65, C_WHITE)
    put_centered(frame, "y calcular los umbrales ideales para vos.", h//2 + 50, 0.65, C_WHITE)
    put_centered(frame, "Asegurate de tener buena iluminacion", h//2 + 90, 0.6, C_GRAY)
    put_centered(frame, "y estar centrado en la camara.", h//2 + 115, 0.6, C_GRAY)
    put_centered(frame, "[ SPACE ] para comenzar", h//2 + 170, 0.85, C_GREEN, 2)
    return frame


def draw_countdown(frame, phase: dict, seconds_left: int):
    frame = overlay_dark(frame, 0.45)
    h, w = frame.shape[:2]
    color = phase["color"]
    put_centered(frame, phase["title"], h//2 - 120, 0.9, color, 2)
    for i, line in enumerate(phase["instruction"].split("\n")):
        put_centered(frame, line, h//2 - 50 + i*50, 1.4, C_WHITE, 2)
    put_centered(frame, phase["sub"], h//2 + 60, 0.6, C_GRAY)
    # Número de cuenta regresiva
    put_centered(frame, str(seconds_left), h//2 + 130, 3.5, C_ORANGE, 5)
    put_centered(frame, "preparate...", h//2 + 200, 0.7, C_GRAY)
    return frame


def draw_measuring(frame, phase: dict, elapsed: float, n_samples: int):
    h, w = frame.shape[:2]
    color = phase["color"]
    # Borde de color parpadeante
    blink = int(time.time() * 3) % 2 == 0
    if blink:
        cv2.rectangle(frame, (0, 0), (w-1, h-1), color, 5)
    # Instrucción en la parte superior
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (w, 100), C_DARK, -1)
    cv2.addWeighted(overlay, 0.7, frame, 0.3, 0, frame)
    put_centered(frame, "● MIDIENDO", 30, 0.8, color, 2)
    put_centered(frame, phase["title"], 65, 0.7, C_WHITE)
    # Progreso
    pct = min(elapsed / MEASURING_SECS, 1.0)
    draw_progress_bar(frame, pct, color)
    put_bg_text(frame, f"Muestras: {n_samples}",
                (10, h - 50), font_scale=0.55, color=C_GRAY)
    return frame


def draw_results(frame, thresholds: dict, calibration: dict):
    frame = overlay_dark(frame, 0.7)
    h, w = frame.shape[:2]
    put_centered(frame, "Calibracion completada!", h//2 - 200, 1.0, C_GREEN, 2)
    put_centered(frame, "Umbrales calculados:", h//2 - 150, 0.7, C_GRAY)

    items = [
        (f"Guino izq  : < {thresholds['blink_left']:.4f}",  C_CYAN),
        (f"Guino der  : < {thresholds['blink_right']:.4f}", C_CYAN),
        (f"Ceja izq   : > {thresholds['brow_left']:.4f}",   C_ORANGE),
        (f"Ceja der   : > {thresholds['brow_right']:.4f}",  C_ORANGE),
        (f"Boca       : > {thresholds['mouth_open']:.4f}",  C_PURPLE),
    ]
    for i, (txt, col) in enumerate(items):
        put_centered(frame, txt, h//2 - 90 + i * 38, 0.8, col, 1)

    put_centered(frame, f"Guardado en: {OUTPUT_PATH}",
                 h//2 + 120, 0.6, C_GRAY)
    put_centered(frame, "[ SPACE ] continuar   [ Q ] salir",
                 h//2 + 170, 0.75, C_WHITE, 1)
    return frame


# ══════════════════════════════════════════════════════════════════════════════
# ESTADOS DE LA MÁQUINA
# ══════════════════════════════════════════════════════════════════════════════

STATE_WELCOME    = "welcome"
STATE_COUNTDOWN  = "countdown"
STATE_MEASURING  = "measuring"
STATE_RESULTS    = "results"
STATE_DONE       = "done"


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def run(user_id: str):
    print("── HeadMouse — Calibración automática ──────────────────────────")
    print(f"   Usuario : {user_id}")
    print(f"   Salida  : {OUTPUT_PATH}")
    print("   Presioná Q para salir en cualquier momento.\n")

    engine = VisionEngine(camera_index=0, target_fps=30)
    engine.start()
    time.sleep(1.0)

    state        = STATE_WELCOME
    phase_idx    = 0
    phase_data   = {}      # {phase_id: Samples}
    t_phase      = 0.0     # timestamp de inicio de la fase actual
    current_samp: Optional[Samples] = None
    thresholds   = {}
    calibration  = {}

    while True:
        frame = engine.get_frame()
        if frame is None:
            time.sleep(0.01)
            continue

        fd  = engine.get_face_data()
        vis = frame.copy()

        # ── Dibujar según estado ──────────────────────────────────────────────

        if state == STATE_WELCOME:
            vis = draw_welcome(vis)

        elif state == STATE_COUNTDOWN:
            phase       = PHASES[phase_idx]
            elapsed     = time.time() - t_phase
            secs_left   = max(1, int(np.ceil(COUNTDOWN_SECS - elapsed)))
            vis = draw_countdown(vis, phase, secs_left)
            draw_live_values(vis, fd)
            draw_step_indicator(vis, phase_idx + 1, len(PHASES))

            if elapsed >= COUNTDOWN_SECS:
                state       = STATE_MEASURING
                t_phase     = time.time()
                current_samp = Samples()

        elif state == STATE_MEASURING:
            phase   = PHASES[phase_idx]
            elapsed = time.time() - t_phase

            if fd.detected:
                current_samp.add(fd)

            vis = draw_measuring(vis, phase, elapsed,
                                 len(current_samp.eye_left))
            draw_live_values(vis, fd)
            draw_step_indicator(vis, phase_idx + 1, len(PHASES))

            if elapsed >= MEASURING_SECS:
                # Guardar muestras de esta fase
                phase_data[phase["id"]] = current_samp
                phase_idx += 1

                if phase_idx >= len(PHASES):
                    # Calcular umbrales
                    neu = phase_data["neutral"]
                    calibration = {
                        "user_id":       user_id,
                        "calibrated_at": datetime.now().isoformat(timespec="seconds"),
                        "neutral_nose_x": round(phase_data["neutral"].median("nose_x"), 4),
                        "neutral_nose_y": round(phase_data["neutral"].median("nose_y"), 4),
                        "neutral": {
                            "eye_left":   round(neu.median("eye_left"),  4),
                            "eye_right":  round(neu.median("eye_right"), 4),
                            "brow_left":  round(neu.median("brow_left"), 4),
                            "brow_right": round(neu.median("brow_right"),4),
                            "mouth":      round(neu.median("mouth"),     4),
                        },
                        "gesture_extremes": {
                            "eye_left_min":  round(phase_data["wink_left"].percentile("eye_left",   10), 4),
                            "eye_right_min": round(phase_data["wink_right"].percentile("eye_right", 10), 4),
                            "brow_left_max": round(phase_data["brow_left"].percentile("brow_left",  90), 4),
                            "brow_right_max":round(phase_data["brow_right"].percentile("brow_right",90), 4),
                            "mouth_max":     round(phase_data["mouth"].percentile("mouth",          90), 4),
                        },
                    }
                    thresholds = compute_thresholds(calibration)
                    calibration["thresholds"] = thresholds

                    # Guardar JSON
                    os.makedirs(os.path.dirname(OUTPUT_PATH) if os.path.dirname(OUTPUT_PATH) else ".", exist_ok=True)
                    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
                        json.dump(calibration, f, indent=2, ensure_ascii=False)
                    print(f"\n✓ Calibración guardada en {OUTPUT_PATH}")
                    print(f"\n  Umbrales calculados:")
                    for k, v in thresholds.items():
                        print(f"    {k:15s}: {v:.4f}")

                    state = STATE_RESULTS
                else:
                    state   = STATE_COUNTDOWN
                    t_phase = time.time()

        elif state == STATE_RESULTS:
            vis = draw_results(vis, thresholds, calibration)

        # ── Mostrar frame ─────────────────────────────────────────────────────
        cv2.imshow("HeadMouse — Calibracion  (Q = salir)", vis)
        key = cv2.waitKey(1) & 0xFF

        if key == ord("q"):
            break
        elif key == ord(" "):
            if state == STATE_WELCOME:
                state   = STATE_COUNTDOWN
                t_phase = time.time()
            elif state == STATE_RESULTS:
                break

    engine.stop()
    cv2.destroyAllWindows()
    print("\n── Calibración finalizada ──────────────────────────────────────")


# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="HeadMouse — Calibración automática de umbrales"
    )
    parser.add_argument(
        "--user", default="default",
        help="ID del usuario (ej: manu1, ivan1). Default: 'default'"
    )
    args = parser.parse_args()
    run(user_id=args.user)
