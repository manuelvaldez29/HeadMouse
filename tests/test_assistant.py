"""Asistente de voz, etapa 1 (2026-11-11): comandos en español, sin IA generativa ni Windows real."""
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from action_mapping import ACTIONS, ActionMapping, DEFAULT_MAPPING
from assistant import ASSISTANT_COMMANDS, AppIndex, Assistant, Command, parse
from config import VoiceConfig
from dictation import Dictation, FocusInfo
import test_dictation
from test_dictation import FakeFocus, FakeRecorder

START_MENU = [("Bloc de notas", "Notepad!App"), ("WhatsApp", "WhatsApp!App"), ("Google Chrome", "Chrome"),
              ("Microsoft Edge", "MSEdge"), ("Calculadora", "Calc!App"), ("Explorador de archivos", "Explorer"),
              ("Desinstalar Java", "UninstallJava"), ("Java Setup", "JavaSetup"), ("Configuración", "Settings")]


def index():
    built = AppIndex(loader=lambda: START_MENU)
    built._ready.wait(2)
    return built


class ParseTests(unittest.TestCase):
    def test_every_documented_example_is_understood(self):
        for phrase, _effect, example in ASSISTANT_COMMANDS:
            with self.subTest(example):
                self.assertIsNotNone(parse(example))

    def test_mouse_commands_exist_only_while_the_eye_joystick_is_connected(self):
        self.assertEqual(parse("Clic."), Command("click"))
        self.assertEqual(parse("Hacé click"), Command("click"))
        self.assertEqual(parse("Doble clic"), Command("double_click"))
        self.assertEqual(parse("Clic derecho."), Command("right_click"))
        self.assertEqual(parse("¡Quieto!"), Command("freeze"))
        self.assertEqual(parse("Frená el mouse"), Command("freeze"))
        self.assertEqual(parse("Mover"), Command("unfreeze"))
        self.assertEqual(parse("Pausa"), Command("play_pause"))
        assistant = Assistant(index=Mock(), keys=Mock())
        done, message = assistant("Clic")  # con Nariz nadie conecta el puntero
        self.assertFalse(done)
        self.assertIn("solo con Ojos", message)
        assistant.keys.click.assert_not_called()
        assistant.pointer = Mock(return_value=True)
        self.assertEqual(assistant("Doble clic"), (True, "Doble clic."))
        assistant.pointer.assert_called_once_with("double_click")

    def test_control_connects_voice_mouse_to_the_eye_joystick_and_not_to_the_nose(self):
        from control_engine import ControlEngine
        from gesture_engine import EV_LEFT_CLICK
        def engine(strategy_name):
            gesture, dictation, backend = Mock(), Mock(), Mock()
            gesture.strategy.name = strategy_name
            backend.size.return_value = (1920, 1080)
            dictation.assistant = Assistant(index=Mock(), keys=Mock())
            return ControlEngine(Mock(), gesture, backend=backend, dictation=dictation), dictation.assistant, backend
        control, assistant, backend = engine("nose")
        self.assertIsNone(assistant.pointer)
        self.assertFalse(control.voice_pointer("click"))
        control, assistant, backend = engine("eye_joystick")
        control.output_allowed.set()
        control._paused = False
        self.assertEqual(assistant("Quieto"), (True, "Puntero quieto. Decí «mover» para liberarlo."))
        self.assertIs(control.ocular_joystick.frozen, True)
        assistant("Mover")
        self.assertIs(control.ocular_joystick.frozen, False)
        self.assertTrue(assistant("Clic")[0])
        backend.click.assert_not_called()  # se ejecuta en el ciclo del control, no en el hilo de voz
        control._run_voice_actions()
        backend.click.assert_called_once()

    def test_rioplatense_variants_and_courtesy(self):
        self.assertEqual(parse("Che, abrime el Word por favor"), Command("open", "word"))
        self.assertEqual(parse("Abrí la calculadora."), Command("open", "calculadora"))
        self.assertEqual(parse("Buscá en Google cómo hacer pan casero"), Command("search", "como hacer pan casero"))
        self.assertEqual(parse("Subí el volumen"), Command("volume_up"))
        self.assertEqual(parse("¿Qué hora es?"), Command("time"))

    def test_text_to_type_keeps_what_was_dictated(self):
        self.assertEqual(parse("Escribí: Hola, ¿cómo andás?"), Command("type", "Hola, ¿cómo andás?"))

    def test_unknown_or_ambiguous_phrases_do_nothing(self):
        for text in ("ponete a bailar", "abrir", "", "poné pausa"):  # "poné X" no abre nada
            with self.subTest(text):
                self.assertIsNone(parse(text))


class AppIndexTests(unittest.TestCase):
    def test_finds_by_name_aliases_and_approximate_spelling(self):
        apps = index()
        self.assertEqual(apps.find("bloc de notas"), ("Bloc de notas", "Notepad!App"))
        self.assertEqual(apps.find("notas"), ("Bloc de notas", "Notepad!App"))
        self.assertEqual(apps.find("watsap"), ("WhatsApp", "WhatsApp!App"))
        self.assertEqual(apps.find("navegador"), ("Google Chrome", "Chrome"))
        self.assertEqual(apps.find("archivos"), ("Explorador de archivos", "Explorer"))
        self.assertIsNone(apps.find("photoshop"))

    def test_never_opens_an_uninstaller_or_installer(self):
        self.assertIsNone(index().find("java"))

    def test_a_failing_start_menu_leaves_an_empty_index(self):
        def broken():
            raise OSError("sin PowerShell")
        apps = AppIndex(loader=broken)
        self.assertIsNone(apps.find("bloc de notas", wait_s=2))


class AssistantTests(unittest.TestCase):
    def make(self, own_window=False):
        self.keys, self.typer, self.launch, self.browse = Mock(), Mock(), Mock(), Mock()
        return Assistant(index=index(), keys=self.keys, typer=self.typer, launch=self.launch, browse=self.browse,
                         own_window=lambda: own_window,
                         clock=lambda: SimpleNamespace(tm_hour=9, tm_min=5))

    def test_open_launches_the_start_menu_entry(self):
        done, message = self.make()("Abrí el bloc de notas.")
        self.assertTrue(done)
        self.launch.assert_called_once_with("Notepad!App")
        self.assertIn("Bloc de notas", message)
        done, message = self.make()("abrir photoshop")
        self.assertFalse(done)
        self.assertIn("No encontré", message)

    def test_search_opens_google_with_the_query_encoded(self):
        self.make()("Buscar recetas de empanadas")
        self.assertEqual(self.browse.call_args.args[0], "https://www.google.com/search?q=recetas+de+empanadas")

    def test_window_and_media_keys(self):
        a = self.make()
        a("cerrar ventana")
        self.keys.hotkey.assert_called_with("alt", "f4", _pause=False)
        a("mostrar escritorio")
        self.keys.hotkey.assert_called_with("win", "d", _pause=False)
        a("subí el volumen")
        self.assertEqual(self.keys.press.call_count, 5)
        self.keys.press.assert_called_with("volumeup", _pause=False)

    def test_never_closes_headmouse_itself(self):
        done, message = self.make(own_window=True)("cerrar ventana")
        self.assertFalse(done)
        self.keys.hotkey.assert_not_called()
        self.assertIn("HeadMouse", message)

    def test_type_and_time_and_unknown(self):
        a = self.make()
        a("Escribí: Hola, ¿cómo andás?")
        self.typer.type_text.assert_called_once_with("Hola, ¿cómo andás?")
        self.assertEqual(a("qué hora es"), (True, "Son las 9:05."))
        done, message = a("ponete a bailar")
        self.assertFalse(done)
        self.assertIn("No entendí", message)


class DictationAssistantModeTests(unittest.TestCase):
    def test_listens_without_a_text_field_and_runs_the_command_instead_of_typing(self):
        transcriber, typer, assistant = Mock(), Mock(), Mock(return_value=(True, "Abriendo Bloc de notas."))
        transcriber.transcribe.return_value = "Abrí el bloc de notas."
        d = Dictation(VoiceConfig(enabled=True, after_dictation_ms=0), FakeFocus(FocusInfo(False)),
                      lambda: FakeRecorder(test_dictation.DictationTests.PHRASE), transcriber, typer, assistant=assistant)
        d.start()
        self.addCleanup(d.close)
        d.start_assistant()
        deadline = time.monotonic() + 5
        while not assistant.called and time.monotonic() < deadline:
            time.sleep(.01)
        while d.state != "idle" and time.monotonic() < deadline:
            time.sleep(.01)
        assistant.assert_called_once_with("Abrí el bloc de notas.")
        typer.type_text.assert_not_called()
        self.assertEqual(d.snapshot()["message"], "Abriendo Bloc de notas.")


class ActionTests(unittest.TestCase):
    def test_assistant_is_an_assignable_action(self):
        self.assertIn("ASSISTANT", ACTIONS)
        mapping = ActionMapping(dict(DEFAULT_MAPPING, MOUTH_OPEN="ASSISTANT"))
        from gesture_engine import GestureEvent
        self.assertEqual(mapping.resolve(GestureEvent("MOUTH_OPEN")).type, "ASSISTANT")
        from desktop.window import ACTION_LABELS
        self.assertEqual(ACTION_LABELS["ASSISTANT"], "Asistente de voz")

    def test_control_starts_the_assistant_on_the_dictation(self):
        from control_engine import ControlEngine
        from gesture_engine import GestureEvent
        backend = Mock()
        backend.size.return_value = (1920, 1080)
        dictation = Mock(busy=False)
        control = ControlEngine(Mock(), Mock(), backend=backend, dictation=dictation, wheel_unit=1)
        control._execute(GestureEvent("ASSISTANT"))
        dictation.start_assistant.assert_called_once()


if __name__ == "__main__":
    unittest.main()
