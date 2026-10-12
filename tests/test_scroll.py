"""Scroll: unidades de rueda en Windows y repetición con la ceja sostenida.

2026-10-11: el scroll se detectaba (8 eventos en 65 s) pero apenas movía la
página. PyAutoGUI en Windows envía el valor crudo a mouse_event y una muesca
son 120 unidades: scroll(3) era 3/120 de muesca.
"""
import unittest
from unittest.mock import Mock
from config import load_config
from control_engine import ControlEngine
from face_data import FaceData
from gesture_engine import GestureEngine, GestureEvent
from test_adaptive_session import NEUTRAL
from test_core import calibration


class ScrollTests(unittest.TestCase):
    def setUp(self):
        self.ms = 1000

    def clock(self): return self.ms / 1000

    def control(self, wheel_unit):
        backend = Mock()
        backend.size.return_value = (1920, 1080)
        return ControlEngine(Mock(), Mock(), backend=backend, wheel_unit=wheel_unit), backend

    def test_scroll_sends_whole_wheel_notches(self):
        control, backend = self.control(120)
        control._execute(GestureEvent("SCROLL_UP"))
        control._execute(GestureEvent("SCROLL_DOWN"))
        self.assertEqual([c.args[0] for c in backend.scroll.call_args_list], [360, -360])
        control, backend = self.control(1)
        control._execute(GestureEvent("SCROLL_UP"))
        backend.scroll.assert_called_once_with(3, _pause=False)

    def test_default_wheel_unit_matches_platform(self):
        import sys
        control, _ = self.control(None)
        self.assertEqual(control.wheel_unit, 120 if sys.platform == "win32" else 1)

    def scrolls(self, engine, frames, **values):
        events = []
        for _ in range(frames):
            self.ms += 50
            events += engine.update(FaceData(True, timestamp_ms=self.ms, **(NEUTRAL | values)))
        return [e.type for e in events if e.type != "CURSOR_MOVE"]

    def engine(self, **settings):
        config = load_config(overrides={"gesture": settings}).gesture
        return GestureEngine(None, config=config, calibration=calibration(), clock=self.clock)

    def test_held_brow_repeats_scroll_until_released(self):
        engine = self.engine()
        # 2 s sostenida: primer scroll a ~200 ms, repeticiones cada 250 ms desde ~700 ms.
        held = self.scrolls(engine, 40, brow_left_lift=.4)
        self.assertEqual(set(held), {"SCROLL_UP"})
        self.assertGreaterEqual(len(held), 6)
        self.assertLessEqual(len(held), 8)
        self.assertEqual(self.scrolls(engine, 20), [])
        self.assertEqual(self.scrolls(engine, 6, brow_left_lift=.4), ["SCROLL_UP"])  # elevación breve: uno

    def test_repeat_can_be_disabled_and_stops_when_head_moves(self):
        self.assertEqual(self.scrolls(self.engine(brow_repeat_ms=0), 40, brow_right_lift=.5), ["SCROLL_DOWN"])
        engine = self.engine()
        first = self.scrolls(engine, 20, brow_right_lift=.5)
        self.assertGreaterEqual(len(first), 2)
        self.assertEqual(self.scrolls(engine, 20, brow_right_lift=.5, nose_y=.42), [])

    def test_both_brows_never_repeat_pause(self):
        engine = self.engine()
        self.assertEqual(self.scrolls(engine, 60, brow_left_lift=.4, brow_right_lift=.5), ["BOTH_BROWS"])


if __name__ == "__main__": unittest.main()
