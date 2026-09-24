"""
control_engine.py
HeadMouse — Módulo 3: Control Engine
Tesis UNSTA 2026 — Bloj · Domfrocht · Petrelli · Valdez

Responsabilidad:
    Recibir GestureEvents del Gesture Engine y ejecutar las acciones
    reales correspondientes en Windows mediante pyautogui.

    Mapa de eventos → acciones:
        CURSOR_MOVE  → mover cursor (moveRel)
        LEFT_CLICK   → click izquierdo
        RIGHT_CLICK  → click derecho
        SCROLL_UP    → scroll arriba
        SCROLL_DOWN  → scroll abajo
        BOTH_BROWS   → pausar / reanudar el control
        MOUTH_OPEN   → tecla Win (abrir menú inicio)

    Comportamiento de seguridad:
        - Auto-pausa si la cara desaparece más de 2 segundos
        - pyautogui failsafe activo: mover cursor a esquina sup-izq detiene todo
        - Modo pausa: cursor sigue visible en pantalla pero no responde a gestos

Uso:
    ce = ControlEngine(vision_engine, gesture_engine)
    ce.start()
    # ... corre en background hasta ce.stop()
"""

from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass

from config import ControlConfig
from action_mapping import ActionMapping
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from vision_engine import VisionEngine

logger = logging.getLogger(__name__)

from gesture_engine import GestureEngine, GestureEvent
from gesture_engine import (EV_CURSOR_MOVE, EV_LEFT_CLICK, EV_RIGHT_CLICK,
                             EV_SCROLL_UP, EV_SCROLL_DOWN,
                             EV_BOTH_BROWS, EV_MOUTH_OPEN)


# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN DE PYAUTOGUI
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ControlStats:
    running:          bool  = False
    paused:           bool  = False
    face_detected:    bool  = False
    fps:              float = 0.0
    last_event:       str   = "—"
    events_total:     int   = 0
    clicks_total:     int   = 0
    scrolls_total:    int   = 0


# ══════════════════════════════════════════════════════════════════════════════
# CONTROL ENGINE
# ══════════════════════════════════════════════════════════════════════════════

class ControlEngine:
    """
    Loop principal de control. Corre en un hilo daemon.

    Ciclo por frame (~60 Hz):
        1. gesture_engine.update() → lista de eventos
        2. Verificar timeout de cara
        3. Ejecutar eventos (si no está pausado)
        4. Actualizar estadísticas
    """

    def __init__(self,
                 vision:  VisionEngine,
                 gesture: GestureEngine,
                 config:  ControlConfig = None, backend=None, metrics=None, mapping=None):

        self.vision  = vision
        self.gesture = gesture
        self.config  = config or ControlConfig()
        self.config.__post_init__()
        if backend is None:
            import pyautogui
            backend = pyautogui
        self.backend = backend
        self.backend.PAUSE = 0
        self.backend.FAILSAFE = True
        self.metrics = metrics
        self.mapping = mapping or ActionMapping()
        self.last_events = ()
        self.last_actions = ()
        self.output_allowed = threading.Event()
        self.output_allowed.set()  # CLI legacy; GUI no construye este motor sin autorización
        self.error = None
        self._stop_requested = threading.Event()

        # Resolución de pantalla
        self._screen_w, self._screen_h = self.backend.size()
        self.gesture.update_screen_size(self._screen_w, self._screen_h)
        logger.info(f"[ControlEngine] Pantalla: {self._screen_w}×{self._screen_h}")

        # Estado
        self._paused        = True    # arranca pausado — activar con BOTH_BROWS
        self._running       = False
        self._face_last_ok  = time.monotonic()
        self._auto_paused   = False   # pausa automática por timeout de cara

        # Estadísticas
        self._stats      = ControlStats()
        self._stats_lock = threading.Lock()

        # Hilo
        self._thread = threading.Thread(
            target=self._loop,
            name="ControlEngine",
            daemon=True,
        )

    # ── API pública ───────────────────────────────────────────────────────────

    def start(self):
        """Arranca el loop de control en background."""
        self._running = True
        self._thread.start()
        logger.info("[ControlEngine] Iniciado. BOTH_BROWS = pausar/reanudar.")
        logger.info("  Failsafe: mover cursor a esquina superior izquierda detiene todo.")

    def stop(self):
        """Detiene el loop de control."""
        self._running = False
        self.output_allowed.clear()
        self._stop_requested.set()
        if self._thread.ident is not None:
            self._thread.join(timeout=2.0)
            if self._thread.is_alive():
                raise RuntimeError("ControlEngine no respondió al cierre")
        logger.info("[ControlEngine] Detenido.")

    def toggle_pause(self):
        """Pausa o reanuda el control manualmente."""
        self._paused = not self._paused
        state = "PAUSADO" if self._paused else "ACTIVO"
        logger.info(f"[ControlEngine] Control {state}.")

    def get_stats(self) -> ControlStats:
        """Devuelve un snapshot de las estadísticas actuales. Thread-safe."""
        with self._stats_lock:
            s = ControlStats(
                running       = self._running,
                paused        = self._paused or self._auto_paused,
                face_detected = self._stats.face_detected,
                fps           = self._stats.fps,
                last_event    = self._stats.last_event,
                events_total  = self._stats.events_total,
                clicks_total  = self._stats.clicks_total,
                scrolls_total = self._stats.scrolls_total,
            )
        return s

    @property
    def paused(self) -> bool:
        return self._paused or self._auto_paused

    # ── Loop principal ────────────────────────────────────────────────────────

    def _loop(self):
        interval = 1.0 / self.config.loop_hz

        while self._running:
            t0 = time.perf_counter()

            try:
                self._tick()
            except self.backend.FailSafeException:
                logger.info("\n[ControlEngine] Failsafe activado — deteniendo.")
                self._running = False
                break
            except Exception as e:
                self.error = e
                logger.exception("ControlEngine detenido por error")
                self._running = False
                break

            # Mantener frecuencia objetivo
            elapsed = time.perf_counter() - t0
            sleep   = max(0.0, interval - elapsed)
            self._stop_requested.wait(sleep)

    def _tick(self):
        """Un ciclo del loop de control."""
        now    = time.monotonic()
        fd = self.vision.get_face_data()
        fresh = fd.fresh(self.gesture.config.stale_after_s, now)
        events = self.gesture.update(fd)
        self.last_events = tuple(events)
        self.last_actions = ()
        if self.metrics:
            self.metrics.tracking(fresh)
            self.metrics.generated(events)

        # ── Timeout de cara ───────────────────────────────────────────────────
        if fresh:
            self._face_last_ok  = now
            self._auto_paused   = False
        else:
            if now - self._face_last_ok > self.config.face_timeout_s:
                if not self._auto_paused:
                    self._auto_paused = True
                    logger.info("[ControlEngine] Sin cara — control auto-pausado.")

        # ── Ejecutar eventos ──────────────────────────────────────────────────
        # Toggle tiene prioridad sobre todas las acciones del mismo frame.
        actions = [self.mapping.resolve(ev) for ev in events]
        toggle = next((ev for ev in actions if ev.type == "PAUSE"), None)
        if toggle is not None and fresh and self.output_allowed.is_set():
            self.toggle_pause()
            self._log_event(EV_BOTH_BROWS)
            if self.metrics:
                self.metrics.action(toggle)
            self.last_actions = (toggle,)
        elif fresh and not self.paused and self.output_allowed.is_set():
            for ev in actions:
                if not self.output_allowed.is_set():
                    break
                self._execute(ev)
                if ev.type != "NONE":
                    self.last_actions += (ev,)

        # ── Estadísticas ──────────────────────────────────────────────────────
        with self._stats_lock:
            self._stats.face_detected = fresh
            self._stats.fps           = self.vision.get_fps()

    # ── Ejecución de acciones ─────────────────────────────────────────────────

    def _execute(self, ev: GestureEvent):
        """Convierte un GestureEvent en una acción real de Windows."""

        if not math.isfinite(ev.dx) or not math.isfinite(ev.dy):
            raise ValueError("Delta no finito")

        if ev.type == EV_CURSOR_MOVE:
            # Limitar delta máximo para evitar saltos bruscos
            dx = max(-self.config.max_cursor_delta,
                     min(self.config.max_cursor_delta, ev.dx))
            dy = max(-self.config.max_cursor_delta,
                     min(self.config.max_cursor_delta, ev.dy))
            if int(dx) != 0 or int(dy) != 0:
                self.backend.moveRel(int(dx), int(dy), _pause=False)
                if self.metrics:
                    self.metrics.action(ev)
            return   # no loguear CURSOR_MOVE para no spamear

        elif ev.type == EV_LEFT_CLICK:
            self.backend.click(_pause=False)
            self._log_event("LEFT_CLICK", clicks=True)

        elif ev.type == EV_RIGHT_CLICK:
            self.backend.rightClick(_pause=False)
            self._log_event("RIGHT_CLICK", clicks=True)

        elif ev.type == EV_SCROLL_UP:
            self.backend.scroll(self.config.scroll_lines, _pause=False)
            self._log_event("SCROLL_UP", scrolls=True)

        elif ev.type == EV_SCROLL_DOWN:
            self.backend.scroll(-self.config.scroll_lines, _pause=False)
            self._log_event("SCROLL_DOWN", scrolls=True)

        elif ev.type in (EV_MOUTH_OPEN, "OPEN_START_MENU"):
            self.backend.hotkey("win", _pause=False)
            self._log_event("MOUTH_OPEN (Win)")

        elif ev.type == "DOUBLE_CLICK":
            self.backend.doubleClick(interval=0.1, _pause=False)
            self._log_event("DOUBLE_CLICK", clicks=True)
        elif ev.type in ("KEY_ENTER", "KEY_ESCAPE", "KEY_SPACE"):
            self.backend.press({"KEY_ENTER": "enter", "KEY_ESCAPE": "esc", "KEY_SPACE": "space"}[ev.type], _pause=False)
            self._log_event(ev.type)
        elif ev.type == "NONE":
            return

        else:
            raise ValueError(f"Evento desconocido: {ev.type}")
        if self.metrics:
            self.metrics.action(ev)

    def _log_event(self, name: str,
                   clicks: bool = False, scrolls: bool = False):
        logger.info(f"  [{time.strftime('%H:%M:%S')}] {name}")
        with self._stats_lock:
            self._stats.last_event  = name
            self._stats.events_total += 1
            if clicks:  self._stats.clicks_total  += 1
            if scrolls: self._stats.scrolls_total += 1
