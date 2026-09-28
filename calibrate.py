"""
calibrate.py
HeadMouse — Calibración automática por usuario
Tesis UNSTA 2026 — Bloj · Domfrocht · Petrelli · Valdez

Captura repeticiones neutrales/activas con el mismo wizard que la GUI
y calcula umbrales adaptativos por gesto. Guarda el resultado
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

def run(user_id: str, config=None, disabled=None):
    # CLI y GUI conducen exactamente la misma máquina de captura/validación.
    global cv2, np
    import cv2
    import numpy as np
    import uuid
    from vision_engine import VisionEngine
    from calibration_session import CalibrationSession
    from gesture_signals import GESTURE_SIGNALS
    from experiment_engine import ResultStore
    validate_user_id(user_id)
    config = config or load_config()
    store = ProfileStore()
    profile = dict(user_id=user_id)
    if store.path(user_id).exists():
        try:
            profile = store.load(user_id)
        except ValueError:
            logger.warning("Perfil inválido: se conservará hasta guardar una nueva calibración validada")
    session = CalibrationSession(profile, config, enabled={key:False for key in (disabled or [])})
    telemetry = ResultStore(ROOT / "data" / "calibration")
    session_id, logged = uuid.uuid4().hex, 0
    logger.info("Calibración adaptativa de %s; salida: %s", user_id, store.path(user_id))
    with ExitStack() as cleanup:
        cleanup.callback(cv2.destroyAllWindows)
        engine = VisionEngine(config=config.vision)
        cleanup.callback(engine.stop)
        engine.start()
        engine.wait_ready()
        while True:
            if engine.error or not engine.is_alive():
                raise RuntimeError("La captura terminó durante la calibración") from engine.error
            frame = engine.get_frame()
            if frame is None:
                time.sleep(.01)
                continue
            session.update(engine.get_face_data())
            while logged < len(session.telemetry):
                telemetry.append(session_id, dict(experiment="gesture_calibration", schema_version=1,
                    profile_id=user_id, recorded_at=time.time(), **session.telemetry[logged]))
                logged += 1
            snapshot = session.snapshot()
            vis = draw_adaptive_calibration(frame.copy(), snapshot)
            cv2.imshow("HeadMouse — Calibracion adaptativa (Q = salir)", vis)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                return None
            if key == ord("c"):
                session.restart()
                session_id, logged = uuid.uuid4().hex, 0
            elif key == ord("r"):
                session.repeat()
            elif key == ord("s") and snapshot.get("gesture_id"):
                session.set_enabled(snapshot["gesture_id"], False)
            elif ord("1") <= key <= ord("6"):
                gesture_id = list(GESTURE_SIGNALS)[key-ord("1")]
                if session.baseline is not None and session.models[gesture_id].enabled:
                    session.repeat(gesture_id)
            elif key == ord(" "):
                if session.state == "ready":
                    session.start()
                elif session.state == "measured":
                    session.validate()
                elif session.state == "validated":
                    path = store.save(session.result())
                    logger.info("Perfil adaptativo validado guardado: %s", path)
                    return path


def draw_adaptive_calibration(frame, snapshot):
    # OpenCV Hershey no representa tildes: transliterar solo la presentación CLI.
    import unicodedata
    def ascii_text(value):
        return unicodedata.normalize("NFKD",str(value)).encode("ascii","ignore").decode()
    height,width=frame.shape[:2]
    scale=max(1,800/width,600/height)
    if scale>1: frame=cv2.resize(frame,(round(width*scale),round(height*scale)))
    vis = overlay_dark(frame,.65)
    h,w=vis.shape[:2]
    lines=["HEADMOUSE v0.3.1 - CALIBRACION ADAPTATIVA",
           snapshot["instruction"],
           f"Paso {snapshot['phase']}/{snapshot['total_phases']} | Intento {snapshot['attempt']}/{snapshot['repetitions']}",
           snapshot["error"] or snapshot["feedback"], snapshot["capture_message"]]
    if snapshot["state"] in ("countdown","settling"):
        lines.append(f"Preparate: {snapshot['countdown']}")
    for i,text in enumerate(lines):
        put_centered(vis,ascii_text(text),30+i*32,.6,C_WHITE,1)
    y=225
    for row in snapshot["meter"]:
        values=[row[k] for k in ("neutral","comfortable","activation","release","value") if row[k] is not None]
        if not values: continue
        lo,hi=min(values),max(values)
        padding=max(.005,(hi-lo)*.15)
        lo,hi=lo-padding,hi+padding
        x=lambda value:int(25+(value-lo)/(hi-lo)*(w-50))
        cv2.line(vis,(25,y),(w-25,y),C_GRAY,2)
        for name,color in (("neutral",C_WHITE),("release",C_PURPLE),("activation",C_ORANGE),("comfortable",C_GREEN)):
            if row[name] is not None:
                cv2.line(vis,(x(row[name]),y-8),(x(row[name]),y+8),color,2)
        if row["value"] is not None:
            cv2.circle(vis,(x(row["value"]),y),5,C_CYAN,-1)
        y+=35
    put_centered(vis,"Neutral blanco | Liberacion violeta | Activacion naranja | Gesto verde",h-65,.45,C_GRAY,1)
    put_centered(vis,"SPACE iniciar/validar/guardar | R repetir | C reiniciar | S omitir | Q salir",h-40,.45,C_WHITE,1)
    put_centered(vis,"Repetir: 1 guino izq | 2 der | 3 ceja izq | 4 der | 5 boca | 6 ambas",h-18,.4,C_GRAY,1)
    return vis


def main(argv=None):
    from gesture_signals import GESTURE_SIGNALS, SOURCES
    parser = argparse.ArgumentParser(description="HeadMouse v0.3.1 — Calibración adaptativa por usuario")
    parser.add_argument("--user", default="default")
    parser.add_argument("--camera", type=int)
    parser.add_argument("--config")
    parser.add_argument("--disable", action="append", choices=tuple(GESTURE_SIGNALS), default=[], help="Gesto no disponible; se puede repetir")
    parser.add_argument("--brow-signal", choices=SOURCES, help="Fuente de cejas; blendshape/hybrid requieren calibración propia")
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
        if args.brow_signal:
            config.calibration.brow_signal_source = args.brow_signal
            config.calibration.__post_init__()
        if args.camera is not None:
            config.vision.camera_index = args.camera
            config.vision.__post_init__()
        logging.getLogger().setLevel(args.log_level or config.log_level)
        if args.check:
            from vision_engine import VisionEngine
            VisionEngine._ensure_model(ROOT / config.vision.model_path)
            logger.info("Dependencias/config/modelo verificados; webcam no probada")
            return 0
        run(args.user, config, args.disable)
        return 0
    except KeyboardInterrupt:
        logger.info("Calibración cancelada; no se guardó un perfil nuevo")
        return 0
    except (OSError, ValueError, RuntimeError, ImportError, TimeoutError) as exc:
        logger.error("Calibración detenida: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
