from pathlib import Path
from dataclasses import asdict
import tempfile
import unittest
from unittest.mock import Mock, patch

from keyboard_dictionary import Dictionary
from keyboard_input import KeyboardSession, KeyboardTyper, Target, WindowsKeyboardFocus


class Buffer:
    """Campo y cursor simulados. Sólo el adaptador de Windows usa SendInput."""
    def __init__(self, text="", cursor=None):
        self.text = text
        self.cursor = len(text) if cursor is None else cursor

    def caret(self,suffix):
        left = self.text[:self.cursor]
        if not left.endswith(suffix):
            return None
        return left[-1:], self.text[self.cursor:self.cursor+1]

    def write(self,text,backspaces=0):
        left = self.cursor - backspaces
        self.text = self.text[:left] + text + self.text[self.cursor:]
        self.cursor = left + len(text)

    def special(self,name,modifiers=()):
        if name=="⌫":
            self.write("",1)
        elif name=="Enter":
            self.write("\n")


class VirtualKeyboardTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.dictionary = Dictionary(self.root,"perfil_A")
        self.addCleanup(lambda: self.dictionary.close())
        self.session = KeyboardSession()
        self.session.set_target(Target(1,(1,2),True,False))
        self.buffer = Buffer()
        self.settings = dict(suggestions=True, learning=True, corrections=False)
        self.allowed = lambda: True

    def type(self,text):
        for char in text:
            self.session.insert(char,self.buffer,self.buffer,self.dictionary,self.settings,self.allowed)

    def predict(self,prefix="",context=()):
        return [word for word,_ in self.dictionary.suggest(prefix,context)]

    def choose(self,word):
        return self.session.choose(word,self.buffer,self.buffer,self.dictionary,self.settings,self.allowed)

    def test_learns_whole_words_and_context_including_accent_and_case(self):
        self.type("Buenos días señor Ñandú HeadMouse")
        self.assertNotIn("HeadMouse",self.dictionary.words())
        self.type(" ")
        self.assertEqual(set(self.dictionary.words()),{"Buenos","días","señor","Ñandú","HeadMouse"})
        self.assertEqual(self.predict("hea")[0],"HeadMouse")
        self.assertEqual(self.predict("",["buenos"])[0],"días")
        self.assertEqual(self.predict("",["Buenos","días"])[0],"señor")
        self.assertEqual(self.predict("ñ")[0],"Ñandú")

    def test_frequency_then_recency_and_reopen_are_per_profile(self):
        self.dictionary.learn("PersonalViejo",[])
        self.dictionary.learn("PersonalViejo",[])
        self.dictionary.learn("PersonalNuevo",[])
        self.assertEqual(self.predict("Personal")[0],"PersonalViejo")
        self.dictionary.close()
        self.dictionary=Dictionary(self.root,"perfil_A")
        self.assertEqual(self.predict("Personal")[0],"PersonalViejo")
        other=Dictionary(self.root,"perfil_a")
        try:self.assertEqual(other.words(),[])
        finally:other.close()
        now=[0.]
        self.dictionary.clock=lambda:now[0]
        self.dictionary.learn("TerminoViejo",[])
        now[0]=100*3600
        self.dictionary.learn("TerminoNuevo",[])
        self.assertEqual(self.predict("termino")[0],"TerminoNuevo")

    def test_completion_replaces_only_verified_prefix_and_preserves_existing_space(self):
        self.dictionary.learn("HeadMouse",[])
        self.buffer=Buffer("Texto: ",6)
        self.type("hea")
        self.assertTrue(self.choose("HeadMouse"))
        self.assertEqual(self.buffer.text,"Texto:HeadMouse ")
        self.session.reset()
        self.buffer=Buffer()
        self.type("Hea")
        self.assertTrue(self.choose("HeadMouse"))
        self.assertEqual(self.buffer.text,"HeadMouse ")

    def test_completion_rejects_changed_caret_or_retracted_authorization(self):
        self.dictionary.learn("HeadMouse",[])
        self.type("Hea")
        self.buffer.cursor=0
        self.assertFalse(self.choose("HeadMouse"))
        self.assertEqual(self.buffer.text,"Hea")
        self.buffer=Buffer()
        self.type("Hea")
        self.allowed=lambda:False
        self.assertFalse(self.choose("HeadMouse"))
        self.type("z")
        self.assertEqual(self.buffer.text,"Hea")

    def test_completion_rechecks_caret_after_focus_guard(self):
        self.dictionary.learn("HeadMouse",[])
        self.type("hea")
        def focus_same_but_caret_moved():
            self.buffer.cursor=0
            return True
        self.allowed=focus_same_but_caret_moved
        self.assertFalse(self.choose("HeadMouse"))
        self.assertEqual(self.buffer.text,"hea")

    def test_classic_edit_reads_bounded_caret_and_never_reads_private_fields(self):
        import ctypes
        focus=WindowsKeyboardFocus.__new__(WindowsKeyboardFocus)
        focus.can_read=True
        focus.element=Mock(CurrentNativeWindowHandle=123)
        focus.element.GetCurrentPattern.side_effect=RuntimeError("TextPattern ausente")
        focus.user32=Mock()
        def class_name(hwnd,buffer,length):
            buffer.value="Edit"
            return 4
        focus.user32.GetClassNameW.side_effect=class_name
        def message(hwnd,code,*args):
            if code==0xB0:return 3 | (3 << 16)
            if code in (0xC9,0xBB):return 0
            if code==0xC4:
                buffer=(ctypes.c_wchar*5).from_address(args[1])
                self.assertEqual(ord(buffer[0]),4)
                buffer[:4]="Hea "
                return 4
            self.fail(f"Mensaje inesperado: {code}")
        focus._edit_message=Mock(side_effect=message)
        self.assertEqual(focus.caret("Hea"),("a"," "))
        self.assertIsNone(focus.caret("Hola"))
        focus._edit_message.reset_mock()
        focus.can_read=False
        self.assertIsNone(focus.caret(""))
        focus._edit_message.assert_not_called()

    def test_password_and_manual_unverified_fields_never_learn_or_query_text(self):
        for target in (Target(1,(2,),True,True),Target(2,None,False,True,unknown=True)):
            self.session.set_target(target)
            self.buffer=Buffer()
            self.buffer.caret=Mock(side_effect=AssertionError("Campo privado leído"))
            self.type("ClaveSecreta ")
            self.assertEqual(self.session.suggestions(self.dictionary,self.settings),[])
            self.assertEqual(self.dictionary.words(),[])

    def test_learning_off_corrections_explicit_and_delete(self):
        self.settings.update(learning=False, corrections=True)
        self.type("Holaa ")
        self.assertEqual(self.dictionary.words(),[])
        self.type("dia")
        self.assertIn(("día",True),self.session.suggestions(self.dictionary,self.settings))
        self.assertEqual(self.buffer.text,"Holaa dia")
        self.assertTrue(self.choose("día"))
        self.assertEqual(self.buffer.text,"Holaa día ")
        self.dictionary.learn("Buenos",[])
        self.dictionary.learn("Ñandú",["Buenos"])
        self.dictionary.delete("ÑANDÚ")
        self.assertNotIn("Ñandú",self.dictionary.words())
        self.dictionary.clear()
        self.assertEqual(self.dictionary.words(),[])

    def test_backspace_enter_and_target_change(self):
        self.type("aa")
        self.session.special("⌫",(),self.buffer,self.buffer,self.dictionary,self.settings,self.allowed)
        self.type("ño")
        self.session.special("Enter",(),self.buffer,self.buffer,self.dictionary,self.settings,self.allowed)
        self.assertEqual(self.buffer.text,"año\n")
        self.assertIn("año",self.dictionary.words())
        self.type("Pendiente")
        self.session.set_target(Target(2,(3,),True,False))
        self.buffer=Buffer()
        self.type(" ")
        self.assertNotIn("Pendiente",self.dictionary.words())

    @unittest.skipUnless(__import__("sys").platform=="win32","Requiere Win32")
    def test_native_batches_preserve_unicode_and_release_modifiers(self):
        typer=KeyboardTyper()
        typer._send=Mock()
        typer.write("Ñá🙂",backspaces=1)
        batch=typer._send.call_args.args[0]
        self.assertEqual([event.u.ki.wScan for event in batch[2::2]], [0xD1,0xE1,0xD83D,0xDE42])
        self.assertEqual(len(batch),10)
        typer.special("←",("Ctrl","Alt"))
        batch=typer._send.call_args.args[0]
        self.assertEqual([event.u.ki.wVk for event in batch],[0x11,0x12,0x25,0x25,0x12,0x11])
        self.assertEqual([event.u.ki.dwFlags for event in batch],[0,0,1,3,2,2])

    def test_panel_auto_open_modes_manual_fallback_and_mic_request(self):
        from threading import Event
        from types import SimpleNamespace
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication
        from config import KeyboardConfig
        from desktop.keyboard import VirtualKeyboard
        from desktop.keyboard_service import KeyboardService

        app = QApplication.instance() or QApplication([])
        settings = asdict(KeyboardConfig())
        voice = Mock(busy=False,state="idle")
        controller = SimpleNamespace(profile={"user_id":"test"}, dictation=voice, data_dir=self.root,
                                     _dictation_allowed=lambda:True, keyboard_visible=Event())
        bridge = SimpleNamespace(controller=controller, snapshot=lambda:dict(
            profile=controller.profile, settings={"keyboard":settings}))
        focus = Mock()
        focus.focused.return_value = Target(1,(4,),True,False)
        focus.caret.side_effect = self.buffer.caret
        with patch("desktop.keyboard.KeyboardService",side_effect=lambda b,p:KeyboardService(
                b,p,focus_factory=lambda:focus,typer_factory=lambda:self.buffer)):
            panel=VirtualKeyboard(bridge)
        self.addCleanup(panel.close)
        def wait_for(condition):
            for _ in range(60):
                if condition():
                    return
                QTest.qWait(20)
            self.fail("El teclado no llegó al estado esperado")
        wait_for(panel.isVisible)
        voice.start_now.assert_not_called()
        for mode,key in (("ABC","ñ"),("?123","7"),("=\\<","€"),("Acentos","á")):
            QTest.mouseClick(panel.page_buttons[mode],Qt.MouseButton.LeftButton)
            item=next(b for b in panel.letter_buttons if b.text()==key)
            QTest.mouseClick(item,Qt.MouseButton.LeftButton)
        wait_for(lambda:self.buffer.text=="ñ7€á")
        QTest.mouseClick(panel.mic,Qt.MouseButton.LeftButton)
        wait_for(lambda:voice.start_now.called)
        voice.start_now.assert_called_once_with(expected_runtime=(4,))
        focus.focused.return_value=Target(2,(5,),False,True)
        wait_for(lambda:not panel.isVisible())
        settings["auto_open"]=False
        focus.focused.return_value=Target(3,None,False,True,unknown=True)
        panel.toggle()
        wait_for(panel.isVisible)
        self.assertTrue(panel.state["usable"])
        self.assertEqual(panel.state["predictions"],[])
        self.assertFalse(panel.mic.isEnabled())

    def test_explorer_xaml_bridge_and_autosuggestbox_focus_resolution(self):
        from types import SimpleNamespace
        from keyboard_input import WindowsKeyboardFocus

        focus = WindowsKeyboardFocus()
        rect = SimpleNamespace(left=1469, top=362, right=1839, bottom=411)
        zero_rect = SimpleNamespace(left=0, top=0, right=0, bottom=0)

        def make_find_all(items):
            return SimpleNamespace(Length=len(items), GetElement=lambda idx: items[idx])

        search_edit = SimpleNamespace(
            CurrentControlType=50004,
            CurrentClassName="TextBox",
            CurrentAutomationId="TextBox",
            CurrentName="Buscar en Inicio",
            CurrentIsEnabled=True,
            CurrentIsPassword=False,
            CurrentIsKeyboardFocusable=True,
            CurrentHasKeyboardFocus=True,
            CurrentNativeWindowHandle=0,
            CurrentBoundingRectangle=rect,
            GetRuntimeId=lambda: (42, 99),
            GetCurrentPropertyValue=lambda pid: True if pid == focus.VALUE_AVAILABLE else False,
            GetCurrentPattern=lambda pid: Mock(CurrentIsReadOnly=0),
            FindAll=lambda scope, cond: make_find_all([]),
        )
        autosuggest = SimpleNamespace(
            CurrentControlType=50026,
            CurrentClassName="AutoSuggestBox",
            CurrentAutomationId="FileExplorerSearchBox",
            CurrentName="",
            CurrentIsEnabled=True,
            CurrentIsPassword=False,
            CurrentIsKeyboardFocusable=False,
            CurrentHasKeyboardFocus=False,
            CurrentNativeWindowHandle=0,
            CurrentBoundingRectangle=rect,
            GetRuntimeId=lambda: (42, 50),
            GetCurrentPropertyValue=lambda pid: False,
            GetCurrentPattern=lambda pid: (_ for _ in ()).throw(OSError()),
            FindAll=lambda scope, cond: make_find_all([search_edit]),
        )
        xaml_bridge = SimpleNamespace(
            CurrentControlType=50033,
            CurrentClassName="Microsoft.UI.Content.DesktopChildSiteBridge",
            CurrentAutomationId="",
            CurrentName="DesktopChildSiteBridge",
            CurrentIsEnabled=True,
            CurrentIsPassword=False,
            CurrentIsKeyboardFocusable=True,
            CurrentHasKeyboardFocus=True,
            CurrentNativeWindowHandle=777,
            CurrentBoundingRectangle=rect,
            GetRuntimeId=lambda: (42, 10),
            GetCurrentPropertyValue=lambda pid: False,
            GetCurrentPattern=lambda pid: (_ for _ in ()).throw(OSError()),
            FindAll=lambda scope, cond: make_find_all([search_edit]),
        )
        file_item = SimpleNamespace(
            CurrentControlType=50004,
            CurrentClassName="UIProperty",
            CurrentAutomationId="System.ItemNameDisplay",
            CurrentName="Nombre",
            CurrentIsEnabled=True,
            CurrentIsPassword=False,
            CurrentIsKeyboardFocusable=False,
            CurrentHasKeyboardFocus=False,
            CurrentNativeWindowHandle=777,
            CurrentBoundingRectangle=rect,
            GetRuntimeId=lambda: (42, 200),
            GetCurrentPropertyValue=lambda pid: True,
            GetCurrentPattern=lambda pid: Mock(CurrentIsReadOnly=0),
            FindAll=lambda scope, cond: make_find_all([]),
        )

        parents = {
            id(search_edit): autosuggest,
            id(autosuggest): xaml_bridge,
            id(xaml_bridge): None,
        }

        class FakeWalker:
            def GetParentElement(self, el):
                return parents.get(id(el))

        walker = FakeWalker()
        focus._automation = SimpleNamespace(
            ControlViewWalker=walker,
            CreatePropertyCondition=lambda pid, val: (pid, val),
        )
        focus._pointer_in_foreground = lambda: False

        self.assertTrue(focus._is_non_input_item(file_item))
        self.assertFalse(focus._is_non_input_item(search_edit))
        self.assertTrue(focus._classify(search_edit).editable)

        resolved, info = focus._resolve_focus_element(777, autosuggest)
        self.assertIs(resolved, search_edit)
        self.assertTrue(info.editable)

        focus._bridge_focus = None
        resolved_bridge, info_bridge = focus._resolve_focus_element(777, xaml_bridge)
        self.assertIs(resolved_bridge, search_edit)
        self.assertTrue(info_bridge.editable)

        search_edit_zero = SimpleNamespace(**{**search_edit.__dict__, "CurrentBoundingRectangle": zero_rect})
        parents[id(search_edit_zero)] = autosuggest
        self.assertEqual(focus._bounds(search_edit_zero, walker), (1469, 362, 370, 49))

    def test_uia_textpattern_bstr_none_and_whitespace_normalization_in_caret_and_composition(self):
        from types import SimpleNamespace
        focus = WindowsKeyboardFocus.__new__(WindowsKeyboardFocus)
        focus.can_read = True
        focus.interfaces = SimpleNamespace(
            IUIAutomationTextPattern="TextPattern",
            IUIAutomationValuePattern="ValuePattern",
        )

        # Simulate comtypes TextPattern returning None for empty BSTR at end of field (e.g. Notepad / Chromium)
        state = {"before": "Buenos\xa0d", "after": None}

        class FakeRange:
            def __init__(self, kind="caret"):
                self.kind = kind
            def CompareEndpoints(self, e1, other, e2):
                return 0
            def Clone(self):
                return FakeRange(self.kind)
            def MoveEndpointByUnit(self, endpoint, unit, count):
                self.kind = "left" if count < 0 else "right"
            def GetText(self, max_len):
                return state["before"] if self.kind == "left" else state["after"]

        pattern = SimpleNamespace(
            GetSelection=lambda: SimpleNamespace(Length=1, GetElement=lambda idx: FakeRange()),
            DocumentRange=FakeRange("doc"),
        )
        focus.element = SimpleNamespace(
            GetCurrentPattern=lambda pid: SimpleNamespace(QueryInterface=lambda iface: pattern)
        )

        # caret() must normalize \xa0 -> " " and None -> "" (never returning None as right char)
        edges = focus.caret("Buenos d")
        self.assertEqual(edges, ("d", ""))
        self.assertTrue(focus.composition_matches("Buenos d", ""))
        self.assertEqual(focus.read_field(), ("Buenos d", ""))

        # Simulate RichEditD2DPT virtual trailing \r at end of document
        state["after"] = "\r"
        self.assertEqual(focus.caret("Buenos d"), ("d", ""))
        self.assertEqual(focus.read_field(), ("Buenos d", ""))

        # Simulate empty field where both before and after return None in comtypes
        state["before"] = None
        state["after"] = None
        self.assertEqual(focus.caret(""), ("", ""))
        self.assertTrue(focus.composition_matches("", ""))
        self.assertEqual(focus.read_field(), ("", ""))

        # Private field must never read
        focus.can_read = False
        self.assertIsNone(focus.read_field())

    def test_word_suggestions_insertion_all_cases_and_gui_click(self):
        from threading import Event
        from types import SimpleNamespace
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication
        from config import KeyboardConfig
        from desktop.keyboard import VirtualKeyboard
        from desktop.keyboard_service import KeyboardService

        # 1. ho -> hola
        self.buffer = Buffer()
        self.session.reset_all()
        self.session.set_target(Target(1, (1, 2), True, False))
        self.type("ho")
        preds = [w for w, _ in self.session.suggestions(self.dictionary, self.settings)]
        self.assertIn("hola", preds)
        self.assertTrue(self.choose("hola"))
        self.assertEqual(self.buffer.text, "hola ")
        self.assertEqual(self.session.composition.text, "hola ")
        self.assertEqual(self.buffer.cursor, 5)

        # 2. Hea -> HeadMouse
        self.dictionary.learn("HeadMouse", [])
        self.buffer = Buffer()
        self.session.reset_all()
        self.session.set_target(Target(1, (1, 2), True, False))
        self.type("Hea")
        self.assertTrue(self.choose("HeadMouse"))
        self.assertEqual(self.buffer.text, "HeadMouse ")
        self.assertEqual(self.session.composition.text, "HeadMouse ")

        # 3. Buenos d -> Buenos días (without duplicating or deleting "Buenos ")
        self.dictionary.learn("Buenos", [])
        self.dictionary.learn("días", ["Buenos"])
        self.buffer = Buffer()
        self.session.reset_all()
        self.session.set_target(Target(1, (1, 2), True, False))
        self.type("Buenos d")
        self.assertIn("días", [w for w, _ in self.session.suggestions(self.dictionary, self.settings)])
        self.assertTrue(self.choose("días"))
        self.assertEqual(self.buffer.text, "Buenos días ")
        self.assertEqual(self.session.composition.text, "Buenos días ")

        # 4. Empty field with context suggestion & words with tildes and Ñ
        self.dictionary.learn("Ñandú", ["días"])
        self.assertIn("Ñandú", [w for w, _ in self.session.suggestions(self.dictionary, self.settings)])
        self.assertTrue(self.choose("Ñandú"))
        self.assertEqual(self.buffer.text, "Buenos días Ñandú ")

        # 5. Empty field from start when a learned word is suggested on empty prefix after context
        self.buffer = Buffer()
        self.session.reset_all()
        self.session.set_target(Target(1, (1, 2), True, False))
        self.session.context = ["Buenos"]
        self.assertIn("días", [w for w, _ in self.session.suggestions(self.dictionary, self.settings)])
        self.assertTrue(self.choose("días"))
        self.assertEqual(self.buffer.text, "días ")

        # 6. Full GUI click on prediction_buttons[0] (simulating Nose/Eye click in compact mode)
        app = QApplication.instance() or QApplication([])
        settings = asdict(KeyboardConfig(size="compact"))
        gui_buffer = Buffer()
        # Simulate COM BSTR returning None at end of field when caret is at end
        def uia_like_caret(suffix):
            left = gui_buffer.text[:gui_buffer.cursor]
            if not left.endswith(suffix):
                return None
            right = gui_buffer.text[gui_buffer.cursor:gui_buffer.cursor+1]
            return (left[-1:] if left else None), (right if right else None)

        controller = SimpleNamespace(
            profile={"user_id": "perfil_A"},
            dictation=None,
            data_dir=self.root,
            _dictation_allowed=lambda: True,
            keyboard_visible=Event(),
        )
        bridge = SimpleNamespace(
            controller=controller,
            snapshot=lambda: dict(profile=controller.profile, settings={"keyboard": settings}),
        )
        focus = Mock()
        focus.focused.return_value = Target(10, (77,), True, False, bounds=(100, 500, 400, 40))
        focus.caret.side_effect = uia_like_caret
        focus.composition_matches.side_effect = lambda b, a: (
            gui_buffer.text[:gui_buffer.cursor].endswith(b) and gui_buffer.text[gui_buffer.cursor:].startswith(a)
        )
        with patch("desktop.keyboard.KeyboardService", side_effect=lambda b, p: KeyboardService(
                b, p, focus_factory=lambda: focus, typer_factory=lambda: gui_buffer)):
            panel = VirtualKeyboard(bridge)
        self.addCleanup(panel.close)

        def wait_for(cond):
            for _ in range(80):
                app.processEvents()
                if cond():
                    return
                QTest.qWait(20)
            self.fail("Condición no alcanzada en prueba GUI de sugerencias")

        wait_for(panel.isVisible)
        for ch in ("h", "o"):
            btn = next(b for b in panel.letter_buttons if b.text() == ch)
            QTest.mouseClick(btn, Qt.MouseButton.LeftButton)
        wait_for(lambda: gui_buffer.text == "ho" and any("hola" in b.text() for b in panel.prediction_buttons if b.isEnabled()))
        sug_btn = next(b for b in panel.prediction_buttons if "hola" in b.text())
        QTest.mouseClick(sug_btn, Qt.MouseButton.LeftButton)
        wait_for(lambda: gui_buffer.text == "hola " and panel.state.get("preview") == "hola ")
        self.assertEqual(gui_buffer.text, "hola ")
        self.assertEqual(panel.state.get("preview"), "hola ")

    def test_windows_search_flyout_detection_and_panel_bounds(self):
        from types import SimpleNamespace
        focus = WindowsKeyboardFocus()
        box_rect = SimpleNamespace(left=78, top=87, right=802, bottom=147)
        flyout_rect = SimpleNamespace(left=45, top=42, right=835, bottom=784)

        search_box = SimpleNamespace(
            CurrentControlType=50004,
            CurrentClassName="RichEditBox",
            CurrentAutomationId="SearchTextBox",
            CurrentName="Cuadro de búsqueda",
            CurrentIsEnabled=True,
            CurrentIsPassword=False,
            CurrentIsKeyboardFocusable=True,
            CurrentHasKeyboardFocus=True,
            CurrentNativeWindowHandle=0,
            CurrentBoundingRectangle=box_rect,
            GetRuntimeId=lambda: (42, 555),
            GetCurrentPropertyValue=lambda pid: True if pid == focus.VALUE_AVAILABLE else False,
            GetCurrentPattern=lambda pid: Mock(CurrentIsReadOnly=0),
            FindAll=lambda scope, cond: SimpleNamespace(Length=0, GetElement=lambda i: None),
        )
        core_window = SimpleNamespace(
            CurrentControlType=50032,
            CurrentClassName="Windows.UI.Core.CoreWindow",
            CurrentAutomationId="",
            CurrentName="Búsqueda",
            CurrentIsEnabled=True,
            CurrentIsPassword=False,
            CurrentIsKeyboardFocusable=True,
            CurrentHasKeyboardFocus=False,
            CurrentNativeWindowHandle=132692,
            CurrentBoundingRectangle=flyout_rect,
            GetRuntimeId=lambda: (42, 1),
            GetCurrentPropertyValue=lambda pid: False,
            GetCurrentPattern=lambda pid: (_ for _ in ()).throw(OSError()),
            FindAll=lambda scope, cond: SimpleNamespace(Length=1, GetElement=lambda i: search_box),
        )
        parents = {id(search_box): core_window, id(core_window): None}
        walker = SimpleNamespace(GetParentElement=lambda el: parents.get(id(el)))
        focus._automation = SimpleNamespace(
            ControlViewWalker=walker,
            CreatePropertyCondition=lambda pid, val: (pid, val),
        )
        focus._pointer_in_foreground = lambda: False
        focus._window_class_and_title = lambda w: ("Windows.UI.Core.CoreWindow", "Búsqueda")

        self.assertTrue(focus._is_shell_flyout(132692, search_box))
        self.assertEqual(focus._panel_bounds(132692, search_box, walker), (45, 42, 790, 742))
        resolved, info = focus._resolve_focus_element(132692, core_window)
        self.assertIs(resolved, search_box)
        self.assertTrue(info.editable)

    def test_chrome_dom_leak_prevention_value_pattern_and_enclosing_element(self):
        from types import SimpleNamespace
        focus = WindowsKeyboardFocus.__new__(WindowsKeyboardFocus)
        focus.can_read = True
        focus.interfaces = SimpleNamespace(
            IUIAutomationTextPattern="TextPattern",
            IUIAutomationValuePattern="ValuePattern",
        )
        focus.user32 = Mock()
        focus.user32.GetClassNameW.return_value = 0

        # Simulate Chrome Google Search <textarea title="Buscar">:
        # TextPattern leaks webpage DOM ("Ir al contenido\n\n" before, "Buscar\nBuscar con Google" after),
        # while ValuePattern.CurrentValue holds the exact input value ("" or "yyyyb").
        dom_state = {
            "val": "",
            "tp_left": "Gmail\nImágenes\n\n",
            "tp_right": "Buscar\nBuscar con Google\nVoy a tener suerte",
        }

        class FakeChromeRange:
            def __init__(self, kind="caret", count=0):
                self.kind = kind
                self.count = count
            def CompareEndpoints(self, e1, other, e2):
                return 0
            def Clone(self):
                return FakeChromeRange(self.kind, self.count)
            def MoveEndpointByUnit(self, endpoint, unit, count):
                self.kind = "left" if count < 0 else "right"
                self.count = abs(count)
            def GetText(self, max_len):
                if self.kind == "left":
                    full = dom_state["tp_left"] + dom_state["val"]
                    return full[-self.count:] if self.count else ""
                full = dom_state["tp_right"]
                return full[:self.count] if self.count else ""

        text_pattern = SimpleNamespace(
            GetSelection=lambda: SimpleNamespace(Length=1, GetElement=lambda idx: FakeChromeRange()),
            DocumentRange=FakeChromeRange("doc"),
        )
        class FakeValuePattern:
            CurrentIsReadOnly = 0
            @property
            def CurrentValue(self_vp):
                return dom_state["val"]
        value_pattern = FakeValuePattern()

        focus.element = SimpleNamespace(
            CurrentControlType=50004,
            CurrentNativeWindowHandle=0,
            GetRuntimeId=lambda: (42, 777),
            GetCurrentPropertyValue=lambda pid: True if pid == focus.VALUE_AVAILABLE else False,
            GetCurrentPattern=lambda pid: SimpleNamespace(
                QueryInterface=lambda iface: value_pattern if pid == 10002 else text_pattern
            ),
        )

        # Case 1: Empty Google search box -> must NOT leak "Buscar" into read_field() or caret()
        self.assertEqual(focus.read_field(), ("", ""))
        self.assertEqual(focus.caret(""), ("", ""))
        self.assertTrue(focus.composition_matches("", ""))

        # Selecting saved/default suggestion "gracias" on empty Google search box must succeed!
        self.buffer = Buffer()
        self.session.reset_all()
        self.session.set_target(Target(1, (42, 777), True, False))
        self.session.restore_or_sync(focus, recover_external=True)
        self.assertEqual(self.session.composition.text, "")
        preds = [w for w, _ in self.session.suggestions(self.dictionary, self.settings)]
        self.assertIn("gracias", preds)
        self.assertTrue(self.session.choose("gracias", focus, self.buffer, self.dictionary, self.settings, self.allowed))
        self.assertEqual(self.buffer.text, "gracias ")
        self.assertEqual(self.session.composition.text, "gracias ")

        # Case 2: Google search results page with "yyyy" -> typing "b" shows "yyyyb" in composition
        dom_state["val"] = "yyyy"
        dom_state["tp_right"] = "\nyyyyb\nyyyyb\nyyyy yyyy\nyyyy3"
        self.buffer = Buffer("yyyy", 4)
        self.session.reset_all()
        self.session.set_target(Target(1, (42, 778), True, False))
        self.assertTrue(self.session.restore_or_sync(focus, recover_external=True))
        self.assertEqual(self.session.composition.text, "yyyy")
        self.assertEqual(self.session.tail, "yyyy")

        def write_and_update_vp(text, backspaces=0):
            self.buffer.write(text, backspaces)
            dom_state["val"] = self.buffer.text

        typer_proxy = SimpleNamespace(write=write_and_update_vp, special=self.buffer.special)
        self.assertTrue(self.session.insert("b", focus, typer_proxy, self.dictionary, self.settings, self.allowed))
        self.assertEqual(self.buffer.text, "yyyyb")
        self.assertEqual(self.session.composition.text, "yyyyb")
        self.assertTrue(focus.composition_matches("yyyyb", ""))

        # Case 3: Contenteditable element without ValuePattern uses GetEnclosingElement boundary check
        outside_el = SimpleNamespace(GetRuntimeId=lambda: (42, 1))
        inside_el = SimpleNamespace(GetRuntimeId=lambda: (42, 999))
        focus._automation = SimpleNamespace(
            ControlViewWalker=SimpleNamespace(GetParentElement=lambda el: None)
        )

        class BoundedDomRange:
            def __init__(self, steps=0, direction=0):
                self.steps = steps
                self.direction = direction
            def CompareEndpoints(self, e1, other, e2):
                return 0
            def Clone(self):
                return BoundedDomRange(self.steps, self.direction)
            def MoveEndpointByUnit(self, endpoint, unit, count):
                self.direction = -1 if count < 0 else 1
                self.steps = abs(count)
            def GetEnclosingElement(self):
                if self.direction < 0 and self.steps <= 2:
                    return inside_el
                if self.direction > 0:
                    return outside_el
                return outside_el
            def GetText(self, max_len):
                if self.direction < 0:
                    return (" CabeceraDOMho")[-self.steps:]
                return ("Buscar"[:self.steps])

        ce_pattern = SimpleNamespace(
            GetSelection=lambda: SimpleNamespace(Length=1, GetElement=lambda idx: BoundedDomRange()),
            DocumentRange=BoundedDomRange(),
        )
        focus.element = SimpleNamespace(
            CurrentControlType=50030,
            CurrentNativeWindowHandle=0,
            GetRuntimeId=lambda: (42, 999),
            GetCurrentPropertyValue=lambda pid: False,
            GetCurrentPattern=lambda pid: SimpleNamespace(QueryInterface=lambda iface: ce_pattern),
        )
        self.assertEqual(focus.read_field(), ("ho", ""))
        self.assertEqual(focus.caret("ho"), ("o", ""))

