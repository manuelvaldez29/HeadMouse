"""Sondeo de foco e inferencia léxica fuera de los hilos de cámara y GUI."""
import queue
import sqlite3
import threading
import time

from PySide6.QtCore import QObject, Signal
from keyboard_dictionary import Dictionary
from keyboard_input import KeyboardSession, KeyboardTyper, WindowsKeyboardFocus


class KeyboardService(QObject):
    view = Signal(object)
    vocabulary = Signal(str, object)
    error = Signal(str)

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

    def close(self):
        self.closed.set()
        self.controller.keyboard_visible.clear()
        self.thread.join(.6)

    def run(self):
        session = KeyboardSession()
        probe = typer = dictionary = None
        profile = None
        manual = False
        hidden = object()
        last_view = None
        generation = 0
        prediction_key, predictions = None, []
        dictionary_unavailable = False
        current_control = None
        prediction_retry = 0.
        try:
            while not self.closed.is_set():
                try:
                    action, data, token = self.queue.get(timeout=.28)
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
                        session.reset()
                        manual = False
                        generation += 1
                    if action in ("list", "delete", "clear"):
                        if profile and token == profile:
                            if dictionary is None:
                                dictionary = Dictionary(self.controller.data_dir, profile)
                            if action == "delete":
                                dictionary.delete(data)
                                session.reset()
                            elif action == "clear":
                                dictionary.clear()
                                session.reset()
                            prediction_key = None
                            self.vocabulary.emit(profile, dictionary.words())
                        continue

                    active = bool(profile and settings and self.controller._dictation_allowed())
                    control = getattr(self.controller,"control",None) if active else None
                    if control is not current_control:
                        current_control = control
                        session.reset()
                        generation += 1
                    if action == "hide":
                        manual = False
                        hidden = session.target
                        session.reset()
                    elif action == "toggle":
                        if not active:
                            self.error.emit("Activá el control de HeadMouse antes de usar el teclado.")
                        elif last_view and last_view["visible"]:
                            manual = False
                            hidden = session.target
                        else:
                            manual = True
                            hidden = object()
                    if not active:
                        manual = False
                    target = None
                    if active and (manual or settings["auto_open"]):
                        if probe is None:
                            probe = self.focus_factory()
                        target = probe.focused()
                    if session.target != target:
                        session.set_target(target)
                        generation += 1
                        if hidden != target:
                            hidden = object()
                    visible = bool(active and (manual or (target and target.editable and target != hidden)))
                    usable = bool(visible and target and (target.editable or (manual and target.unknown)))
                    if visible:
                        self.controller.keyboard_visible.set()
                    else:
                        self.controller.keyboard_visible.clear()
                    voice = self.controller.dictation
                    busy = bool(voice and voice.busy)
                    if busy:
                        session.reset()  # no inferir contexto de texto dictado
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

                    if usable and token == generation and action in ("text", "key", "suggest", "mic"):
                        if action == "mic":
                            if voice and settings["microphone"] and target.predictive and allowed():
                                if busy:
                                    voice.cancel()
                                else:
                                    session.reset()
                                    voice.start_now(expected_runtime=target.runtime)
                        elif not busy:
                            if typer is None:
                                typer = self.typer_factory()
                            if action == "text":
                                session.insert(data, probe, typer, dictionary, settings, allowed)
                            elif action == "key":
                                session.special(*data, probe, typer, dictionary, settings, allowed)
                            else:
                                if not session.choose(data, probe, typer, dictionary, settings, allowed):
                                    self.error.emit("La sugerencia ya no coincide con el campo. Seguí escribiendo.")
                    wanted = bool(usable and not busy and dictionary and settings["suggestions"])
                    current_key = (generation,wanted,session.draft,tuple(session.context),settings.get("corrections"))
                    changed = current_key != prediction_key
                    if changed or (prediction_retry and time.monotonic()>=prediction_retry):
                        verified = wanted and probe.caret(session.tail) is not None
                        predictions = (session.suggestions(dictionary,settings)
                                       if verified else [])
                        prediction_key = current_key
                        # SendInput encola la tecla; el otro programa puede actualizar el caret después.
                        prediction_retry = time.monotonic()+.08 if changed and wanted and not verified else 0.
                    result = dict(visible=visible, usable=usable and not busy, token=generation,
                                  predictions=predictions, private=bool(target and target.private),
                                  mic=bool(usable and target.predictive and voice and settings.get("microphone")),
                                  show_mic=settings.get("microphone", True), busy=busy,
                                  listening=bool(voice and voice.state=="listening"),
                                  size=settings.get("size","normal"), position=settings.get("position","bottom"))
                    if result != last_view and not self.closed.is_set():
                        self.view.emit(result)
                        last_view = result
                except Exception:
                    # Ni texto de campos ni errores con parámetros SQL llegan a logs o interfaz.
                    session.reset()
                    if not self.closed.is_set():
                        self.error.emit("No se pudo completar la operación del teclado. Revisá el campo o el diccionario.")
        finally:
            if dictionary:
                dictionary.close()
            self.controller.keyboard_visible.clear()
