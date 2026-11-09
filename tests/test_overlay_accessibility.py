"""Composición, reapertura y geometría simuladas, sin acciones físicas."""
from dataclasses import asdict, replace
import os
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from config import KeyboardConfig, load_config
from keyboard_input import Composition, KeyboardSession, Target
from desktop.keyboard_service import KeyboardService, KeyboardVisibility
from desktop.overlay_layout import CameraPlacement, CORNERS, keyboard_rect, logical_field, overlap
from test_virtual_keyboard import Buffer


class VerifiedBuffer(Buffer):
    def composition_matches(self, before, after):
        return (self.text[:self.cursor].endswith(before) and
                self.text[self.cursor:].startswith(after))

    def special(self, name, modifiers=()):
        if name == "Supr":
            self.text = self.text[:self.cursor]+self.text[self.cursor+1:]
        elif name == "←":
            self.cursor = max(0,self.cursor-1)
        elif name == "→":
            self.cursor = min(len(self.text),self.cursor+1)
        else:
            super().special(name,modifiers)


class CompositionTests(unittest.TestCase):
    def session(self, private=False):
        session=KeyboardSession()
        session.set_target(Target(1,(1,),True,private))
        return session,VerifiedBuffer(),asdict(KeyboardConfig(suggestions=False))

    def test_unicode_spaces_punctuation_and_backspace_are_sent_once(self):
        session,buffer,settings=self.session()
        for char in "Hola, Ñandú 🙂 ":
            self.assertTrue(session.insert(char,buffer,buffer,None,settings,lambda:True))
        self.assertEqual(buffer.text,session.composition.text)
        self.assertTrue(session.composition.verify(buffer))
        self.assertEqual(session.composition.status,"confirmed")
        session.special("⌫",(),buffer,buffer,None,settings,lambda:True)
        self.assertEqual(buffer.text,session.composition.text)
        session.special("Enter",(),buffer,buffer,None,settings,lambda:True)
        self.assertEqual(buffer.text,session.composition.text)

    def test_own_navigation_and_delete_keep_a_composition_cursor(self):
        session,buffer,settings=self.session()
        session.insert("hola",buffer,buffer,None,settings,lambda:True)
        session.special("←",(),buffer,buffer,None,settings,lambda:True)
        self.assertEqual(session.composition.cursor,3)
        session.insert("Ñ",buffer,buffer,None,settings,lambda:True)
        session.special("Supr",(),buffer,buffer,None,settings,lambda:True)
        self.assertEqual(buffer.text,"holÑ")
        self.assertEqual(buffer.text,session.composition.text)
        self.assertTrue(session.composition.verify(buffer))

    def test_long_text_is_bounded_but_external_text_is_not_truncated(self):
        session,buffer,settings=self.session()
        text="á\n"*1600
        session.insert(text,buffer,buffer,None,settings,lambda:True)
        self.assertEqual(buffer.text,text)
        self.assertEqual(len(session.composition.text),Composition.LIMIT)
        self.assertEqual(session.composition.cursor,Composition.LIMIT)

    def test_blocked_input_private_fields_and_new_targets_do_not_preview(self):
        session,buffer,settings=self.session(private=True)
        session.insert("private",buffer,buffer,None,settings,lambda:True)
        self.assertEqual(session.composition.text,"")
        session.set_target(Target(2,(1,),True,False))
        self.assertFalse(session.insert("blocked",buffer,buffer,None,settings,lambda:False))
        self.assertEqual(buffer.text,"private")
        session.insert("visible",buffer,buffer,None,settings,lambda:True)
        session.set_target(Target(3,(2,),True,False))
        self.assertEqual(session.composition.text,"")

    def test_external_edit_and_unreadable_provider_are_distinct(self):
        session,buffer,settings=self.session()
        session.insert("hola",buffer,buffer,None,settings,lambda:True)
        self.assertTrue(session.composition.verify(buffer))
        buffer.text="externo"
        self.assertFalse(session.composition.verify(buffer))
        self.assertIsNone(session.composition.verify(object()))

    def test_bounds_changes_do_not_change_target_identity(self):
        target=Target(1,(1,),True,False,bounds=(0,0,50,30))
        self.assertEqual(target,replace(target,bounds=(100,300,50,30)))

    def test_suggestion_updates_the_own_preview_without_duplicate_prefix(self):
        from keyboard_dictionary import Dictionary
        session,buffer,settings=self.session()
        settings["suggestions"]=True
        with tempfile.TemporaryDirectory() as root:
            dictionary=Dictionary(root,"synthetic")
            try:
                dictionary.learn("HeadMouse",[])
                for char in "Hea":
                    session.insert(char,buffer,buffer,dictionary,settings,lambda:True)
                self.assertTrue(session.choose("HeadMouse",buffer,buffer,dictionary,settings,lambda:True))
                self.assertEqual(buffer.text,"HeadMouse ")
                self.assertEqual(session.composition.text,buffer.text)
            finally:dictionary.close()

    def test_only_executed_headmouse_clicks_produce_a_reselection_event(self):
        from contextlib import nullcontext
        from control_engine import ControlEngine
        from gesture_engine import GestureEvent
        backend=Mock()
        backend.size.return_value=(1920,1080)
        backend.position.return_value=(30,20)
        control=ControlEngine(Mock(),Mock(),backend=backend)
        self.assertEqual(control.pointer_click,(0,None,0.))
        with patch("screen_mapping.physical_coordinates",side_effect=nullcontext):
            control._execute(GestureEvent("LEFT_CLICK"))
            self.assertEqual(control.pointer_click[:2],(1,(30,20)))
            control._execute(GestureEvent("DOUBLE_CLICK"))
            self.assertEqual(control.pointer_click[0],2)
            control.movement_only=True
            control._execute(GestureEvent("LEFT_CLICK"))
            self.assertEqual(control.pointer_click[0],2)

    @unittest.skipUnless(os.name=="nt","Adaptador Win32")
    def test_unsupported_modified_character_is_not_reported_as_sent(self):
        from keyboard_input import KeyboardTyper
        typer=KeyboardTyper()
        typer._send=Mock()
        session,buffer,settings=self.session()
        self.assertFalse(session.special("ñ",("Ctrl",),buffer,typer,None,settings,lambda:True))
        typer._send.assert_not_called()
        self.assertEqual(session.composition.text,"")


class ReopenTests(unittest.TestCase):
    def test_hide_waits_for_a_new_selection_of_the_same_field(self):
        state=KeyboardVisibility()
        field=Target(1,(1,),True,False,bounds=(10,10,80,40))
        self.assertFalse(state.update(True,True,field,None,(0,None,0.),0.))
        self.assertTrue(state.update(True,True,field,None,(0,None,0.),.2))
        self.assertFalse(state.update(True,True,field,"hide",(1,(30,20),.2),.3))
        # El click de Ocultar y los sondeos repetidos no reabren el teclado.
        for now in (.31,.5,1.,2.):
            self.assertFalse(state.update(True,True,field,None,(1,(30,20),.35),now))
        self.assertTrue(state.update(True,True,field,None,(2,(30,20),2.1),2.2))

    def test_temporary_focus_loss_does_not_cancel_voluntary_hiding(self):
        state=KeyboardVisibility()
        field=Target(1,(1,),True,False)
        state.update(True,True,field,None,(0,None,0.),0.)
        state.update(True,True,field,"hide",(0,None,0.),.2)
        state.update(True,True,None,None,(0,None,0.),.3)
        self.assertFalse(state.update(True,True,field,None,(0,None,0.),.5))
        self.assertFalse(state.update(True,True,field,None,(0,None,0.),1.))

    def test_new_field_new_window_manual_reopen_and_disable(self):
        state=KeyboardVisibility()
        first=Target(1,(1,),True,False)
        second=Target(1,(2,),True,False)
        state.update(True,True,first,"hide",(0,None,0.),0.)
        state.update(True,True,second,None,(0,None,0.),.2)
        self.assertTrue(state.update(True,True,second,None,(0,None,0.),.4))
        other=replace(second,window=2)
        state.update(True,True,other,None,(0,None,0.),.5)
        self.assertTrue(state.update(True,True,other,None,(0,None,0.),.7))
        for now in (1.,2.,3.):
            self.assertFalse(state.update(True,False,other,"hide",(0,None,0.),now))
            self.assertTrue(state.update(True,False,other,"toggle",(0,None,0.),now+.2))
        self.assertFalse(state.update(False,True,other,"toggle",(0,None,0.),4.))


class FakeScreen:
    def __init__(self, rect, dpr=1.):
        self.rect=QRect(*rect)
        self.dpr=dpr
    def geometry(self):return self.rect
    def availableGeometry(self):return self.rect
    def devicePixelRatio(self):return self.dpr


class OverlayGeometryTests(unittest.TestCase):
    def test_keyboard_upper_lower_central_edges_and_fixed_preferences(self):
        area=QRect(0,0,1920,1040)
        size=QSize(1500,360)
        for field in (QRect(40,950,1500,50),QRect(40,20,1500,50),QRect(40,480,1500,30)):
            rect=keyboard_rect(area,size,field)
            self.assertTrue(area.contains(rect))
            self.assertEqual(overlap(rect,field),0)
        self.assertLess(keyboard_rect(area,size,QRect(0,900,1900,100)).y(),100)
        self.assertGreater(keyboard_rect(area,size,QRect(0,0,1900,100)).y(),600)
        self.assertEqual(keyboard_rect(area,size,None),keyboard_rect(area,size,None,"bottom"))
        self.assertLess(keyboard_rect(area,size,QRect(0,0,1920,100),"top").y(),20)
        for small in (QRect(0,0,640,480),QRect(-1280,0,1280,720)):
            self.assertTrue(small.contains(keyboard_rect(small,QSize(1800,800))))

    def test_uia_physical_coordinates_map_to_the_correct_monitor_at_all_scales(self):
        for scale in (1.,1.25,1.5):
            primary=FakeScreen((0,0,1920,1080))
            secondary=FakeScreen((-1920,120,round(1920/scale),round(1080/scale)),scale)
            screen,rect=logical_field((-1820,220,400,60),[primary,secondary])
            self.assertIs(screen,secondary)
            self.assertEqual(rect.x(),round(-1920+100/scale))
            self.assertEqual(rect.y(),round(120+100/scale))
            self.assertEqual(rect.width(),round(400/scale))
        self.assertEqual(logical_field(None,[primary]),(None,None))
        self.assertEqual(logical_field((99999,99999,20,20),[primary]),(None,None))

    def test_camera_corners_evade_opposite_then_return_after_stability(self):
        area=QRect(-1280,0,1280,720)
        size=QSize(304,268)
        for corner in CORNERS:
            state=CameraPlacement()
            home=state.place(area,size,corner,True,1.,QPoint(-640,350),[],0.)
            away=state.place(area,size,corner,True,1.,home.center(),[],1.)
            self.assertFalse(away.intersects(home))
            self.assertTrue(area.contains(away))
            state.place(area,size,corner,True,1.,QPoint(-640,350),[],1.2)
            self.assertEqual(state.place(area,size,corner,True,1.,QPoint(-640,350),[],1.8),away)
            self.assertEqual(state.place(area,size,corner,True,1.,QPoint(-640,350),[],2.3),home)

    def test_camera_hysteresis_disabled_mode_and_keyboard_priority(self):
        area=QRect(0,0,1920,1080)
        size=QSize(304,268)
        state=CameraPlacement()
        home=state.place(area,size,"bottom_right",False,1.,QPoint(1900,1000),[],0.)
        self.assertGreater(home.x(),1500)
        self.assertEqual(state.place(area,size,"bottom_right",False,1.,home.center(),[],1.),home)
        keyboard=QRect(0,650,1920,430)
        away=state.place(area,size,"bottom_right",False,1.,home.center(),[keyboard],2.)
        self.assertFalse(away.intersects(keyboard))
        # Jitter dentro del margen de retorno no produce cambios por frame.
        state=CameraPlacement()
        state.place(area,size,"bottom_right",True,1.,home.center(),[],0.)
        away=state.place(area,size,"bottom_right",True,1.,home.center(),[],1.)
        for i in range(100):
            point=QPoint(home.left()-20+(i%3),home.top()+20)
            self.assertEqual(state.place(area,size,"bottom_right",True,1.,point,[],1.1+i*.02),away)

    def test_camera_remains_inside_a_new_resolution(self):
        state=CameraPlacement()
        for area in (QRect(0,0,1920,1080),QRect(0,0,640,480),QRect(-800,-600,800,600)):
            rect=state.place(area,QSize(384,320),"bottom_right",True,1.,area.center(),[],10.)
            self.assertTrue(area.contains(rect))


class KeyboardOverlayGUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.buffer=VerifiedBuffer()
        self.focus=Mock()
        self.target=Target(100,(1,),True,False,bounds=(20,650,600,40))
        self.focus.focused.side_effect=lambda:self.target
        self.focus.caret.side_effect=self.buffer.caret
        self.focus.composition_matches.side_effect=self.buffer.composition_matches
        self.settings=asdict(KeyboardConfig(suggestions=False))
        self.control=SimpleNamespace(pointer_click=(0,None,0.))
        self.allowed=True
        self.controller=SimpleNamespace(profile={"user_id":"synthetic"},control=self.control,dictation=None,
            data_dir=Path(self.temp.name),keyboard_visible=threading.Event(),_dictation_allowed=lambda:self.allowed)
        self.bridge=SimpleNamespace(controller=self.controller,snapshot=lambda:dict(
            profile=self.controller.profile,settings={"keyboard":self.settings}))
        from desktop.keyboard import VirtualKeyboard
        with patch("desktop.keyboard.KeyboardService",side_effect=lambda b,p:KeyboardService(
                b,p,focus_factory=lambda:self.focus,typer_factory=lambda:self.buffer)):
            self.panel=VirtualKeyboard(self.bridge)
        self.addCleanup(self.panel.close)

    def wait(self,condition):
        for _ in range(150):
            self.app.processEvents()
            if condition():return
            QTest.qWait(20)
        self.fail("El overlay no llegó al estado esperado")

    def test_visual_acknowledgement_preview_privacy_and_external_change(self):
        self.wait(self.panel.isVisible)
        button=next(b for b in self.panel.letter_buttons if b.text()=="ñ")
        QTest.mouseClick(button,Qt.MouseButton.LeftButton)
        self.assertEqual(button.property("feedback"),"pending")
        self.wait(lambda:self.buffer.text=="ñ")
        self.wait(lambda:button.property("feedback")=="sent")
        self.wait(lambda:self.panel.composition.toPlainText()=="ñ▏")
        self.assertIn("cursor comprobado",self.panel.composition_label.text())
        self.buffer.text="cambio externo"
        self.buffer.cursor=len(self.buffer.text)
        self.wait(lambda:self.panel.state.get("preview")=="")
        self.target=replace(self.target,private=True)
        self.wait(lambda:self.panel.state.get("private"))
        self.assertFalse(self.panel.composition.isVisible())
        self.assertEqual(self.panel.state["preview"],"")

    def test_hide_restore_same_field_manual_and_repeated_cycles(self):
        self.wait(self.panel.isVisible)
        for i in range(3):
            self.panel.hide_keyboard()
            self.wait(self.panel.restore_handle.isVisible)
            QTest.qWait(200)
            self.assertFalse(self.panel.isVisible())
            self.control.pointer_click=(i+1,(40,660),time.monotonic())
            self.wait(self.panel.isVisible)
            self.assertFalse(self.panel.restore_handle.isVisible())
        self.settings["auto_open"]=False
        self.panel.hide_keyboard()
        self.wait(self.panel.restore_handle.isVisible)
        QTest.mouseClick(self.panel.restore_handle,Qt.MouseButton.LeftButton)
        self.wait(self.panel.isVisible)
        self.assertFalse(self.settings["auto_open"])

    def test_layout_is_stable_on_keys_opacity_keeps_input_and_authority_loss_clears(self):
        self.settings.update(opacity=80,enlarged_key=True)
        self.wait(self.panel.isVisible)
        initial=self.panel.geometry()
        self.assertAlmostEqual(self.panel.windowOpacity(),.8,places=1)
        self.assertFalse(self.panel.windowFlags() & Qt.WindowType.WindowTransparentForInput)
        self.panel.press("á")
        self.wait(lambda:self.panel.state.get("preview")=="á")
        self.assertEqual(self.panel.geometry(),initial)
        self.target=replace(self.target,bounds=(22,651,600,40))
        QTest.qWait(260)
        self.assertEqual(self.panel.geometry(),initial)
        self.allowed=False
        self.wait(lambda:not self.panel.isVisible())
        self.assertEqual(self.panel.state["preview"],"")

    def test_preferences_validate_and_survive_existing_profiles(self):
        config=load_config(overrides={"keyboard":{"position":"bottom","opacity":90,"preview":False}})
        self.assertEqual(config.keyboard.position,"bottom")
        self.assertFalse(config.keyboard.preview)
        self.assertEqual(load_config(overrides={"keyboard":asdict(config.keyboard)}).keyboard,config.keyboard)
        for values in ({"opacity":True},{"opacity":65},{"feedback":"yes"},{"position":"unknown"}):
            with self.assertRaises(ValueError):KeyboardConfig(**values)

    def test_camera_and_keyboard_share_the_same_geometry_coordinator(self):
        from PySide6.QtWidgets import QWidget
        self.wait(self.panel.isVisible)
        camera=QWidget()
        self.addCleanup(camera.close)
        camera.show()
        screen=QApplication.primaryScreen()
        coordinator=self.panel.coordinator
        with patch("desktop.overlay_layout.QCursor.pos",return_value=screen.geometry().center()):
            coordinator.present_camera(camera,screen,dict(corner="top_right",size="compact",avoid=True,delay=.3))
            QTest.qWait(180)
            self.assertFalse(camera.geometry().intersects(self.panel.geometry()))
            moves=coordinator.camera_moves
            for _ in range(20):coordinator.update_camera()
            self.assertEqual(coordinator.camera_moves,moves)

    def test_camera_visual_preferences_persist_as_typed_values(self):
        from PySide6.QtCore import QSettings
        from desktop.window import UIPreferences
        prefs=UIPreferences.__new__(UIPreferences)
        path=str(Path(self.temp.name)/"visual.ini")
        prefs._settings=QSettings(path,QSettings.Format.IniFormat)
        for key,value in (("camera_corner","top_left"),("camera_return",1.7),("camera_avoid",False)):
            prefs.set(key,value)
        prefs._settings.sync()
        prefs._settings=QSettings(path,QSettings.Format.IniFormat)
        self.assertEqual(prefs.get("camera_corner","bottom_right"),"top_left")
        self.assertAlmostEqual(prefs.get("camera_return",1.),1.7)
        self.assertFalse(prefs.get("camera_avoid",True))

    def test_destroyed_camera_stops_its_timer_without_late_callbacks(self):
        from PySide6.QtCore import QCoreApplication,QEvent
        from PySide6.QtWidgets import QWidget
        from desktop.overlay_layout import OverlayCoordinator
        camera=QWidget()
        camera.show()
        coordinator=OverlayCoordinator()
        coordinator.present_camera(camera,QApplication.primaryScreen(),{})
        camera.deleteLater()
        QCoreApplication.sendPostedEvents(camera,QEvent.Type.DeferredDelete)
        coordinator.update_camera()
        self.assertFalse(coordinator.timer.isActive())
        self.assertIsNone(coordinator.camera)

    def test_reopen_handle_recovers_when_its_previous_monitor_disappears(self):
        self.wait(self.panel.isVisible)
        removed=Mock()
        removed.availableGeometry.side_effect=AssertionError("Monitor desconectado")
        self.panel.coordinator.keyboard_screen=removed
        self.panel.present(dict(self.panel.state,visible=False,restore=True,bounds=None))
        self.assertTrue(self.panel.restore_handle.isVisible())
        self.assertTrue(QApplication.primaryScreen().availableGeometry().contains(self.panel.restore_handle.geometry()))

    def test_adaptive_size_resolution_and_explorer_search_box_compact_fallback(self):
        from desktop.overlay_layout import resolve_keyboard_size
        # 1080p @ 150% DPI = 1280 x 672 logical work area
        dpi150_area = QRect(0, 0, 1280, 672)
        self.assertEqual(resolve_keyboard_size(dpi150_area, None, "auto"), "compact")
        # 1080p @ 100% DPI = 1920 x 1040 logical work area
        dpi100_area = QRect(0, 0, 1920, 1040)
        self.assertEqual(resolve_keyboard_size(dpi100_area, None, "auto"), "normal")
        # Tight vertical field forces compact even on taller screen
        tight_field = QRect(400, 310, 300, 40)
        self.assertEqual(resolve_keyboard_size(QRect(0, 0, 1440, 650), tight_field, "auto"), "compact")

        # Real Windows Explorer Search Box geometry on 1280x672 logical work area
        explorer_search_logical = QRect(979, 241, 247, 33)
        self.wait(self.panel.isVisible)
        self.panel.apply_effective_size("compact")
        rect = keyboard_rect(dpi150_area, self.panel.sizeHint(), explorer_search_logical, "auto")
        self.assertTrue(dpi150_area.contains(rect))
        self.assertEqual(overlap(rect, explorer_search_logical), 0)
        self.assertLessEqual(rect.height(), 275)
        self.assertLessEqual(rect.width(), 800)

    def test_preview_modes_compact_expanded_toggle_and_hidden(self):
        self.wait(self.panel.isVisible)
        # Default is compact 1-line preview
        self.assertTrue(self.panel.preview_row.isVisible())
        self.assertFalse(self.panel.is_preview_expanded())
        compact_h = self.panel.height()

        # Toggle to expanded preview via button
        QTest.mouseClick(self.panel.preview_toggle, Qt.MouseButton.LeftButton)
        self.assertTrue(self.panel.is_preview_expanded())
        self.assertGreater(self.panel.height(), compact_h)

        # Toggle back to compact preview
        QTest.mouseClick(self.panel.preview_toggle, Qt.MouseButton.LeftButton)
        self.assertFalse(self.panel.is_preview_expanded())
        self.assertEqual(self.panel.height(), compact_h)

        # Hidden preview mode hides preview_row and reduces total keyboard height further
        self.settings["preview_mode"] = "hidden"
        self.panel.present(dict(self.panel.state, preview_mode="hidden", show_preview=False))
        self.assertFalse(self.panel.preview_row.isVisible())
        self.assertLess(self.panel.height(), compact_h)

    def test_win32_topmost_zorder_and_modal_dialog_protection(self):
        from desktop.keyboard import _win32_ensure_topmost, _win32_is_obscured_in_zorder
        self.wait(self.panel.isVisible)
        # Modal dialog active -> must not force topmost over modal dialog
        with patch("desktop.keyboard.QApplication.activeModalWidget", return_value=Mock(isVisible=lambda: True)):
            self.assertFalse(_win32_ensure_topmost(self.panel, target_hwnd=100, force=True, always_on_top=True))

        # Simulated Win32 Z-order where Explorer (hwnd=100) is above keyboard
        fake_u32 = Mock()
        fake_u32.GetWindowRect.return_value = False
        fake_u32.IsWindowVisible.return_value = True
        fake_u32.GetWindow.side_effect = [100, 0]
        self.assertTrue(_win32_is_obscured_in_zorder(fake_u32, 999, 100))

    def test_manual_position_drag_and_new_keyboard_config_options(self):
        cfg = KeyboardConfig(size="auto", position="manual", preview_mode="expanded",
                             keep_visible=True, always_on_top=True)
        self.assertEqual(cfg.size, "auto")
        self.assertEqual(cfg.position, "manual")
        self.assertEqual(cfg.preview_mode, "expanded")
        with self.assertRaises(ValueError):
            KeyboardConfig(preview_mode="invalid")
        with self.assertRaises(ValueError):
            KeyboardConfig(keep_visible="yes")

        self.wait(self.panel.isVisible)
        self.panel.coordinator.set_manual_position(QPoint(120, 140))
        self.assertEqual(self.panel.coordinator.manual_pos, (120, 140))
        area = QRect(0, 0, 1280, 672)
        rect = keyboard_rect(area, QSize(700, 240), None, "manual", manual_pos=self.panel.coordinator.manual_pos)
        self.assertEqual(rect.topLeft(), QPoint(120, 140))

    def test_windows_search_panel_evasion_zero_overlap_and_restore_handle(self):
        self.wait(self.panel.isVisible)
        # Simulate a real 1280x672 screen (1080p @ 150% DPI) and 1920x1040 screen (1080p @ 100% DPI)
        fake_screen = FakeScreen((0, 0, 1280, 672), dpr=1.5)
        search_box = (78, 87, 724, 60)
        search_panel = (45, 42, 790, 742)
        with patch("desktop.overlay_layout.QApplication.screens", return_value=[fake_screen]), \
             patch("desktop.overlay_layout.QApplication.primaryScreen", return_value=fake_screen), \
             patch("desktop.keyboard.QApplication.screens", return_value=[fake_screen]), \
             patch("desktop.keyboard.QApplication.primaryScreen", return_value=fake_screen):
            self.target = Target(132692, (42, 555), True, False, bounds=search_box, panel_bounds=search_panel)
            self.wait(lambda: self.panel.isVisible() and self.panel.state.get("panel_bounds") == search_panel)

            kb_geo = self.panel.geometry()
            _, panel_qrect = logical_field(search_panel, [fake_screen])
            _, box_qrect = logical_field(search_box, [fake_screen])
            self.assertEqual(overlap(kb_geo, panel_qrect), 0)
            self.assertEqual(overlap(kb_geo, box_qrect), 0)
            self.assertTrue(fake_screen.availableGeometry().contains(kb_geo))

            # Hiding keyboard while in Windows Search must place restore_handle outside the Search panel too
            self.panel.hide_keyboard()
            self.wait(self.panel.restore_handle.isVisible)
            self.assertEqual(overlap(self.panel.restore_handle.geometry(), panel_qrect), 0)

            # Reopening restores keyboard outside Search panel
            QTest.mouseClick(self.panel.restore_handle, Qt.MouseButton.LeftButton)
            self.wait(self.panel.isVisible)
            self.assertEqual(overlap(self.panel.geometry(), panel_qrect), 0)

    def test_preview_recovery_on_hide_and_reopen_via_uia_and_session_cache(self):
        self.settings["suggestions"] = True
        self.wait(self.panel.isVisible)

        def type_keys(seq):
            for ch in seq:
                prev_len = len(self.buffer.text)
                self.panel.press(ch)
                self.wait(lambda: len(self.buffer.text) == prev_len + len(ch))

        # Case 1 (Solución B - Session Cache without read_field):
        # Type "Hola, cómo estás", hide keyboard, reopen on same field -> recovers preview & continues typing
        type_keys("Hola, cómo estás")
        self.wait(lambda: self.panel.state.get("preview") == "Hola, cómo estás")
        self.panel.hide_keyboard()
        self.wait(self.panel.restore_handle.isVisible)
        self.assertEqual(self.panel.composition.toPlainText(), "")

        # Reopen keyboard on same field via restore_handle
        QTest.mouseClick(self.panel.restore_handle, Qt.MouseButton.LeftButton)
        self.wait(self.panel.isVisible)
        self.wait(lambda: self.panel.state.get("preview") == "Hola, cómo estás")
        self.assertEqual(self.panel.composition.toPlainText(), "Hola, cómo estás▏")

        type_keys(" amigo")
        self.wait(lambda: self.buffer.text == "Hola, cómo estás amigo")
        self.wait(lambda: self.panel.state.get("preview") == "Hola, cómo estás amigo")

        # Case 2 (Coordination with Suggestions after reopen):
        # Switch to a second field, type "Hola, buen", hide keyboard, reopen -> recovers "Hola, buen" & suggests "buenos"
        self.buffer.text = ""
        self.buffer.cursor = 0
        self.target = Target(100, (2,), True, False, bounds=(20, 650, 600, 40))
        self.wait(lambda: self.panel.state.get("target") == (100, (2,)))

        type_keys("Hola, buen")
        self.wait(lambda: self.panel.state.get("preview") == "Hola, buen")
        self.panel.hide_keyboard()
        self.wait(self.panel.restore_handle.isVisible)

        QTest.mouseClick(self.panel.restore_handle, Qt.MouseButton.LeftButton)
        self.wait(self.panel.isVisible)
        self.wait(lambda: self.panel.state.get("preview") == "Hola, buen")
        self.wait(lambda: any("buen" in b.text() for b in self.panel.prediction_buttons if b.isEnabled()))

        sug_btn = next(b for b in self.panel.prediction_buttons if b.isEnabled() and b.text().startswith("buen"))
        chosen_word = sug_btn.text().replace("✓ ", "")
        QTest.mouseClick(sug_btn, Qt.MouseButton.LeftButton)
        self.wait(lambda: self.buffer.text == f"Hola, {chosen_word} " and self.panel.state.get("preview") == f"Hola, {chosen_word} ")
        self.assertEqual(self.panel.state.get("preview"), f"Hola, {chosen_word} ")

        # Case 3 (Solución A - UIA read_field recovery of existing or externally edited text):
        self.focus.read_field = Mock(side_effect=lambda: (
            self.buffer.text[:self.buffer.cursor], self.buffer.text[self.buffer.cursor:]
        ))
        self.buffer.text = "Buenos d"
        self.buffer.cursor = len(self.buffer.text)
        self.target = Target(100, (3,), True, False, bounds=(20, 650, 600, 40))
        self.wait(lambda: self.panel.state.get("preview") == "Buenos d")
        self.assertEqual(self.panel.composition.toPlainText(), "Buenos d▏")
        self.wait(lambda: any("día" in b.text() for b in self.panel.prediction_buttons if b.isEnabled()))
        dia_btn = next(b for b in self.panel.prediction_buttons if b.isEnabled() and "día" in b.text())
        dia_word = dia_btn.text().replace("✓ ", "")
        QTest.mouseClick(dia_btn, Qt.MouseButton.LeftButton)
        self.wait(lambda: self.buffer.text == f"Buenos {dia_word} " and self.panel.state.get("preview") == f"Buenos {dia_word} ")
        self.assertEqual(self.panel.state.get("preview"), f"Buenos {dia_word} ")
