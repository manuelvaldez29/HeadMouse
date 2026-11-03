"""Detección de voz con Silero y gesto para terminar el dictado (2026-11-03).

Banco con voces sintéticas de Windows (Helena) más ruido, palabras bien transcriptas:
ventilador a 8 dB 67 % → 97 %, a 3 dB 0 % → 97 %, golpes/vajilla 0 % → 97 %.
Una voz de fondo sigue siendo habla para la red: la cubre el gesto de terminar.
"""
import importlib.util
import time
import unittest
from unittest.mock import Mock

from config import VoiceConfig, load_config
from control_engine import ControlEngine
from dictation import Dictation, Endpointer, FocusInfo, SAMPLE_RATE, SileroDetector, detector_factory
from gesture_engine import GestureEvent
from test_dictation import FakeFocus


class ScriptedDetector:
    """Voz o no voz por trama, según una lista; después del final, `tail`."""
    frame = 512

    def __init__(self, script, tail=False):
        self.script, self.tail = list(script), tail

    def speech(self, chunk):
        return self.script.pop(0) if self.script else self.tail


def frames(count):
    return [0.] * (512 * count)


class NeuralEndpointerTests(unittest.TestCase):
    def test_detector_decides_start_end_and_keeps_preroll(self):
        # 20 tramas quietas, 40 de voz (1,3 s), después silencio: 32 ms por trama.
        e = Endpointer(silence_s=1.0, detector=ScriptedDetector([False] * 20 + [True] * 40))
        state = None
        for _ in range(120):
            state = e.feed(frames(1))
            if state == "done":
                break
        self.assertEqual(state, "done")
        self.assertEqual(e.end_reason, "silence")
        self.assertEqual(e.speech_start, 20 - 9)  # 300 ms de pre-roll ≈ 9 tramas
        self.assertAlmostEqual(len(e.audio()) / SAMPLE_RATE, (40 + 9 + 4) * 512 / SAMPLE_RATE, delta=.05)

    def test_no_noise_calibration_delay_with_a_detector(self):
        e = Endpointer(detector=ScriptedDetector([True] * 3))
        self.assertEqual(e.feed(frames(3)), "speech")  # la energía esperaba 300 ms antes de decidir

    def test_finish_transcribes_what_was_said_or_nothing(self):
        e = Endpointer(detector=ScriptedDetector([], tail=True))  # voz de fondo que nunca para
        e.feed(frames(60))
        self.assertEqual(e.state, "speech")
        e.finish()
        self.assertEqual((e.state, e.end_reason), ("done", "gesture"))
        self.assertGreater(len(e.audio()), 0)

    def test_finish_before_speaking_or_right_after_starting_is_ignored(self):
        # 2026-11-03: un guiño suelto 1,5-2 s después del click cerraba con "no se escuchó nada".
        quiet = Endpointer(no_speech_s=6, detector=ScriptedDetector([False] * 40 + [True] * 60, tail=False))
        quiet.feed(frames(20))
        self.assertFalse(quiet.finish())
        self.assertEqual(quiet.state, "waiting")  # sigue esperando tu voz
        quiet.feed(frames(25))                    # empezaste a hablar hace ~0,2 s
        self.assertEqual(quiet.state, "speech")
        self.assertFalse(quiet.finish())
        quiet.feed(frames(20))                    # ya hablaste más de medio segundo
        self.assertTrue(quiet.finish())
        self.assertEqual((quiet.state, quiet.end_reason), ("done", "gesture"))

    def test_end_reasons_for_the_log(self):
        e = Endpointer(max_s=1, detector=ScriptedDetector([], tail=True))
        e.feed(frames(80))
        self.assertEqual((e.state, e.end_reason), ("done", "max"))
        e = Endpointer(no_speech_s=1, detector=ScriptedDetector([], tail=False))
        e.feed(frames(80))
        self.assertEqual((e.state, e.end_reason), ("timeout", "timeout"))


@unittest.skipUnless(importlib.util.find_spec("faster_whisper") and importlib.util.find_spec("onnxruntime"),
                     "sin requirements-voice.txt")
class SileroDetectorTests(unittest.TestCase):
    def test_room_noise_is_not_speech(self):
        import numpy as np
        detector = SileroDetector(SileroDetector.load_session())
        rng = np.random.default_rng(3)
        hum = .05 * np.sin(2 * np.pi * 100 * np.arange(SAMPLE_RATE * 2) / SAMPLE_RATE)
        audio = (rng.normal(0, .02, SAMPLE_RATE * 2) + hum).astype(np.float32)
        probabilities = [detector.probability(audio[i:i + 512]) for i in range(0, len(audio) - 511, 512)]
        self.assertTrue(all(0 <= p <= 1 for p in probabilities))
        self.assertLess(max(probabilities), .5)
        e = Endpointer(no_speech_s=1.5, detector=SileroDetector(SileroDetector.load_session()))
        self.assertEqual(e.feed(audio.tolist()), "timeout")  # el ruido nunca abre el dictado

    def test_factory_follows_the_setting(self):
        self.assertIsNone(detector_factory(VoiceConfig(detector="energy")))
        factory = detector_factory(VoiceConfig(detector="neural"))
        self.assertIsInstance(factory(), SileroDetector)
        self.assertIsNot(factory(), factory())  # estado nuevo en cada dictado


class RealTimeRecorder:
    """Silencio entregado a velocidad real (30 ms cada 30 ms), como un micrófono."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def read(self, timeout=.2):
        time.sleep(.03)
        return [0.] * 480


class FinishGestureTests(unittest.TestCase):
    def test_finish_types_without_waiting_for_silence(self):
        typer, transcriber = Mock(), Mock()
        transcriber.transcribe.return_value = "hola"
        d = Dictation(VoiceConfig(enabled=True, after_dictation_ms=0), FakeFocus(FocusInfo(True)),
                      RealTimeRecorder, transcriber, typer,
                      detector_factory=lambda: ScriptedDetector([], tail=True))
        d.start()
        self.addCleanup(d.close)
        d.on_click()
        deadline = time.monotonic() + 3
        while d.state != "listening" and time.monotonic() < deadline:
            time.sleep(.01)
        d.finish()   # guiño suelto apenas empieza: no cierra
        time.sleep(.3)
        self.assertEqual(d.state, "listening")
        time.sleep(.6)  # ya habló más de medio segundo
        d.finish()
        while d.state != "idle" and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertEqual(d.state, "idle")
        typer.type_text.assert_called_once_with("hola ")

    def test_click_gesture_while_dictating_finishes_and_pause_still_cancels(self):
        backend = Mock()
        backend.size.return_value = (1920, 1080)
        dictation, vision, gesture = Mock(busy=True), Mock(), Mock()
        from face_data import FaceData
        vision.get_face_data.return_value = FaceData(True, timestamp_ms=int(time.monotonic() * 1000))
        vision.get_fps.return_value = 30
        gesture.config = load_config().gesture
        control = ControlEngine(vision, gesture, backend=backend, dictation=dictation, wheel_unit=1)
        control._paused = False
        gesture.update.return_value = [GestureEvent("LEFT_CLICK")]
        control._tick()
        dictation.finish.assert_called_once()
        backend.click.assert_not_called()  # no hace click en otro lado
        gesture.update.return_value = [GestureEvent("BOTH_BROWS")]
        control._tick()
        dictation.cancel.assert_called_once()

    def test_setting_rejects_unknown_detector(self):
        self.assertEqual(VoiceConfig().detector, "neural")
        with self.assertRaises(ValueError):
            VoiceConfig(detector="magia")


if __name__ == "__main__":
    unittest.main()
