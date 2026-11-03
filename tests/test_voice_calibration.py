"""Calibración de voz y huella de voz (2026-11-03), sin micrófono real.

Banco con el código real (voces sintéticas de Windows, WeSpeaker ResNet34): con la
tele hablando sin parar a 10 y 6 dB por debajo, la huella cortó 6/6 y 6/6 sin
cortes tempranos; sin huella, 0/6. Ventilador prendido después de calibrar (3 dB)
y sala en silencio: 6/6 por silencio, sin cortes tempranos.
"""
import importlib.util
import math
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from config import VoiceConfig
from dictation import Endpointer, SAMPLE_RATE
from speaker import MODEL_NAME, SpeakerGate, cosine, enroll, model_path, validate_voiceprint
from voice_calibration import PHRASES, VoiceCalibration, validate_voice_calibration, word_accuracy


def unit(values):
    norm = math.sqrt(sum(v * v for v in values))
    return [v / norm for v in values]


OWN, OTHER = unit([1.] + [0.] * 255), unit([.4, .9165] + [0.] * 254)  # coseno 0,4


class FakeSpeakerModel:
    """Huella según la amplitud: |muestra| ≥ 0,3 suena al usuario; menor, a otra voz."""

    def embed(self, samples):
        loud = sum(abs(v) >= .3 for v in samples) / max(1, len(samples))
        return unit([a * loud + b * (1 - loud) for a, b in zip(OWN, OTHER)])


class Loudness:
    """Detector: voz si la trama no es silencio (cualquier voz, como Silero)."""
    frame = 512

    def speech(self, chunk):
        return max(abs(v) for v in chunk) > .05


def frames_of(level, count):
    return [[level] * 512 for _ in range(count)]


class SpeakerGateTests(unittest.TestCase):
    def setUp(self):
        self.print = dict(embedding=OWN, threshold=.7, model=MODEL_NAME)

    def test_cuts_when_only_the_other_voice_remains_and_trims_it(self):
        # 3 s del usuario y después otra voz que no para: para la red, todo es habla.
        e = Endpointer(silence_s=1.2, detector=Loudness(), speaker=SpeakerGate(FakeSpeakerModel(), self.print))
        for chunk in frames_of(.5, 94) + frames_of(.1, 200):
            if e.feed(chunk) == "done":
                break
        self.assertEqual((e.state, e.end_reason), ("done", "speaker"))
        kept = e.audio()
        self.assertLess(sum(abs(v) < .3 for v in kept) / len(kept), .4)  # la cola ajena quedó afuera

    def test_first_windows_always_count_and_noise_lowers_the_bar(self):
        gate = SpeakerGate(FakeSpeakerModel(), dict(self.print, threshold=.9))
        frames = frames_of(.35, 0)
        for chunk in frames_of(.5, 80):  # sonando "peor" que el umbral pero igual al inicio
            frames.append(chunk)
            gate.update(frames, 0)
        self.assertEqual(gate.silent_frames(len(frames)), 0)  # nunca la tomó como otra voz

    def test_enroll_threshold_is_bounded_and_validated(self):
        model = FakeSpeakerModel()
        phrases = [[.5] * SAMPLE_RATE * 2 for _ in range(4)]
        voiceprint = enroll(model, phrases, room_noise=[.001] * SAMPLE_RATE)
        self.assertTrue(.5 <= voiceprint["threshold"] <= .75)
        self.assertGreater(cosine(voiceprint["embedding"], OWN), .5)
        validate_voiceprint(voiceprint)
        with self.assertRaises(ValueError):
            enroll(model, phrases[:1])
        for broken in (dict(voiceprint, model="otro.onnx"), dict(voiceprint, embedding=[0.] * 3),
                       dict(voiceprint, threshold=2)):
            with self.assertRaises(ValueError):
                validate_voiceprint(broken)


@unittest.skipUnless(importlib.util.find_spec("sherpa_onnx") and model_path(), "sin sherpa-onnx o sin el modelo")
class RealSpeakerModelTests(unittest.TestCase):
    def test_embedding_is_a_unit_vector_of_256(self):
        from speaker import SpeakerModel
        import numpy as np
        t = np.arange(SAMPLE_RATE * 2) / SAMPLE_RATE
        vector = SpeakerModel().embed((.1 * np.sin(2 * np.pi * 180 * t)).astype(np.float32))
        self.assertEqual(len(vector), 256)
        self.assertAlmostEqual(sum(v * v for v in vector), 1, places=4)


class ScriptedRecorder:
    """Silencio y después, por frase, 1,5 s de voz y 1,5 s de silencio."""

    def __init__(self, voice=.5, phrases=4, silence_s=3):
        audio = [0.] * int(silence_s * SAMPLE_RATE)
        for _ in range(phrases):
            audio += [voice] * int(1.5 * SAMPLE_RATE) + [0.] * int(1.5 * SAMPLE_RATE)
        self.audio, self.position = audio + [0.] * SAMPLE_RATE * 20, 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def read(self, timeout=.2):
        block = self.audio[self.position:self.position + 4800]
        self.position += 4800
        return block or [0.] * 480


class VoiceCalibrationTests(unittest.TestCase):
    def run_calibration(self, transcripts=PHRASES, speaker_model=None, recorder=None):
        transcriber = Mock()
        transcriber.transcribe.side_effect = list(transcripts)
        wizard = VoiceCalibration(VoiceConfig(), lambda: recorder or ScriptedRecorder(), transcriber,
                                  detector_factory=Loudness, speaker_model=speaker_model)
        wizard.start()
        deadline = time.monotonic() + 20
        while wizard.state not in ("done", "error", "cancelled") and time.monotonic() < deadline:
            time.sleep(.01)
        return wizard

    def test_full_calibration_measures_room_voice_accuracy_and_voiceprint(self):
        wizard = self.run_calibration(speaker_model=FakeSpeakerModel())
        self.assertEqual(wizard.state, "done", wizard.snapshot())
        result = wizard.snapshot()["result"]
        self.assertEqual(result["accuracy"], 1)
        self.assertEqual(result["speech_in_silence"], 0)
        self.assertGreater(result["snr_db"], 30)
        self.assertIsNotNone(result["voiceprint"])
        self.assertIn("buen estado", result["recommendations"][0])
        validate_voice_calibration(result)
        self.assertNotIn("audio", str(result.keys()))  # nunca se guarda audio

    def test_without_speaker_model_it_still_calibrates_and_says_how_to_get_it(self):
        wizard = self.run_calibration(transcripts=["hoy quiero escribir", *PHRASES[1:]])
        result = wizard.snapshot()["result"]
        self.assertIsNone(result["voiceprint"])
        self.assertLess(result["accuracy"], 1)
        self.assertTrue(any("reconocimiento de voz" in tip for tip in result["recommendations"]))

    def test_no_voice_ends_in_a_clear_error(self):
        wizard = self.run_calibration(recorder=ScriptedRecorder(voice=0.))
        self.assertEqual(wizard.state, "error")
        self.assertIn("micrófono", wizard.snapshot()["message"])

    def test_cancel(self):
        transcriber = Mock()
        wizard = VoiceCalibration(VoiceConfig(), ScriptedRecorder, transcriber, detector_factory=Loudness)
        wizard.start()
        wizard.cancel()
        wizard.join(5)
        self.assertEqual(wizard.state, "cancelled")
        transcriber.transcribe.assert_not_called()

    def test_word_accuracy_ignores_accents_case_punctuation_and_digits(self):
        self.assertEqual(word_accuracy("Mañana a las nueve tengo turno.", "mañana a las 9 tengo turno"), 1)
        self.assertAlmostEqual(word_accuracy("Necesito comprar pan.", "Necesito pan"), 2 / 3)
        self.assertEqual(word_accuracy("Hola", ""), 0)


class ControllerVoiceCalibrationTests(unittest.TestCase):
    def test_saved_calibration_reaches_the_profile_and_the_next_dictation(self):
        from application_controller import ApplicationController
        from profile_manager import ProfileManager
        from profiles import ProfileStore
        with tempfile.TemporaryDirectory() as temp:
            c = ApplicationController(ProfileManager(ProfileStore(Path(temp) / "p")), data_dir=temp)
            c.create_profile("Voz")
            wizard = VoiceCalibrationTests().run_calibration(speaker_model=FakeSpeakerModel())
            c.voice_wizard = wizard
            c.save_voice_calibration()
            stored = c.profiles.store.load(c.profile["user_id"])
            self.assertEqual(stored["voice_calibration"]["accuracy"], 1)
            summary = c.snapshot(include_frame=False)["voice_calibration"]
            self.assertIs(summary["voiceprint"], True)  # la GUI no recibe la huella
            self.assertIsNone(c.voice_wizard)
            c.config.voice.enabled = True
            with patch("dictation.create_dictation") as create:
                c._start_dictation()
            self.assertEqual(create.call_args.kwargs["voiceprint"], stored["voice_calibration"]["voiceprint"])
            with self.assertRaises(ValueError):
                c.save_voice_calibration()  # ya no hay una terminada


if __name__ == "__main__":
    unittest.main()
