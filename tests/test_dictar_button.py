"""Botón Dictar del teclado virtual en WhatsApp (2026-11-16).

WhatsApp Desktop es WebView2 dentro de WinUI 3: UI Automation deja el foco en el puente
de WinUI y el dictado sólo encontraba el cuadro de mensaje bajo el puntero. Con el botón
Dictar el puntero está sobre el teclado de CONFA: "Click sin campo de texto" y nada.
"""
import unittest

from dictation import FocusInfo
import test_dictation

BRIDGE = FocusInfo(False, control_type="50033")  # Pane: lo que ve el dictado en WhatsApp
FIELD = (42, 7)                                    # runtime id que encontró el teclado


class WindowFocus(test_dictation.FakeFocus):
    def __init__(self, *infos, window=100):
        super().__init__(*infos)
        self.window = window

    def foreground_window(self):
        return self.window


class DictarButtonTests(test_dictation.DictationTests):
    def test_dictates_into_the_field_the_keyboard_found(self):
        d = self.make(WindowFocus(BRIDGE))
        d.start_now(expected_runtime=FIELD, window=100)
        self.wait_idle(d)
        self.typer.type_text.assert_called_once_with("hola mundo ")

    def test_voice_commands_work_there_too(self):
        d = self.make(WindowFocus(BRIDGE), text="borrar todo")
        d.start_now(expected_runtime=FIELD, window=100)
        self.wait_idle(d)
        self.typer.select_all.assert_called_once()

    def test_never_when_another_window_is_in_front(self):
        focus = WindowFocus(BRIDGE, window=200)
        d = self.make(focus)
        d.start_now(expected_runtime=FIELD, window=100)
        self.wait_idle(d)
        self.typer.type_text.assert_not_called()
        self.transcriber.transcribe.assert_not_called()

    def test_never_into_a_password(self):
        d = self.make(WindowFocus(FocusInfo(False, password=True)))
        d.start_now(expected_runtime=FIELD, window=100)
        self.wait_idle(d)
        self.transcriber.transcribe.assert_not_called()

    def test_not_if_the_focus_moved_to_another_field_while_speaking(self):
        other = FocusInfo(True, control_type="Edit", runtime_id=(9, 9))
        d = self.make(WindowFocus(BRIDGE, BRIDGE, other))
        d.start_now(expected_runtime=FIELD, window=100)
        self.wait_idle(d)
        self.transcriber.transcribe.assert_called_once()
        self.typer.type_text.assert_not_called()

    def test_not_if_the_window_changed_while_speaking(self):
        focus = WindowFocus(BRIDGE)
        d = self.make(focus)
        original = focus.focused

        def focused():
            if focus.calls >= 2:
                focus.window = 200  # el usuario cambió de ventana mientras hablaba
            return original()
        focus.focused = focused
        d.start_now(expected_runtime=FIELD, window=100)
        self.wait_idle(d)
        self.typer.type_text.assert_not_called()

    def test_gesture_dictate_without_keyboard_is_unchanged(self):
        d = self.make(WindowFocus(BRIDGE))
        d.start_now()
        self.wait_idle(d)
        self.transcriber.transcribe.assert_not_called()


# Que unittest no vuelva a correr acá los tests heredados de DictationTests.
for name in [n for n in dir(test_dictation.DictationTests) if n.startswith("test_")]:
    if name not in DictarButtonTests.__dict__:
        setattr(DictarButtonTests, name, None)

if __name__ == "__main__":
    unittest.main()
