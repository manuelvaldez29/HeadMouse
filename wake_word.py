"""«Oye Gema»: activar a Gema con la voz, sin gesto. Todo local, sin Internet.

Cómo escucha, de lo más barato a lo más caro:

1. El micrófono queda abierto sólo mientras el control está activo, sin pausa y sin
   otro dictado en curso. Fuera de eso se cierra: Windows deja de mostrar el
   micrófono en uso.
2. Silero VAD (el mismo detector del dictado) separa frases. Sólo pasan las de
   0,35 a 6 s de voz: «Oye Gema» sola dura ~1 s y «Oye Gema, abrí el bloc de notas» ~3 s.
   Una pausa de 0,7 s cierra la frase: la gente hace una pausa después de «Oye Gema,»
   y con 0,45 s el pedido quedaba en otra frase y se perdía.
   Una charla larga o la tele de fondo nunca llegan a Whisper.
3. Con calibración de voz, la huella descarta frases de otras personas.
4. Whisper `base` (~0,85 s por frase; `small` tardaba 2,7 s) transcribe con «Gema»
   como palabra favorecida, y la frase se compara por cómo suena, no letra por letra:
   base escribe «Oye Gema», «Hoy ejema», «Oye, Hema» o «Oye Gemma» para lo mismo
   (banco con voces sintéticas del 2026-11-15, `tests/test_wake_word.py`).

Nunca se guarda audio ni se registra lo dicho: sólo cuántas frases se revisaron
y cuántas activaron a Gema.
"""
from collections import deque
from difflib import SequenceMatcher
import logging
import re
import threading
import time
import unicodedata

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
FRAME = 512                       # 32 ms, lo que pide Silero
WAKE_KEY = "oyeJema"              # «oye gema» tal como suena (ver `sound_key`)
WAKE_THRESHOLD = .88              # «oye tema» (.857) queda afuera, «Oye, Hema» (.92) adentro
WAKE_HOTWORDS = "Gema"            # «Oye Gema» como hotword hacía que Whisper se comiera la frase
WAKE_MODELS = ("base", "tiny", "small", "medium")  # el primero instalado; base es el equilibrio


def _plain(text):
    text = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def sound_key(word):
    """Cómo suena una palabra, para comparar transcripciones desprolijas.

    La h no suena; g y c delante de e/i, j, k y qu se parecen lo suficiente como
    para que Whisper las confunda en «Gema» («Jema», «Cema», «quema»): son una
    sola letra J. ll e y, también. Las letras dobles cuentan una vez («Gemma»).
    La t queda aparte a propósito: «oye, tema» no es «Oye Gema».
    """
    w = re.sub(r"[^a-zñ]", "", _plain(word))
    w = w.replace("ll", "y").replace("qu", "J").replace("h", "")
    w = re.sub(r"[gc](?=[ei])", "J", w)
    w = w.replace("j", "J").replace("k", "J")
    w = re.sub(r"oi$", "oy", w)
    return re.sub(r"(.)\1+", r"\1", w)


def find_wake(text):
    """Si la frase empieza con «Oye Gema», devuelve lo que sigue (puede ser ""). Si no, None.

    Busca en las primeras palabras: se admite algo antes («eh, oye Gema»), pero no
    «la gema del anillo» ni «oye, ¿qué tema es este?».
    """
    words = [w for w in re.findall(r"[\wáéíóúüñÁÉÍÓÚÜÑ]+|[^\w\s]", text or "") if w.strip()]
    keys, owner = "", []  # owner[i]: palabra a la que pertenece la letra i de keys
    for index, word in enumerate(words[:6]):
        key = sound_key(word)
        keys += key
        owner += [index] * len(key)
    best, end = 0., None
    # El fragmento empieza y termina en el borde de una palabra: si no, «oye, gemelos»
    # («oyeJem…») o «yo y Gema» («…oyJema») pasaban por «Oye Gema».
    starts = [i for i in range(min(4, len(keys))) if i == 0 or owner[i] != owner[i - 1]]
    for start in starts:
        for size in (5, 6, 7, 8, 9):
            piece = keys[start:start + size]
            stop = start + len(piece) - 1
            if len(piece) < 5 or (stop + 1 < len(keys) and owner[stop + 1] == owner[stop]):
                continue
            score = SequenceMatcher(None, piece, WAKE_KEY).ratio()
            if score > best:
                best, end = score, start + len(piece) - 1
    if best < WAKE_THRESHOLD or end is None:
        return None
    rest = words[owner[end] + 1:]
    while rest and not re.match(r"[\w¿¡«]", rest[0]):
        rest = rest[1:]  # la coma o el cierre después de «Gema»; «¿» abre el pedido y queda
    text_rest = " ".join(rest)
    return re.sub(r"\s+([,.;:!?…»])", r"\1", re.sub(r"([¿¡«])\s+", r"\1", text_rest)).strip()


class VoiceCheck:
    """¿La frase es del usuario? Con la huella de la calibración de voz.

    La frase de activación es corta (~1 s) y la huella se calibró con ventanas de
    1,5 s, así que se acepta hasta MARGIN por debajo del umbral: ante la duda,
    Gema escucha (lo peor es un «no se escuchó nada»), y la tele queda muy abajo.
    """
    MARGIN = .1

    def __init__(self, model, voiceprint):
        self.model, self.embedding = model, voiceprint["embedding"]
        self.threshold = voiceprint["threshold"] - self.MARGIN

    def __call__(self, audio):
        from speaker import cosine
        score = cosine(self.model.embed(audio), self.embedding)
        return score >= self.threshold, score


class WakeListener:
    """Hilo propio. `on_wake(audio, resto, después)` se llama con el micrófono ya cerrado.

    `después` es lo que se grabó mientras Whisper revisaba la frase (~0,85 s): si el
    usuario dijo «Oye Gema…» con una pausa larga y siguió con el pedido, el comienzo
    no se pierde al pasarle el micrófono al dictado."""

    # MIN_S cuenta sólo voz: el colchón previo y el silencio final no hacen pasar un golpe.
    # MAX_S se mide sin el silencio del final.
    MIN_S, MAX_S, SILENCE_S, PREROLL_S = .35, 6., .7, .3

    def __init__(self, recorder_factory, detector_factory, transcriber, on_wake, allowed,
                 voice_check=None, language="es", clock=time.monotonic):
        self.recorder_factory, self.detector_factory = recorder_factory, detector_factory
        self.transcriber, self.on_wake, self.allowed = transcriber, on_wake, allowed
        self.voice_check, self.language, self.clock = voice_check, language, clock
        self.state, self.message = "off", ""
        self.counts = dict(phrases=0, other_voice=0, checked=0, activations=0)
        self._closed = threading.Event()
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._run, name="OyeGema", daemon=True)
        self._thread.start()
        if hasattr(self.transcriber, "preload"):  # que la primera activación no espere la carga
            threading.Thread(target=self.transcriber.preload, name="OyeGemaLoad", daemon=True).start()

    def close(self):
        self._closed.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=3)

    def snapshot(self):
        return dict(state=self.state, message=self.message, voice_check=self.voice_check is not None, **self.counts)

    def _run(self):
        while not self._closed.is_set():
            if not self.allowed():
                self.state = "off"
                self._closed.wait(.25)
                continue
            try:
                heard = self._listen()
            except Exception as exc:
                logger.warning("«Oye Gema» sin micrófono: %s", exc)
                self.state, self.message = "error", f"«Oye Gema» no puede usar el micrófono: {exc}"
                self._closed.wait(5)
                continue
            if heard is not None:
                self.counts["activations"] += 1
                logger.info("«Oye Gema»: activación (%s)", "con pedido" if heard[1] else "sin pedido")
                try:
                    self.on_wake(*heard)
                except Exception:
                    logger.exception("«Oye Gema»: no se pudo abrir a Gema")
                self._closed.wait(.5)  # que el dictado tome el micrófono antes de volver a mirar

    def _listen(self):
        """Escucha hasta oír «Oye Gema» (devuelve (audio, resto)) o hasta que deje de estar permitido."""
        import numpy as np
        detector = self.detector_factory()
        preroll = deque(maxlen=max(1, int(self.PREROLL_S * SAMPLE_RATE / FRAME)))
        silence_limit = int(self.SILENCE_S * SAMPLE_RATE / FRAME)
        max_frames = int(self.MAX_S * SAMPLE_RATE / FRAME)
        phrase, quiet, too_long, voiced = None, 0, False, 0
        pending = np.zeros(0, np.float32)
        with self.recorder_factory() as recorder:
            self.state, self.message = "listening", ""
            last_audio = self.clock()
            while not self._closed.is_set() and self.allowed():
                block = recorder.read(timeout=.2)
                if block is None:
                    if self.clock() - last_audio >= 2:
                        raise RuntimeError("el micrófono dejó de enviar audio")
                    continue
                last_audio = self.clock()
                pending = np.concatenate([pending, np.asarray(block, np.float32)])
                while len(pending) >= FRAME:
                    frame, pending = pending[:FRAME], pending[FRAME:]
                    speech = detector.speech(frame)
                    if phrase is None:
                        if speech:
                            phrase, quiet, too_long, voiced = list(preroll) + [frame], 0, False, 1
                        else:
                            preroll.append(frame)
                        continue
                    if not too_long:
                        phrase.append(frame)
                        too_long = len(phrase) - quiet > max_frames
                    quiet = 0 if speech else quiet + 1
                    voiced += bool(speech)
                    if quiet < silence_limit:
                        continue
                    audio = None if too_long else np.concatenate(phrase)
                    phrase = None
                    preroll.clear()
                    if audio is None or voiced * FRAME < self.MIN_S * SAMPLE_RATE:
                        continue
                    rest = self._check(audio)
                    if rest is not None:
                        return audio, rest, self._drain(pending, recorder)
        return None

    @staticmethod
    def _drain(pending, recorder):
        import numpy as np
        blocks = [pending]
        while (block := recorder.read(timeout=0)) is not None and len(block):
            blocks.append(np.asarray(block, np.float32))
            if sum(len(b) for b in blocks) > 3 * SAMPLE_RATE:
                break  # con un micrófono que no para de mandar, alcanza con lo último
        return np.concatenate(blocks)

    def _check(self, audio):
        self.counts["phrases"] += 1
        if self.voice_check is not None:
            own, score = self.voice_check(audio)
            if not own:
                self.counts["other_voice"] += 1
                logger.debug("«Oye Gema»: otra voz (%.2f)", score)
                return None
        self.state = "checking"
        try:
            self.counts["checked"] += 1
            text = self.transcriber.transcribe(audio, self.language, hotwords=WAKE_HOTWORDS)
        finally:
            self.state = "listening"
        return find_wake(text)


def wake_transcriber(config):
    """Whisper chico para la frase de activación: base si está, si no el del dictado."""
    from dictation import WhisperTranscriber, installed_model
    model = next((m for m in WAKE_MODELS if installed_model(m) is not None), config.model)
    return WhisperTranscriber(model)


def voice_check(config, voiceprint):
    if not voiceprint or not config.speaker_check:
        return None
    try:
        from speaker import SpeakerModel
        return VoiceCheck(SpeakerModel(), voiceprint)
    except Exception:
        logger.warning("«Oye Gema» sin huella de voz: cualquier voz puede activar a Gema", exc_info=True)
        return None
