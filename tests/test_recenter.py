"""Recentrado automático al reanudar: cámara más alta o más baja que al calibrar."""
import unittest
from unittest.mock import Mock
from calibration_session import CalibrationSession
from config import load_config
from control_engine import ControlEngine
from face_data import FaceData
from gesture_engine import GestureEngine, GestureEvent
from test_adaptive_session import NEUTRAL, ACTIVE
from test_core import calibration


class RecenterTests(unittest.TestCase):
    def setUp(self):
        self.ms = 1000

    def clock(self): return self.ms / 1000

    def feed(self, engine, frames, **values):
        events = []
        for _ in range(frames):
            self.ms += 50
            events += engine.update(FaceData(True, timestamp_ms=self.ms, **(NEUTRAL | values)))
        return events

    def engine(self, profile=None, **settings):
        config = load_config(overrides={"gesture": settings} if settings else None).gesture
        return GestureEngine(None, config=config, calibration=profile or calibration(), clock=self.clock)

    def test_camera_moved_cursor_drifts_until_recentered(self):
        engine = self.engine()
        # Cámara más baja: la nariz relajada aparece 0,06 más arriba en la imagen.
        drift = [e for e in self.feed(engine, 40, nose_x=.51, nose_y=.44) if e.type == "CURSOR_MOVE"]
        self.assertTrue(drift)  # el cursor se iba solo hacia arriba
        result = engine.recenter(self.ms, guard_ms=0)
        self.assertTrue(result["ok"], result)
        self.assertAlmostEqual(engine.config.neutral_y, .44)
        self.assertAlmostEqual(result["dy"], -.06)
        still = [e for e in self.feed(engine, 30, nose_x=.51, nose_y=.44) if e.type == "CURSOR_MOVE"]
        self.assertEqual(still, [])
        self.assertTrue(engine.head_still)
        self.assertAlmostEqual(engine.diagnostic()["neutral_y"], .44)

    def test_refuses_when_moving_far_or_without_data(self):
        engine = self.engine()
        self.assertFalse(engine.recenter(self.ms)["ok"])
        for k in range(40):
            self.feed(engine, 1, nose_x=.5 + (.03 if k % 2 else -.03))
        moving = engine.recenter(self.ms, guard_ms=0)
        self.assertFalse(moving["ok"])
        self.assertIn("quieta", moving["reason"])
        self.feed(engine, 40, nose_x=.95, nose_y=.5)
        far = engine.recenter(self.ms, guard_ms=0)
        self.assertFalse(far["ok"])
        self.assertIn("recalibrá", far["reason"])
        self.assertEqual(engine.config.neutral_x, .5)

    def test_low_camera_in_bed_is_recentered_with_warning(self):
        """2026-10-12: nariz en Y 0,736 con neutral calibrado 0,511 (0,225 de diferencia)."""
        engine = self.engine()
        self.feed(engine, 40, nose_x=.49, nose_y=.725)
        result = engine.recenter(self.ms, guard_ms=0)
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["far"])
        self.assertAlmostEqual(engine.config.neutral_y, .725)
        self.assertEqual(engine.diagnostic()["calibrated_neutral"], (.5, .5))

    def test_guard_excludes_the_resume_gesture_itself(self):
        engine = self.engine()
        self.feed(engine, 40, nose_y=.44)
        self.feed(engine, 10, nose_y=.60)  # últimos 0,5 s: otra postura (el gesto)
        self.assertAlmostEqual(engine.recenter(self.ms, guard_ms=500)["dy"], -.06, places=3)

    def calibrated_profile(self):
        config = load_config()
        cc = config.calibration
        cc.countdown_s = cc.measuring_s = cc.transition_s = cc.neutral_window_s = .3
        session = CalibrationSession({"user_id": "recenter"}, config, self.clock)
        session.start()
        for _ in range(4000):
            if session.state in ("measured", "error"): break
            values = ACTIVE.get(session.gesture_id, {}) if session.stage == "active" and \
                3 <= len(session._rows) % 30 < 15 else {}
            self.ms += 50
            session.update(FaceData(True, timestamp_ms=self.ms, **(NEUTRAL | values)))
        self.assertEqual(session.state, "measured")
        return session.candidate

    def test_gesture_thresholds_follow_rest_shift_with_cap(self):
        profile = self.calibrated_profile()
        record = profile["gesture_calibrations"]["LEFT_BROW"]
        rest, activation = record["neutral_statistics"]["left"]["median"], record["activation_threshold"]["left"]
        margin = activation - rest
        engine = self.engine(profile)
        # Con otro ángulo de cámara la ceja relajada mide un 30 % del margen más.
        shifted_rest = rest + .3 * margin
        self.feed(engine, 40, brow_left_lift=shifted_rest)
        self.assertTrue(engine.recenter(self.ms, guard_ms=0)["ok"])
        offset = engine.gesture_offsets["LEFT_BROW"]["left"]
        self.assertAlmostEqual(offset, .3 * margin, places=6)
        self.assertAlmostEqual(engine._gates["LEFT_BROW"].activation["left"], activation + offset, places=6)
        # El reposo desplazado ya no está a 30 % del umbral sino lejos; el gesto sigue detectándose.
        self.assertEqual([e.type for e in self.feed(engine, 8, brow_left_lift=.4) if e.type != "CURSOR_MOVE"],
                         ["SCROLL_UP"])
        # Un desplazamiento enorme se limita a la mitad del margen calibrado.
        engine = self.engine(profile)
        self.feed(engine, 40, brow_left_lift=rest + 3 * margin, brow_right_lift=.22)
        engine.recenter(self.ms, guard_ms=0)
        self.assertNotIn("LEFT_BROW", engine.gesture_offsets)  # ceja "activa" todo el rato: no es reposo

    def test_resume_soon_after_pausing_uses_the_still_moment(self):
        """Pausar mueve la nariz (hasta 0,034 al levantar ambas cejas)."""
        engine = self.engine()
        self.feed(engine, 30, nose_y=.60)                      # cursor yéndose solo
        for k in range(12):                                    # pausa: cejas arriba, nariz se mueve
            self.feed(engine, 1, nose_y=.60 + (.02 if k % 2 else -.02), brow_left_lift=.4, brow_right_lift=.5)
        for k in range(8):                                     # baja las cejas, acomoda la cabeza
            self.feed(engine, 1, nose_y=.60 - .02 * k)
        self.feed(engine, 25, nose_y=.45)                      # 1,25 s quieto en la postura cómoda
        self.feed(engine, 12, nose_y=.45, brow_left_lift=.4, brow_right_lift=.5)  # gesto de reanudar
        result = engine.recenter(self.ms, guard_ms=630)
        self.assertTrue(result["ok"], result)
        self.assertAlmostEqual(engine.config.neutral_y, .45)

    def test_still_frames_inside_short_gaps_are_not_enough(self):
        engine = self.engine()
        for k in range(80):
            self.feed(engine, 1, nose_y=.5 + .03 * ((k // 3) % 2))  # 150 ms quieto, salta, repite
        self.assertFalse(engine.recenter(self.ms, guard_ms=0)["ok"])

    def test_recenter_never_accumulates(self):
        engine = self.engine()
        for _ in range(3):
            self.feed(engine, 40, nose_y=.45)
            engine.recenter(self.ms, guard_ms=0)
        self.assertAlmostEqual(engine.config.neutral_y, .45)
        self.feed(engine, 40, nose_y=.5)
        self.assertAlmostEqual(engine.recenter(self.ms, guard_ms=0)["dy"], 0)


class ControlResumeTests(unittest.TestCase):
    def make(self, **settings):
        backend = Mock()
        backend.size.return_value = (1920, 1080)
        gesture = Mock()
        gesture.config = load_config(overrides={"gesture": settings} if settings else None).gesture
        gesture.recenter.return_value = dict(ok=True, dx=0, dy=-.05, gestures=6)
        vision = Mock()
        import time
        vision.get_face_data.return_value = FaceData(True, timestamp_ms=int(time.monotonic() * 1000))
        vision.get_fps.return_value = 30
        return ControlEngine(vision, gesture, backend=backend, wheel_unit=1), gesture

    def test_only_resume_recenters_excluding_the_gesture(self):
        control, gesture = self.make()
        gesture.update.return_value = [GestureEvent("BOTH_BROWS", source_timestamp_ms=5000)]
        control._tick()  # pausado → activo
        self.assertFalse(control.paused)
        c = gesture.config
        # Primera reanudación (arranca en pausa): sin pausa previa registrada.
        gesture.recenter.assert_called_once_with(5000, guard_ms=c.brow_decision_ms + c.both_brows_hold_ms + 250,
                                                 since_ms=None)
        self.assertTrue(control.last_recenter["ok"])
        control._tick()  # activo → pausado: no recentra
        self.assertTrue(control.paused)
        self.assertEqual(gesture.recenter.call_count, 1)

    def test_can_be_disabled(self):
        control, gesture = self.make(auto_recenter=False)
        gesture.update.return_value = [GestureEvent("BOTH_BROWS", source_timestamp_ms=5000)]
        control._tick()
        gesture.recenter.assert_not_called()


if __name__ == "__main__": unittest.main()


class DiagnosticRecenterTests(unittest.TestCase):
    """Sin control activo (vista previa / diagnóstico), ambas cejas también recentran."""

    def test_pause_gesture_recenters_without_control(self):
        import tempfile, time
        from pathlib import Path
        from application_controller import ApplicationController
        from profile_manager import ProfileManager
        from profiles import ProfileStore
        with tempfile.TemporaryDirectory() as temp:
            c = ApplicationController(ProfileManager(ProfileStore(Path(temp) / "p")), data_dir=temp)
            c.vision = Mock(error=None)
            c.vision.is_alive.return_value = True
            c.vision.get_face_data.return_value = FaceData(True, timestamp_ms=int(time.monotonic() * 1000))
            c.gesture = Mock()
            c.gesture.update.return_value = [GestureEvent("BOTH_BROWS", source_timestamp_ms=7000)]
            c.gesture.recenter.return_value = dict(ok=True, dx=0, dy=.22, gestures=6, far=True)
            c.step()
            g = c.config.gesture
            c.gesture.recenter.assert_called_once_with(7000, guard_ms=g.brow_decision_ms + g.both_brows_hold_ms + 250)
            self.assertIn("Centro ajustado", c.message)
            self.assertIn("recalibrá", c.message)
            c.vision = None


class UnreachableCenterTests(unittest.TestCase):
    """2026-10-12: con el centro mal ubicado, la nariz relajada quedaba fuera de la
    zona muerta; el bloqueo de cejas impedía pausar/reanudar sin buscar el cuadro."""

    def setUp(self):
        self.ms = 1000

    def clock(self): return self.ms / 1000

    def face(self, **values):
        return FaceData(True, timestamp_ms=self.ms, **(NEUTRAL | values))

    def test_paused_accepts_both_brows_off_center_but_never_scroll(self):
        engine = GestureEngine(None, calibration=calibration(), clock=self.clock)
        engine.both_brows_anywhere = True
        events = []
        for _ in range(20):
            self.ms += 50
            events += engine.update(self.face(nose_y=.70, brow_left_lift=.4, brow_right_lift=.5))
        self.assertIn("BOTH_BROWS", [e.type for e in events])
        for _ in range(30):
            self.ms += 50
            engine.update(self.face(nose_y=.70))
        scroll = []
        for _ in range(20):
            self.ms += 50
            scroll += engine.update(self.face(nose_y=.70, brow_left_lift=.4))
        self.assertEqual([e.type for e in scroll if e.type != "CURSOR_MOVE"], [])

    def control(self, gesture, position):
        backend = Mock()
        backend.size.return_value = (1920, 1080)
        backend.position.side_effect = position
        vision = Mock()
        vision.get_face_data.side_effect = lambda: self.current
        vision.get_fps.return_value = 22
        return ControlEngine(vision, gesture, backend=backend, wheel_unit=1), backend

    def run_control(self, control, seconds, **values):
        from unittest.mock import patch
        with patch("control_engine.time.monotonic", self.clock):
            for _ in range(int(seconds / .05)):
                self.ms += 50
                self.current = self.face(**values)
                control._tick()

    def test_flag_follows_pause_state(self):
        gesture = Mock()
        gesture.config = load_config().gesture
        gesture.update.return_value = []
        control, _ = self.control(gesture, lambda: (0, 0))
        self.run_control(control, .1)
        self.assertTrue(gesture.both_brows_anywhere)
        control._paused = False
        self.run_control(control, .1)
        self.assertFalse(gesture.both_brows_anywhere)

    def test_cursor_pinned_against_edge_recenters_by_itself(self):
        engine = GestureEngine(None, calibration=calibration(), clock=self.clock)
        control, backend = self.control(engine, lambda: (960, 1079))  # abajo de todo, no se mueve más
        control._paused = False
        self.run_control(control, 1.5, nose_y=.70)                   # cámara baja: el cursor se va solo
        self.assertTrue(backend.moveRel.called)
        self.assertIsNone(control.last_recenter)
        self.run_control(control, 1.0, nose_y=.70)
        self.assertTrue(control.last_recenter and control.last_recenter["ok"], control.last_recenter)
        self.assertTrue(control.last_recenter["pinned"])
        self.assertAlmostEqual(engine.config.neutral_y, .70)
        backend.moveRel.reset_mock()
        self.run_control(control, 1.0, nose_y=.70)
        backend.moveRel.assert_not_called()                          # ya no se desvía

    def test_cursor_that_keeps_moving_is_not_recentered(self):
        engine = GestureEngine(None, calibration=calibration(), clock=self.clock)
        positions = iter((960, y) for y in range(100, 100000, 7))
        control, _ = self.control(engine, lambda: next(positions))
        control._paused = False
        self.run_control(control, 4, nose_y=.70)                     # el usuario mueve el cursor a propósito
        self.assertIsNone(control.last_recenter)
        self.assertEqual(engine.config.neutral_y, .5)

    def test_resume_uses_posture_taken_during_the_pause(self):
        """Log del 2026-10-28: pausaba en la zona quieta, se acomodaba y reanudaba en ~1 s;
        el recentrado elegía el segundo previo a la pausa y el centro casi no se movía."""
        engine = GestureEngine(None, calibration=calibration(), clock=self.clock)
        control, _ = self.control(engine, lambda: (960, 540))
        control._paused = False
        self.run_control(control, 2.0)                                           # activo, en la zona quieta
        self.run_control(control, 0.6, brow_left_lift=.4, brow_right_lift=.5)  # pausa con ambas cejas
        self.assertTrue(control.paused)
        self.run_control(control, 0.4, nose_y=.6)                              # se acomoda
        self.run_control(control, 0.7, nose_y=.68)                             # postura cómoda, < 1 s quieto
        self.run_control(control, 0.6, nose_y=.68, brow_left_lift=.4, brow_right_lift=.5)  # reanuda
        self.assertFalse(control.paused)
        self.assertTrue(control.last_recenter["ok"], control.last_recenter)
        self.assertAlmostEqual(engine.config.neutral_y, .68, places=3)

    def test_controller_reports_pinned_recenter(self):
        import tempfile
        from pathlib import Path
        from application_controller import ApplicationController
        from profile_manager import ProfileManager
        from profiles import ProfileStore
        with tempfile.TemporaryDirectory() as temp:
            c = ApplicationController(ProfileManager(ProfileStore(Path(temp) / "p")), data_dir=temp)
            c._report_recenter(dict(ok=True, dx=0, dy=.2, gestures=6, far=True, pinned=True))
            self.assertIn("trabado contra el borde", c.message)
