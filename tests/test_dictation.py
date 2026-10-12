"""Dictado por voz con dobles: sin micrófono, modelo, UI Automation ni teclado real."""
import math
import random
import sys
import time
import unittest
from unittest.mock import Mock
from config import VoiceConfig, load_config
from control_engine import ControlEngine
from dictation import Dictation, Endpointer, FocusInfo, SAMPLE_RATE, finish_text
from gesture_engine import GestureEvent

RNG = random.Random(7)


def noise(seconds, level=.002):
    return [RNG.uniform(-level, level) for _ in range(int(seconds * SAMPLE_RATE))]


def speech(seconds, level=.1):
    return [level * math.sin(2 * math.pi * 220 * i / SAMPLE_RATE) + RNG.uniform(-.002, .002)
            for i in range(int(seconds * SAMPLE_RATE))]


class EndpointerTests(unittest.TestCase):
    def feed(self, endpoint, samples):
        for i in range(0, len(samples), 480):
            state = endpoint.feed(samples[i:i + 480])
        return state

    def test_detects_phrase_and_trims_closing_silence(self):
        e = Endpointer(silence_s=1.0)
        self.assertEqual(self.feed(e, noise(.6)), "waiting")
        self.assertEqual(self.feed(e, speech(1.5)), "speech")
        self.assertEqual(self.feed(e, noise(1.2)), "done")
        seconds = len(e.audio()) / SAMPLE_RATE
        self.assertGreater(seconds, 1.5)        # incluye pre-roll
        self.assertLess(seconds, 1.5 + .3 + .3)  # sin el segundo de silencio final

    def test_short_pauses_inside_phrase_do_not_end_it(self):
        e = Endpointer(silence_s=1.0)
        self.feed(e, noise(.5) + speech(.8) + noise(.5) + speech(.8))
        self.assertEqual(e.state, "speech")

    def test_no_speech_times_out_and_max_length_caps(self):
        e = Endpointer(no_speech_s=2)
        self.assertEqual(self.feed(e, noise(2.5)), "timeout")
        self.assertEqual(e.audio(), [])
        e = Endpointer(max_s=2)
        self.assertEqual(self.feed(e, noise(.5) + speech(3)), "done")

    def test_noise_floor_adapts_to_loud_room(self):
        e = Endpointer()
        self.assertEqual(self.feed(e, noise(1.5, level=.02)), "waiting")  # ruido de fondo alto, no es habla
        self.assertEqual(self.feed(e, speech(.5, level=.3)), "speech")


class TextTests(unittest.TestCase):
    def test_spacing_send_word_and_hallucinations(self):
        config = VoiceConfig()
        self.assertEqual(finish_text("  Hola,  ¿cómo estás? ", config), ("Hola, ¿cómo estás? ", False))
        self.assertEqual(finish_text("Gracias por ver el video.", config), ("", False))
        config = VoiceConfig(send_word="enviar")
        self.assertEqual(finish_text("Nos vemos mañana, enviar.", config), ("Nos vemos mañana", True))
        self.assertEqual(finish_text("Enviar", config), ("", True))
        self.assertEqual(finish_text("Tengo que enviarte algo", config), ("Tengo que enviarte algo ", False))

    def test_config_validation(self):
        self.assertFalse(load_config().voice.enabled)
        for bad in ({"model": "huge"}, {"enabled": "si"}, {"silence_s": 0}, {"send_word": "x" * 40}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                load_config(overrides={"voice": bad})


class FakeFocus:
    def __init__(self, *infos):
        self.infos, self.calls = list(infos), 0

    def focused(self):
        self.calls += 1
        return self.infos[min(self.calls - 1, len(self.infos) - 1)]


class FakeRecorder:
    opened = 0

    def __init__(self, samples):
        self.samples = samples

    def __enter__(self):
        FakeRecorder.opened += 1
        self.position = 0
        return self

    def read(self, timeout=.2):
        if self.position >= len(self.samples):
            time.sleep(.001)
            return [0.] * 480
        block = self.samples[self.position:self.position + 4800]
        self.position += 4800
        return block

    def __exit__(self, *exc):
        pass


class DictationTests(unittest.TestCase):
    PHRASE = noise(.5) + speech(1.2) + noise(1.6)

    def make(self, focus, samples=None, text="hola mundo", **config):
        self.typer = Mock()
        self.metrics = Mock()
        self.transcriber = Mock()
        self.transcriber.transcribe.return_value = text
        self.cues = []
        FakeRecorder.opened = 0
        d = Dictation(VoiceConfig(enabled=True, after_dictation_ms=0, **config), focus,
                      lambda: FakeRecorder(self.PHRASE if samples is None else samples),
                      self.transcriber, self.typer, metrics=self.metrics, cue=self.cues.append)
        d.start()
        self.addCleanup(d.close)
        return d

    def wait_idle(self, d, timeout=5):
        started = time.monotonic()
        time.sleep(.02)
        while d.state != "idle" and time.monotonic() - started < timeout:
            time.sleep(.01)
        self.assertEqual(d.state, "idle")

    def test_click_into_text_field_types_transcription(self):
        d = self.make(FakeFocus(FocusInfo(False), FocusInfo(True, control_type="Edit")))
        d.on_click()
        self.wait_idle(d)
        self.typer.type_text.assert_called_once_with("hola mundo ")
        self.typer.press_enter.assert_not_called()
        self.assertEqual(self.cues, ["start", "end"])
        self.assertEqual(d.snapshot()["last_text"], "hola mundo")
        result = self.metrics.dictation.call_args.args[0]
        self.assertEqual(result["result"], "typed")
        self.assertNotIn("text", result)  # nunca se guarda el texto
        audio = self.transcriber.transcribe.call_args.args[0]
        self.assertLess(len(audio) / SAMPLE_RATE, 2)

    def test_send_word_presses_enter(self):
        d = self.make(FakeFocus(FocusInfo(True)), text="Ya llego, enviar", send_word="enviar")
        d.on_click()
        self.wait_idle(d)
        self.typer.type_text.assert_called_once_with("Ya llego")
        self.typer.press_enter.assert_called_once()

    def test_password_and_non_text_never_open_microphone(self):
        for focus in (FakeFocus(FocusInfo(True, password=True)), FakeFocus(FocusInfo(False))):
            d = self.make(focus, focus_window_ms=200)
            d.on_click()
            self.wait_idle(d)
            self.assertEqual(FakeRecorder.opened, 0)
            self.typer.type_text.assert_not_called()

    def test_disabled_does_nothing_and_busy_blocks_second_request(self):
        d = Dictation(VoiceConfig(enabled=False), FakeFocus(FocusInfo(True)), Mock(), Mock(), Mock())
        d.on_click()
        self.assertEqual(d.state, "idle")
        d = self.make(FakeFocus(FocusInfo(True)))
        d.on_click()
        d.on_click()
        self.wait_idle(d)
        self.assertEqual(self.typer.type_text.call_count, 1)

    def test_cancel_while_listening_types_nothing(self):
        d = self.make(FakeFocus(FocusInfo(True)), samples=noise(.5) + speech(30))
        d.on_click()
        for _ in range(200):
            if d.state == "listening": break
            time.sleep(.005)
        self.assertTrue(d.busy)
        d.cancel()
        self.wait_idle(d)
        self.typer.type_text.assert_not_called()
        self.assertEqual(self.metrics.dictation.call_args.args[0]["result"], "cancelled")
        self.assertIn("cancel", self.cues)

    def test_silence_closes_without_typing(self):
        d = self.make(FakeFocus(FocusInfo(True)), samples=noise(8), no_speech_timeout_s=1)
        d.on_click()
        self.wait_idle(d)
        self.transcriber.transcribe.assert_not_called()
        self.assertEqual(self.metrics.dictation.call_args.args[0]["result"], "no_speech")

    def test_dictate_action_requires_current_focus(self):
        d = self.make(FakeFocus(FocusInfo(False)))
        d.start_now()
        self.wait_idle(d)
        self.assertIn("No hay un campo", d.snapshot()["message"])

    def test_quiet_period_after_dictation(self):
        clock = [100.]
        d = Dictation(VoiceConfig(enabled=True, after_dictation_ms=500), FakeFocus(FocusInfo(False)),
                      Mock(), Mock(), Mock(), clock=lambda: clock[0])
        d._quiet_until = 100.4
        self.assertTrue(d.busy)
        clock[0] = 100.5
        self.assertFalse(d.busy)


class ControlIntegrationTests(unittest.TestCase):
    def control(self, busy):
        backend = Mock()
        backend.size.return_value = (1920, 1080)
        dictation = Mock(busy=busy)
        vision, gesture = Mock(), Mock()
        from face_data import FaceData
        vision.get_face_data.return_value = FaceData(True, timestamp_ms=int(time.monotonic() * 1000))
        vision.get_fps.return_value = 30
        gesture.config = load_config().gesture
        control = ControlEngine(vision, gesture, backend=backend, dictation=dictation, wheel_unit=1)
        control._paused = False
        return control, gesture, backend, dictation

    def test_while_dictating_only_cursor_moves_and_pause_cancels(self):
        control, gesture, backend, dictation = self.control(busy=True)
        gesture.update.return_value = [GestureEvent("CURSOR_MOVE", dx=5, dy=0), GestureEvent("LEFT_CLICK"),
                                       GestureEvent("MOUTH_OPEN"), GestureEvent("BOTH_BROWS")]
        control._tick()
        backend.moveRel.assert_called_once()
        backend.click.assert_not_called()
        backend.hotkey.assert_not_called()
        dictation.cancel.assert_called_once()
        self.assertFalse(control.paused)

    def test_click_arms_dictation_and_dictate_action_starts_it(self):
        control, gesture, backend, dictation = self.control(busy=False)
        control._execute(GestureEvent("LEFT_CLICK"))
        dictation.on_click.assert_called_once()
        control._execute(GestureEvent("DICTATE"))
        dictation.start_now.assert_called_once()


@unittest.skipUnless(sys.platform == "win32", "SendInput solo existe en Windows")
class SendInputLayoutTests(unittest.TestCase):
    def test_input_struct_matches_windows_abi(self):
        import ctypes
        from dictation import SendInputTyper
        typer = SendInputTyper()
        self.assertEqual(ctypes.sizeof(typer.INPUT), 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)


if __name__ == "__main__": unittest.main()
