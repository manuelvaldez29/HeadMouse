"""
gesture_engine.py
HeadMouse — Módulo 2: Gesture Engine
Tesis UNSTA 2026 — Bloj · Domfrocht · Petrelli · Valdez

Responsabilidad:
    Recibir FaceData del Vision Engine, interpretarlo como gestos con
    significado y emitir GestureEvents que el Control Engine ejecuta.

    Detecta:
        CURSOR_MOVE  → movimiento de cabeza (nariz como joystick)
        LEFT_CLICK   → guiño ojo izquierdo
        RIGHT_CLICK  → guiño ojo derecho
        SCROLL_UP    → ceja izquierda levantada
        SCROLL_DOWN  → ceja derecha levantada
        BOTH_BROWS   → ambas cejas levantadas (gesto combinado)
        MOUTH_OPEN   → boca abierta (para combinar con otros gestos)

Uso desde Control Engine:
    ge = GestureEngine(vision_engine)
    while True:
        events = ge.update()
        for event in events:
            print(event.type, event.dx, event.dy)
"""

import json
import time
from dataclasses import dataclass, field
from typing import Optional

from vision_engine import VisionEngine, FaceData


# ══════════════════════════════════════════════════════════════════════════════
# EVENTOS
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class GestureEvent:
    """
    Evento producido por el Gesture Engine.
    El Control Engine los convierte en acciones reales del SO.
    """
    type: str          # tipo de evento (ver constantes abajo)
    dx:   float = 0.0  # desplazamiento X en píxeles (solo CURSOR_MOVE)
    dy:   float = 0.0  # desplazamiento Y en píxeles (solo CURSOR_MOVE)
    ts:   float = field(default_factory=time.time)  # timestamp

    def __repr__(self):
        if self.type == "CURSOR_MOVE":
            return f"GestureEvent(CURSOR_MOVE dx={self.dx:.1f} dy={self.dy:.1f})"
        return f"GestureEvent({self.type})"


# Tipos de eventos
EV_CURSOR_MOVE  = "CURSOR_MOVE"
EV_LEFT_CLICK   = "LEFT_CLICK"
EV_RIGHT_CLICK  = "RIGHT_CLICK"
EV_SCROLL_UP    = "SCROLL_UP"
EV_SCROLL_DOWN  = "SCROLL_DOWN"
EV_BOTH_BROWS   = "BOTH_BROWS"
EV_MOUTH_OPEN   = "MOUTH_OPEN"


# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class GestureConfig:
    """
    Parámetros de comportamiento del Gesture Engine.
    Independientes de los umbrales de calibración (que vienen del JSON).
    """
    # ── Cursor ────────────────────────────────────────────────────────────────
    sensitivity:     float = 80.0   # amplificación del movimiento (más = más rápido)
    acceleration:    float = 600.0  # componente cuadrática (da velocidad en movimientos grandes)
    dead_zone:       float = 0.06   # zona muerta alrededor del centro [0-0.5]
    smoothing_alpha: float = 0.35   # suavizado exponencial [0=instantáneo, 1=congelado]
    neutral_x:       float = 0.5    # posición neutral de la nariz en X
    neutral_y:       float = 0.5    # posición neutral de la nariz en Y

    # ── Timing de gestos ──────────────────────────────────────────────────────
    # hold_ms: el gesto debe mantenerse este tiempo antes de disparar
    # cooldown_ms: tiempo de espera antes de poder disparar de nuevo
    blink_hold_ms:    float = 60     # ms
    blink_cooldown_ms:float = 600
    brow_hold_ms:     float = 120
    brow_cooldown_ms: float = 220    # más corto: scroll es continuo
    mouth_hold_ms:    float = 150
    mouth_cooldown_ms:float = 800
    both_brows_hold_ms:    float = 180
    both_brows_cooldown_ms:float = 1000

    # ── Scroll ────────────────────────────────────────────────────────────────
    screen_w: int = 1920            # resolución de pantalla (se actualiza en runtime)
    screen_h: int = 1080


# ══════════════════════════════════════════════════════════════════════════════
# DETECTOR DE GESTO INDIVIDUAL
# ══════════════════════════════════════════════════════════════════════════════

class SingleGestureDetector:
    """
    Máquina de estados para un único gesto binario.

    Estados:
        IDLE      → esperando que el gesto supere el umbral
        HOLDING   → umbral superado, midiendo si se mantiene hold_ms
        COOLDOWN  → gesto disparado, esperando cooldown_ms antes de resetear

    El estado HOLDING evita disparos accidentales por parpadeos involuntarios.
    El estado COOLDOWN evita ráfagas de eventos repetidos.
    """

    def __init__(self, event_type: str, hold_ms: float, cooldown_ms: float):
        self.event_type  = event_type
        self.hold_ms     = hold_ms
        self.cooldown_ms = cooldown_ms

        self._state   = "IDLE"
        self._t_start = 0.0     # cuando empezó el HOLDING
        self._t_fired = 0.0     # cuando se disparó el evento

    def update(self, active: bool) -> Optional[GestureEvent]:
        """
        Actualiza el estado con el valor actual del gesto.

        Args:
            active: True si el gesto está activo (umbral superado)

        Returns:
            GestureEvent si el gesto se disparó en este ciclo, None si no.
        """
        now = time.monotonic() * 1000  # ms

        if self._state == "IDLE":
            if active:
                self._state   = "HOLDING"
                self._t_start = now

        elif self._state == "HOLDING":
            if not active:
                # El gesto no se sostuvo → cancelar
                self._state = "IDLE"
            elif now - self._t_start >= self.hold_ms:
                # Gesto sostenido el tiempo mínimo → disparar
                self._state   = "COOLDOWN"
                self._t_fired = now
                return GestureEvent(type=self.event_type)

        elif self._state == "COOLDOWN":
            # Esperar que el gesto se libere Y que pase el cooldown
            if not active and now - self._t_fired >= self.cooldown_ms:
                self._state = "IDLE"

        return None

    @property
    def state(self) -> str:
        return self._state

    def reset(self):
        self._state = "IDLE"


# ══════════════════════════════════════════════════════════════════════════════
# GESTURE ENGINE
# ══════════════════════════════════════════════════════════════════════════════

class GestureEngine:
    """
    Interpreta FaceData del Vision Engine y emite GestureEvents.

    Uso:
        ge = GestureEngine(vision_engine)
        while True:
            events = ge.update()
            for ev in events:
                handle(ev)
    """

    def __init__(self,
                 vision:             VisionEngine,
                 calibration_path:   str = "calibration.json",
                 config:             GestureConfig = None):

        self.vision  = vision
        self.config  = config or GestureConfig()
        self._thresholds = self._load_calibration(calibration_path)

        # ── Suavizado del cursor ───────────────────────────────────────────────
        self._smooth_x = self.config.neutral_x
        self._smooth_y = self.config.neutral_y

        # ── Detectores por gesto ──────────────────────────────────────────────
        c = self.config
        self._detectors = {
            "blink_left":  SingleGestureDetector(EV_LEFT_CLICK,  c.blink_hold_ms,     c.blink_cooldown_ms),
            "blink_right": SingleGestureDetector(EV_RIGHT_CLICK, c.blink_hold_ms,     c.blink_cooldown_ms),
            "brow_left":   SingleGestureDetector(EV_SCROLL_UP,   c.brow_hold_ms,      c.brow_cooldown_ms),
            "brow_right":  SingleGestureDetector(EV_SCROLL_DOWN, c.brow_hold_ms,      c.brow_cooldown_ms),
            "mouth_open":  SingleGestureDetector(EV_MOUTH_OPEN,  c.mouth_hold_ms,     c.mouth_cooldown_ms),
            "both_brows":  SingleGestureDetector(EV_BOTH_BROWS,  c.both_brows_hold_ms,c.both_brows_cooldown_ms),
        }

        # Cargar neutral de nariz desde calibración si está disponible
        try:
            with open(calibration_path, encoding="utf-8") as f:
                raw = __import__('json').load(f)
            if "neutral_nose_x" in raw:
                self.config.neutral_x = raw["neutral_nose_x"]
                self.config.neutral_y = raw["neutral_nose_y"]
                self._smooth_x = self.config.neutral_x
                self._smooth_y = self.config.neutral_y
        except Exception:
            pass

        print(f"[GestureEngine] Calibración cargada:")
        for k, v in self._thresholds.items():
            print(f"  {k:15s}: {v:.4f}")
        print(f"  neutral_x      : {self.config.neutral_x:.3f}")
        print(f"  neutral_y      : {self.config.neutral_y:.3f}")

    # ── API pública ───────────────────────────────────────────────────────────

    def update(self) -> list:
        """
        Procesa el FaceData más reciente y devuelve la lista de eventos
        ocurridos en este ciclo. Llamar una vez por frame desde el Control Engine.
        """
        fd = self.vision.get_face_data()

        if not fd.detected:
            # Sin cara: resetear suavizado al centro para evitar deriva
            self._smooth_x = self.config.neutral_x
            self._smooth_y = self.config.neutral_y
            return []

        events = []

        # 1. Cursor
        cursor_ev = self._update_cursor(fd)
        if cursor_ev:
            events.append(cursor_ev)

        # 2. Gestos binarios
        gesture_evs = self._update_gestures(fd)
        events.extend(gesture_evs)

        return events

    def update_screen_size(self, w: int, h: int):
        """Actualiza la resolución de pantalla para el cálculo de velocidad."""
        self.config.screen_w = w
        self.config.screen_h = h

    def get_detector_states(self) -> dict:
        """Devuelve el estado de cada detector (para debug/UI)."""
        return {k: d.state for k, d in self._detectors.items()}

    # ── Cursor ────────────────────────────────────────────────────────────────

    def _update_cursor(self, fd: FaceData) -> Optional[GestureEvent]:
        """
        Convierte la posición de la nariz en un desplazamiento de cursor.

        Modelo: joystick de velocidad
            - Nariz en el centro → cursor quieto
            - Nariz desviada → cursor se mueve en esa dirección
            - Más desviada = más rápido
            - La zona muerta previene deriva por micro-movimientos
        """
        alpha = self.config.smoothing_alpha

        # Suavizado exponencial de la posición de la nariz
        self._smooth_x = alpha * self._smooth_x + (1 - alpha) * fd.nose_x
        self._smooth_y = alpha * self._smooth_y + (1 - alpha) * fd.nose_y

        # Desviación desde el centro neutral
        dx = self._smooth_x - self.config.neutral_x
        dy = self._smooth_y - self.config.neutral_y

        # Aplicar zona muerta
        dz = self.config.dead_zone
        dx = 0.0 if abs(dx) < dz else (dx - dz * (1 if dx > 0 else -1))
        dy = 0.0 if abs(dy) < dz else (dy - dz * (1 if dy > 0 else -1))

        if dx == 0.0 and dy == 0.0:
            return None

        # Curva de aceleración: lineal + cuadrática
        # Movimiento pequeño → lento (precisión)
        # Movimiento grande  → rápido (navegación)
        #
        # dx=0.03 → px = 0.03*80 + 0.03²*600 = 2.4 + 0.5 =  2.9 px/frame
        # dx=0.10 → px = 0.10*80 + 0.10²*600 = 8.0 + 6.0 = 14.0 px/frame
        # dx=0.20 → px = 0.20*80 + 0.20²*600 = 16 + 24.0 = 40.0 px/frame
        s   = self.config.sensitivity
        acc = self.config.acceleration

        px = dx * s + (dx * abs(dx)) * acc
        py = dy * s + (dy * abs(dy)) * acc

        return GestureEvent(type=EV_CURSOR_MOVE, dx=px, dy=py)

    # ── Gestos binarios ───────────────────────────────────────────────────────

    def _update_gestures(self, fd: FaceData) -> list:
        t = self._thresholds

        # ── Activaciones actuales ─────────────────────────────────────────────
        brow_l_active = fd.brow_left_lift  > t["brow_left"]
        brow_r_active = fd.brow_right_lift > t["brow_right"]
        both_brows    = brow_l_active and brow_r_active

        active = {
            "blink_left":  fd.eye_left_ratio  < t["blink_left"],
            "blink_right": fd.eye_right_ratio < t["blink_right"],
            # Si ambas cejas están levantadas, suprimir las individuales
            # para evitar SCROLL_UP + SCROLL_DOWN simultáneos
            "brow_left":   brow_l_active and not both_brows,
            "brow_right":  brow_r_active and not both_brows,
            "mouth_open":  fd.mouth_open      > t["mouth_open"],
            "both_brows":  both_brows,
        }

        events = []
        for gesture_id, is_active in active.items():
            ev = self._detectors[gesture_id].update(is_active)
            if ev:
                events.append(ev)

        return events

    # ── Calibración ───────────────────────────────────────────────────────────

    @staticmethod
    def _load_calibration(path: str) -> dict:
        """Carga los umbrales desde calibration.json."""
        try:
            with open(path, encoding="utf-8") as f:
                cal = json.load(f)
            return cal["thresholds"]
        except FileNotFoundError:
            print(f"[GestureEngine] ADVERTENCIA: '{path}' no encontrado.")
            print("  Corré primero: python calibrate.py")
            print("  Usando umbrales genéricos de fallback.")
            return {
                "blink_left":  0.045,
                "blink_right": 0.045,
                "brow_left":   0.290,
                "brow_right":  0.290,
                "mouth_open":  0.180,
            }
        except (KeyError, json.JSONDecodeError) as e:
            raise ValueError(f"[GestureEngine] Error en calibration.json: {e}")
