"""Edición acotada al campo actual. El contexto contiene sólo teclas propias."""
from dataclasses import dataclass, field
import ctypes
from ctypes import wintypes
import os
import re
import unicodedata

from dictation import SendInputTyper, UIAFocusProbe
from keyboard_dictionary import WORD

SENSITIVE = re.compile(
    r"password|passcode|contrase[nñ]a|clave|credential|credencial|secret|otp|cvv|cvc|"
    r"credit.?card|tarjeta|social.?security|n[uú]mero.{0,8}documento|\bpin\b|"
    r"verification.?code|c[oó]digo.{0,8}verificaci[oó]n", re.I)


@dataclass(frozen=True)
class Target:
    window: int
    runtime: tuple | None
    editable: bool
    private: bool
    unknown: bool = False
    bounds: tuple | None = field(default=None, compare=False)

    @property
    def predictive(self):
        return self.editable and not self.private and self.runtime is not None


class WindowsKeyboardFocus(UIAFocusProbe):
    """Usa el foco real de UI Automation, sin consultar el valor completo del campo."""
    def __init__(self):
        super().__init__()
        self.user32 = ctypes.WinDLL("user32")
        self.user32.GetForegroundWindow.restype = wintypes.HWND
        self.user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self.user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.user32.SendMessageTimeoutW.argtypes = [
            wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
            wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)]
        self.user32.SendMessageTimeoutW.restype = wintypes.LPARAM
        self.element = None
        self.can_read = False

    def focused(self):
        self.element = None
        self.can_read = False
        window = self.user32.GetForegroundWindow()
        process = wintypes.DWORD()
        if not window or not self.user32.GetWindowThreadProcessId(window, ctypes.byref(process)):
            return None
        if process.value == os.getpid():
            return None
        try:
            if self._automation is None:
                self.init_thread()
                import comtypes.client
                self.interfaces = comtypes.client.GetModule("UIAutomationCore.dll")
                try:
                    options = self._automation.QueryInterface(self.interfaces.IUIAutomation2)
                    options.ConnectionTimeout = 250
                    options.TransactionTimeout = 350
                except Exception:
                    pass
            element = self._automation.GetFocusedElement()
            if not element or not element.CurrentHasKeyboardFocus:
                return Target(window, None, False, True, unknown=True)
            info = self._classify(element)
            # Un provider que omite IsPassword nunca habilita predicción o aprendizaje.
            password = element.GetCurrentPropertyValueEx(30019, True)
            private = password is not False or info.password
            if not private:
                description = " ".join(str(getattr(element, prop) or "") for prop in
                                       ("CurrentName", "CurrentAutomationId", "CurrentHelpText", "CurrentClassName"))
                private = bool(SENSITIVE.search(description))
            if self.user32.GetForegroundWindow() != window:
                return None
            self.element = element
            target = Target(window, info.runtime_id, info.editable or info.password, private,
                            unknown=info.control_type in ("50025", "50032", "50033"),
                            bounds=self._bounds(element))
            self.can_read = target.predictive
            return target
        except Exception:
            return Target(window, None, False, True, unknown=True)

    @staticmethod
    def _bounds(element):
        try:
            rect = element.CurrentBoundingRectangle
            result = (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)
            return result if result[2] > 0 and result[3] > 0 else None
        except Exception:
            return None

    def composition_matches(self, before, after):
        """Compara sólo caracteres que ya envió este teclado, en la línea del cursor."""
        if not self.can_read:
            return None
        before, after = before.rsplit("\n", 1)[-1][-180:], after.split("\n", 1)[0][:180]
        try:
            pattern = self.element.GetCurrentPattern(10014).QueryInterface(self.interfaces.IUIAutomationTextPattern)
            selection = pattern.GetSelection()
            if selection.Length != 1:
                return False
            caret = selection.GetElement(0)
            if caret.CompareEndpoints(0, caret, 1) != 0:
                return False
            left, right = caret.Clone(), caret.Clone()
            left.MoveEndpointByUnit(0, 0, -len(before))
            right.MoveEndpointByUnit(1, 0, len(after))
            return left.GetText(-1) == before and right.GetText(-1) == after
        except Exception:
            return self._native_edit_matches(before, after)

    def caret(self, suffix):
        """Confirma sólo el sufijo propio y lee el carácter contiguo, sin persistirlo."""
        if not self.can_read:
            return None
        try:
            pattern = self.element.GetCurrentPattern(10014).QueryInterface(self.interfaces.IUIAutomationTextPattern)
            selection = pattern.GetSelection()
            if selection.Length != 1:
                return None
            caret = selection.GetElement(0)
            if caret.CompareEndpoints(0, caret, 1) != 0:
                return None
            before = caret.Clone()
            before.MoveEndpointByUnit(0, 0, -(len(suffix) or 1))
            left = before.GetText(len(suffix) or 1)
            if suffix and left != suffix:
                return None
            after = caret.Clone()
            after.MoveEndpointByUnit(1, 0, 1)
            return left[-1:], after.GetText(1)
        except Exception:
            return self._native_edit_caret(suffix)

    def _edit_message(self, hwnd, message, wparam=0, lparam=0):
        result = ctypes.c_size_t()
        if not self.user32.SendMessageTimeoutW(hwnd, message, wparam, lparam, 2, 100, ctypes.byref(result)):
            raise OSError("El campo de Windows no respondió")
        return result.value

    def _native_edit_caret(self, suffix):
        """Bloc de notas clásico: leer sólo hasta el cursor y un carácter más."""
        try:
            hwnd = self.element.CurrentNativeWindowHandle
            name = ctypes.create_unicode_buffer(32)
            if not hwnd or not self.user32.GetClassNameW(hwnd, name, len(name)) or name.value != "Edit":
                return None
            selection = self._edit_message(hwnd, 0xB0)  # EM_GETSEL
            start, end = selection & 0xFFFF, (selection >> 16) & 0xFFFF
            if selection >= 0xFFFFFFFF or start != end:
                return None
            row = self._edit_message(hwnd, 0xC9, start)  # EM_LINEFROMCHAR
            beginning = self._edit_message(hwnd, 0xBB, row)  # EM_LINEINDEX
            offset = start - beginning
            if not len(suffix) <= offset < 1023:
                return None
            buffer = ctypes.create_unicode_buffer(offset + 2)
            buffer[0] = chr(offset + 1)
            count = self._edit_message(hwnd, 0xC4, row, ctypes.addressof(buffer))  # EM_GETLINE
            if not offset <= count <= offset + 1:
                return None
            if suffix and buffer[offset-len(suffix):offset] != suffix:
                return None
            right = buffer[offset] if count > offset else ""
            if not right and row + 1 < self._edit_message(hwnd, 0xBA):  # EM_GETLINECOUNT
                if self._edit_message(hwnd, 0xBB, row + 1) <= start:
                    return None  # límite visual de línea: puede partir una palabra
                right = "\n"
            return buffer[offset-1] if offset else "", right
        except Exception:
            return None

    def _native_edit_matches(self, before, after):
        try:
            hwnd = self.element.CurrentNativeWindowHandle
            name = ctypes.create_unicode_buffer(32)
            if not hwnd or not self.user32.GetClassNameW(hwnd, name, len(name)) or name.value != "Edit":
                return None
            selection = self._edit_message(hwnd, 0xB0)
            start, end = selection & 0xFFFF, (selection >> 16) & 0xFFFF
            if selection >= 0xFFFFFFFF or start != end:
                return False
            row = self._edit_message(hwnd, 0xC9, start)
            offset = start - self._edit_message(hwnd, 0xBB, row)
            # Edit usa unidades UTF-16, incluso para emojis fuera del BMP.
            left_units = len(before.encode("utf-16-le")) // 2
            right_units = len(after.encode("utf-16-le")) // 2
            if offset < left_units or offset + right_units >= 1023:
                return None
            buffer = ctypes.create_unicode_buffer(offset + right_units + 2)
            buffer[0] = chr(offset + right_units + 1)
            count = self._edit_message(hwnd, 0xC4, row, ctypes.addressof(buffer))
            if count < offset + right_units:
                return False
            raw = ctypes.string_at(ctypes.addressof(buffer), count * 2)
            actual = raw[(offset-left_units)*2:(offset+right_units)*2].decode("utf-16-le")
            return actual == before + after
        except Exception:
            return None


KEYS = {"⌫": 0x08, "Tab": 0x09, "Enter": 0x0D, "Inicio": 0x24, "Fin": 0x23,
        "←": 0x25, "↑": 0x26, "→": 0x27, "↓": 0x28, "Supr": 0x2E}
EXTENDED = {"Inicio", "Fin", "←", "↑", "→", "↓", "Supr"}


class KeyboardTyper(SendInputTyper):
    def write(self, text, backspaces=0):
        events = [event for _ in range(backspaces) for event in
                  (self._key(vk=8), self._key(vk=8, flags=2))]
        data = text.encode("utf-16-le")
        for i in range(0, len(data), 2):
            unit = int.from_bytes(data[i:i+2], "little")
            events.extend((self._key(scan=unit, flags=4), self._key(scan=unit, flags=6)))
        if events:
            self._send(events)

    def special(self, name, modifiers=()):
        vk = 0x20 if name==" " else KEYS.get(name)
        if vk is None:
            if not modifiers or len(name) != 1 or not name.isascii() or not name.isalnum():
                return False
            vk = ord(name.upper())
        flags = int(name in EXTENDED)
        mods = [0x11 if mod == "Ctrl" else 0x12 for mod in modifiers]
        events = [self._key(vk=mod) for mod in mods]
        events += [self._key(vk=vk, flags=flags), self._key(vk=vk, flags=flags | 2)]
        events += [self._key(vk=mod, flags=2) for mod in reversed(mods)]
        self._send(events)
        return True


class Composition:
    """Texto propio, sólo en RAM y acotado. Nunca importa texto de otras ventanas."""
    LIMIT = 2048

    def __init__(self):
        self.clear()

    def clear(self):
        self.text, self.cursor, self.status = "", 0, "empty"

    def write(self, text, backspaces=0):
        start = max(0, self.cursor - backspaces)
        self.text = self.text[:start] + text + self.text[self.cursor:]
        self.cursor = start + len(text)
        if len(self.text) > self.LIMIT:
            trim = len(self.text) - self.LIMIT
            self.text = self.text[trim:]
            self.cursor = max(0, self.cursor - trim)
        self.status = "sent"

    def special(self, name, modifiers):
        if modifiers or name == "Tab":
            self.clear()
        elif name == "Enter":
            self.write("\n")
        elif name == "⌫":
            start = max(0, self.cursor - 1)
            while start and (unicodedata.combining(self.text[start]) or self.text[start] in "\ufe0e\ufe0f"):
                start -= 1
            self.write("", self.cursor - start)
        elif name == "Supr":
            self.text = self.text[:self.cursor] + self.text[self.cursor+1:]
            self.status = "sent"
        elif name == "←":
            self.cursor = max(0, self.cursor - 1)
            self.status = "sent"
        elif name == "→":
            self.cursor = min(len(self.text), self.cursor + 1)
            self.status = "sent"
        elif name == "Inicio":
            self.cursor = self.text.rfind("\n", 0, self.cursor) + 1
            self.status = "sent"
        elif name == "Fin":
            end = self.text.find("\n", self.cursor)
            self.cursor = len(self.text) if end < 0 else end
            self.status = "sent"
        else:
            # Saltos verticales dependen del ajuste de línea de la aplicación.
            self.clear()

    def verify(self, probe):
        matcher = getattr(probe, "composition_matches", None)
        if not self.text or not callable(matcher):
            return None
        result = matcher(self.text[:self.cursor], self.text[self.cursor:])
        if result is True:
            self.status = "confirmed"
        return result


class KeyboardSession:
    def __init__(self):
        self.target = None
        self.composition = Composition()
        self.reset()

    def reset(self):
        self.composition.clear()
        self.reset_words()

    def reset_words(self):
        self.draft, self.tail, self.context = "", "", []

    def set_target(self, target):
        if target != self.target:
            self.target = target
            self.reset()

    def suggestions(self, dictionary, settings):
        if not self.target or not self.target.predictive or not settings["suggestions"]:
            return []
        return dictionary.suggest(self.draft, self.context, settings["corrections"])

    def commit(self, word, dictionary, settings):
        if WORD.fullmatch(word):
            if settings["learning"]:
                dictionary.learn(word, self.context)
            self.context = [*self.context[-1:], word]

    def insert(self, text, probe, typer, dictionary, settings, allowed):
        if not self.target.predictive or not (settings["suggestions"] or settings["learning"]):
            if allowed():
                typer.write(text)
                if self.target.predictive:
                    self.composition.write(text)
                self.reset_words()
                return True
            return False
        edges = probe.caret(self.tail)
        verified = edges is not None and not (not self.tail and
                   (edges[0].isalnum() or edges[1].isalnum() or "_" in edges))
        if not verified:
            self.reset_words()
        if not allowed():
            return False
        typer.write(text)
        self.composition.write(text)
        if not verified:
            return True
        combined = unicodedata.normalize("NFC", self.draft + text)
        if WORD.fullmatch(combined):
            self.draft = combined
            self.tail = (self.tail + text)[-180:]
        elif text.isspace() or text in ",.;:!?¿¡":
            if verified:
                self.commit(self.draft, dictionary, settings)
            self.draft = ""
            self.tail = (self.tail + text)[-180:]
            if not text.isspace():
                self.context.clear()
        else:
            self.reset_words()
        return True

    def special(self, name, modifiers, probe, typer, dictionary, settings, allowed):
        verified = (not modifiers and name in ("⌫","Enter","Tab") and self.target.predictive
                    and self.tail and probe.caret(self.tail) is not None)
        if not allowed():
            return False
        if typer.special(name, modifiers) is False:
            return False
        if self.target.predictive:
            self.composition.special(name, modifiers)
        if not modifiers and name == "⌫" and verified and self.draft:
            self.draft, self.tail = self.draft[:-1], self.tail[:-1]
        else:
            if not modifiers and name in ("Enter","Tab") and verified:
                self.commit(self.draft, dictionary, settings)
            self.reset_words()
        return True

    def choose(self, word, probe, typer, dictionary, settings, allowed):
        if word not in {value for value, _ in self.suggestions(dictionary, settings)}:
            return False
        edges = probe.caret(self.tail)
        if edges is None:
            self.reset()
            return False
        left, right = edges
        if (not self.draft and left.isalnum()) or right.isalnum() or right == "_":
            return False
        if not allowed():
            return False
        if probe.caret(self.tail) != edges or not allowed():
            self.reset()
            return False
        space = " " if not right else ""
        leading = " " if not self.draft and left and left in ",.;:!?" else ""
        if word.startswith(self.draft):
            inserted = leading + word[len(self.draft):] + space
            typer.write(inserted)
            self.composition.write(inserted)
        else:
            typer.write(word + space, backspaces=len(self.draft))
            self.composition.write(word + space, backspaces=len(self.draft))
        self.commit(word, dictionary, settings)
        self.tail = (self.tail[:-len(self.draft)] if self.draft else self.tail) + leading + word + space
        self.tail = self.tail[-180:]
        self.draft = ""
        if not space:
            self.reset_words()
        return True
