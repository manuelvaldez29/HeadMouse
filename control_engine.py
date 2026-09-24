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

import threading
import time
from dataclasses import dataclass
from typing import Optional

import pyautogui

from vision_engine  import VisionEngine
from gesture_engine import GestureEngine, GestureEvent
from gesture_engine import (EV_CURSOR_MOVE, EV_LEFT_CLICK, EV_RIGHT_CLICK,
                             EV_SCROLL_UP, EV_SCROLL_DOWN,
                             EV_BOTH_BROWS, EV_MOUTH_OPEN)


# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN DE PYAUTOGUI
# ══════════════════════════════════════════════════════════════════════════════

pyautogui.PAUSE    = 0        # sin delay entre llamadas (default = 0.1s → laggy)
pyautogui.FAILSAFE = True     # mover cursor a esquina sup-izq detiene el programa


# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN DEL CONTROL ENGINE
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ControlConfig:
    scroll_lines:     int   = 3      # líneas por evento de scroll
    face_timeout_s:   float = 2.0    # segundos sin cara → auto-pausa
    max_cursor_delta: float = 60.0   # píxeles máximos por frame (anti-spike)
    loop_hz:          float = 60.0   # frecuencia del loop de control


# ══════════════════════════════════════════════════════════════════════════════
# ESTADÍSTICAS EN TIEMPO REAL
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
                 config:  ControlConfig = None):

        self.vision  = vision
        self.gesture = gesture
        self.config  = config or ControlConfig()

        # Resolución de pantalla
        self._screen_w, self._screen_h = pyautogui.size()
        self.gesture.update_screen_size(self._screen_w, self._screen_h)
        print(f"[ControlEngine] Pantalla: {self._screen_w}×{self._screen_h}")

        # Estado
        self._paused        = True    # arranca pausado — activar con BOTH_BROWS
        self._running       = False
        self._face_last_ok  = time.monotonic()
        self._auto_paused   = False   # pausa automática por timeout de cara

        # Estadísticas
        self._stats      = ControlStats()
        self._stats_lock = threading.Lock()
        self._fps_times  = []

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
        print("[ControlEngine] Iniciado. BOTH_BROWS = pausar/reanudar.")
        print("  Failsafe: mover cursor a esquina superior izquierda detiene todo.")

    def stop(self):
        """Detiene el loop de control."""
        self._running = False
        self._thread.join(timeout=2.0)
        print("[ControlEngine] Detenido.")

    def toggle_pause(self):
        """Pausa o reanuda el control manualmente."""
        self._paused = not self._paused
        state = "PAUSADO" if self._paused else "ACTIVO"
        print(f"[ControlEngine] Control {state}.")

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
            except pyautogui.FailSafeException:
                if not self._paused:
                    print("\n[ControlEngine] Failsafe activado — auto-pausando por seguridad.")
                    self._paused = True
            except Exception as e:
                print(f"[ControlEngine] Error inesperado: {e}")

            # Mantener frecuencia objetivo
            elapsed = time.perf_counter() - t0
            sleep   = max(0.0, interval - elapsed)
            time.sleep(sleep)

    def _tick(self):
        """Un ciclo del loop de control."""
        now    = time.monotonic()
        events = self.gesture.update()
        fd     = self.vision.get_face_data()

        # ── Timeout de cara ───────────────────────────────────────────────────
        if fd.detected:
            self._face_last_ok  = now
            self._auto_paused   = False
        else:
            if now - self._face_last_ok > self.config.face_timeout_s:
                if not self._auto_paused:
                    self._auto_paused = True
                    print("[ControlEngine] Sin cara — control auto-pausado.")

        # ── Ejecutar eventos ──────────────────────────────────────────────────
        for ev in events:
            # BOTH_BROWS siempre funciona (incluso pausado) → toggle
            if ev.type == EV_BOTH_BROWS:
                self.toggle_pause()
                continue

            if self.paused:
                continue

            self._execute(ev)

        # ── Estadísticas ──────────────────────────────────────────────────────
        t_now = time.perf_counter()
        self._fps_times.append(t_now)
        self._fps_times = [t for t in self._fps_times if t_now - t < 1.0]

        with self._stats_lock:
            self._stats.face_detected = fd.detected
            self._stats.fps           = len(self._fps_times)

    # ── Ejecución de acciones ─────────────────────────────────────────────────

    def _execute(self, ev: GestureEvent):
        """Convierte un GestureEvent en una acción real de Windows."""

        if ev.type == EV_CURSOR_MOVE:
            # Limitar delta máximo para evitar saltos bruscos
            dx = max(-self.config.max_cursor_delta,
                     min(self.config.max_cursor_delta, ev.dx))
            dy = max(-self.config.max_cursor_delta,
                     min(self.config.max_cursor_delta, ev.dy))
            if dx != 0.0 or dy != 0.0:
                pyautogui.moveRel(int(dx), int(dy), _pause=False)
            return   # no loguear CURSOR_MOVE para no spamear

        elif ev.type == EV_LEFT_CLICK:
            pyautogui.click(_pause=False)
            self._log_event("LEFT_CLICK", clicks=True)

        elif ev.type == EV_RIGHT_CLICK:
            pyautogui.rightClick(_pause=False)
            self._log_event("RIGHT_CLICK", clicks=True)

        elif ev.type == EV_SCROLL_UP:
            pyautogui.scroll(self.config.scroll_lines, _pause=False)
            self._log_event("SCROLL_UP", scrolls=True)

        elif ev.type == EV_SCROLL_DOWN:
            pyautogui.scroll(-self.config.scroll_lines, _pause=False)
            self._log_event("SCROLL_DOWN", scrolls=True)

        elif ev.type == EV_MOUTH_OPEN:
            pyautogui.hotkey("win", _pause=False)
            self._log_event("MOUTH_OPEN (Win)")

    def _log_event(self, name: str,
                   clicks: bool = False, scrolls: bool = False):
        print(f"  [{time.strftime('%H:%M:%S')}] {name}")
        with self._stats_lock:
            self._stats.last_event  = name
            self._stats.events_total += 1
            if clicks:  self._stats.clicks_total  += 1
            if scrolls: self._stats.scrolls_total += 1
