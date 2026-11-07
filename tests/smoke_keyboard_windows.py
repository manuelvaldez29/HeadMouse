"""Prueba supervisable de teclado en un Bloc de notas temporal de Windows.

Ejecutar desde la raíz con el Python de compilación. No inicia cámara ni voz.
Cada envío exige que el Bloc de notas creado por esta prueba siga en foco.
"""
import ctypes
from ctypes import wintypes
from dataclasses import asdict
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    if sys.platform != "win32":
        raise RuntimeError("Esta prueba requiere Windows")
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from config import KeyboardConfig
    from desktop.keyboard import VirtualKeyboard
    from desktop.keyboard_service import KeyboardService
    from keyboard_input import KeyboardTyper, WindowsKeyboardFocus

    app = QApplication.instance() or QApplication([])
    if app.platformName() != "windows":
        raise RuntimeError("Usá Qt nativo para verificar el foco de Windows")
    app.setQuitOnLastWindowClosed(False)
    user = ctypes.WinDLL("user32")
    user.GetForegroundWindow.restype = wintypes.HWND
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user.SendMessageW.restype = wintypes.LPARAM
    test_root = ROOT / "build"
    test_root.mkdir(exist_ok=True)

    def wait_for(check, message):
        end = time.monotonic() + 5
        while time.monotonic() < end:
            app.processEvents()
            if check():
                return
            time.sleep(.008)
        raise AssertionError(message)

    with tempfile.TemporaryDirectory(prefix="notepad-keyboard-", dir=test_root) as folder:
        root = Path(folder)
        scratch = root / "HeadMouse - prueba temporal.txt"
        scratch.write_text("", encoding="utf-8-sig")
        process = subprocess.Popen([str(Path(os.environ["WINDIR"]) / "System32/notepad.exe"), str(scratch)])
        panel = None
        try:
            def owns(hwnd):
                pid = wintypes.DWORD()
                return bool(hwnd and user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)) and pid.value == process.pid)

            wait_for(lambda: owns(user.GetForegroundWindow()), "El Bloc de notas temporal no obtuvo el foco")
            hwnd = user.GetForegroundWindow()
            probe = WindowsKeyboardFocus()
            target = probe.focused()
            assert target and target.window == hwnd and target.predictive
            edit = probe.element.CurrentNativeWindowHandle
            assert edit and owns(edit)

            def allowed():
                active = user.GetForegroundWindow()
                return active == hwnd and owns(active)

            class GuardedTyper(KeyboardTyper):
                def _send(self, events):
                    if not allowed():
                        raise RuntimeError("El Bloc de notas temporal perdió el foco")
                    super()._send(events)

            def contents():
                buffer = ctypes.create_unicode_buffer(128)
                if not allowed():
                    raise RuntimeError("Cambió el foco durante el ensayo")
                user.SendMessageW(edit, 0x000D, len(buffer), ctypes.addressof(buffer))
                return buffer.value

            options = asdict(KeyboardConfig(learning=True))
            controller = SimpleNamespace(profile={"user_id": "synthetic"}, control=object(), dictation=None,
                                         data_dir=root, _dictation_allowed=allowed, keyboard_visible=threading.Event())
            bridge = SimpleNamespace(controller=controller, snapshot=lambda: {
                "profile": controller.profile, "settings": {"keyboard": options}})
            with patch("desktop.keyboard.KeyboardService",
                       side_effect=lambda b, p: KeyboardService(b, p, typer_factory=GuardedTyper)):
                panel = VirtualKeyboard(bridge)
            wait_for(panel.isVisible, "El teclado no se abrió en el campo editable")
            assert allowed(), "Abrir el teclado cambió el foco"
            assert user.SendMessageW(int(panel.winId()), 0x0021, 0, 0) == 3  # MA_NOACTIVATE
            samples = []
            expected = ""
            for char in "HeadMouse Hea":
                expected += char
                start = time.perf_counter()
                panel.press("Espacio" if char == " " else char)
                wait_for(lambda: contents() == expected, "Una tecla no llegó al Bloc")
                samples.append((time.perf_counter()-start)*1000)
            wait_for(lambda: any(b.text() == "HeadMouse" and b.isEnabled() for b in panel.prediction_buttons),
                     "No llegó la sugerencia aprendida")
            QTest.mouseClick(next(b for b in panel.prediction_buttons if b.text()=="HeadMouse"),Qt.MouseButton.LeftButton)
            expected = "HeadMouse HeadMouse "
            wait_for(lambda: contents() == expected, "La sugerencia duplicó o perdió texto")
            for mode, char in (("Acentos","Ñ"),("?123","7"),("=\\<","€")):
                QTest.mouseClick(panel.page_buttons[mode], Qt.MouseButton.LeftButton)
                QTest.mouseClick(next(b for b in panel.letter_buttons if b.text()==char), Qt.MouseButton.LeftButton)
                expected += char
                wait_for(lambda: contents() == expected, "No llegó el carácter Unicode")
            panel.press("Enter")
            expected += "\r\n"
            wait_for(lambda: contents() == expected, "No llegó Enter")
            panel.press("⌫")
            expected = expected[:-2]
            wait_for(lambda: contents() == expected, "No llegó Retroceso")
            panel.hide_keyboard()
            wait_for(lambda: not controller.keyboard_visible.is_set(), "El teclado se volvió a abrir en el mismo campo")
            assert allowed()
            samples.sort()
            print(f"PASS: Bloc de notas real, foco conservado, Unicode, Enter, Retroceso y sugerencia aprendida. "
                  f"Mediana desde tecla a texto: {samples[len(samples)//2]:.1f} ms, máximo: {samples[-1]:.1f} ms.")
        finally:
            if panel:
                panel.close()
            if process.poll() is None:
                process.terminate()  # Sólo nuestra instancia y su texto sintético.
                process.wait(timeout=5)


if __name__ == "__main__":
    main()
