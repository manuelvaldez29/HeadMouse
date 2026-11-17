"""Banco de comandos de voz: «borrar», «deshacer» y los pedidos a Gema («abrí …»).

Usa el mismo camino que la app: el fin de frase del dictado (Silero), Whisper con el
modelo y las palabras frecuentes de la configuración, `parse_command` para los comandos
de edición y, para Gema, `assistant.parse` más el índice del menú Inicio. No escribe,
no borra y no abre nada: sólo muestra qué hubiera hecho.

    python tools/banco_comandos.py
        Te pide cada frase y muestra qué entendió y qué hubiera hecho.

    python tools/banco_comandos.py --grabar CARPETA
        Además guarda cada frase como WAV para ajustar los comandos con tu voz.
        Son grabaciones tuyas y quedan en tu PC: borralas cuando ya no hagan falta.

    python tools/banco_comandos.py --archivos CARPETA
        Vuelve a evaluar las grabaciones de CARPETA (para comparar ajustes).
"""
import argparse
import sys
import time
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from assistant import AppIndex, parse  # noqa: E402
from config import VoiceConfig  # noqa: E402
from dictation import Endpointer, SileroDetector, SoundDeviceRecorder, WhisperTranscriber, parse_command  # noqa: E402

# (modo, frase, lo esperado). Dictado: lo que devuelve parse_command (None = es texto).
# Gema: tipo de comando, y para «open» el programa que debería abrir.
PROMPTS = [
    ("dictado", "Borrar", ("last", 1)), ("gema", "Abrí el bloc de notas", ("open", "bloc de notas")),
    ("dictado", "Borrar todo", ("all", 1)), ("gema", "Abrí WhatsApp", ("open", "whatsapp")),
    ("dictado", "Borrar", ("last", 1)), ("gema", "Abrí la calculadora", ("open", "calculadora")),
    ("dictado", "Deshacer", ("undo", 1)), ("gema", "Abrir el explorador de archivos", ("open", "explorador")),
    ("dictado", "Borrar dos palabras", ("word", 2)), ("gema", "Abrí la configuración", ("open", "configuraci")),
    ("dictado", "Borrar", ("last", 1)), ("gema", "Subí el volumen", ("volume_up", None)),
    ("dictado", "Borrar tres letras", ("char", 3)), ("gema", "Abrí Chrome", ("open", "chrome")),
    ("dictado", "Borrar", ("last", 1)), ("gema", "Buscar recetas de empanadas", ("search", None)),
    ("dictado", "Nos vemos mañana en la facultad", None), ("dictado", "Deshacer", ("undo", 1)),
    ("dictado", "Borrar eso", ("last", 1)), ("dictado", "Hay que borrar la pizarra", None),
]


class TeeRecorder:
    def __init__(self, inner):
        self.inner, self.blocks = inner, []

    def __enter__(self):
        self.inner.__enter__()
        return self

    def read(self, timeout=.2):
        block = self.inner.read(timeout)
        if block is not None:
            self.blocks.append(np.asarray(block, np.float32))
        return block

    def __exit__(self, *exc):
        return self.inner.__exit__(*exc)


class ArrayRecorder:
    def __init__(self, audio):
        self.audio = np.concatenate([audio, np.zeros(16000 * 2, np.float32)])

    def __enter__(self):
        self.position = 0
        return self

    def read(self, timeout=.2):
        block = self.audio[self.position:self.position + 480]
        self.position += 480
        return block if len(block) else None

    def __exit__(self, *exc):
        pass


def listen(recorder, config, session):
    """Como `Dictation._session`: hasta que el fin de frase termina o vence."""
    endpoint = Endpointer(config.silence_s, config.max_utterance_s, config.no_speech_timeout_s,
                          detector=SileroDetector(session))
    with recorder:
        while endpoint.state not in ("done", "timeout"):
            block = recorder.read(.2)
            if block is None:
                break
            endpoint.feed(block)
    return np.asarray(endpoint.audio(), np.float32) if endpoint.state == "done" else None


def save(path, blocks):
    audio = np.clip(np.concatenate(blocks or [np.zeros(1, np.float32)]), -1, 1)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes((audio * 32767).astype(np.int16).tobytes())


def load(path):
    with wave.open(str(path)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768


def judge(mode, expected, text, apps):
    """(bien, qué hubiera hecho)."""
    if mode == "dictado":
        got = parse_command(text)
        return got == expected, (f"comando {got[0]} ×{got[1]}" if got else "lo escribe como texto")
    command = parse(text)
    if command is None:
        return False, "Gema no entiende el pedido"
    if command.kind != expected[0]:
        return False, f"Gema haría «{command.kind}»"
    if command.kind == "open":
        found = apps.find(command.argument)
        title = found[0] if found else None
        return bool(title and expected[1] in title.lower()), (f"abriría «{title}»" if title else
                                                              f"no encuentra «{command.argument}» en el menú Inicio")
    return True, f"haría «{command.kind}»"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--grabar", type=Path, metavar="CARPETA")
    parser.add_argument("--archivos", type=Path, metavar="CARPETA")
    parser.add_argument("--vueltas", type=int, default=1)
    args = parser.parse_args(argv)
    from profiles import ProfileStore
    store = ProfileStore()
    config = VoiceConfig()
    try:  # el modelo y las palabras frecuentes del último perfil, como en la app
        import json
        from app_paths import data_root
        last = json.loads((data_root() / "last_profile.json").read_text(encoding="utf-8"))["user_id"]
        config = VoiceConfig(**{k: v for k, v in store.load(last).get("settings", {}).get("voice", {}).items()
                                if k in VoiceConfig.__dataclass_fields__})
    except Exception:
        pass
    print(f"Modelo {config.model} · palabras frecuentes: {config.vocabulary or '(ninguna)'}")
    transcriber = WhisperTranscriber(config.model)
    transcriber._load()
    apps = AppIndex()
    session = SileroDetector.load_session()
    script = PROMPTS * max(1, args.vueltas)
    rows = []
    if args.archivos:
        files = sorted(args.archivos.glob("*.wav"))
        items = [(PROMPTS[(int(f.name[:2]) - 1) % len(PROMPTS)], f) for f in files]
    else:
        items = [(p, None) for p in script]
        print("Decí cada frase cuando aparezca. "
              + (f"Se guarda en {args.grabar}.\n" if args.grabar else "No se guarda nada.\n"))
    for number, ((mode, phrase, expected), path) in enumerate(items, 1):
        if path is None:
            print(f"[{number}/{len(items)}] {'Dictado' if mode == 'dictado' else 'Gema'} → «{phrase}»")
            recorder = TeeRecorder(SoundDeviceRecorder(config.microphone))
            audio = listen(recorder, config, session)
            if args.grabar:
                slug = "".join(c if c.isalnum() else "_" for c in phrase.lower())[:28].strip("_")
                save(args.grabar / f"{number:02d}_{mode}_{slug}.wav", recorder.blocks)
        else:
            audio = listen(ArrayRecorder(load(path)), config, session)
        if audio is None:
            rows.append((mode, False))
            print("   MAL: no se oyó la frase\n" if path is None else f"MAL  {path.stem}: no se oyó la frase")
            continue
        started = time.perf_counter()
        text = transcriber.transcribe(audio, config.language, hotwords=config.vocabulary)
        ok, effect = judge(mode, expected, text, apps)
        rows.append((mode, ok))
        mark = "bien" if ok else "MAL "
        line = f"entendió «{text}» → {effect} ({time.perf_counter() - started:.1f} s)"
        print(f"   {mark.strip()}: {line}\n" if path is None else f"{mark} {path.stem[:30]:30s} {line}")
    for mode, title in (("dictado", "Comandos de dictado"), ("gema", "Pedidos a Gema")):
        done = [ok for m, ok in rows if m == mode]
        if done:
            print(f"{title}: {sum(done)}/{len(done)} bien")


if __name__ == "__main__":
    main()
