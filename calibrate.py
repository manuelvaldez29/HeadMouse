"""
calibrate.py
HeadMouse — Calibración automática por usuario
Tesis UNSTA 2026 — Bloj · Domfrocht · Petrelli · Valdez

Mide los valores neutros y extremos de cada gesto para cada usuario
y calcula umbrales personalizados automáticamente. Guarda el resultado
en data/profiles/<usuario>.json después de validación interactiva.

Uso:
    python calibrate.py
    python calibrate.py --user ivan1

Controles:
    SPACE → avanzar a la siguiente fase
    Q     → salir sin guardar
"""

from __future__ import annotations

import argparse
import time
from datetime import datetime

import logging
from contextlib import ExitStack
from dataclasses import asdict
from face_data import FaceData
from config import ROOT, CalibrationConfig, load_config, configure_logging
from calibration_logic import Samples, compute_thresholds, build_calibration
from calibration_validation import CalibrationValidation
from profiles import ProfileStore, validate_user_id
from gesture_engine import GestureEngine

logger = logging.getLogger(__name__)


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

OUTPUT_PATH = "data/profiles/<usuario>.json"

# Duración de cada fase en segundos
COUNTDOWN_SECS  = CalibrationConfig().countdown_s    # cuenta regresiva antes de medir
MEASURING_SECS  = CalibrationConfig().measuring_s    # tiempo de medición


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

def overlay_dark(frame, alpha=0.55):
    """Aplica overlay oscuro semitransparente."""
    dark = np.zeros_like(frame)
    return cv2.addWeighted(frame, 1 - alpha, dark, alpha, 0)


def put_centered(frame, text, y, font_scale, color, thickness=1):
    h, w = frame.shape[:2]
    font = cv2.FONT_HERSHEY_SIMPLEX
    (tw, th), _ = cv2.getTextSize(text, font, font_scale, thickness)
    if tw > w - 30:
        font_scale *= (w - 30) / tw
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
    put_centered(frame, "y calcular umbrales personalizados.", h//2 + 50, 0.65, C_WHITE)
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


def draw_measuring(frame, phase: dict, elapsed: float, n_samples: int, duration=MEASURING_SECS):
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
    pct = min(elapsed / duration, 1.0)
    draw_progress_bar(frame, pct, color)
    put_bg_text(frame, f"Muestras: {n_samples}",
                (10, h - 50), font_scale=0.55, color=C_GRAY)
    return frame


def draw_results(frame, thresholds: dict, calibration: dict):
    frame = overlay_dark(frame, 0.7)
    h, w = frame.shape[:2]
    put_centered(frame, "Umbrales calculados", h//2 - 200, 1.0, C_GREEN, 2)
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

    put_centered(frame, "Falta validar gestos antes de guardar",
                 h//2 + 120, 0.6, C_GRAY)
    put_centered(frame, "[ SPACE ] validar   [ Q ] descartar",
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

def run(user_id: str, config=None):
    # Dependencias visuales se cargan solo al ejecutar, no para lógica/tests/help.
    global cv2, np
    import cv2
    import numpy as np
    from vision_engine import VisionEngine
    validate_user_id(user_id)
    config = config or load_config()
    store = ProfileStore()
    cc = config.calibration
    logger.info("Calibración de %s; salida: %s", user_id, store.path(user_id))
    with ExitStack() as cleanup:
        cleanup.callback(cv2.destroyAllWindows)
        engine = VisionEngine(config=config.vision)
        cleanup.callback(engine.stop)
        engine.start()
        engine.wait_ready()
        state = STATE_WELCOME
        phase_idx = 0
        phase_data = {}
        current_samp = None
        t_phase = 0.0
        calibration = {}
        error = ""
        validator = None
        while True:
            if engine.error or not engine.is_alive():
                raise RuntimeError("La captura terminó durante la calibración") from engine.error
            frame = engine.get_frame()
            if frame is None:
                time.sleep(.01)
                continue
            fd = engine.get_face_data()
            vis = frame.copy()
            now = time.monotonic()
            if state == STATE_WELCOME:
                vis = draw_welcome(vis)
            elif state == STATE_COUNTDOWN:
                phase = PHASES[phase_idx]
                elapsed = now - t_phase
                vis = draw_countdown(vis, phase, max(1, int(np.ceil(cc.countdown_s - elapsed))))
                draw_step_indicator(vis, phase_idx + 1, len(PHASES))
                if elapsed >= cc.countdown_s:
                    state = STATE_MEASURING
                    t_phase = now
                    current_samp = Samples()
            elif state == STATE_MEASURING:
                phase = PHASES[phase_idx]
                elapsed = now - t_phase
                current_samp.add(fd, config.gesture.stale_after_s, now)
                vis = draw_measuring(vis, phase, elapsed, len(current_samp.eye_left), cc.measuring_s)
                draw_live_values(vis, fd)
                draw_step_indicator(vis, phase_idx + 1, len(PHASES))
                if elapsed >= cc.measuring_s:
                    if len(current_samp.eye_left) < cc.min_samples:
                        error = "Pocas muestras. R: repetir esta fase"
                        state = "error"
                    else:
                        phase_data[phase["id"]] = current_samp
                        phase_idx += 1
                        if phase_idx < len(PHASES):
                            state, t_phase = STATE_COUNTDOWN, now
                        else:
                            try:
                                calibration = build_calibration(user_id, phase_data, cc)
                                calibration["settings"] = asdict(config)
                                if store.path(user_id).exists():
                                    try:
                                        calibration["display_name"] = store.load(user_id).get("display_name", user_id)
                                    except ValueError:
                                        pass  # Perfil anterior dañado: se permite recalibrar.
                                state = STATE_RESULTS
                            except ValueError as exc:
                                logger.warning("Calibración rechazada: %s", exc)
                                error = "Umbrales invalidos. R: recalibrar; detalle en terminal"
                                state = "error"
            elif state == STATE_RESULTS:
                vis = draw_results(vis, calibration["thresholds"], calibration)
            elif state == "validate":
                validator.update(fd)
                vis = overlay_dark(vis, .6)
                put_centered(vis, validator.instruction, vis.shape[0] // 2, .65,
                             C_GREEN if validator.passed else C_WHITE, 1)
                put_centered(vis, f"Gestos verificados: {len(validator.recognized)}/6", 50, .7, C_CYAN, 1)
                put_centered(vis, "R: repetir validacion | C: recalibrar | Q: descartar", vis.shape[0]-30, .55, C_GRAY, 1)
            elif state == "error":
                vis = overlay_dark(vis)
                put_centered(vis, error, vis.shape[0] // 2, .6, C_RED, 1)
            cv2.imshow("HeadMouse — Calibracion (Q = salir)", vis)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                return None
            if key == ord("c") and state == "validate":
                state, phase_idx, phase_data = STATE_WELCOME, 0, {}
            elif key == ord("r") and state == "error":
                if phase_idx >= len(PHASES):
                    phase_idx, phase_data = 0, {}
                state, t_phase = STATE_COUNTDOWN, now
            elif (key == ord(" ") and state == STATE_RESULTS or
                  key == ord("r") and state == "validate"):
                gesture = GestureEngine(engine, config=config.gesture, calibration=calibration)
                validator = CalibrationValidation(gesture, cc.validation_timeout_s,
                                                  neutral_s=cc.validation_neutral_s)
                state = "validate"
            elif key == ord(" "):
                if state == STATE_WELCOME:
                    state, t_phase = STATE_COUNTDOWN, now
                elif state == "validate" and validator.passed:
                    calibration["validation"] = {
                        "passed": True, "recognized": validator.recognized,
                        "validated_at": datetime.now().astimezone().isoformat(timespec="seconds")}
                    path = store.save(calibration)
                    logger.info("Perfil validado guardado: %s", path)
                    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description="HeadMouse v0.2 — Calibración y validación por usuario")
    parser.add_argument("--user", default="default")
    parser.add_argument("--camera", type=int)
    parser.add_argument("--config")
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    parser.add_argument("--check", action="store_true", help="Verificar dependencias/config/modelo sin abrir cámara")
    args = parser.parse_args(argv)
    configure_logging(args.log_level or "INFO")
    try:
        validate_user_id(args.user)
        store = ProfileStore()
        try:
            settings = store.load(args.user).get("settings", {}) if store.path(args.user).exists() else {}
        except ValueError as exc:
            logger.warning("Perfil anterior inválido; recalibrar con configuración base: %s", exc)
            settings = {}
        config = load_config(args.config, settings)
        if args.camera is not None:
            config.vision.camera_index = args.camera
            config.vision.__post_init__()
        logging.getLogger().setLevel(args.log_level or config.log_level)
        if args.check:
            from vision_engine import VisionEngine
            VisionEngine._ensure_model(ROOT / config.vision.model_path)
            logger.info("Dependencias/config/modelo verificados; webcam no probada")
            return 0
        run(args.user, config)
        return 0
    except KeyboardInterrupt:
        logger.info("Calibración cancelada; no se guardó un perfil nuevo")
        return 0
    except (OSError, ValueError, RuntimeError, ImportError, TimeoutError) as exc:
        logger.error("Calibración detenida: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
