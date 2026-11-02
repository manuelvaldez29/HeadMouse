"""
dictation.py
HeadMouse — Dictado por voz local

Cuando un click de HeadMouse deja el foco en un campo de texto editable (y no
es una contraseña), se abre el micrófono, se detecta el fin de la frase por
silencio, se transcribe localmente con faster-whisper y el texto se escribe en
el campo con SendInput Unicode (respeta tildes y ñ, no toca el portapapeles).

Privacidad: el audio vive solo en RAM durante el dictado; no se guarda audio
ni texto. La transcripción es local; el modelo se descarga una sola vez:

    python dictation.py --download-model           # preparación, requiere Internet
    python dictation.py --test                     # probar micrófono + modelo

Las partes puras (Endpointer, Dictation) no dependen de Windows ni de audio y
se prueban con dobles; los adaptadores reales se cargan solo al usarlos.
"""
from app_paths import RESOURCE_ROOT, data_root
import argparse
import importlib.util
import logging
import math
import os
import queue
import sys
import threading
import time
import unicodedata
from dataclasses import dataclass

from config import ROOT, VoiceConfig, configure_logging

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
MODEL_DIR = data_root() / "models" / "whisper"  # donde se descargan
# Antes de 0.4.0 se descargaban dentro del proyecto: se siguen usando sin copiar
# cientos de MB al directorio de datos (2026-11-02, el dictado "desapareció").
MODEL_DIRS = (MODEL_DIR, RESOURCE_ROOT / "models" / "whisper")


_legacy_found = {}


def installed_model(model):
    """Carpeta del modelo de voz instalado, o None.

    La GUI lo consulta cada 2 s desde el worker: las carpetas viejas (dentro de
    OneDrive) se revisan una sola vez; sólo la de descarga puede cambiar.
    """
    if (MODEL_DIRS[0] / model / "model.bin").is_file():
        return MODEL_DIRS[0] / model
    for directory in MODEL_DIRS[1:]:
        key = (directory, model)
        if key not in _legacy_found:
            _legacy_found[key] = (directory / model / "model.bin").is_file()
        if _legacy_found[key]:
            return directory / model
    return None


def model_path(model):
    """Carpeta del modelo de voz instalado, o la de descarga si todavía no está."""
    return installed_model(model) or MODEL_DIRS[0] / model


# ══════════════════════════════════════════════════════════════════════════════
# FIN DE FRASE (VAD por energía)
# ══════════════════════════════════════════════════════════════════════════════

class Endpointer:
    """Detecta inicio y fin de habla por energía con piso de ruido adaptativo.

    Los primeros `calibration_ms` estiman el ruido del ambiente. Hay habla
    cuando la energía de 3 tramas seguidas de 30 ms supera max(piso, ruido ×
    ratio). Termina tras `silence_s` de silencio, al llegar a `max_s`, o vence
    si no hubo habla en `no_speech_s`. Se conserva un pre-roll para no cortar
    la primera sílaba.
    """
    FRAME_MS = 30

    def __init__(self, silence_s=1.2, max_s=20, no_speech_s=6, rate=SAMPLE_RATE,
                 calibration_ms=300, ratio=3.0, floor=0.004, preroll_ms=300, onset_frames=3):
        self.rate, self.silence_s, self.max_s, self.no_speech_s = rate, silence_s, max_s, no_speech_s
        self.frame = int(rate * self.FRAME_MS / 1000)
        self.calibration_frames = max(1, calibration_ms // self.FRAME_MS)
        self.ratio, self.floor, self.onset_frames = ratio, floor, onset_frames
        self.preroll = int(preroll_ms / self.FRAME_MS)
        self.frames, self.levels = [], []
        self.noise = None
        self.state = "waiting"
        self.speech_start = None
        self._above = 0
        self._silent = 0
        self._pending = []

    @property
    def threshold(self):
        return max(self.floor, (self.noise or 0) * self.ratio)

    def feed(self, samples):
        """Agrega muestras float en [-1, 1]; devuelve el estado: waiting, speech, done o timeout."""
        if self.state in ("done", "timeout"):
            return self.state
        self._pending.extend(float(v) for v in samples)
        while len(self._pending) >= self.frame and self.state not in ("done", "timeout"):
            chunk, self._pending = self._pending[:self.frame], self._pending[self.frame:]
            self._frame(chunk)
        return self.state

    def _frame(self, chunk):
        level = math.sqrt(sum(v * v for v in chunk) / len(chunk))
        self.frames.append(chunk)
        self.levels.append(level)
        index = len(self.frames)
        if index <= self.calibration_frames:
            if index == self.calibration_frames:
                self.noise = sorted(self.levels)[len(self.levels) // 2]
            return
        loud = level > self.threshold
        elapsed = index * self.FRAME_MS / 1000
        if self.state == "waiting":
            self._above = self._above + 1 if loud else 0
            if not loud:  # el ruido de fondo se adapta solo en silencio
                self.noise = .95 * self.noise + .05 * level
            if self._above >= self.onset_frames:
                self.state = "speech"
                self.speech_start = max(0, index - self._above - self.preroll)
            elif elapsed >= self.no_speech_s:
                self.state = "timeout"
            return
        self._silent = 0 if loud else self._silent + 1
        speech_s = (index - self.speech_start) * self.FRAME_MS / 1000
        if self._silent * self.FRAME_MS / 1000 >= self.silence_s or speech_s >= self.max_s:
            self.state = "done"

    def audio(self):
        """Muestras desde el pre-roll hasta el final, sin el silencio de cierre."""
        if self.speech_start is None:
            return []
        end = len(self.frames) - min(self._silent, max(0, len(self.frames) - self.speech_start))
        tail = int(150 / self.FRAME_MS)  # conservar 150 ms para no cortar la última sílaba
        return [v for chunk in self.frames[self.speech_start:min(len(self.frames), end + tail)] for v in chunk]


# ══════════════════════════════════════════════════════════════════════════════
# TEXTO
# ══════════════════════════════════════════════════════════════════════════════

# Frases que Whisper suele inventar con silencio o ruido (no hay habla real).
HALLUCINATIONS = {"gracias.", "gracias por ver el video.", "¡gracias por ver el video!",
                  "subtítulos realizados por la comunidad de amara.org", "suscríbete al canal.",
                  "gracias por ver.", "...", "."}


# Ayuda visible en la GUI. Mantener en sincronía con parse_command (lo verifica test_dictation).
VOICE_COMMANDS = (
    ("«borrar»", "borra lo último que dictaste", "Borrar."),
    ("«borrar palabra» · «borrar tres palabras»", "borra palabra por palabra", "Borrar tres palabras"),
    ("«borrar letra» · «borrar cinco letras»", "borra letra por letra", "borrar cinco letras"),
    ("«borrar todo»", "vacía el campo", "Borrar todo."),
    ("«deshacer»", "deshace lo último (Ctrl+Z)", "Deshacer"),
)

NUMBERS = dict(un=1, una=1, uno=1, dos=2, tres=3, cuatro=4, cinco=5, seis=6, siete=7,
               ocho=8, nueve=9, diez=10)
MAX_REPEAT = 50  # tope de teclas por comando, por seguridad


def _normalize(text):
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return " ".join("".join(c if c.isalnum() else " " for c in text).split())


def parse_command(text):
    """Comando de edición si la frase entera es un comando; None si es texto.

    "borrar" (lo último dictado), "borrar todo", "borrar [N] letra(s)",
    "borrar [N] palabra(s)" y "deshacer". Un comando dentro de una frase más
    larga ("hay que borrar la pizarra") se escribe como texto normal.
    """
    words = _normalize(text).split()
    if words == ["deshacer"]:
        return "undo", 1
    if not words or words[0] not in ("borrar", "borra", "borre"):
        return None
    rest = words[1:]
    if rest in ([], ["eso"], ["ultimo"], ["lo", "ultimo"]):
        return "last", 1
    if rest == ["todo"]:
        return "all", 1
    count = 1
    if rest and (rest[0].isdigit() or rest[0] in NUMBERS):
        count = int(rest[0]) if rest[0].isdigit() else NUMBERS[rest[0]]
        rest = rest[1:]
    if not 1 <= count <= MAX_REPEAT:
        return None
    if rest in (["letra"], ["letras"], ["caracter"], ["caracteres"]):
        return "char", count
    if rest in (["palabra"], ["palabras"]):
        return "word", count
    return None


def finish_text(text, config):
    """Limpia la transcripción. Devuelve (texto a escribir, presionar Enter)."""
    text = " ".join(text.split())
    if text.lower() in HALLUCINATIONS:
        return "", False
    send = False
    word = config.send_word.strip().lower()
    if word:
        stripped = text.rstrip(" .,!?¡¿;:")
        if stripped.lower() == word or stripped.lower().endswith(" " + word):
            text, send = stripped[:len(stripped) - len(word)].rstrip(" ,"), True
    if text and config.append_space and not send:
        text += " "
    return text, send


# ══════════════════════════════════════════════════════════════════════════════
# SESIÓN DE DICTADO
# ══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class FocusInfo:
    editable: bool
    password: bool = False
    control_type: str = ""
    name: str = ""


class Dictation:
    """Estados: idle → arming (espera el foco) → listening → transcribing → idle.

    Un único hilo propio hace todo el trabajo lento: el ciclo de control solo
    llama on_click/start_now/cancel y consulta `busy`. Mientras dicta, los gestos
    deben suprimirse (hablar mueve boca, ojos y cejas), salvo el de cancelar.
    """

    def __init__(self, config: VoiceConfig, focus, recorder_factory, transcriber, typer,
                 clock=time.monotonic, metrics=None, cue=None):
        self.config, self.focus, self.recorder_factory = config, focus, recorder_factory
        self.transcriber, self.typer, self.clock, self.metrics = transcriber, typer, clock, metrics
        self.cue = cue or (lambda kind: None)
        self.state, self.message, self.last_text = "idle", "", ""
        self._last_typed = ""  # para "borrar": lo escrito por el último dictado
        self._lock = threading.Lock()
        self._request = None
        self._wake = threading.Event()
        self._cancel = threading.Event()
        self._closed = threading.Event()
        self._quiet_until = 0.
        self._thread = None

    # ── API para el ciclo de control ───────────────────────────────────────────

    def start(self):
        self._thread = threading.Thread(target=self._run, name="Dictation", daemon=True)
        self._thread.start()
        if hasattr(self.transcriber, "preload"):
            threading.Thread(target=self.transcriber.preload, name="WhisperLoad", daemon=True).start()

    def close(self):
        self._cancel.set()
        self._closed.set()
        self._wake.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=3)

    @property
    def busy(self):
        """True mientras escucha/transcribe y durante la cola posterior."""
        return self.state != "idle" or self.clock() < self._quiet_until

    def on_click(self):
        """Click ejecutado por HeadMouse: dictar si el foco queda en un campo de texto."""
        self._arm("click")

    def start_now(self):
        """Acción DICTATE: dictar en el campo que ya tiene el foco."""
        self._arm("now")

    def cancel(self):
        if self.state != "idle":
            self._cancel.set()

    def snapshot(self):
        with self._lock:
            return dict(state=self.state, message=self.message, last_text=self.last_text)

    # ── Hilo de trabajo ────────────────────────────────────────────────────────

    def _arm(self, kind):
        if not self.config.enabled or self._closed.is_set():
            return
        with self._lock:
            if self.state != "idle":
                return
            self._request = (kind, self.clock())
            self._set("arming", "Buscando campo de texto…")
        self._cancel.clear()
        self._wake.set()

    def _set(self, state, message=""):
        self.state, self.message = state, message

    def _run(self):
        try:
            self._init_thread()
        except Exception:
            logger.exception("No se pudo inicializar el dictado")
        while not self._closed.is_set():
            self._wake.wait()
            self._wake.clear()
            if self._closed.is_set():
                break
            request, self._request = self._request, None
            if request is None:
                continue
            try:
                self._session(*request)
            except Exception as exc:
                logger.exception("Dictado interrumpido")
                self._record(dict(result="error"))
                with self._lock:
                    self.message = f"Error de dictado: {exc}"
            finally:
                with self._lock:
                    self._quiet_until = self.clock() + self.config.after_dictation_ms / 1000
                    self.state = "idle"

    def _init_thread(self):
        if hasattr(self.focus, "init_thread"):
            self.focus.init_thread()

    def _wait_focus(self, kind, since):
        deadline = since + (0 if kind == "now" else self.config.focus_window_ms / 1000)
        while True:
            info = self.focus.focused()
            if info and info.editable and not info.password:
                return info
            if info and info.password:
                return None  # nunca dictar contraseñas
            if self.clock() >= deadline or self._cancel.is_set():
                # Sin el nombre del elemento: puede contener texto del usuario.
                logger.info("Click sin campo de texto para dictar: %s",
                            getattr(self.focus, "last", None) or (info and info.control_type))
                return None
            time.sleep(.05)

    def _session(self, kind, since):
        info = self._wait_focus(kind, since)
        if info is None or self._cancel.is_set():
            with self._lock:
                self.message = "" if kind == "click" else "No hay un campo de texto con el foco."
            return
        started = self.clock()
        self.cue("start")
        with self._lock:
            self._set("listening", "Escuchando… hablá. Decí «borrar» para corregir · ambas cejas cancelan.")
        endpoint = Endpointer(self.config.silence_s, self.config.max_utterance_s,
                              self.config.no_speech_timeout_s)
        with self.recorder_factory() as recorder:
            while endpoint.state not in ("done", "timeout"):
                if self._cancel.is_set():
                    break
                block = recorder.read(timeout=.2)
                if block is not None:
                    endpoint.feed(block)
        if self._cancel.is_set():
            self.cue("cancel")
            with self._lock:
                self.message = "Dictado cancelado."
            self._record(dict(result="cancelled", listen_s=self.clock() - started))
            return
        if endpoint.state == "timeout":
            self.cue("cancel")
            with self._lock:
                self.message = "No se escuchó nada; dictado cerrado."
            self._record(dict(result="no_speech", listen_s=self.clock() - started))
            return
        self.cue("end")
        audio = endpoint.audio()
        spoken_at = self.clock()
        with self._lock:
            self._set("transcribing", "Transcribiendo…")
        text = self.transcriber.transcribe(audio, self.config.language)
        if self._cancel.is_set():
            self._record(dict(result="cancelled", listen_s=spoken_at - started))
            return
        command = parse_command(text) if self.config.commands else None
        if command:
            self._command(*command, listen_s=spoken_at - started, audio_s=len(audio) / SAMPLE_RATE,
                          transcribe_s=self.clock() - spoken_at)
            return
        text, send = finish_text(text, self.config)
        if text:
            self.typer.type_text(text)
        if send:
            self.typer.press_enter()
        self._last_typed = "" if send else text
        latency = self.clock() - spoken_at
        with self._lock:
            self.last_text = text.strip()
            self.message = (f"Escrito: {self.last_text}" + (" ⏎" if send else " · decí «borrar» para quitarlo")) \
                if text or send else \
                "No se entendió; probá de nuevo."
        self._record(dict(result="typed" if text or send else "empty", listen_s=spoken_at - started,
                          audio_s=len(audio) / SAMPLE_RATE, transcribe_s=latency,
                          characters=len(text.strip()), sent=send))

    def _command(self, name, count, **timing):
        if name == "last":
            if not self._last_typed:
                with self._lock:
                    self.message = "No hay un dictado anterior para borrar."
                self._record(dict(result="command", command=name, **timing))
                return
            self.typer.backspace(len(self._last_typed))
            message = "Borrado lo último dictado."
        elif name == "all":
            self.typer.select_all()
            self.typer.backspace(1)
            message = "Campo borrado."
        elif name == "char":
            self.typer.backspace(count)
            message = f"Borrada{'s' if count > 1 else ''} {count} letra{'s' if count > 1 else ''}."
        elif name == "word":
            self.typer.delete_words(count)
            message = f"Borrada{'s' if count > 1 else ''} {count} palabra{'s' if count > 1 else ''}."
        else:
            self.typer.undo()
            message = "Deshecho."
        self._last_typed = ""
        with self._lock:
            self.last_text = ""
            self.message = message
        self._record(dict(result="command", command=name, **timing))

    def _record(self, data):
        if self.metrics and hasattr(self.metrics, "dictation"):
            self.metrics.dictation(data)


# ══════════════════════════════════════════════════════════════════════════════
# ADAPTADORES REALES (Windows / audio / modelo)
# ══════════════════════════════════════════════════════════════════════════════

class UIAFocusProbe:
    """Elemento con foco vía Windows UI Automation (comtypes). Un objeto por hilo."""
    EDIT, DOCUMENT, COMBOBOX = 50004, 50030, 50003
    VALUE_AVAILABLE, VALUE_READ_ONLY = 30043, 30046
    NAMES = {50004: "Edit", 50030: "Document", 50003: "ComboBox"}

    def __init__(self):
        self._automation = None

    def init_thread(self):
        import comtypes
        import comtypes.client
        try:
            comtypes.CoInitialize()  # comtypes ya inicializa COM al importarse en este hilo
        except OSError:
            pass
        uia = comtypes.client.GetModule("UIAutomationCore.dll")
        self._automation = comtypes.client.CreateObject(uia.CUIAutomation, interface=uia.IUIAutomation)

    def focused(self):
        if self._automation is None:
            self.init_thread()
        try:
            element = self._automation.GetFocusedElement()
        except Exception:
            return None  # ventanas elevadas o en transición
        if element is None:
            return None
        try:
            info = self._classify(element)
        except Exception:
            return None
        self.last = self.describe(element)
        if not info.editable and not info.password:
            return self._focused_under_pointer() or info
        return info

    def _classify(self, element):
        control = element.CurrentControlType
        password = bool(element.CurrentIsPassword)
        has_value = bool(element.GetCurrentPropertyValue(self.VALUE_AVAILABLE))
        read_only = bool(element.GetCurrentPropertyValue(self.VALUE_READ_ONLY)) if has_value else False
        name = element.CurrentName or ""
        editable = (control == self.EDIT and not read_only) or \
                   (control in (self.DOCUMENT, self.COMBOBOX) and has_value and not read_only)
        return FocusInfo(editable, password, self.NAMES.get(control, str(control)), name[:80])

    def _focused_under_pointer(self):
        """Campo con foco que GetFocusedElement no alcanza.

        WhatsApp Desktop 2.2640 es WebView2 dentro de WinUI 3: con el foco ya en el
        cuadro de mensaje (el palito parpadeando), GetFocusedElement se queda en el
        puente de WinUI ('Microsoft.UI.Content.DesktopChildSiteBridge', un Pane) y no
        entra al contenido web. El cuadro sí informa HasKeyboardFocus si se lo pide
        por posición. Se acepta el primero con foco de teclado entre el elemento bajo
        el puntero y sus ancestros, y sólo si esa ventana es la activa: justo después
        del click es el mismo campo. Un click fuera del campo (p. ej. en un mensaje)
        no lo encuentra aunque el cuadro conserve el foco.
        """
        try:
            if not self._pointer_in_foreground():
                return None
            for element in self._pointer_chain(4):
                if element.CurrentHasKeyboardFocus:
                    info = self._classify(element)
                    self.last = dict(self.describe(element), via="puntero")
                    return info
        except Exception:
            pass
        return None

    def _cursor_point(self):
        import ctypes
        import ctypes.wintypes
        import comtypes.client
        point = ctypes.wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
        return comtypes.client.GetModule("UIAutomationCore.dll").tagPOINT(point.x, point.y)

    def _pointer_in_foreground(self):
        import ctypes
        import ctypes.wintypes as w
        user32 = ctypes.WinDLL("user32")  # instancia propia: no tocar los argtypes globales
        user32.GetCursorPos.argtypes = [ctypes.POINTER(w.POINT)]
        user32.WindowFromPoint.argtypes, user32.WindowFromPoint.restype = [w.POINT], w.HWND
        user32.GetAncestor.argtypes, user32.GetAncestor.restype = [w.HWND, w.UINT], w.HWND
        user32.GetForegroundWindow.restype = w.HWND
        point = w.POINT()
        user32.GetCursorPos(ctypes.byref(point))
        hwnd, foreground = user32.WindowFromPoint(point), user32.GetForegroundWindow()
        return bool(hwnd and foreground) and user32.GetAncestor(hwnd, 2) == user32.GetAncestor(foreground, 2)  # GA_ROOT

    def _pointer_chain(self, limit):
        element = self._automation.ElementFromPoint(self._cursor_point())
        walker = self._automation.ControlViewWalker
        for _ in range(limit):
            if element is None:
                return
            yield element
            try:
                element = walker.GetParentElement(element)
            except Exception:
                return

    TEXT_AVAILABLE = 30040

    def describe(self, element):
        """Rasgos técnicos del elemento, sin su nombre ni su texto (diagnóstico)."""
        def read(getter):
            try:
                return getter()
            except Exception:
                return None
        return dict(control=read(lambda: element.CurrentControlType),
                    framework=read(lambda: element.CurrentFrameworkId),
                    class_name=(read(lambda: element.CurrentClassName) or "")[:40],
                    keyboard_focus=read(lambda: bool(element.CurrentHasKeyboardFocus)),
                    value=read(lambda: bool(element.GetCurrentPropertyValue(self.VALUE_AVAILABLE))),
                    read_only=read(lambda: bool(element.GetCurrentPropertyValue(self.VALUE_READ_ONLY))),
                    text=read(lambda: bool(element.GetCurrentPropertyValue(self.TEXT_AVAILABLE))),
                    password=read(lambda: bool(element.CurrentIsPassword)))

    def under_cursor(self):
        """Elemento bajo el puntero y sus ancestros (hasta 4), para el diagnóstico."""
        return [self.describe(element) for element in self._pointer_chain(5)]


def probe_focus(seconds):
    """Imprime qué ve UI Automation (foco y elemento bajo el puntero) cada vez que cambia."""
    probe = UIAFocusProbe()
    probe.init_thread()
    print(f"Durante {seconds:.0f} s: hacé click (con el mouse común) en el campo que falla, "
          "con y sin el palito parpadeando. Ctrl+C para cortar.")
    previous, end = None, time.monotonic() + seconds
    while time.monotonic() < end:
        info = probe.focused()
        try:
            under = probe.under_cursor()
        except Exception as exc:
            under = [f"<{type(exc).__name__}>"]
        current = (info and (info.editable, info.password), probe.last if info else None, under)
        if current != previous:
            previous = current
            print()
            print(f"[{time.strftime('%H:%M:%S')}] ¿dictaría? {bool(info and info.editable and not info.password)}")
            print("  foco:", probe.last if info else None)
            for depth, element in enumerate(under):
                print("  bajo el puntero" + " ↑" * depth + ":", element)
        time.sleep(.3)


class SoundDeviceRecorder:
    """Micrófono predeterminado a 16 kHz mono; remuestrea si el dispositivo no lo admite."""

    def __init__(self, device=None):
        self.device = device
        self._queue = queue.Queue()
        self._stream = None
        self._ratio = 1.

    def __enter__(self):
        import sounddevice as sd
        def callback(data, frames, time_info, status):
            self._queue.put(data[:, 0].copy())
        try:
            self._stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                                          blocksize=480, device=self.device, callback=callback)
            self._ratio = 1.
        except Exception:
            rate = int(sd.query_devices(self.device, "input")["default_samplerate"])
            self._stream = sd.InputStream(samplerate=rate, channels=1, dtype="float32",
                                          blocksize=int(rate * .03), device=self.device, callback=callback)
            self._ratio = SAMPLE_RATE / rate
        self._stream.start()
        return self

    def read(self, timeout=.2):
        try:
            block = self._queue.get(timeout=timeout)
        except queue.Empty:
            return None
        if self._ratio != 1.:
            import numpy as np
            n = max(1, int(len(block) * self._ratio))
            block = np.interp(np.linspace(0, len(block) - 1, n), np.arange(len(block)), block)
        return block

    def __exit__(self, *exc):
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()


class WhisperTranscriber:
    """faster-whisper en CPU con int8; solo archivos locales en uso normal."""

    def __init__(self, model="small", directory=None):
        self.model_name, self.directory = model, directory
        self._model = None
        self._lock = threading.Lock()

    def preload(self):
        try:
            self._load()
        except Exception:
            logger.exception("No se pudo cargar el modelo de voz")

    def _load(self):
        with self._lock:
            if self._model is None:
                from faster_whisper import WhisperModel
                path = model_path(self.model_name) if self.directory is None else self.directory / self.model_name
                if not path.is_dir():
                    raise FileNotFoundError(f"Falta el modelo de voz: {path}. Ejecutar "
                                            "python dictation.py --download-model durante la preparación.")
                self._model = WhisperModel(str(path), device="cpu", compute_type="int8",
                                           cpu_threads=min(8, os.cpu_count() or 4), local_files_only=True)
        return self._model

    def transcribe(self, audio, language="es"):
        import numpy as np
        if len(audio) < SAMPLE_RATE * .3:
            return ""
        segments, _ = self._load().transcribe(np.asarray(audio, dtype=np.float32), language=language,
                                              beam_size=1, vad_filter=True, condition_on_previous_text=False)
        # Descartar segmentos que el modelo considera no-habla (alucinaciones con ruido).
        return " ".join(s.text.strip() for s in segments if s.no_speech_prob < .6 and s.avg_logprob > -1.2)

    @staticmethod
    def download(model="small", directory=MODEL_DIR):
        from faster_whisper import download_model
        target = directory / model
        target.mkdir(parents=True, exist_ok=True)
        download_model(model, output_dir=str(target))
        logger.info("Modelo de voz preparado: %s", target)
        return target


class SendInputTyper:
    """Escribe texto Unicode con SendInput (tildes, ñ, emojis) sin usar el portapapeles."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.ctypes = ctypes
        ULONG_PTR = ctypes.c_size_t

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                        ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                        ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

        class _U(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]

        class INPUT(ctypes.Structure):
            _fields_ = [("type", wintypes.DWORD), ("u", _U)]

        self.KEYBDINPUT, self.INPUT = KEYBDINPUT, INPUT
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)

    def _send(self, inputs):
        array = (self.INPUT * len(inputs))(*inputs)
        sent = self.user32.SendInput(len(inputs), array, self.ctypes.sizeof(self.INPUT))
        if sent != len(inputs):
            raise OSError("Windows bloqueó la escritura (¿ventana con permisos de administrador?)")

    def _key(self, vk=0, scan=0, flags=0):
        item = self.INPUT(type=1)
        item.u.ki = self.KEYBDINPUT(vk, scan, flags, 0, 0)
        return item

    def type_text(self, text):
        KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 0x0002, 0x0004
        data = text.encode("utf-16-le")
        units = [int.from_bytes(data[i:i + 2], "little") for i in range(0, len(data), 2)]
        for start in range(0, len(units), 64):  # lotes cortos para no saturar la cola de entrada
            batch = []
            for unit in units[start:start + 64]:
                batch += [self._key(scan=unit, flags=KEYEVENTF_UNICODE),
                          self._key(scan=unit, flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)]
            self._send(batch)
            time.sleep(.005)

    def press(self, vk, times=1, ctrl=False):
        VK_CONTROL, KEYEVENTF_KEYUP = 0x11, 0x0002
        for start in range(0, times, 32):
            batch = []
            for _ in range(min(32, times - start)):
                batch += [self._key(vk=VK_CONTROL)] if ctrl else []
                batch += [self._key(vk=vk), self._key(vk=vk, flags=KEYEVENTF_KEYUP)]
                batch += [self._key(vk=VK_CONTROL, flags=KEYEVENTF_KEYUP)] if ctrl else []
            self._send(batch)
            time.sleep(.005)

    def press_enter(self):
        self.press(0x0D)

    def backspace(self, times=1):
        self.press(0x08, times)

    def delete_words(self, times=1):
        self.press(0x08, times, ctrl=True)  # Ctrl+Retroceso

    def select_all(self):
        self.press(0x41, ctrl=True)  # Ctrl+A

    def undo(self):
        self.press(0x5A, ctrl=True)  # Ctrl+Z


def sound_cue(kind):
    """Tonos cortos: empieza a escuchar (agudo), terminó (grave), cancelado (doble)."""
    try:
        import winsound
        if kind == "start":
            winsound.Beep(880, 90)
        elif kind == "end":
            winsound.Beep(523, 90)
        elif kind == "cancel":
            winsound.Beep(392, 70)
            winsound.Beep(330, 70)
    except Exception:
        pass


def create_dictation(config: VoiceConfig, metrics=None):
    """Dictado real de Windows. Falla temprano si faltan dependencias o modelo."""
    missing = [name for name in ("faster_whisper", "comtypes", "sounddevice")
               if importlib.util.find_spec(name) is None]
    if missing:
        raise RuntimeError("Faltan dependencias de dictado: " + ", ".join(missing) +
                           ". Instalar con: pip install -r requirements-voice.txt")
    if installed_model(config.model) is None:
        raise RuntimeError(f"Falta el modelo de voz '{config.model}'. "
                           "Preparalo en Configuración o con: python dictation.py --download-model")
    return Dictation(config, UIAFocusProbe(), SoundDeviceRecorder, WhisperTranscriber(config.model),
                     SendInputTyper(), metrics=metrics, cue=sound_cue if config.sound_cues else None)


# ══════════════════════════════════════════════════════════════════════════════
# CLI de preparación y prueba
# ══════════════════════════════════════════════════════════════════════════════

def main(argv=None):
    parser = argparse.ArgumentParser(description="Dictado local de HeadMouse: preparar y probar")
    parser.add_argument("--download-model", action="store_true", help="Descargar el modelo (requiere Internet)")
    parser.add_argument("--test", action="store_true", help="Grabar una frase y mostrar la transcripción")
    parser.add_argument("--model", choices=("tiny", "base", "small", "medium"), default=VoiceConfig().model)
    parser.add_argument("--language", default="es")
    parser.add_argument("--probe-focus", type=float, metavar="SEGUNDOS",
                        help="Mostrar qué campo ve UI Automation (diagnóstico de apps donde no dicta)")
    args = parser.parse_args(argv)
    configure_logging("INFO")
    if args.download_model:
        WhisperTranscriber.download(args.model)
    if args.test:
        transcriber = WhisperTranscriber(args.model)
        print("Cargando modelo…")
        loaded = time.monotonic()
        transcriber.preload()
        print(f"Modelo listo en {time.monotonic() - loaded:.1f} s. Hablá después del tono.")
        sound_cue("start")
        config = VoiceConfig()
        endpoint = Endpointer(config.silence_s, config.max_utterance_s, config.no_speech_timeout_s)
        with SoundDeviceRecorder() as recorder:
            while endpoint.state not in ("done", "timeout"):
                block = recorder.read()
                if block is not None:
                    endpoint.feed(block)
        sound_cue("end")
        if endpoint.state == "timeout":
            print("No se detectó habla.")
            return 1
        started = time.monotonic()
        text = transcriber.transcribe(endpoint.audio(), args.language)
        print(f"Ruido {endpoint.noise:.4f} · umbral {endpoint.threshold:.4f} · "
              f"audio {len(endpoint.audio()) / SAMPLE_RATE:.1f} s · transcripción {time.monotonic() - started:.1f} s")
        print("Texto:", text or "(vacío)")
    if args.probe_focus:
        probe_focus(args.probe_focus)
    if not (args.download_model or args.test or args.probe_focus):
        parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
