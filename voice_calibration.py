"""Calibración de voz: silencio de la sala y cuatro frases. Sin Qt; hilo propio.

Mide el ruido de la sala, el nivel de la voz y cuánto entiende Whisper, y arma
la huella de voz (speaker.enroll) para que el dictado ignore otras voces. El
resultado va al perfil como `voice_calibration`; nunca se guarda audio.
"""
import logging
import math
import re
import threading
import time
import unicodedata
from datetime import datetime, timezone

from dictation import SAMPLE_RATE, Endpointer

logger = logging.getLogger(__name__)

PHRASES = (
    "Hoy quiero escribir un mensaje corto.",
    "Mañana a las nueve tengo turno con el médico.",
    "Por favor, abrí el correo y leeme lo último.",
    "Necesito comprar pan, leche y fruta.",
)
SILENCE_S = 3.0


def words(text):
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.findall(r"[a-zñ0-9]+", text)


NUMBERS = {"9": "nueve"}


def word_accuracy(reference, hypothesis):
    """1 − distancia de edición por palabras / palabras de la referencia (0 a 1)."""
    ref = words(reference)
    hyp = [NUMBERS.get(w, w) for w in words(hypothesis)]
    d = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        previous, d[0] = d[0], i
        for j, h in enumerate(hyp, 1):
            previous, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, previous + (r != h))
    return max(0., 1 - d[-1] / max(1, len(ref)))


def rms(samples):
    return math.sqrt(sum(v * v for v in samples) / len(samples)) if samples else 0.


def recommendations(result, model_name):
    tips = []
    if result["snr_db"] < 10:
        tips.append("Hay bastante ruido para tu voz. Un micrófono de auricular, o acercarte al micrófono, "
                    "ayuda más que cualquier ajuste. En Windows 11 probá Configuración → Sonido → "
                    "micrófono → Efectos de voz (supresión de ruido).")
    if result["speech_in_silence"] > .2:
        tips.append("Durante el silencio se escuchó voz (tele o gente hablando). La huella de voz corta el "
                    "dictado cuando dejás de hablar; si no corta, terminá con tu gesto de click.")
    if result["accuracy"] < .8:
        tips.append(f"Whisper entendió el {result['accuracy']:.0%} de las palabras. Hablá un poco más lento"
                    + (" o probá el modelo «small», más preciso." if model_name in ("tiny", "base") else "."))
    if result["voiceprint"] is None:
        tips.append("Prepará el reconocimiento de voz en Configuración para que el dictado ignore otras voces, "
                    "y repetí esta calibración.")
    if not tips:
        tips.append("Sala y micrófono en buen estado: el dictado debería funcionar bien.")
    return tips


class VoiceCalibration:
    """Estados: ready → silence → phrase → processing → done | error | cancelled."""

    def __init__(self, config, recorder_factory, transcriber, detector_factory=None, speaker_model=None,
                 clock=time.monotonic, phrases=PHRASES, silence_s=SILENCE_S):
        self.config, self.recorder_factory, self.transcriber = config, recorder_factory, transcriber
        self.detector_factory, self.speaker_model, self.clock = detector_factory, speaker_model, clock
        self.phrases, self.silence_s = tuple(phrases), silence_s
        self.state, self.index, self.message, self.level = "ready", 0, "", 0.
        self.result = None
        self._cancel = threading.Event()
        self._lock = threading.Lock()
        self._thread = None

    def start(self):
        self._set("silence", "Preparando micrófono…")
        self._thread = threading.Thread(target=self._run, name="VoiceCalibration", daemon=True)
        self._thread.start()

    def cancel(self):
        self._cancel.set()

    def join(self, timeout=None):
        if self._thread:
            self._thread.join(timeout)

    def snapshot(self):
        with self._lock:
            total = len(self.phrases)
            steps = {"ready": 0, "silence": 0, "phrase": 1 + self.index, "processing": 1 + total, "done": 2 + total}
            return dict(state=self.state, phrase=self.phrases[self.index] if self.state == "phrase" else "",
                        index=self.index, total=total, message=self.message, level=round(self.level, 4),
                        progress=steps.get(self.state, 0) / (2 + total), result=self.result)

    def _set(self, state, message, index=None):
        with self._lock:
            self.state, self.message = state, message
            if index is not None:
                self.index = index

    def _run(self):
        try:
            if self._cancel.is_set():
                self._set("cancelled", "Calibración cancelada.")
                return
            with self.recorder_factory() as recorder:
                noise, speech_share = self._silence(recorder)
                if noise is None:
                    return
                captured = []
                for i, phrase in enumerate(self.phrases):
                    audio = self._phrase(recorder, i, phrase)
                    if audio is None:
                        return
                    captured.append(audio)
            self._finish(noise, speech_share, captured)
        except Exception as exc:
            logger.exception("Calibración de voz interrumpida")
            self._set("error", f"No se pudo calibrar la voz: {exc}")

    def _read(self, recorder):
        block = recorder.read(timeout=.2)
        if block is not None:
            with self._lock:
                self.level = rms(list(block))
        return block

    def _silence(self, recorder):
        self._set("silence", "Quedate en silencio unos segundos: estoy escuchando tu sala.")
        samples, started = [], self.clock()
        while len(samples) < self.silence_s * SAMPLE_RATE:
            if self._cancel.is_set():
                self._set("cancelled", "Calibración de voz cancelada.")
                return None, None
            if self.clock() - started > self.silence_s + 5:
                raise RuntimeError("el micrófono no entrega audio")
            block = self._read(recorder)
            if block is not None:
                samples.extend(float(v) for v in block)
        share = 0.
        if self.detector_factory:
            detector = self.detector_factory()
            frames = [samples[i:i + detector.frame] for i in range(0, len(samples) - detector.frame + 1, detector.frame)]
            share = sum(detector.speech(f) for f in frames) / max(1, len(frames))
        return samples, share

    def _phrase(self, recorder, index, phrase):
        for attempt in (1, 2):
            self._set("phrase", ("Leé en voz alta, como hablás siempre:" if attempt == 1 else
                                 "No te escuché bien. Leé de nuevo, un poco más fuerte:"), index)
            endpoint = Endpointer(silence_s=1.0, max_s=15, no_speech_s=8,
                                  detector=self.detector_factory() if self.detector_factory else None)
            while endpoint.state not in ("done", "timeout"):
                if self._cancel.is_set():
                    self._set("cancelled", "Calibración de voz cancelada.")
                    return None
                block = self._read(recorder)
                if block is not None:
                    endpoint.feed(block)
            if endpoint.state == "done" and len(endpoint.audio()) >= SAMPLE_RATE * .6:
                return endpoint.audio()
        self._set("error", "No escuché las frases. Revisá que el micrófono esté conectado y elegido en Windows.")
        return None

    def _finish(self, noise, speech_share, captured):
        self._set("processing", "Analizando tu voz… tarda unos segundos.")
        accuracy = []
        for phrase, audio in zip(self.phrases, captured):
            if self._cancel.is_set():
                self._set("cancelled", "Calibración de voz cancelada.")
                return
            accuracy.append(word_accuracy(phrase, self.transcriber.transcribe(audio, self.config.language)))
        voiced = [v for audio in captured for v in audio if abs(v) > .01]
        noise_rms, voice_rms = max(rms(noise), 1e-5), rms(voiced) or rms([v for a in captured for v in a])
        voiceprint = None
        if self.speaker_model is not None:
            import numpy as np
            from speaker import enroll
            voiceprint = enroll(self.speaker_model, [np.asarray(a, np.float32) for a in captured],
                                room_noise=np.asarray(noise, np.float32))
        result = dict(version=1, calibrated_at=datetime.now(timezone.utc).isoformat(),
                      noise_rms=round(noise_rms, 6), voice_rms=round(voice_rms, 6),
                      snr_db=round(20 * math.log10(voice_rms / noise_rms), 1),
                      speech_in_silence=round(speech_share, 3),
                      accuracy=round(sum(accuracy) / len(accuracy), 3),
                      phrase_accuracy=[round(a, 3) for a in accuracy],
                      model=self.config.model, voiceprint=voiceprint)
        result["recommendations"] = recommendations(result, self.config.model)
        with self._lock:
            if self._cancel.is_set():
                self.state, self.message = "cancelled", "Calibración de voz cancelada."
                return
            self.result = result
            self.state, self.message = "done", "Listo. Revisá el resultado y guardalo en tu perfil."


def validate_voice_calibration(record):
    """Lo que se guarda en el perfil: números finitos, y la huella si la hay."""
    if not isinstance(record, dict) or record.get("version") != 1:
        raise ValueError("Calibración de voz inválida")
    for name, low, high in (("noise_rms", 0, 1), ("voice_rms", 0, 1), ("snr_db", -60, 120),
                            ("speech_in_silence", 0, 1), ("accuracy", 0, 1)):
        value = record.get(name)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f"Calibración de voz inválida: {name}")
    if record.get("voiceprint") is not None:
        from speaker import validate_voiceprint
        validate_voiceprint(record["voiceprint"])
