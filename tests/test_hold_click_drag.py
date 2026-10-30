"""Click izquierdo sostenido (arrastrar con guiño + nariz) y calibración en una sola pantalla."""
import importlib.util
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

from config import ControlConfig, GestureConfig, load_config
from control_engine import ControlEngine
from face_data import FaceData
from gesture_engine import GestureEngine
from test_adaptive_session import NEUTRAL
from test_core import calibration


class HoldClickDragTests(unittest.TestCase):
    def setUp(self):
        self.ms = 1000
        self.face = FaceData(True, timestamp_ms=self.ms, **NEUTRAL)
        self.vision = Mock()
        self.vision.get_fps.return_value = 30
        self.vision.get_face_data.side_effect = lambda: self.face
        self.backend = Mock()
        self.backend.size.return_value = (1920, 1080)
        self.backend.position.return_value = (500, 500)
        self.backend.FailSafeException = RuntimeError

    def clock(self):
        return self.ms / 1000.0

    def build_engines(self, **control_overrides):
        g_cfg = GestureConfig(smoothing_alpha=0.0)
        c_cfg = ControlConfig(**control_overrides)
        gesture = GestureEngine(self.vision, config=g_cfg, calibration=calibration(), clock=self.clock)
        control = ControlEngine(self.vision, gesture, config=c_cfg, backend=self.backend,
                                wheel_unit=1, clock=self.clock)
        control.toggle_pause()  # activo
        return gesture, control

    def step(self, control, dt_ms=50, **overrides):
        self.ms += dt_ms
        if overrides.get("detected") is False:
            self.face = FaceData(False, timestamp_ms=self.ms)
        else:
            self.face = replace(FaceData(True, timestamp_ms=self.ms, **NEUTRAL), **overrides)
        control._tick()

    def test_short_left_wink_fires_normal_click_without_drag(self):
        _, control = self.build_engines()
        # Guiño corto (~150 ms < 350 ms) y apertura del ojo.
        for _ in range(3):
            self.step(control, 50, eye_left_ratio=0.02)
        self.backend.click.assert_not_called()
        self.backend.mouseDown.assert_not_called()
        self.assertFalse(control.dragging)

        self.step(control, 50)  # ojo izquierdo vuelve a abrirse
        self.backend.click.assert_called_once_with(_pause=False)
        self.backend.mouseDown.assert_not_called()
        self.backend.mouseUp.assert_not_called()
        self.assertFalse(control.dragging)

    def test_sustained_left_wink_latches_drag_with_eyes_open_until_next_left_wink(self):
        _, control = self.build_engines(drag_hold_ms=400, drag_release_ms=80)
        # 1) Guiño izquierdo largo (>= 400 ms) engancha el arrastre.
        for _ in range(9):
            self.step(control, 50, eye_left_ratio=0.02)

        self.assertTrue(control.dragging)
        self.backend.mouseDown.assert_called_once_with(button="left", _pause=False)
        self.backend.click.assert_not_called()  # evita doble click accidental al iniciar arrastre

        # 2) Abrir el ojo izquierdo NO suelta el arrastre: el usuario queda cómodo con ambos ojos abiertos.
        for _ in range(5):
            self.step(control, 50)
        self.assertTrue(control.dragging)
        self.backend.mouseUp.assert_not_called()

        # 3) Con ambos ojos abiertos, mover la nariz mueve el cursor libremente manteniendo presionado el click.
        self.step(control, 50, nose_x=0.68, nose_y=0.40)
        self.step(control, 50, nose_x=0.68, nose_y=0.40)
        self.assertTrue(control.dragging)
        self.assertGreaterEqual(self.backend.moveRel.call_count, 2)
        dx, dy = self.backend.moveRel.call_args.args[:2]
        self.assertGreater(dx, 0)
        self.assertLess(dy, 0)

        # 4) Un parpadeo natural de ambos ojos mientras se mueve el cursor NO corta el arrastre.
        self.step(control, 50, eye_left_ratio=0.02, eye_right_ratio=0.02, nose_x=0.68)
        self.step(control, 50, eye_left_ratio=0.02, eye_right_ratio=0.02, nose_x=0.68)
        self.step(control, 50, nose_x=0.68)
        self.assertTrue(control.dragging)
        self.backend.mouseUp.assert_not_called()

        # 5) Volver a guiñar el ojo izquierdo suelta el arrastre (anclando el cursor y sin disparar click extra).
        moves_before_release = self.backend.moveRel.call_count
        for _ in range(3):  # >= blink_hold_ms (60 ms)
            self.step(control, 50, eye_left_ratio=0.02, nose_x=0.70)
        self.assertFalse(control.dragging)
        self.backend.mouseUp.assert_called_once_with(button="left", _pause=False)
        self.backend.click.assert_not_called()
        self.assertEqual(self.backend.moveRel.call_count, moves_before_release)

        # Aunque el usuario tarde en abrir el ojo tras soltar, no se re-engancha otro arrastre ni hace click.
        for _ in range(10):
            self.step(control, 50, eye_left_ratio=0.02)
        self.step(control, 50)
        self.assertFalse(control.dragging)
        self.assertEqual(self.backend.mouseDown.call_count, 1)
        self.backend.click.assert_not_called()

    def test_quick_second_wink_releases_drag_even_before_blink_cooldown_expires(self):
        _, control = self.build_engines(drag_hold_ms=350, drag_release_ms=50)
        for _ in range(8):  # 400 ms cerrado -> engancha arrastre
            self.step(control, 50, eye_left_ratio=0.02)
        self.assertTrue(control.dragging)
        # Abre el ojo apenas 2 frames (100 ms) y vuelve a guiñar enseguida (< 600 ms de blink_cooldown_ms).
        self.step(control, 50)
        self.step(control, 50)
        self.assertTrue(control.dragging)
        for _ in range(3):
            self.step(control, 50, eye_left_ratio=0.02)
        self.assertFalse(control.dragging)
        self.backend.mouseUp.assert_called_once_with(button="left", _pause=False)
        self.backend.click.assert_not_called()

    def test_safety_releases_mouse_button_on_pause_face_loss_and_stop(self):
        for scenario in ("pause", "face_loss", "stop"):
            with self.subTest(scenario=scenario):
                self.setUp()
                _, control = self.build_engines(drag_hold_ms=300)
                for _ in range(7):
                    self.step(control, 50, eye_left_ratio=0.02)
                self.assertTrue(control.dragging)
                self.backend.mouseDown.assert_called_once_with(button="left", _pause=False)

                if scenario == "pause":
                    control.toggle_pause()
                elif scenario == "face_loss":
                    self.step(control, 50, detected=False)
                else:
                    control.stop()

                self.assertFalse(control.dragging)
                self.backend.mouseUp.assert_called_once_with(button="left", _pause=False)

    def test_disabling_hold_click_executes_immediate_click(self):
        _, control = self.build_engines(hold_click_enabled=False)
        for _ in range(3):
            self.step(control, 50, eye_left_ratio=0.02)
        self.backend.click.assert_called_once_with(_pause=False)
        self.backend.mouseDown.assert_not_called()


@unittest.skipUnless(importlib.util.find_spec("PySide6"), "requiere PySide6")
class SingleScreenCalibrationLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        from desktop.style import apply_style
        cls.app = QApplication.instance() or QApplication([])
        apply_style(cls.app)

    def make_window(self, **overrides):
        from application_controller import ApplicationController
        from desktop.window import MainWindow
        from profile_manager import ProfileManager
        from profiles import ProfileStore
        from render_gui import ReviewBridge
        with tempfile.TemporaryDirectory() as temp:
            snap = ApplicationController(ProfileManager(ProfileStore(Path(temp) / "p")), data_dir=temp).snapshot()
        snap.update(dict(profiles=[], profile={"user_id": "a", "display_name": "Ana"}) | overrides)
        bridge = ReviewBridge(snap)
        window = MainWindow(bridge)
        self.addCleanup(window.close)
        return window, bridge

    def test_calibration_fits_single_laptop_screen_without_scrolling(self):
        meter_two_rows = [
            dict(channel="left", direction=1, neutral=0.20, release=0.24, activation=0.28, comfortable=0.33, value=0.29),
            dict(channel="right", direction=1, neutral=0.21, release=0.25, activation=0.29, comfortable=0.34, value=0.30),
        ]
        wizard_base = dict(
            stage="active", phase=6, total_phases=7, gesture_id="BOTH_BROWS",
            instruction="Levantá AMBAS cejas de forma cómoda y sostenida",
            countdown=0, progress=0.85, samples=24, attempt=2, repetitions=3,
            feedback="Mantené el gesto un instante más", capture_message="Señal clara",
            recognized=["LEFT_CLICK", "RIGHT_CLICK"], meter=meter_two_rows, error="",
            enabled={k: True for k in ("LEFT_WINK", "RIGHT_WINK", "LEFT_BROW", "RIGHT_BROW", "MOUTH_OPEN", "BOTH_BROWS")},
            quality={"LEFT_WINK": dict(label="BUENA", score=1, retries=0)}, can_save=False,
        )
        window, bridge = self.make_window()
        window.resize(1240, 700)  # simula pantalla 1366x768 con barra de tareas de Windows
        window.show()
        window.show_page(2)

        scenarios = (
            ("idle", dict(state="HOME", wizard=None), window.calibration_primary),
            ("measuring_two_channels", dict(state="CALIBRATING", wizard=wizard_base | dict(state="measuring")), window.calibration_primary),
            ("error_retry", dict(state="CALIBRATING", wizard=wizard_base | dict(state="error", error="Gesto débil. Volvé a intentarlo.")), window.calibration_primary),
            ("validated_save", dict(state="CALIBRATING", wizard=wizard_base | dict(state="validated", can_save=True)), window.save_calibration_button),
        )
        for name, patch_data, action_btn in scenarios:
            with self.subTest(scenario=name):
                bridge.data = dict(bridge.data, **patch_data)
                window.refresh()
                self.app.processEvents()
                bar = window.gesture_calibration_scroll.verticalScrollBar()
                self.assertEqual(bar.maximum(), 0, f"No debe requerir scroll vertical en {name} (max={bar.maximum()})")
                viewport = window.gesture_calibration_scroll.viewport().rect()
                top_pos = window.wizard_instruction.mapTo(window.gesture_calibration_scroll.viewport(),
                                                          window.wizard_instruction.rect().topLeft())
                bot_pos = action_btn.mapTo(window.gesture_calibration_scroll.viewport(),
                                           action_btn.rect().bottomRight())
                self.assertGreaterEqual(top_pos.y(), 0)
                self.assertLessEqual(bot_pos.y(), viewport.height())


if __name__ == "__main__":
    unittest.main()
