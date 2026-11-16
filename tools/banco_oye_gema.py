"""Banco de «Oye Gema»: cuántas veces se activa cuando corresponde y cuántas sin querer.

Usa el mismo camino que la app (Silero → huella de voz → Whisper chico → comparación
por sonido) sin abrir la cámara ni mover el mouse, y no guarda audio.

    python tools/banco_oye_gema.py --microfono
        Te pide frases en voz alta: unas con «Oye Gema», otras parecidas sin ella.
        Al final muestra aciertos, activaciones sin querer y cuánto tardó.

    python tools/banco_oye_gema.py --microfono --libre 120
        Dos minutos con el micrófono abierto mientras hablás normal, mirás un video o
        hay gente charlando: cuenta las activaciones sin querer.

    python tools/banco_oye_gema.py carpeta_con_wav
        Archivos WAV mono de 16 kHz; los que empiezan con «pos» deberían activar a Gema.
"""
import argparse
import sys
import time
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import VoiceConfig  # noqa: E402
from dictation import SileroDetector, SoundDeviceRecorder  # noqa: E402
from wake_word import FRAME, WAKE_HOTWORDS, WakeListener, find_wake, voice_check, wake_transcriber  # noqa: E402

PROMPTS = [
    (True, "Oye Gema"), (False, "Oye, ¿me pasás el mate?"), (True, "Oye Gema, abrí el bloc de notas"),
    (False, "Hoy tengo que ir a la facultad"), (True, "Oye Gema, ¿qué hora es?"),
    (False, "Oye, ¿qué tema es este?"), (True, "Oye Gema, subí el volumen"),
    (False, "La gema del anillo es azul"), (True, "Oye Gema"), (False, "Tenemos un problema con el sistema"),
    (True, "Oye Gema, buscar recetas de empanadas"), (False, "Me quemé con la yema del huevo"),
]


class ArrayRecorder:
    """Un WAV como si fuera el micrófono, seguido de silencio."""
    def __init__(self, audio):
        self.audio = np.concatenate([audio, np.zeros(16000, np.float32)])

    def __enter__(self):
        self.position = 0
        return self

    def read(self, timeout=.2):
        block = self.audio[self.position:self.position + 480]
        self.position += 480
        return block if len(block) else None

    def __exit__(self, *exc):
        pass


def load_wav(path):
    with wave.open(str(path)) as w:
        if w.getframerate() != 16000 or w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise ValueError(f"{path.name}: tiene que ser WAV mono de 16 kHz y 16 bits")
        return np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768


def phrases(recorder, detector, seconds):
    """Frases como las corta WakeListener (mismos límites), para medir sin hilos."""
    listener = WakeListener(None, None, None, None, None)
    found, stop = [], time.monotonic() + seconds
    pending, phrase, quiet, voiced = np.zeros(0, np.float32), None, 0, 0
    silence_limit = int(listener.SILENCE_S * 16000 / FRAME)
    with recorder:
        while time.monotonic() < stop:
            block = recorder.read(.2)
            if block is None:
                break
            pending = np.concatenate([pending, np.asarray(block, np.float32)])
            while len(pending) >= FRAME:
                frame, pending = pending[:FRAME], pending[FRAME:]
                speech = detector.speech(frame)
                if phrase is None:
                    if speech:
                        phrase, quiet, voiced = [frame], 0, 1
                    continue
                phrase.append(frame)
                quiet = 0 if speech else quiet + 1
                voiced += bool(speech)
                if quiet >= silence_limit:
                    audio = np.concatenate(phrase)
                    ok = voiced * FRAME >= listener.MIN_S * 16000 and len(audio) - quiet * FRAME <= listener.MAX_S * 16000
                    found.append((audio, ok))
                    phrase = None
    return found


def judge(audio, transcriber, check):
    started = time.perf_counter()
    if check is not None:
        own, score = check(audio)
        if not own:
            return None, f"otra voz ({score:.2f})", time.perf_counter() - started
    text = transcriber.transcribe(audio, "es", hotwords=WAKE_HOTWORDS)
    return find_wake(text), text, time.perf_counter() - started


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("carpeta", nargs="?", type=Path)
    parser.add_argument("--microfono", action="store_true")
    parser.add_argument("--libre", type=float, metavar="SEGUNDOS", help="micrófono abierto sin guion")
    parser.add_argument("--perfil", help="id del perfil para usar su huella de voz")
    args = parser.parse_args(argv)
    config = VoiceConfig(enabled=True, wake_word=True)
    transcriber = wake_transcriber(config)
    transcriber._load()
    print(f"Modelo para «Oye Gema»: {transcriber.model_name}")
    check = None
    if args.perfil:
        from profiles import ProfileStore
        voiceprint = (ProfileStore().load(args.perfil).get("voice_calibration") or {}).get("voiceprint")
        check = voice_check(config, voiceprint)
        print("Con huella de voz." if check else "El perfil no tiene huella de voz.")
    session = SileroDetector.load_session()
    rows = []
    if args.carpeta:
        for path in sorted(args.carpeta.glob("*.wav")):
            heard = [judge(a, transcriber, check) if ok else (None, "(fuera de límites)", 0)
                     for a, ok in phrases(ArrayRecorder(load_wav(path)), SileroDetector(session), 60)]
            woke = any(rest is not None for rest, _text, _s in heard)
            seconds = max((s for _r, _t, s in heard), default=0)
            rows.append((path.stem.startswith("pos"), woke, seconds))
            print(f"{'GEMA' if woke else '    '}  {seconds:4.2f}s  {path.stem:18s} " + " | ".join(t for _r, t, _s in heard))
    elif args.microfono and args.libre:
        print(f"Micrófono abierto {args.libre:.0f} s: hablá normal, poné un video, charlá. Nada se guarda.")
        for audio, ok in phrases(SoundDeviceRecorder(), SileroDetector(session), args.libre):
            if ok:
                rest, _text, seconds = judge(audio, transcriber, check)
                rows.append((False, rest is not None, seconds))
                print("  ¡activación sin querer!" if rest is not None else "  frase revisada: no era «Oye Gema»")
    elif args.microfono:
        print("Decí cada frase cuando aparezca y esperá el resultado. Nada se guarda.\n")
        for expected, prompt in PROMPTS:
            print(f"→ «{prompt}»")
            heard = phrases(SoundDeviceRecorder(), SileroDetector(session), 6)
            results = [judge(a, transcriber, check) for a, ok in heard if ok]
            woke = any(r[0] is not None for r in results)
            rows.append((expected, woke, max((r[2] for r in results), default=0)))
            mark = "bien" if woke == expected else "MAL"
            print(f"   {mark}: {'Gema se activó' if woke else 'no se activó'}"
                  + (f" · entendió «{results[-1][1]}»" if results else " · no se oyó una frase") + "\n")
    else:
        parser.error("indicá una carpeta o --microfono")
    should = [r for r in rows if r[0]]
    should_not = [r for r in rows if not r[0]]
    print()
    if should:
        print(f"Activaciones correctas: {sum(r[1] for r in should)}/{len(should)}")
    print(f"Activaciones sin querer: {sum(r[1] for r in should_not)}/{len(should_not)} frases revisadas")
    times = sorted(r[2] for r in rows if r[2])
    if times:
        print(f"Tiempo de revisión: mediana {times[len(times) // 2]:.2f} s · máximo {times[-1]:.2f} s")


if __name__ == "__main__":
    main()
