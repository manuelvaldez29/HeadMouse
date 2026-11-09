"""Edición acotada al campo actual. El contexto contiene sólo teclas propias o verificadas."""
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
    panel_bounds: tuple | None = field(default=None, compare=False)

    @property
    def predictive(self):
        return self.editable and not self.private and self.runtime is not None


class WindowsKeyboardFocus(UIAFocusProbe):
    """Usa el foco real de UI Automation y recupera contexto acotado en campos autorizados."""
    def __init__(self):
        super().__init__()
        self.user32 = ctypes.WinDLL("user32")
        self.user32.GetForegroundWindow.restype = wintypes.HWND
        self.user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self.user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self.user32.GetWindowRect.restype = wintypes.BOOL
        self.user32.SendMessageTimeoutW.argtypes = [
            wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
            wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)]
        self.user32.SendMessageTimeoutW.restype = wintypes.LPARAM
        self.element = None
        self.can_read = False
        self._bridge_focus = None

    @staticmethod
    def _normalize_uia_text(text):
        if not isinstance(text, str) or not text:
            return ""
        return text.replace("\xa0", " ").replace("\r\n", "\n").replace("\r", "\n").replace("\u200b", "")

    def _window_class_and_title(self, window):
        if not window or not hasattr(self, "user32"):
            return "", ""
        try:
            cls_buf = ctypes.create_unicode_buffer(96)
            title_buf = ctypes.create_unicode_buffer(128)
            self.user32.GetClassNameW(window, cls_buf, len(cls_buf))
            if hasattr(self.user32, "GetWindowTextW"):
                self.user32.GetWindowTextW(window, title_buf, len(title_buf))
            return (cls_buf.value or ""), (title_buf.value or "")
        except Exception:
            return "", ""

    def _is_shell_flyout(self, window, element=None):
        cls_name, title = self._window_class_and_title(window)
        if cls_name in ("Windows.UI.Core.CoreWindow", "XamlExplorerHostIslandWindow",
                        "SearchPane", "Shell_LightDismissOverlay"):
            return True
        title_low = (title or "").lower()
        if cls_name == "ApplicationFrameWindow" and any(k in title_low for k in ("búsqueda", "search", "inicio", "start")):
            return True
        if element is not None:
            try:
                el_cls = element.CurrentClassName or ""
                el_aid = element.CurrentAutomationId or ""
                if isinstance(el_aid, str) and el_aid == "SearchTextBox":
                    return True
                if isinstance(el_cls, str) and el_cls == "Windows.UI.Core.CoreWindow":
                    return True
            except Exception:
                pass
        return False

    def _panel_bounds(self, window, element, walker=None):
        if not self._is_shell_flyout(window, element):
            return None
        candidates = []
        current = element
        for _ in range(8):
            if current is None:
                break
            try:
                rect = current.CurrentBoundingRectangle
                w, h = rect.right - rect.left, rect.bottom - rect.top
                if w >= 240 and h >= 180:
                    candidates.append((rect.left, rect.top, w, h))
                if walker is None:
                    break
                current = walker.GetParentElement(current)
            except Exception:
                break
        if window and hasattr(self, "user32") and hasattr(self.user32, "GetWindowRect"):
            try:
                rc = wintypes.RECT()
                if self.user32.GetWindowRect(window, ctypes.byref(rc)):
                    w, h = rc.right - rc.left, rc.bottom - rc.top
                    if isinstance(w, int) and isinstance(h, int) and w >= 240 and h >= 180:
                        candidates.append((rc.left, rc.top, w, h))
            except Exception:
                pass
        if not candidates:
            return None
        return max(candidates, key=lambda r: r[2] * r[3])

    @staticmethod
    def _is_non_input_item(element):
        try:
            cls_name = element.CurrentClassName or ""
            aid = element.CurrentAutomationId or ""
            return cls_name == "UIProperty" or aid.startswith("System.")
        except Exception:
            return False

    def _focused_child_edit(self, container):
        try:
            cond = self._automation.CreatePropertyCondition(30003, self.EDIT)
            children = container.FindAll(4, cond)
            single = None
            under_pt = None
            pt = None
            try:
                pt = self._cursor_point()
            except Exception:
                pt = None
            for i in range(min(children.Length, 12)):
                child = children.GetElement(i)
                if self._is_non_input_item(child):
                    continue
                if child.CurrentHasKeyboardFocus:
                    return child
                if single is None:
                    single = child
                if pt is not None and under_pt is None:
                    b = self._bounds(child)
                    if b and b[0] <= pt.x <= b[0] + b[2] and b[1] <= pt.y <= b[1] + b[3]:
                        under_pt = child
            if under_pt is not None:
                return under_pt
            if single is not None:
                container_cls = container.CurrentClassName or ""
                single_aid = getattr(single, "CurrentAutomationId", "") or ""
                if (container_cls in ("AutoSuggestBox", "Windows.UI.Core.CoreWindow", "ScrollViewer", "Popup") or
                        single_aid in ("SearchTextBox", "TextBox")):
                    return single
        except Exception:
            pass
        return None

    def _resolve_focus_element(self, window, element):
        is_bridge = False
        bridge_has_focus = False
        if element is not None:
            try:
                cls_name = element.CurrentClassName or ""
                ctrl = element.CurrentControlType
                is_bridge = (cls_name in ("Microsoft.UI.Content.DesktopChildSiteBridge", "AutoSuggestBox",
                                          "InputSiteWindowClass", "Windows.UI.Core.CoreWindow",
                                          "XamlExplorerHostIslandWindow", "ScrollViewer") or
                             ctrl in (50026, 50033))
                bridge_has_focus = bool(is_bridge and element.CurrentHasKeyboardFocus)
            except Exception:
                pass
        if self._is_shell_flyout(window, element):
            is_bridge = True
            bridge_has_focus = True
        if self._pointer_in_foreground():
            try:
                for candidate in self._pointer_chain(5):
                    if self._is_non_input_item(candidate):
                        continue
                    cls_name = candidate.CurrentClassName or ""
                    if cls_name in ("AutoSuggestBox", "Windows.UI.Core.CoreWindow") or candidate.CurrentControlType == 50026:
                        child = self._focused_child_edit(candidate)
                        if child is not None:
                            info = self._classify(child)
                            if info.editable or info.password:
                                self._bridge_focus = (window, child)
                                return child, info
                    if candidate.CurrentHasKeyboardFocus or bridge_has_focus:
                        info = self._classify(candidate)
                        if info.editable or info.password:
                            self._bridge_focus = (window, candidate)
                            return candidate, info
            except Exception:
                pass
        cached = getattr(self, "_bridge_focus", None)
        if cached and cached[0] == window and cached[1] is not None:
            try:
                if (cached[1].CurrentHasKeyboardFocus or bridge_has_focus) and not self._is_non_input_item(cached[1]):
                    info = self._classify(cached[1])
                    if info.editable or info.password:
                        return cached[1], info
            except Exception:
                pass
        if is_bridge and element is not None:
            try:
                child = self._focused_child_edit(element)
                if child is not None:
                    info = self._classify(child)
                    if info.editable or info.password:
                        self._bridge_focus = (window, child)
                        return child, info
            except Exception:
                pass
        self._bridge_focus = None
        return None, None

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
            info = None
            if element and element.CurrentHasKeyboardFocus and not self._is_non_input_item(element):
                info = self._classify(element)
                if info.editable or info.password:
                    self._bridge_focus = (window, element)
            if info is None or (not info.editable and not info.password):
                resolved_el, resolved_info = self._resolve_focus_element(window, element)
                if resolved_el is not None and resolved_info is not None:
                    element, info = resolved_el, resolved_info
                elif not element or not element.CurrentHasKeyboardFocus:
                    return Target(window, None, False, True, unknown=True)
                elif info is None:
                    info = self._classify(element)
                    if self._is_non_input_item(element):
                        walker = getattr(self._automation, "ControlViewWalker", None)
                        return Target(window, info.runtime_id, False, False, unknown=False,
                                      bounds=self._bounds(element, walker))
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
            walker = getattr(self._automation, "ControlViewWalker", None)
            target = Target(window, info.runtime_id, info.editable or info.password, private,
                            unknown=info.control_type in ("50025", "50032", "50033"),
                            bounds=self._bounds(element, walker),
                            panel_bounds=self._panel_bounds(window, element, walker))
            self.can_read = target.predictive
            return target
        except Exception:
            return Target(window, None, False, True, unknown=True)

    @staticmethod
    def _bounds(element, walker=None):
        current = element
        for _ in range(3):
            if current is None:
                break
            try:
                rect = current.CurrentBoundingRectangle
                result = (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)
                if result[2] > 0 and result[3] > 0:
                    return result
                if walker is None:
                    break
                current = walker.GetParentElement(current)
            except Exception:
                break
        return None

    def composition_matches(self, before, after):
        """Compara sólo caracteres que ya envió este teclado, en la línea del cursor."""
        if not self.can_read:
            return None
        before = self._normalize_uia_text(before.rsplit("\n", 1)[-1])[-180:]
        after = self._normalize_uia_text(after.split("\n", 1)[0])[:180]
        try:
            pattern = self.element.GetCurrentPattern(10014).QueryInterface(self.interfaces.IUIAutomationTextPattern)
            selection = pattern.GetSelection()
            if selection.Length != 1:
                return False
            caret = selection.GetElement(0)
            if caret.CompareEndpoints(0, caret, 1) != 0:
                return False
            if before:
                left = caret.Clone()
                left.MoveEndpointByUnit(0, 0, -len(before))
                got_left = self._normalize_uia_text(left.GetText(-1))
            else:
                got_left = ""
            if after:
                right = caret.Clone()
                right.MoveEndpointByUnit(1, 0, len(after))
                got_right = self._normalize_uia_text(right.GetText(-1))
            else:
                got_right = ""
            return got_left == before and got_right == after
        except Exception:
            res = self._native_edit_matches(before, after)
            if res is not None:
                return res
            return self._value_pattern_matches(before, after)

    def caret(self, suffix):
        """Confirma sólo el sufijo propio y lee el carácter contiguo, sin persistirlo."""
        if not self.can_read:
            return None
        line_suffix = self._normalize_uia_text(suffix.rsplit("\n", 1)[-1]) if suffix else ""
        try:
            pattern = self.element.GetCurrentPattern(10014).QueryInterface(self.interfaces.IUIAutomationTextPattern)
            selection = pattern.GetSelection()
            if selection.Length != 1:
                return None
            caret = selection.GetElement(0)
            if caret.CompareEndpoints(0, caret, 1) != 0:
                return None
            n_back = len(line_suffix) or 1
            before = caret.Clone()
            before.MoveEndpointByUnit(0, 0, -n_back)
            left = self._normalize_uia_text(before.GetText(n_back))
            if line_suffix and left != line_suffix:
                return None
            after = caret.Clone()
            after.MoveEndpointByUnit(1, 0, 1)
            right = self._normalize_uia_text(after.GetText(1))
            if right == "\n":
                right = ""
            return (left[-1:] if left else ""), (right[:1] if right else "")
        except Exception:
            res = self._native_edit_caret(line_suffix)
            if res is not None:
                return res
            return self._value_pattern_caret(line_suffix)

    def read_field(self):
        """Recupera (antes_cursor, despues_cursor) en campos autorizados no privados (máx. LIMIT)."""
        if not self.can_read or self.element is None:
            return None
        limit = Composition.LIMIT
        try:
            pattern = self.element.GetCurrentPattern(10014).QueryInterface(self.interfaces.IUIAutomationTextPattern)
            selection = pattern.GetSelection()
            if selection.Length != 1:
                return None
            caret = selection.GetElement(0)
            if caret.CompareEndpoints(0, caret, 1) != 0:
                return None
            left, right = caret.Clone(), caret.Clone()
            left.MoveEndpointByUnit(0, 0, -limit)
            right.MoveEndpointByUnit(1, 0, limit)
            before = self._normalize_uia_text(left.GetText(limit))
            after = self._normalize_uia_text(right.GetText(limit))
            if after.endswith("\n"):
                try:
                    doc_end = pattern.DocumentRange
                    if right.CompareEndpoints(1, doc_end, 1) == 0:
                        after = after[:-1]
                except Exception:
                    if after == "\n":
                        after = ""
            before = before[-limit:]
            after = after[:max(0, limit - len(before))]
            return before, after
        except Exception:
            pass
        res = self._native_edit_read(limit)
        if res is not None:
            return res
        return self._value_pattern_read(limit)

    def _value_pattern_caret(self, line_suffix):
        try:
            hwnd = getattr(self.element, "CurrentNativeWindowHandle", 0)
            if hwnd and hasattr(self, "user32"):
                name = ctypes.create_unicode_buffer(32)
                if self.user32.GetClassNameW(hwnd, name, len(name)) and name.value == "Edit":
                    return None
            vp = self.element.GetCurrentPattern(10002).QueryInterface(self.interfaces.IUIAutomationValuePattern)
            raw_val = vp.CurrentValue
            if raw_val is not None and not isinstance(raw_val, str):
                return None
            val = self._normalize_uia_text(raw_val or "")
            if len(val) > Composition.LIMIT:
                return None
            line = val.rsplit("\n", 1)[-1]
            if line_suffix:
                if not line.endswith(line_suffix):
                    return None
                return line_suffix[-1:], ""
            return (line[-1:] if line else ""), ""
        except Exception:
            return None

    def _value_pattern_matches(self, before, after):
        if after:
            return None
        try:
            vp = self.element.GetCurrentPattern(10002).QueryInterface(self.interfaces.IUIAutomationValuePattern)
            raw_val = vp.CurrentValue
            if raw_val is not None and not isinstance(raw_val, str):
                return None
            val = self._normalize_uia_text(raw_val or "")
            line = val.rsplit("\n", 1)[-1]
            return line.endswith(before)
        except Exception:
            return None

    def _value_pattern_read(self, limit):
        try:
            vp = self.element.GetCurrentPattern(10002).QueryInterface(self.interfaces.IUIAutomationValuePattern)
            raw_val = vp.CurrentValue
            if raw_val is not None and not isinstance(raw_val, str):
                return None
            val = self._normalize_uia_text(raw_val or "")
            if len(val) > limit:
                val = val[-limit:]
            return val, ""
        except Exception:
            return None

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

    def _native_edit_read(self, limit):
        try:
            hwnd = self.element.CurrentNativeWindowHandle
            name = ctypes.create_unicode_buffer(32)
            if not hwnd or not self.user32.GetClassNameW(hwnd, name, len(name)) or name.value != "Edit":
                return None
            selection = self._edit_message(hwnd, 0xB0)  # EM_GETSEL
            start, end = selection & 0xFFFF, (selection >> 16) & 0xFFFF
            if selection >= 0xFFFFFFFF or start != end:
                return None
            length = self._edit_message(hwnd, 0x0E)  # WM_GETTEXTLENGTH
            if 0 <= length <= limit:
                buf = ctypes.create_unicode_buffer(length + 2)
                self._edit_message(hwnd, 0x0D, length + 1, ctypes.addressof(buf))  # WM_GETTEXT
                raw = buf.value or ""
                before = self._normalize_uia_text(raw[:start])
                after = self._normalize_uia_text(raw[start:])
                return before[-limit:], after[:max(0, limit - len(before))]
            return None
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


def _read_probe_field(probe):
    reader = getattr(probe, "read_field", None)
    if not callable(reader):
        return None
    try:
        res = reader()
    except Exception:
        return None
    if isinstance(res, tuple) and len(res) == 2 and isinstance(res[0], str) and isinstance(res[1], str):
        return res
    return None


class Composition:
    """Texto en RAM y acotado para el campo activo verificado."""
    LIMIT = 2048

    def __init__(self):
        self.clear()

    def clear(self):
        self.text, self.cursor, self.status = "", 0, "empty"

    def load(self, before, after="", status="confirmed"):
        before = (before or "")[-self.LIMIT:]
        rem = max(0, self.LIMIT - len(before))
        after = (after or "")[:rem]
        self.text = before + after
        self.cursor = len(before)
        self.status = status if self.text else "empty"

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
    MAX_SAVED_FIELDS = 16

    def __init__(self):
        self.target = None
        self.composition = Composition()
        self._saved_fields = {}
        self.reset()

    def _field_key(self, target=None):
        t = self.target if target is None else target
        if t is not None and t.predictive:
            return (t.window, t.runtime)
        return None

    def save_current_field(self):
        key = self._field_key()
        if key is None:
            return
        if self.composition.text:
            if key not in self._saved_fields and len(self._saved_fields) >= self.MAX_SAVED_FIELDS:
                oldest = next(iter(self._saved_fields))
                self._saved_fields.pop(oldest, None)
            self._saved_fields[key] = (
                self.composition.text,
                self.composition.cursor,
                self.composition.status,
                self.draft,
                self.tail,
                list(self.context),
            )
        else:
            self._saved_fields.pop(key, None)

    def reset(self, clear_saved=False):
        if clear_saved:
            key = self._field_key()
            if key is not None:
                self._saved_fields.pop(key, None)
        self.composition.clear()
        self.reset_words()

    def reset_all(self):
        self._saved_fields.clear()
        self.reset()

    def reset_words(self):
        self.draft, self.tail, self.context = "", "", []

    def sync_words_from_composition(self):
        if not self.target or not self.target.predictive or not self.composition.text:
            self.reset_words()
            return
        after = self.composition.text[self.composition.cursor:]
        if after and (after[0].isalnum() or after[0] == "_"):
            self.reset_words()
            return
        before = unicodedata.normalize("NFC", self.composition.text[:self.composition.cursor])
        line = before.rsplit("\n", 1)[-1]
        self.tail = line[-180:]
        if not line:
            self.draft = ""
            self.context = []
            return
        matches = list(WORD.finditer(line))
        if matches and matches[-1].end() == len(line):
            start_idx = matches[-1].start()
            if start_idx == 0 or (not line[start_idx - 1].isalnum() and line[start_idx - 1] != "_"):
                self.draft = matches[-1].group(0)
                prefix_clause = re.split(r"[,.;:!?¿¡]+", line[:start_idx])[-1]
                self.context = WORD.findall(prefix_clause)[-2:]
                return
        if line[-1].isspace():
            self.draft = ""
            clause = re.split(r"[,.;:!?¿¡]+", line)[-1]
            self.context = WORD.findall(clause)[-2:]
        elif line[-1] in ",.;:!?¿¡":
            self.draft = ""
            self.context = []
        else:
            self.reset_words()

    def restore_or_sync(self, probe, recover_external=True):
        if not self.target or not self.target.predictive:
            self.reset()
            return False
        key = self._field_key()
        if recover_external:
            field_text = _read_probe_field(probe)
            if field_text is not None:
                before, after = field_text
                if before or after:
                    self.composition.load(before, after, status="confirmed")
                    self.sync_words_from_composition()
                    self.save_current_field()
                    return True
                # El proveedor UIA confirmó que el campo está vacío actualmente
                if key is not None:
                    self._saved_fields.pop(key, None)
                self.reset()
                return False
        saved = self._saved_fields.get(key) if key is not None else None
        if saved is not None:
            text, cursor, status, draft, tail, context = saved
            self.composition.text = text
            self.composition.cursor = cursor
            self.composition.status = status if status != "empty" else "recovered"
            self.draft, self.tail, self.context = draft, tail, list(context)
            verified = self.composition.verify(probe)
            if verified is False:
                self._saved_fields.pop(key, None)
                self.reset()
                self.composition.status = "changed"
                return False
            if verified is None:
                self.composition.status = "recovered"
            self.sync_words_from_composition()
            return True
        return False

    def set_target(self, target):
        if target != self.target:
            self.save_current_field()
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
                    self.save_current_field()
                self.reset_words()
                return True
            return False
        raw_edges = probe.caret(self.tail)
        edges = ((raw_edges[0] or ""), (raw_edges[1] or "")) if raw_edges is not None else None
        verified = edges is not None and not (not self.tail and
                   (edges[0].isalnum() or edges[1].isalnum() or "_" in edges))
        if not verified:
            self.reset_words()
        if not allowed():
            return False
        typer.write(text)
        self.composition.write(text)
        if not verified:
            self.save_current_field()
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
        self.save_current_field()
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
            if not modifiers and name == "⌫" and self.target.predictive and self.composition.text:
                self.sync_words_from_composition()
            else:
                self.reset_words()
        if self.target.predictive:
            self.save_current_field()
        return True

    def choose(self, word, probe, typer, dictionary, settings, allowed):
        if word not in {value for value, _ in self.suggestions(dictionary, settings)}:
            return False
        raw_edges = probe.caret(self.tail)
        if raw_edges is None:
            self.reset()
            return False
        left, right = (raw_edges[0] or ""), (raw_edges[1] or "")
        if right in ("\r", "\n", "\u200b"):
            right = ""
        if (not self.draft and left.isalnum()) or right.isalnum() or right == "_":
            return False
        if not allowed():
            return False
        recheck = probe.caret(self.tail)
        if recheck is None:
            self.reset()
            return False
        recheck_left, recheck_right = (recheck[0] or ""), (recheck[1] or "")
        if recheck_right in ("\r", "\n", "\u200b"):
            recheck_right = ""
        if (recheck_left, recheck_right) != (left, right) or not allowed():
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
        self.save_current_field()
        return True
