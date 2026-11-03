"""Huella de la voz del usuario: sin Qt ni micrófono; el modelo se carga al usarlo.

Sirve para un solo problema: con otra persona o la tele hablando de fondo, el
detector de voz (Silero) oye habla todo el tiempo y el dictado no termina nunca.
La huella dice cuándo dejó de hablar el usuario. Se usa del lado seguro:
- sólo decide el final y recorta la cola; nunca borra palabras del medio;
- el umbral sale de la calibración del usuario, y además se compara con cómo
  sonaba al empezar ese mismo dictado: si el ruido cambió (ventilador prendido
  después de calibrar), el umbral baja y no corta en medio de una frase.

Banco del 2026-11-03 (WeSpeaker ResNet34, voces sintéticas de Windows): con la
tele hablando sin parar, a 10 y 6 dB por debajo, cortó 1,6-2,2 s después de las
12 frases y nunca antes. Sin la huella no cortaba ninguna.
"""
import hashlib
import logging
import math
from pathlib import Path

from app_paths import RESOURCE_ROOT, data_root

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
MODEL_NAME = "wespeaker_en_voxceleb_resnet34.onnx"
MODEL_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/"
             "speaker-recongition-models/" + MODEL_NAME)
MODEL_SHA256 = "5ef208a9da1453335308a6b6f4e6dfbd7e183a38b604de0a57664f45d257fe94"
MODEL_DIRS = (data_root() / "models" / "speaker", RESOURCE_ROOT / "models" / "speaker")


def model_path():
    """Modelo instalado, o None. Se descarga a la carpeta de datos."""
    return next((d / MODEL_NAME for d in MODEL_DIRS if (d / MODEL_NAME).is_file()), None)


def download_model():
    import os
    import tempfile
    import urllib.request
    target = MODEL_DIRS[0] / MODEL_NAME
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=target.parent, suffix=".part")
    os.close(handle)
    try:
        urllib.request.urlretrieve(MODEL_URL, temporary)
        digest = hashlib.sha256(Path(temporary).read_bytes()).hexdigest()
        if digest != MODEL_SHA256:
            raise ValueError("El modelo de reconocimiento de voz descargado no coincide con el esperado")
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)
    logger.info("Modelo de reconocimiento de voz preparado: %s", target)
    return target


def _unit(vector):
    norm = math.sqrt(sum(v * v for v in vector))
    return [v / norm for v in vector] if norm > 0 else list(vector)


def cosine(a, b):
    return sum(x * y for x, y in zip(a, b))


class SpeakerModel:
    """WeSpeaker por sherpa-onnx: 256 números por fragmento de voz (~60 ms por 1,5 s)."""

    def __init__(self, path=None, threads=2):
        import sherpa_onnx
        path = path or model_path()
        if path is None:
            raise FileNotFoundError("Falta el modelo de reconocimiento de voz: preparalo en Configuración")
        config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(path), num_threads=threads)
        self._extractor = sherpa_onnx.SpeakerEmbeddingExtractor(config)

    def embed(self, samples):
        import numpy as np
        stream = self._extractor.create_stream()
        stream.accept_waveform(SAMPLE_RATE, np.asarray(samples, dtype=np.float32))
        stream.input_finished()
        return _unit(self._extractor.compute(stream))


def windows(samples, seconds=1.5):
    """Ventanas de `seconds` con salto de la mitad (la frase entera si es más corta)."""
    n = int(seconds * SAMPLE_RATE)
    if len(samples) <= n:
        return [samples]
    return [samples[i:i + n] for i in range(0, len(samples) - n + 1, n // 2)]


def enroll(model, phrases, room_noise=None, margin=.14):
    """Huella y umbral a partir de las frases de la calibración.

    Cada frase entra tal cual y, si hay ruido de la sala, también con ese ruido
    reforzado: la huella grabada sólo en silencio confundía al usuario con ruido
    de ventilador, y la grabada sólo con ruido, al revés (banco del 2026-11-03).
    El umbral sale de dejar una frase afuera: el p10 de sus ventanas menos 0,14,
    entre 0,5 y 0,75. Inclinado a aceptar: ante la duda, no corta.
    """
    import numpy as np
    if len(phrases) < 2:
        raise ValueError("Hacen falta al menos dos frases para la huella de voz")
    variants = [[np.asarray(p, np.float32)] for p in phrases]
    noise = np.asarray(room_noise if room_noise is not None else [], np.float32)
    if len(noise) < SAMPLE_RATE // 2 or np.std(noise) < 1e-4:
        # Sala en silencio digital: ruido marrón genérico, para que la huella no quede
        # sólo "de silencio" (con ventilador después confundía al usuario con otros).
        rng = np.random.default_rng(0)
        noise = np.cumsum(rng.normal(0, 1, SAMPLE_RATE * 3)).astype(np.float32)
        noise -= np.convolve(noise, np.ones(400, np.float32) / 400, "same")
    for group in variants:
        phrase = group[0]
        voiced = phrase[np.abs(phrase) > .01]
        level = float(np.sqrt(np.mean(voiced ** 2))) if len(voiced) else float(np.std(phrase))
        reps = np.resize(noise, len(phrase))
        group.append((phrase + reps * (level / max(float(np.std(reps)), 1e-9)) / 10 ** .5).astype(np.float32))  # 10 dB abajo
    embeddings = [[model.embed(v) for v in group] for group in variants]
    profile = _unit([sum(col) / len(col) for col in zip(*(e for group in embeddings for e in group))])
    scores = []
    for i, group in enumerate(variants):
        rest = [e for j, g in enumerate(embeddings) if j != i for e in g]
        held_out = _unit([sum(col) / len(col) for col in zip(*rest)])
        scores += [cosine(model.embed(w), held_out) for v in group for w in windows(v)]
    p10 = sorted(scores)[max(0, int(len(scores) * .1) - 1)]
    threshold = min(.75, max(.5, p10 - margin))
    return dict(embedding=[round(v, 6) for v in profile], threshold=round(threshold, 4),
                self_score_p10=round(p10, 4), model=MODEL_NAME)


def validate_voiceprint(record):
    if not isinstance(record, dict) or record.get("model") != MODEL_NAME:
        raise ValueError("Huella de voz inválida o de otro modelo")
    embedding, threshold = record.get("embedding"), record.get("threshold")
    if not isinstance(embedding, list) or len(embedding) != 256 or not all(
            isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in embedding):
        raise ValueError("Huella de voz inválida")
    if not isinstance(threshold, (int, float)) or isinstance(threshold, bool) or not .3 <= threshold <= .9:
        raise ValueError("Umbral de huella de voz inválido")


class SpeakerGate:
    """Durante un dictado: ¿sigue hablando el usuario? Para que el Endpointer termine.

    Cada `hop_frames` tramas (0,5 s) compara la huella con la última ventana de
    1,5 s de audio desde que empezó el habla. Es del usuario si supera el menor
    entre el umbral calibrado y su mejor puntaje de las primeras ventanas menos
    `START_MARGIN`. Las primeras ventanas siempre cuentan como suyas: acaba de
    hacer click para dictar. El mejor y no el primero, porque la tele puede estar
    hablando desde antes y la primera ventana ser casi toda de ella.
    """
    HOP_FRAMES, WINDOW_FRAMES, MIN_FRAMES = 16, 47, 32  # tramas de 32 ms
    START_WINDOWS, START_MARGIN = 3, .12

    def __init__(self, model, voiceprint):
        self.model, self.embedding, self.threshold = model, voiceprint["embedding"], voiceprint["threshold"]
        self.start_score = None
        self.last_own = None
        self.scores = []

    def update(self, frames, speech_start):
        """Llamar con cada trama nueva durante el habla. Devuelve True si hubo ventana nueva."""
        n = len(frames)
        if n - speech_start < self.MIN_FRAMES or n % self.HOP_FRAMES:
            return False
        window = [v for chunk in frames[max(speech_start, n - self.WINDOW_FRAMES):n] for v in chunk]
        score = cosine(self.model.embed(window), self.embedding)
        self.scores.append(score)
        if len(self.scores) <= self.START_WINDOWS:
            self.start_score = max(self.scores)
            self.last_own = n
        elif score >= min(self.threshold, self.start_score - self.START_MARGIN):
            self.last_own = n
        return True

    def silent_frames(self, n):
        """Tramas desde la última ventana del usuario (None si todavía no hubo ninguna)."""
        return None if self.last_own is None else n - self.last_own
