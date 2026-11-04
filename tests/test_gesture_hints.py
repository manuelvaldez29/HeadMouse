"""Los mensajes nombran el gesto que el perfil tiene asignado (2026-11-04).

Con el besito para pausar, la mini cámara y el inicio decían "ambas cejas".
"""
import unittest
from unittest.mock import Mock

from action_mapping import DEFAULT_MAPPING, capitalized, gesture_phrase
from config import VoiceConfig
from dictation import Dictation


def snapshot(bindings, enabled=None, **state):
    gates = {k: dict(enabled=k in enabled) for k in DEFAULT_MAPPING} if enabled is not None else {}
    return dict(dict(control_enabled=True, paused=True, settings=dict(actions=dict(bindings=bindings)),
                     diagnostic=dict(gates=gates)), **state)


KISS_PAUSES = dict(DEFAULT_MAPPING, KISS="PAUSE", BOTH_BROWS="NONE")


class GesturePhraseTests(unittest.TestCase):
    def test_phrase_follows_bindings_and_enabled_gestures(self):
        self.assertEqual(gesture_phrase(KISS_PAUSES, "PAUSE"), "tirá un besito")
        self.assertEqual(gesture_phrase(DEFAULT_MAPPING, "PAUSE", short=True), "ambas cejas")
        both = dict(DEFAULT_MAPPING, KISS="PAUSE")
        self.assertEqual(gesture_phrase(both, "PAUSE"), "levantá ambas cejas o tirá un besito")
        self.assertEqual(gesture_phrase(both, "PAUSE", enabled={"BOTH_BROWS"}), "levantá ambas cejas")
        self.assertIsNone(gesture_phrase(KISS_PAUSES, "PAUSE", enabled={"LEFT_WINK"}))  # sin calibrar
        self.assertEqual(capitalized("tirá un besito"), "Tirá un besito")


class StatusMessageTests(unittest.TestCase):
    def test_status_line_names_the_assigned_pause_gesture(self):
        from desktop.window import status_message
        self.assertEqual(status_message(snapshot(KISS_PAUSES))[0], "Tirá un besito para empezar a mover el cursor.")
        active = status_message(snapshot(KISS_PAUSES, paused=False))[0]
        self.assertTrue(active.startswith("Besito: pausar"))
        self.assertNotIn("cejas", active)
        self.assertIn("guiñá el ojo izquierdo de nuevo",
                      status_message(snapshot(DEFAULT_MAPPING, paused=False, dragging=True))[0])

    def test_warns_when_no_calibrated_gesture_can_resume(self):
        from desktop.window import NO_PAUSE_GESTURE, status_message
        text, error = status_message(snapshot(KISS_PAUSES, enabled={"LEFT_WINK", "RIGHT_WINK"}))
        self.assertEqual(text, NO_PAUSE_GESTURE)
        self.assertTrue(error)  # en pausa y sin forma de reanudar con la cara


class DictationHintTests(unittest.TestCase):
    def test_listening_message_uses_the_profile_gestures(self):
        d = Dictation(VoiceConfig(enabled=True), Mock(), Mock(), Mock(), Mock(),
                      hints=dict(finish="guiño izq.", cancel="besito"))
        self.assertEqual(d.hints, dict(finish="guiño izq.", cancel="besito"))
        generic = Dictation(VoiceConfig(enabled=True), Mock(), Mock(), Mock(), Mock())
        self.assertEqual(generic.hints["cancel"], "tu gesto de pausa")


if __name__ == "__main__":
    unittest.main()
