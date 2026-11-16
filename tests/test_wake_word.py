"""«Oye Gema» (2026-11-15): activar a Gema con la voz. Sin micrófono ni Whisper reales."""
import threading
import time
import unittest
from unittest.mock import Mock

import numpy as np

from config import VoiceConfig
from dictation import Dictation, FocusInfo
from test_dictation import FakeFocus, FakeRecorder, noise, speech
from wake_word import WakeListener, find_wake, sound_key

# Transcripciones reales de Whisper tiny/base/small con voces sintéticas de Windows
# (banco del 2026-11-15): así escriben «Oye Gema» los modelos chicos.
HEARD_AS_WAKE = [
    ("Oye Gemma, abrí el blog de notas.", "abrí el blog de notas."),
    ("Oye, Gema, subí el volumen.", "subí el volumen."),
    ("Oye Gema", ""), ("¡Oye, Gema!", ""), ("Oye, Hema.", ""), ("¿Oye Cema?", ""),
    ("Hoy Egema, abri el blog de Notas.", "abri el blog de Notas."),
    ("Hoy Eje Ma, abri el blog de Notas.", "abri el blog de Notas."),
    ("Hoy ejema, abri el blog de notas.", "abri el blog de notas."),
    ("Oyejema, buscar recetas de empanadas.", "buscar recetas de empanadas."),
    ("Hoyé, Gema, subí el volumen.", "subí el volumen."),
    ("hoy es Jema, su piel volumen.", "su piel volumen."),
    ("Oye, Gemma! ¿Qué hora es?", "¿Qué hora es?"),
    ("Eh, oye Gema, qué hora es", "qué hora es"),
]
NOT_WAKE = [
    "La gema del anillo es azul.", "La Jema de la Niño es azul.", "Hoy tengo que ir a la facultad.",
    "Oye, me pasás el mate.", "Oye, mira esto.", "Tenemos un problema con el sistema.",
    "Oye, ¿qué tema es este?", "Oye, que te más este?", "Me quemé con la yema del huevo.",
    "Hoy es que te más este.", "Oye, tema nuevo", "Oye, gemelos", "Oye, Jimena, vení",
    "Yo y Gema fuimos al cine", "Hoy gané", "Oye, jefe", "", "Gracias.",
]


class WakePhraseTests(unittest.TestCase):
    def test_sloppy_transcriptions_of_oye_gema_are_recognized_with_the_request(self):
        for text, rest in HEARD_AS_WAKE:
            with self.subTest(text):
                self.assertEqual(find_wake(text), rest)

    def test_similar_phrases_do_not_wake_gema(self):
        for text in NOT_WAKE:
            with self.subTest(text):
                self.assertIsNone(find_wake(text))

    def test_sound_key_merges_letters_whisper_confuses(self):
        self.assertEqual(sound_key("Gemma"), sound_key("Jema"))
        self.assertEqual(sound_key("Hoy"), "oy")
        self.assertNotEqual(sound_key("tema"), sound_key("gema"))


def silent(seconds):
    return np.zeros(int(seconds * 16000), np.float32)


def loud(seconds):
    return np.full(int(seconds * 16000), .1, np.float32)


class LoudDetector:
    def speech(self, frame):
        return float(np.abs(frame).mean()) > .05


class Recorder:
    """Entrega el audio en bloques de 30 ms y después silencio; registra si está abierto."""
    def __init__(self, audio):
        self.audio, self.open, self.opened = audio, False, 0

    def __call__(self):
        return self

    def __enter__(self):
        self.open, self.position = True, 0
        self.opened += 1
        return self

    def read(self, timeout=.2):
        block = self.audio[self.position:self.position + 480]
        self.position += 480
        time.sleep(.0005)
        return block if len(block) else np.zeros(480, np.float32)

    def __exit__(self, *exc):
        self.open = False


class WakeListenerTests(unittest.TestCase):
    def listen(self, audio, said, voice_check=None, allowed=None):
        recorder, heard, transcriber = Recorder(audio), [], Mock()
        transcriber.transcribe.return_value = said
        done = threading.Event()

        def on_wake(clip, rest, after):
            heard.append((len(clip), rest, recorder.open, after))
            done.set()
        listener = WakeListener(recorder, LoudDetector, transcriber, on_wake, allowed or (lambda: True),
                                voice_check=voice_check)
        listener.start()
        self.addCleanup(listener.close)
        done.wait(3)
        time.sleep(.05)
        return heard, transcriber, recorder, listener

    def test_wakes_with_the_request_and_releases_the_microphone_first(self):
        heard, transcriber, recorder, listener = self.listen(
            np.concatenate([silent(.5), loud(1.5), silent(1)]), "Oye Gema, abrí el bloc de notas.")
        self.assertEqual(heard[0][1], "abrí el bloc de notas.")
        self.assertFalse(heard[0][2], "el micrófono tiene que estar cerrado para que lo use el dictado")
        transcriber.transcribe.assert_called_once()
        self.assertEqual(transcriber.transcribe.call_args.kwargs["hotwords"], "Gema")
        self.assertEqual(listener.snapshot()["activations"], 1)

    def test_long_talk_never_reaches_whisper(self):
        heard, transcriber, *_ = self.listen(np.concatenate([loud(6), silent(1)]), "Oye Gema")
        self.assertEqual(heard, [])
        transcriber.transcribe.assert_not_called()

    def test_short_noises_never_reach_whisper(self):
        heard, transcriber, *_ = self.listen(np.concatenate([loud(.2), silent(1)]), "Oye Gema")
        transcriber.transcribe.assert_not_called()

    def test_other_voices_are_dropped_by_the_voiceprint_before_whisper(self):
        check = Mock(return_value=(False, .2))
        heard, transcriber, _, listener = self.listen(np.concatenate([loud(1.2), silent(1)]), "Oye Gema", check)
        self.assertEqual(heard, [])
        transcriber.transcribe.assert_not_called()
        self.assertEqual(listener.snapshot()["other_voice"], 1)

    def test_other_phrases_keep_listening(self):
        heard, transcriber, *_ = self.listen(np.concatenate([loud(1.2), silent(1)]), "Oye, ¿qué tema es este?")
        self.assertEqual(heard, [])
        transcriber.transcribe.assert_called_once()

    def test_microphone_stays_closed_while_not_allowed(self):
        heard, transcriber, recorder, listener = self.listen(loud(1), "Oye Gema", allowed=lambda: False)
        self.assertEqual(recorder.opened, 0)
        self.assertEqual(listener.snapshot()["state"], "off")


class DictationWakeTests(unittest.TestCase):
    def make(self, said="Oye Gema, abrí el bloc de notas.", allowed=True, **config):
        self.transcriber, self.typer = Mock(), Mock()
        self.transcriber.transcribe.return_value = said
        self.assistant = Mock(return_value=(True, "Abriendo Bloc de notas."))
        d = Dictation(VoiceConfig(enabled=True, wake_word=True, after_dictation_ms=0, **config),
                      FakeFocus(FocusInfo(False)), lambda: FakeRecorder(noise(.5) + speech(1.2) + noise(1.6)),
                      self.transcriber, self.typer, assistant=self.assistant, output_allowed=lambda: allowed)
        d.start()
        self.addCleanup(d.close)
        return d

    def wait_idle(self, d):
        deadline = time.monotonic() + 5
        while not self.assistant.called and time.monotonic() < deadline:
            time.sleep(.01)
        while d.state != "idle" and time.monotonic() < deadline:
            time.sleep(.01)

    def test_request_in_the_same_phrase_runs_without_listening_again(self):
        d = self.make()
        FakeRecorder.opened = 0
        d.wake_heard(np.zeros(16000, np.float32), "abrí el blog de notas.")
        self.wait_idle(d)
        self.assistant.assert_called_once_with("abrí el bloc de notas.")  # el modelo del dictado, más preciso
        self.assertEqual(FakeRecorder.opened, 0)
        self.assertIn("Gema", self.transcriber.transcribe.call_args.kwargs["hotwords"])
        self.assertEqual(d.snapshot()["message"], "Gema: abriendo Bloc de notas.")

    def test_simple_requests_skip_the_second_transcription(self):
        """«Oye Gema, subí el volumen»: lo que entendió el modelo chico alcanza; responde enseguida."""
        d = self.make()
        d.wake_heard(np.zeros(16000, np.float32), "subí el volumen.")
        self.wait_idle(d)
        self.assistant.assert_called_once_with("subí el volumen.")
        self.transcriber.transcribe.assert_not_called()

    def test_wake_requests_are_counted_apart_in_the_metrics(self):
        metrics = Mock()
        d = self.make()
        d.metrics = metrics
        d.wake_heard(np.zeros(16000, np.float32), "subí el volumen.")
        self.wait_idle(d)
        self.assertEqual(metrics.dictation.call_args.args[0]["result"], "assistant_oye_gema")

    def test_if_the_dictation_model_misses_the_wake_phrase_the_first_reading_counts(self):
        d = self.make(said="Abrí el bloc de notas.")
        d.wake_heard(np.zeros(16000, np.float32), "abrí el blog de notas.")
        self.wait_idle(d)
        self.assistant.assert_called_once_with("abrí el blog de notas.")

    def test_wake_alone_opens_gema_listening(self):
        d = self.make(said="Abrí el bloc de notas.")
        d.wake_heard(np.zeros(16000, np.float32), "")
        self.wait_idle(d)
        self.assistant.assert_called_once_with("Abrí el bloc de notas.")

    def test_what_was_said_while_checking_the_wake_phrase_is_not_lost(self):
        """«Oye Gema… (pausa) qué hora es»: el pedido empezó antes de que Gema abra su micrófono."""
        d = self.make(said="¿Qué hora es?")
        d.recorder_factory = lambda: FakeRecorder(noise(3))  # el micrófono de Gema ya no oye el pedido
        d.wake_heard(np.zeros(16000, np.float32), "", after=np.asarray(noise(.4) + speech(1.2) + noise(.2), np.float32))
        self.wait_idle(d)
        self.assistant.assert_called_once_with("¿Qué hora es?")

    def test_listens_only_when_enabled_active_and_idle(self):
        self.assertFalse(VoiceConfig().wake_word, "micrófono siempre abierto: lo elige el usuario")
        self.assertTrue(self.make().wake_allowed())
        self.assertFalse(self.make(allowed=False).wake_allowed())  # pausa, F8 o sin control
        d = Dictation(VoiceConfig(enabled=True), None, None, Mock(), Mock())
        self.assertFalse(d.wake_allowed())
        with self.assertRaises(ValueError):
            VoiceConfig(wake_word="sí")


class SettingsTests(unittest.TestCase):
    def test_the_option_is_saved_in_the_profile(self):
        import test_gui
        case = test_gui.GUITests("test_window_pages_safe_start_and_no_backend")
        test_gui.GUITests.setUpClass()
        case.setUp()
        self.addCleanup(case.tearDown)
        case.select_calibrated()
        case.window.refresh()
        self.assertFalse(case.window.voice_wake.isChecked())
        case.window.voice_wake.setChecked(True)
        case.window.save_settings()
        case.wait(lambda: case.bridge.snapshot()["settings"]["voice"]["wake_word"] is True)
        self.assertTrue(case.manager.store.load("julian")["settings"]["voice"]["wake_word"])


class StatusLineTests(unittest.TestCase):
    def test_status_line_says_when_gema_is_listening(self):
        from desktop.window import wake_hint
        self.assertIn("Oye Gema", wake_hint(dict(dictation=dict(wake=dict(state="listening")))))
        self.assertEqual(wake_hint(dict(dictation=dict(wake=dict(state="off")))), "")
        self.assertEqual(wake_hint(dict(dictation=None)), "")


if __name__ == "__main__":
    unittest.main()
