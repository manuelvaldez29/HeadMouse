"""Sondeo de foco e inferencia léxica fuera de los hilos de cámara y GUI."""
import queue
import sqlite3
import threading
import time

from PySide6.QtCore import QObject, Signal
from keyboard_dictionary import Dictionary
from keyboard_input import KeyboardSession, KeyboardTyper, WindowsKeyboardFocus


class KeyboardVisibility:
    """Ocultar espera otra selección; apertura manual y desactivación son independientes."""
    def __init__(self):
        self.manual = False
        self.hidden = None
        self.hidden_at = 0.
        self.suppressed = False
        self.target = None
        self.since = 0.

    def update(self, active, auto, target, action, click, now):
        if not active:
            self.manual, self.hidden = False, None
            self.suppressed = False
        if target != self.target:
            self.target, self.since = target, now
            if target is not None and target != self.hidden:
                self.hidden = None
                self.suppressed = False
        visible = bool(active and (self.manual or
                       (auto and target and target.editable and target != self.hidden and now-self.since >= .1)))
        if action == "hide" or (action == "toggle" and visible):
            self.manual, self.hidden, self.hidden_at = False, target, now
            self.suppressed = True
            visible = False
        elif action == "toggle" and active:
            self.manual, self.hidden = True, None
            self.suppressed = False
            visible = True
        if active and auto and self.hidden is not None and target == self.hidden:
            _, point, when = click
            bounds = target.bounds
            if (point and bounds and when > self.hidden_at + .15 and
                    bounds[0] <= point[0] < bounds[0]+bounds[2] and
                    bounds[1] <= point[1] < bounds[1]+bounds[3]):
                self.hidden = None
                self.suppressed = False
                visible = True
        return visible


class KeyboardService(QObject):
    view = Signal(object)
    vocabulary = Signal(str, object)
    error = Signal(str)
    feedback = Signal(object)

    def __init__(self, bridge, parent=None, focus_factory=WindowsKeyboardFocus, typer_factory=KeyboardTyper):
        super().__init__(parent)
        self.bridge = bridge
        self.controller = bridge.controller
        self.focus_factory, self.typer_factory = focus_factory, typer_factory
        self.queue = queue.Queue(maxsize=8)
        self.closed = threading.Event()
        self.thread = threading.Thread(target=self.run, name="HeadMouseKeyboard", daemon=True)
        self.thread.start()

    def submit(self, action, data=None, token=None):
        if self.closed.is_set():
            return
        try:
            self.queue.put_nowait((action, data, token))
        except queue.Full:
            self.error.emit("Esperá a que se procese la última tecla.")
            self.feedback.emit(dict(action=action,data=None,executed=False,token=token))

    def close(self):
        self.closed.set()
        self.controller.keyboard_visible.clear()
        self.thread.join(.6)

    def run(self):
        session = KeyboardSession()
        probe = typer = dictionary = None
        profile = None
        visibility = KeyboardVisibility()
        last_view = None
        generation = 0
        prediction_key, predictions = None, []
        dictionary_unavailable = False
        current_control = None
        prediction_retry = 0.
        retry_count = 0
        preview_edited_at = 0.
        last_synced_key = None
        try:
            while not self.closed.is_set():
                try:
                    action, data, token = self.queue.get(timeout=.12)
                except queue.Empty:
                    action, data, token = None, None, None
                if self.closed.is_set():
                    break
                try:
                    snapshot = self.bridge.snapshot()
                    current = (snapshot.get("profile") or {}).get("user_id")
                    settings = snapshot.get("settings", {}).get("keyboard", {})
                    if profile != current:
                        if dictionary:
                            dictionary.close()
                        dictionary = None
                        dictionary_unavailable = False
                        profile = current
                        session.reset_all()
                        last_synced_key = None
                        visibility = KeyboardVisibility()
                        generation += 1
                    if action in ("list", "delete", "clear"):
                        if profile and token == profile:
                            if dictionary is None:
                                dictionary = Dictionary(self.controller.data_dir, profile)
                            if action == "delete":
                                dictionary.delete(data)
                                session.reset_all()
                                last_synced_key = None
                            elif action == "clear":
                                dictionary.clear()
                                session.reset_all()
                                last_synced_key = None
                            prediction_key = None
                            self.vocabulary.emit(profile, dictionary.words())
                        continue

                    active = bool(profile and settings and self.controller._dictation_allowed())
                    control = getattr(self.controller,"control",None) if active else None
                    if control is not current_control:
                        current_control = control
                        session.reset_all()
                        last_synced_key = None
                        generation += 1
                    if not active:
                        session.reset_all()
                        last_synced_key = None
                    if action == "toggle" and not active:
                        self.error.emit("Activá el control de HeadMouse antes de usar el teclado.")
                    target = None
                    if active and (visibility.manual or settings["auto_open"] or action == "toggle"):
                        if probe is None:
                            probe = self.focus_factory()
                        target = probe.focused()
                    if session.target != target:
                        session.set_target(target)
                        generation += 1
                    click = getattr(control, "pointer_click", (0, None, 0.))
                    if not isinstance(click, tuple) or len(click) != 3:
                        click = (0, None, 0.)
                    visible = visibility.update(active, settings.get("auto_open",False), target, action, click, time.monotonic())
                    usable = bool(visible and target and (target.editable or (visibility.manual and target.unknown)))
                    if not visible:
                        session.save_current_field()
                        session.reset()
                        last_synced_key = None
                    elif not target or not target.predictive:
                        session.reset()
                        last_synced_key = None
                    if visible:
                        self.controller.keyboard_visible.set()
                    else:
                        self.controller.keyboard_visible.clear()
                    voice = self.controller.dictation
                    busy = bool(voice and voice.busy)
                    if busy:
                        session.reset(clear_saved=True)  # no inferir contexto de texto dictado
                        last_synced_key = None
                    if usable and target.predictive and (settings["suggestions"] or settings["learning"]):
                        if dictionary is None and not dictionary_unavailable:
                            try:
                                dictionary = Dictionary(self.controller.data_dir, profile)
                            except (OSError,sqlite3.Error):
                                dictionary_unavailable = True
                                self.error.emit("El diccionario no está disponible. Podés seguir escribiendo.")
                        if dictionary_unavailable:
                            settings = dict(settings,suggestions=False,learning=False)

                    def control_allows_input():
                        live = self.controller.profile or {}
                        return (not self.closed.is_set() and live.get("user_id") == profile
                                and getattr(self.controller,"control",None) is control
                                and self.controller._dictation_allowed())

                    def allowed():
                        return control_allows_input() and probe.focused() == target and control_allows_input()

                    synced_key = (target.window, target.runtime) if (usable and target and target.predictive and not busy) else None
                    if synced_key is not None and synced_key != last_synced_key:
                        if session.restore_or_sync(probe, recover_external=True):
                            preview_edited_at = time.monotonic()
                            prediction_key = None
                        last_synced_key = synced_key

                    input_action = action in ("text", "key", "suggest", "mic")
                    executed = False
                    if (input_action and session.composition.text and usable and allowed() and
                            time.monotonic()-preview_edited_at > .3 and session.composition.verify(probe) is False):
                        session.reset(clear_saved=True)
                    if usable and token == generation and input_action:
                        if action == "mic":
                            if voice and settings["microphone"] and target.predictive and allowed():
                                if busy:
                                    voice.cancel()
                                else:
                                    session.reset(clear_saved=True)
                                    voice.start_now(expected_runtime=target.runtime)
                                executed = True
                        elif not busy:
                            if typer is None:
                                typer = self.typer_factory()
                            if action == "text":
                                executed = session.insert(data, probe, typer, dictionary, settings, allowed)
                            elif action == "key":
                                executed = session.special(*data, probe, typer, dictionary, settings, allowed)
                            else:
                                executed = session.choose(data, probe, typer, dictionary, settings, allowed)
                                if not executed:
                                    self.error.emit("La sugerencia ya no coincide con el campo. Seguí escribiendo.")
                    if input_action:
                        if executed:
                            preview_edited_at = time.monotonic()
                        elif action != "mic":
                            self.error.emit("La tecla no se envió: el campo cambió o el control está detenido.")
                        self.feedback.emit(dict(action=action, data=None if target and target.private else data,
                                                executed=bool(executed), token=token))
                    if session.composition.text:
                        if not usable or not target.predictive or not allowed():
                            session.save_current_field()
                            session.reset()
                            last_synced_key = None
                        else:
                            verified_preview = session.composition.verify(probe)
                            if verified_preview is False and time.monotonic()-preview_edited_at > .3:
                                session.reset(clear_saved=True)
                                session.composition.status = "changed"
                            elif verified_preview is None and session.composition.status not in ("recovered", "confirmed"):
                                session.composition.status = "sent"
                            else:
                                session.save_current_field()
                    preview_mode = settings.get("preview_mode", "compact")
                    show_preview = bool(settings.get("preview", True) and preview_mode != "hidden")
                    if not settings.get("preview", True):
                        session.composition.clear()
                    wanted = bool(usable and not busy and dictionary and settings["suggestions"])
                    current_key = (generation,wanted,session.draft,tuple(session.context),settings.get("corrections"))
                    changed = current_key != prediction_key
                    if changed:
                        retry_count = 0
                    if changed or (prediction_retry and time.monotonic()>=prediction_retry):
                        verified = wanted and probe.caret(session.tail) is not None
                        predictions = (session.suggestions(dictionary,settings)
                                       if verified else [])
                        prediction_key = current_key
                        # SendInput encola la tecla; el otro programa puede actualizar el caret después.
                        if wanted and not verified and retry_count < 6:
                            retry_count += 1
                            prediction_retry = time.monotonic() + .07
                        else:
                            prediction_retry = 0.
                    result = dict(visible=visible, usable=usable and not busy, token=generation,
                                  predictions=predictions, private=bool(target and target.private),
                                  mic=bool(usable and target.predictive and voice and settings.get("microphone")),
                                  show_mic=settings.get("microphone", True), busy=busy,
                                  listening=bool(voice and voice.state=="listening"),
                                  size=settings.get("size","auto"), position=settings.get("position","auto"),
                                  preview_mode=preview_mode, keep_visible=settings.get("keep_visible",True),
                                  always_on_top=settings.get("always_on_top",True),
                                  suggestions=settings.get("suggestions",True))
                    result.update(bounds=target.bounds if target else None,
                                  panel_bounds=target.panel_bounds if target else None,
                                  target=(target.window,target.runtime) if target else None,
                                  window=target.window if target else None,
                                  restore=bool(active and visibility.suppressed),
                                  preview=session.composition.text if show_preview else "",
                                  cursor=session.composition.cursor, preview_status=session.composition.status,
                                  show_preview=show_preview,
                                  feedback=settings.get("feedback",True), enlarged_key=settings.get("enlarged_key",False),
                                  opacity=settings.get("opacity",100))
                    if result != last_view and not self.closed.is_set():
                        self.view.emit(result)
                        last_view = result
                except Exception:
                    # Ni texto de campos ni errores con parámetros SQL llegan a logs o interfaz.
                    session.reset()
                    if action in ("text", "key", "suggest", "mic"):
                        self.feedback.emit(dict(action=action, data=None, executed=False, token=token))
                    if not self.closed.is_set():
                        self.error.emit("No se pudo completar la operación del teclado. Revisá el campo o el diccionario.")
        finally:
            if dictionary:
                dictionary.close()
            self.controller.keyboard_visible.clear()
