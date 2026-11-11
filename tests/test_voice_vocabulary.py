"""Palabras frecuentes para el dictado (2026-11-11).

Con la voz del usuario (9 frases leídas): sin lista 95,4 % de palabras bien ("yerba" salía
"hierba", "Julián" "Julianne"); con la lista por defecto 97,1 %, sin empeorar ninguna frase.
"""
import time
import unittest
from unittest.mock import Mock

from config import VoiceConfig, load_config
from dictation import Dictation, FocusInfo, WhisperTranscriber
import test_dictation
from test_dictation import FakeFocus, FakeRecorder
from voice_calibration import VoiceCalibration
from test_voice_calibration import Loudness, ScriptedRecorder


class VocabularyConfigTests(unittest.TestCase):
    def test_default_list_is_short_and_regional(self):
        words = VoiceConfig().vocabulary.split(", ")
        self.assertIn("yerba", words)
        self.assertLessEqual(len(words), 10)

    def test_list_is_normalized_and_bounded(self):
        self.assertEqual(VoiceConfig(vocabulary="  Julián ,Iván,\nyerba ,, ").vocabulary, "Julián, Iván, yerba")
        self.assertEqual(VoiceConfig(vocabulary="").vocabulary, "")
        for bad in ("x" * 301, 5, None):
            with self.assertRaises(ValueError):
                VoiceConfig(vocabulary=bad)
        self.assertEqual(load_config(overrides={"voice": {"vocabulary": "mate"}}).voice.vocabulary, "mate")


class VocabularyReachesWhisperTests(unittest.TestCase):
    def test_transcriber_passes_the_words_as_hotwords(self):
        transcriber = WhisperTranscriber("small")
        model = Mock()
        model.transcribe.return_value = ([], None)
        transcriber._model = model
        transcriber.transcribe([0.] * 16000, "es", hotwords="yerba, Julián")
        self.assertEqual(model.transcribe.call_args.kwargs["hotwords"], "yerba, Julián")
        transcriber.transcribe([0.] * 16000, "es")
        self.assertIsNone(model.transcribe.call_args.kwargs["hotwords"])  # sin lista, nada

    def test_dictation_and_voice_calibration_use_the_profile_list(self):
        transcriber = Mock()
        transcriber.transcribe.return_value = "hola"
        d = Dictation(VoiceConfig(enabled=True, after_dictation_ms=0, vocabulary="Ary, mate"),
                      FakeFocus(FocusInfo(True)), lambda: FakeRecorder(test_dictation.DictationTests.PHRASE), transcriber, Mock())
        d.start()
        self.addCleanup(d.close)
        d.on_click()
        deadline = time.monotonic() + 5
        while not transcriber.transcribe.called and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertEqual(transcriber.transcribe.call_args.kwargs["hotwords"], "Ary, mate")

        calibration = Mock()
        calibration.transcribe.return_value = "hola"
        wizard = VoiceCalibration(VoiceConfig(vocabulary="Ary"), ScriptedRecorder, calibration, detector_factory=Loudness)
        wizard.start()
        wizard.join(20)
        self.assertEqual(calibration.transcribe.call_args.kwargs["hotwords"], "Ary")


if __name__ == "__main__":
    unittest.main()
