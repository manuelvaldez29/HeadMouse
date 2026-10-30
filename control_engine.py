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
import sys
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
                 config:  ControlConfig = None, backend=None, metrics=None, mapping=None,
                 wheel_unit=None, dictation=None, screen_bounds=None, movement_only=False,
                 clock=None):

        self.vision  = vision
        self.gesture = gesture
        self.config  = config or ControlConfig()
        self.config.__post_init__()
        self._clock = clock if callable(clock) else (lambda: time.monotonic())
        if backend is None:
            import pyautogui
            backend = pyautogui
        self.backend = backend
        self.screen_bounds = tuple(screen_bounds) if screen_bounds is not None else None
        self.movement_only = movement_only
        # PyAutoGUI en Windows pasa el valor directo a mouse_event: una muesca de
        # rueda son 120 unidades (WHEEL_DELTA). Sin escalar, scroll(3) movía 3/120
        # de muesca. En macOS/Linux PyAutoGUI ya cuenta muescas.
        self.wheel_unit = wheel_unit if wheel_unit is not None else (120 if sys.platform == "win32" else 1)
        self.backend.PAUSE = 0
        self.backend.FAILSAFE = True
        self.metrics = metrics
        self.mapping = mapping or ActionMapping()
        self.dictation = dictation  # opcional: dictation.Dictation
        self.last_recenter = None   # resultado del último recentrado, para la GUI
        self._pinned_since = None   # cursor apretado contra un borde (centro mal ubicado)
        self._paused_at_ms = None   # cuándo se pausó con ambas cejas: el recentrado mira desde ahí
        self._pinned_retry = 0.
        self._last_cursor = None
        self._fraction = [0., 0.]
        self._fraction_frame = 0
        self._pending_click = None  # guiño corto (click al soltar) vs guiño largo (enganchar arrastre)
        self._dragging = False
        self._drag_gesture = ""
        self._drag_release_armed = False
        self._drag_open_since = None
        self.last_events = ()
        self.last_actions = ()
        self.output_allowed = threading.Event()
        self.output_allowed.set()  # CLI legacy; GUI no construye este motor sin autorización
        self.error = None
        self._stop_requested = threading.Event()

        # Resolución de pantalla
        self._screen_w, self._screen_h = self.backend.size()
        if self.screen_bounds is not None:
            from screen_mapping import physical_coordinates
            ox,oy,width,height = self.screen_bounds
            with physical_coordinates():
                self._screen_w, self._screen_h = self.backend.size()
                x,y = self.backend.position()
            if (width,height) != (self._screen_w,self._screen_h):
                raise ValueError("La resolución física del backend no coincide con el monitor principal. Revisá DPI/escalado.")
            if not (ox <= x < ox+width and oy <= y < oy+height):
                raise ValueError("Llevá el cursor al monitor principal antes de activar el control ocular.")
        self.gesture.update_screen_size(self._screen_w, self._screen_h)
        logger.info(f"[ControlEngine] Pantalla: {self._screen_w}×{self._screen_h}")

        # Estado
        self._paused        = True    # arranca pausado — activar con BOTH_BROWS
        self._running       = False
        self._face_last_ok  = self._clock()
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
        self._release_held_mouse()
        logger.info("[ControlEngine] Detenido.")

    def toggle_pause(self):
        """Pausa o reanuda el control manualmente."""
        self._paused = not self._paused
        self._fraction = [0., 0.]
        if self._paused:
            self._release_held_mouse()
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

    @property
    def dragging(self) -> bool:
        return self._dragging

    def _is_gesture_held(self, key: str) -> bool:
        checker = getattr(self.gesture, "is_gesture_held", None)
        return bool(key and callable(checker) and checker(key))

    def _is_gesture_active(self, key: str) -> bool:
        checker = getattr(self.gesture, "is_gesture_active", None)
        if callable(checker):
            return bool(key and checker(key))
        return self._is_gesture_held(key)

    def _can_hold_click(self, ev: GestureEvent) -> bool:
        return bool(self.config.hold_click_enabled
                    and getattr(getattr(self.gesture, "strategy", None), "name", None) == "nose"
                    and self._is_gesture_held(ev.gesture))

    def _start_drag(self, ev: GestureEvent):
        self.backend.mouseDown(button="left", _pause=False)
        self._dragging = True
        self._drag_gesture = ev.gesture
        self._drag_release_armed = not self._is_gesture_held(ev.gesture)
        self._drag_open_since = None
        self._log_event("LEFT_DRAG_START", clicks=True)
        if self.metrics:
            self.metrics.action(ev)
        self.last_actions += (GestureEvent("LEFT_DRAG_START", gesture=ev.gesture),)

    def _release_held_mouse(self) -> bool:
        """Suelta de forma idempotente cualquier click pendiente o botón izquierdo enganchado."""
        self._pending_click = None
        if not self._dragging:
            return False
        gesture_key = self._drag_gesture
        self._dragging = False
        self._drag_gesture = ""
        self._drag_release_armed = False
        self._drag_open_since = None
        try:
            self.backend.mouseUp(button="left", _pause=False)
            self._log_event("LEFT_DRAG_END")
            return bool(gesture_key or True)
        except Exception:
            logger.exception("[ControlEngine] No se pudo liberar click sostenido")
            return False

    def _update_hold_click(self, now: float):
        if self._pending_click is not None:
            pending = self._pending_click
            if not self._is_gesture_held(pending["gesture"]):
                self._pending_click = None
                ev = pending["event"]
                self._execute(ev)
                self.last_actions += (ev,)
            elif (now - pending["started_at"]) * 1000.0 + 1e-6 >= self.config.drag_hold_ms:
                self._pending_click = None
                self._start_drag(pending["event"])
            return
        if self._dragging and not self._drag_release_armed:
            if self._is_gesture_held(self._drag_gesture):
                self._drag_open_since = None
            else:
                if self._drag_open_since is None:
                    self._drag_open_since = now
                if (now - self._drag_open_since) * 1000.0 + 1e-6 >= self.config.drag_release_ms:
                    self._drag_release_armed = True
                    self._drag_open_since = None
                    rearm = getattr(self.gesture, "rearm_gesture", None)
                    if callable(rearm):
                        rearm(self._drag_gesture)

    # ── Loop principal ────────────────────────────────────────────────────────

    def _loop(self):
        interval = 1.0 / self.config.loop_hz

        try:
            while self._running:
                t0 = time.perf_counter()

                try:
                    self._tick()
                except self.backend.FailSafeException:
                    logger.info("\n[ControlEngine] Failsafe activado — deteniendo.")
                    self._running = False
                    self.output_allowed.clear()
                    break
                except Exception as e:
                    self.error = e
                    logger.exception("ControlEngine detenido por error")
                    self._running = False
                    self.output_allowed.clear()
                    break

                # Mantener frecuencia objetivo
                elapsed = time.perf_counter() - t0
                sleep   = max(0.0, interval - elapsed)
                self._stop_requested.wait(sleep)
        finally:
            self._release_held_mouse()

    def _tick(self):
        """Un ciclo del loop de control."""
        now    = self._clock()
        fd = self.vision.get_face_data()
        fresh = fd.fresh(self.gesture.config.stale_after_s, now)
        self.gesture.both_brows_anywhere = self.paused
        events = self.gesture.update(fd)
        self.last_events = tuple(events)
        self.last_actions = ()
        new_frame = fd.timestamp_ms != self._fraction_frame
        if not fresh or self.paused or (new_frame and not any(e.type == EV_CURSOR_MOVE for e in events)):
            self._fraction = [0., 0.]
        self._fraction_frame = fd.timestamp_ms
        if self.metrics:
            self.metrics.tracking(fresh)
            self.metrics.generated(events)

        if not fresh or not self.output_allowed.is_set():
            self._release_held_mouse()

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
        if self.movement_only:
            actions = [ev for ev in actions if ev.type in (EV_CURSOR_MOVE,"CURSOR_ABSOLUTE")]
        if self.dictation is not None and self.dictation.busy:
            self._release_held_mouse()
            # Hablar mueve boca, ojos y cejas: mientras se dicta solo se mueve el
            # cursor, y el gesto de pausa cancela el dictado en lugar de pausar.
            if any(ev.type == "PAUSE" for ev in actions):
                self.dictation.cancel()
            actions = [ev for ev in actions if ev.type in (EV_CURSOR_MOVE, "CURSOR_ABSOLUTE")]
        toggle = next((ev for ev in actions if ev.type == "PAUSE"), None)
        if toggle is not None and fresh and self.output_allowed.is_set():
            resuming = self._paused
            self.toggle_pause()
            if not resuming:
                self._paused_at_ms = toggle.source_timestamp_ms
            elif getattr(self.gesture.config, "auto_recenter", False) and hasattr(self.gesture, "recenter"):
                # Excluir el propio gesto: decisión de cejas + hold de ambas cejas + margen.
                # Después de una pausa, el centro es la postura en la que te acomodaste
                # durante la pausa: con medio segundo quieto alcanza.
                c = self.gesture.config
                since = self._paused_at_ms
                if since is None:  # primera reanudación: arranca en pausa, sin pausa previa
                    self.last_recenter = self.gesture.recenter(
                        toggle.source_timestamp_ms, guard_ms=c.brow_decision_ms + c.both_brows_hold_ms + 250,
                        since_ms=None)
                else:
                    # Los cuadros con las cejas arriba ya se excluyen; el margen cubre la subida.
                    self.last_recenter = self.gesture.recenter(
                        toggle.source_timestamp_ms, guard_ms=c.both_brows_hold_ms + 250, since_ms=since,
                        window_ms=600, search_ms=10000, min_samples=8)
                logger.info("[ControlEngine] Recentrado: %s", self.last_recenter)
            self._log_event(EV_BOTH_BROWS)
            if self.metrics:
                self.metrics.action(toggle)
            self.last_actions = (toggle,)
        elif fresh and not self.paused and self.output_allowed.is_set():
            self._update_hold_click(now)
            releasing_wink = (self._dragging and self._drag_release_armed
                              and self._is_gesture_active(self._drag_gesture))
            for ev in actions:
                if not self.output_allowed.is_set():
                    break
                if ev.type == EV_CURSOR_MOVE and (self._pending_click is not None or releasing_wink):
                    continue  # anclar puntero durante guiño antes de click, enganchar o soltar arrastre
                if ev.type == EV_LEFT_CLICK:
                    if self._dragging:
                        if self._drag_release_armed or ev.gesture != self._drag_gesture:
                            gesture_key = self._drag_gesture or ev.gesture
                            if self._release_held_mouse():
                                self.last_actions += (GestureEvent("LEFT_DRAG_END", gesture=gesture_key),)
                        continue
                    if self._pending_click is not None:
                        continue
                    if self._can_hold_click(ev):
                        started_fn = getattr(self.gesture, "gesture_started_at", None)
                        started_at = started_fn(ev.gesture) if callable(started_fn) else None
                        if started_at is None:
                            hold_offset_s = getattr(getattr(self.gesture, "config", None), "blink_hold_ms", 60.0) / 1000.0
                            started_at = now - hold_offset_s
                        if (now - started_at) * 1000.0 + 1e-6 >= self.config.drag_hold_ms:
                            self._start_drag(ev)
                        else:
                            self._pending_click = dict(event=ev, gesture=ev.gesture, started_at=started_at)
                        continue
                self._execute(ev)
                if ev.type != "NONE":
                    self.last_actions += (ev,)
            if not self._dragging and self._pending_click is None:
                self._check_pinned(actions, fd, now)

        # ── Estadísticas ──────────────────────────────────────────────────────
        with self._stats_lock:
            self._stats.face_detected = fresh
            self._stats.fps           = self.vision.get_fps()

    PINNED_S = 2.0

    def _check_pinned(self, actions, fd, now):
        """Recentrar solo si el cursor lleva PINNED_S apretado contra un borde.

        Con la cabeza quieta y el cursor empujando contra el borde de la pantalla,
        el centro está mal ubicado (cámara movida): nadie empuja el cursor contra
        la pared a propósito. Evita también llegar a una esquina (failsafe).
        """
        if not getattr(self.gesture.config, "auto_recenter", False) or not hasattr(self.gesture, "recenter"):
            return
        move = next((ev for ev in actions if ev.type == EV_CURSOR_MOVE and (int(ev.dx) or int(ev.dy))), None)
        if move is None:
            return  # sin frame nuevo o cursor quieto: no cambia el estado
        try:
            position = tuple(self.backend.position())
        except Exception:
            return
        pinned = position == self._last_cursor
        self._last_cursor = position
        if not pinned:
            self._pinned_since = None
            return
        if self._pinned_since is None:
            self._pinned_since = now
        if now - self._pinned_since >= self.PINNED_S and now >= self._pinned_retry:
            result = self.gesture.recenter(fd.timestamp_ms, guard_ms=0, search_ms=1000)
            if result.get("ok"):
                result = dict(result, pinned=True)
                self.last_recenter = result
                self._pinned_since = None
                logger.info("[ControlEngine] Recentrado por cursor trabado en el borde: %s", result)
            else:
                self._pinned_retry = now + 1.0  # cabeza en movimiento: volver a probar en 1 s

    # ── Ejecución de acciones ─────────────────────────────────────────────────

    def _execute(self, ev: GestureEvent):
        if self.movement_only and ev.type not in (EV_CURSOR_MOVE,"CURSOR_ABSOLUTE"):
            return
        if self.screen_bounds is not None:
            from screen_mapping import physical_coordinates
            with physical_coordinates():
                return self._execute_event(ev)
        return self._execute_event(ev)

    def _execute_event(self, ev: GestureEvent):
        """Convierte un GestureEvent en una acción real de Windows."""

        if not math.isfinite(ev.dx) or not math.isfinite(ev.dy):
            raise ValueError("Delta no finito")

        if ev.type == "CURSOR_ABSOLUTE":
            if not 0 <= ev.dx <= 1 or not 0 <= ev.dy <= 1:
                raise ValueError("Predicción fuera de pantalla")
            x, y = self.backend.position()
            ox, oy, width, height = self.screen_bounds or (0,0,self._screen_w,self._screen_h)
            if not (ox <= x < ox+width and oy <= y < oy+height):
                raise ValueError("El cursor salió del monitor principal. Detené el control, llevá el cursor al principal y volvé a activar.")
            tx, ty = ox+ev.dx*(width-1), oy+ev.dy*(height-1)
            limit = min(self.config.max_cursor_delta, self.gesture.strategy.config.max_step_px)
            distance = math.hypot(tx-x, ty-y)
            scale = min(1., limit/distance) if distance else 1.
            if distance >= self.gesture.strategy.config.jitter_px:
                self.backend.moveTo(round(max(ox, min(ox+width-1, x+(tx-x)*scale))),
                                    round(max(oy, min(oy+height-1, y+(ty-y)*scale))), _pause=False)
                if self.metrics:
                    self.metrics.action(ev)
            return

        if ev.type == EV_CURSOR_MOVE:
            # Limitar delta máximo para evitar saltos bruscos
            dx = max(-self.config.max_cursor_delta,
                     min(self.config.max_cursor_delta, ev.dx))
            dy = max(-self.config.max_cursor_delta,
                     min(self.config.max_cursor_delta, ev.dy))
            if getattr(self.gesture.strategy, "name", None) == "eye":
                # Sumar únicamente deltas nuevos; nunca integrar la posición del EMA.
                dx, dy = dx+self._fraction[0], dy+self._fraction[1]
                ix, iy = math.trunc(dx), math.trunc(dy)
                self._fraction = [dx-ix, dy-iy]
            else:
                ix, iy = int(dx), int(dy)  # conservar la fórmula nasal histórica
            if ix != 0 or iy != 0:
                self.backend.moveRel(ix, iy, _pause=False)
                if self.metrics:
                    self.metrics.action(ev)
            return   # no loguear CURSOR_MOVE para no spamear

        elif ev.type == EV_LEFT_CLICK:
            self.backend.click(_pause=False)
            self._log_event("LEFT_CLICK", clicks=True)
            if self.dictation is not None:
                self.dictation.on_click()

        elif ev.type == EV_RIGHT_CLICK:
            self.backend.rightClick(_pause=False)
            self._log_event("RIGHT_CLICK", clicks=True)

        elif ev.type == EV_SCROLL_UP:
            self.backend.scroll(self.config.scroll_lines * self.wheel_unit, _pause=False)
            self._log_event("SCROLL_UP", scrolls=True)

        elif ev.type == EV_SCROLL_DOWN:
            self.backend.scroll(-self.config.scroll_lines * self.wheel_unit, _pause=False)
            self._log_event("SCROLL_DOWN", scrolls=True)

        elif ev.type in (EV_MOUTH_OPEN, "OPEN_START_MENU"):
            self.backend.hotkey("win", _pause=False)
            self._log_event("MOUTH_OPEN (Win)")

        elif ev.type == "DOUBLE_CLICK":
            self.backend.doubleClick(interval=0.1, _pause=False)
            self._log_event("DOUBLE_CLICK", clicks=True)
            if self.dictation is not None:
                self.dictation.on_click()
        elif ev.type == "KEY_BACKSPACE":
            self.backend.press("backspace", _pause=False)
            self._log_event(ev.type)
        elif ev.type == "DELETE_WORD":
            self.backend.hotkey("ctrl", "backspace", _pause=False)
            self._log_event(ev.type)
        elif ev.type == "DICTATE":
            if self.dictation is not None:
                self.dictation.start_now()
            self._log_event("DICTATE")
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
