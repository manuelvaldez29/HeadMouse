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

from __future__ import annotations

import logging
from copy import deepcopy
import time
from dataclasses import dataclass, field
from typing import Optional

from typing import TYPE_CHECKING
from face_data import FaceData
from config import GestureConfig, DEFAULT_THRESHOLDS
from profiles import load_legacy, validate_profile
from tracking import NoseTrackingStrategy
from action_mapping import LEGACY_GESTURES

if TYPE_CHECKING:
    from vision_engine import VisionEngine

logger = logging.getLogger(__name__)


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
    ts:   float = field(default_factory=time.monotonic)  # timestamp
    source_timestamp_ms: int = 0
    detected_at: float = 0.0
    gesture: str = ""  # identidad independiente de la acción, sin romper type legacy

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

    def __init__(self, event_type: str, hold_ms: float, cooldown_ms: float, clock=time.monotonic):
        self._clock = clock
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
        now = self._clock() * 1000  # ms

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
                 config:             GestureConfig = None,
                 calibration=None, strategy=None, clock=time.monotonic):

        self.vision  = vision
        self.config = deepcopy(config or GestureConfig())
        self.config.__post_init__()
        self._clock = clock
        self.strategy = strategy or NoseTrackingStrategy()
        self._last_timestamp = 0
        if calibration is None:
            try:
                calibration = load_legacy(calibration_path)
            except FileNotFoundError:
                logger.warning("Sin calibración: umbrales genéricos; calibrar antes de usar")
                calibration = {"thresholds": DEFAULT_THRESHOLDS.copy()}
        validate_profile(calibration)
        if calibration.get("status") == "draft":
            raise ValueError("El perfil aún no está calibrado")
        self._thresholds = calibration["thresholds"].copy()
        self.config.neutral_x = calibration.get("neutral_nose_x", self.config.neutral_x)
        self.config.neutral_y = calibration.get("neutral_nose_y", self.config.neutral_y)

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

        for detector in self._detectors.values():
            detector._clock = clock
        logger.debug("Thresholds: %s", self._thresholds)

    # ── API pública ───────────────────────────────────────────────────────────

    def update(self, fd=None) -> list:
        """
        Procesa el FaceData más reciente y devuelve la lista de eventos
        ocurridos en este ciclo. Llamar una vez por frame desde el Control Engine.
        """
        fd = self.vision.get_face_data() if fd is None else fd

        if not fd.fresh(self.config.stale_after_s, self._clock()):
            # Sin cara: resetear suavizado al centro para evitar deriva
            self.reset()
            return []

        if fd.timestamp_ms <= self._last_timestamp:
            return []
        if self._last_timestamp and fd.timestamp_ms - self._last_timestamp > self.config.stale_after_s * 1000:
            self.reset()  # Una pausa del consumidor tampoco debe completar un hold.
        self._last_timestamp = fd.timestamp_ms

        events = []

        # 1. Cursor
        cursor_ev = self._update_cursor(fd)
        if cursor_ev:
            events.append(cursor_ev)

        # 2. Gestos binarios
        gesture_evs = self._update_gestures(fd)
        events.extend(gesture_evs)

        for event in events:
            event.source_timestamp_ms = fd.timestamp_ms
            event.detected_at = fd.detected_at
            event.gesture = LEGACY_GESTURES.get(event.type, event.type)
        return events

    def diagnostic(self):
        return dict(smooth_x=self._smooth_x, smooth_y=self._smooth_y,
                    normalized_dx=self._smooth_x - self.config.neutral_x,
                    normalized_dy=self._smooth_y - self.config.neutral_y,
                    thresholds=self._thresholds.copy(), states=self.get_detector_states())

    def reset(self):
        self._smooth_x = self.config.neutral_x
        self._smooth_y = self.config.neutral_y
        for detector in self._detectors.values():
            detector.reset()

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

        x, y = self.strategy.position(fd)

        # Suavizado exponencial de la posición de la nariz
        self._smooth_x = alpha * self._smooth_x + (1 - alpha) * x
        self._smooth_y = alpha * self._smooth_y + (1 - alpha) * y

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

        sx = s if self.config.sensitivity_x is None else self.config.sensitivity_x
        sy = s if self.config.sensitivity_y is None else self.config.sensitivity_y
        px = dx * sx + (dx * abs(dx)) * acc
        py = dy * sy + (dy * abs(dy)) * acc

        return GestureEvent(type=EV_CURSOR_MOVE, dx=px, dy=py)

    # ── Gestos binarios ───────────────────────────────────────────────────────

    def _update_gestures(self, fd: FaceData) -> list:
        t = self._thresholds

        # ── Activaciones actuales ─────────────────────────────────────────────
        brow_l_active = fd.brow_left_lift  > t["brow_left"]
        brow_r_active = fd.brow_right_lift > t["brow_right"]
        both_brows    = brow_l_active and brow_r_active

        both_eyes = (fd.eye_left_ratio < t["blink_left"] and
                     fd.eye_right_ratio < t["blink_right"])
        active = {
            "blink_left":  fd.eye_left_ratio  < t["blink_left"] and not both_eyes,
            "blink_right": fd.eye_right_ratio < t["blink_right"] and not both_eyes,
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
        try:
            return load_legacy(path)["thresholds"]
        except FileNotFoundError:
            logger.warning("Calibración ausente: %s", path)
            return DEFAULT_THRESHOLDS.copy()
