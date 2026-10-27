"""Geometría sintética y backend simulado: ningún movimiento real."""
import unittest
from unittest.mock import Mock
from screen_mapping import primary_context,screen_display,same_context
from control_engine import ControlEngine
from gesture_engine import GestureEvent
from config import ControlConfig,AbsoluteTrackingConfig


class ScreenMappingTests(unittest.TestCase):
    def context(self,dpr=1.,logical=(-500,100),physical=(200,-100),count=3):
        qt=dict(rect=[*logical,1280,720],dpr=dpr,screen="Pantalla principal",primary=True,monitor_count=count)
        native=[dict(primary=True,screen="DISPLAY2",rect=[*physical,round(1280*dpr),round(720*dpr)])]
        native += [dict(primary=False,screen=f"DISPLAY{i+3}",rect=[-1920*(i+1),-1080,1920,1080]) for i in range(count-1)]
        return primary_context(qt,native)

    def test_multi_monitor_uses_primary_with_independent_logical_and_physical_origins(self):
        for scale in (1.,1.25,1.5,2.):
            context=self.context(scale)
            self.assertEqual(context["monitor_count"],3)
            self.assertEqual(context["origin"],[-500,100])
            self.assertEqual(screen_display(context)["physical_rect"],[200,-100,round(1280*scale),round(720*scale)])

    def test_unverified_multi_monitor_or_mismatched_dpi_is_rejected(self):
        qt=dict(rect=[0,0,1280,720],dpr=1.5,screen="primary",primary=True,monitor_count=2)
        with self.assertRaisesRegex(ValueError,"verificar"):
            primary_context(qt)
        native=[dict(primary=True,screen="DISPLAY1",rect=[0,0,1280,720]),dict(primary=False,screen="DISPLAY2",rect=[1280,0,1280,720])]
        with self.assertRaisesRegex(ValueError,"escalado"):
            primary_context(qt,native)
        native[0]["primary"]=False
        with self.assertRaisesRegex(ValueError,"principal"):
            primary_context(qt,native)

    def test_context_ignores_other_monitor_count_but_detects_primary_dpi_origin_or_camera_changes(self):
        current=self.context()|dict(camera_index=0,frame_width=640,frame_height=480)
        self.assertTrue(same_context(current,current|dict(monitor_count=4)))
        for key,value in (("dpr",1.5),("camera_index",1),("frame_width",1280)):
            self.assertFalse(same_context(current,current|{key:value}))
        moved=self.context(physical=(0,0))|dict(camera_index=0,frame_width=640,frame_height=480)
        self.assertFalse(same_context(current,moved))

    def engine(self,context):
        backend=Mock()
        ox,oy,w,h=screen_display(context)["physical_rect"]
        backend.size.return_value=(w,h)
        backend.position.return_value=(ox+w/2,oy+h/2)
        gesture=Mock()
        gesture.strategy.config=AbsoluteTrackingConfig(max_step_px=30)
        engine=ControlEngine(Mock(),gesture,ControlConfig(max_cursor_delta=36),backend=backend,
            screen_bounds=(ox,oy,w,h))
        return engine,backend

    def test_absolute_conversion_stays_on_primary_and_keeps_step_limit(self):
        context=self.context(1.5)
        engine,backend=self.engine(context)
        x,y=backend.position()
        for nx,ny in ((0,0),(1,1),(.5,.5),(0,1),(1,0)):
            engine._execute(GestureEvent("CURSOR_ABSOLUTE",nx,ny))
            if backend.moveTo.called:
                tx,ty=backend.moveTo.call_args.args
                self.assertLessEqual(((tx-x)**2+(ty-y)**2)**.5,31)
                self.assertTrue(200<=tx<2120 and -100<=ty<980)
        self.assertTrue(backend.FAILSAFE)

    def test_cursor_outside_primary_cannot_jump_in_or_start(self):
        engine,backend=self.engine(self.context())
        backend.position.return_value=(-1000,-500)
        with self.assertRaisesRegex(ValueError,"salió"):
            engine._execute(GestureEvent("CURSOR_ABSOLUTE",.5,.5))
        backend.moveTo.assert_not_called()
        with self.assertRaisesRegex(ValueError,"Llevá"):
            ControlEngine(Mock(),Mock(),backend=backend,screen_bounds=(200,-100,1280,720))
