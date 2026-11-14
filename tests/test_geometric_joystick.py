import math
import unittest
from unittest.mock import Mock, patch

from dataclasses import asdict, replace
from copy import deepcopy
from config import EyeTrackingConfig, load_config, settings_for_save
from direction_diagnostic import DIRECTIONS, TARGETS
from face_data import FaceData
from geometric_calibration import GeometricSession, fit, gate_weighted, local_point, repair_axis
from geometric_joystick import GeometricJoystick, calibration_quality, select_usable_candidate
import test_gui


def samples(point):
    return [({"local_both": point}, (.5,.5,-1.4,0.,0.,0.)) for _ in range(10)]


class GeometricTests(unittest.TestCase):
    def record(self):
        data = [(label,samples(TARGETS[label])) for _ in range(2) for label in DIRECTIONS]
        return fit(data,"both",False) | {"context": dict(source="both", camera=dict(frame_width=640,frame_height=480),
            blink_limits=dict(left=.04,right=.04))}

    def test_migration_preserves_nose_and_dwell(self):
        settings = load_config(overrides={"ui":{"tracking_method":"nose","ocular_engine":"eye_openvino",
            "openvino_keyboard_dwell":True}, "gesture":{"sensitivity":83}, "openvino_eye":{"sensitivity":40}})
        self.assertEqual(settings.ui.tracking_method,"nose")
        self.assertEqual(settings.ui.ocular_engine,"eye_joystick")
        self.assertEqual(settings.gesture.sensitivity,83)
        self.assertTrue(settings.ui.ocular_keyboard_dwell)

    def test_projection_uses_comisures_and_weights_reject_disagreement(self):
        eye = dict(blink=False,available=True,eye_ratio=.1,geometry=dict(
            width_px=20.,corner_1_x_px=30.,corner_1_y_px=30.,corner_2_x_px=30.,corner_2_y_px=50.,
            iris_x_px=29.,iris_y_px=38.,canthi_y_raw=.55))
        self.assertEqual(local_point(eye),(.4,.55))
        self.assertIsNone(local_point(eye|{"blink":True}))
        values = dict(local_left=(.4,.5),local_right=(.6,.5),weighted=(.5,.5))
        self.assertNotIn("weighted",gate_weighted(values,(.15,.15)))

    def test_axis_repair_preserves_other_axis_and_invalidates_physical(self):
        record=self.record()
        record["validation"]={"fingerprint":"old"}
        rows=[(label,samples((TARGETS[label][0],TARGETS[label][1]+.01))) for label in ("center","up","down")]
        updated=repair_axis(record,rows,1)
        for label in DIRECTIONS:
            self.assertEqual(updated["candidates"]["local_both"]["centers"][label][0],TARGETS[label][0])
        self.assertNotIn("validation", updated)

    def joystick(self, record=None, arm=True):
        clock = [100.]
        joystick = GeometricJoystick(Mock(_frame_size=(640,480)), record or self.record(), EyeTrackingConfig(), .25,
                                     lambda: clock[0])
        def feed(point, detected=True, *, frame=True, ratio=.12):
            clock[0] += .075 if frame else .016
            stamp = int(clock[0]*1000) if frame else joystick.last_stamp
            fd=FaceData(detected,timestamp_ms=stamp,eye_left_ratio=ratio,eye_right_ratio=ratio,
                        nose_x=.5,nose_y=.5,face_scale=math.exp(-1.4),
                        head_pitch=0.,head_yaw=0.,head_roll=0.)
            with patch("geometric_joystick.observe_direction",return_value={"head":(.5,.5,.25,0.,0.,0.)}), \
                 patch("geometric_joystick.signals",return_value={"local_both":point}):
                return joystick.update(fd,clock[0])
        for _ in range(4 if arm else 0):
            feed(joystick.model.centers["center"])
        return joystick, feed

    def test_zone_moves_center_stops_and_signal_loss_disarms(self):
        joystick, feed = self.joystick(arm=False)
        for _ in range(3):
            self.assertIsNone(feed(TARGETS["right"]))
        self.assertIn("centro de la pantalla", joystick.reason)  # sin pasar por el centro no manda
        for _ in range(4):
            self.assertIsNone(feed(TARGETS["center"]))
        self.assertEqual(joystick.zone, "center")
        self.assertIsNone(feed(TARGETS["right"]))
        self.assertEqual(joystick.reason, "Estabilizando mirada")
        self.assertIsNone(feed(TARGETS["right"]))
        self.assertIsNone(feed(TARGETS["right"]))
        self.assertEqual(joystick.zone, "right")
        event = feed(TARGETS["right"])
        self.assertGreater(event.dx, 0)
        self.assertEqual(event.dy, 0)
        self.assertGreater(feed(TARGETS["right"], frame=False).dx, 0)  # sigue entre fotogramas
        self.assertIsNone(feed(TARGETS["center"]))
        self.assertEqual(joystick.movement,(0.,0.))
        self.assertTrue(joystick.reason.startswith("Centro"))
        self.assertIsNone(feed(TARGETS["right"],False))
        self.assertFalse(joystick.armed)

    def test_each_zone_moves_its_own_direction(self):
        for zone, expected in dict(left=(-1,0), right=(1,0), up=(0,-1), down=(0,1)).items():
            joystick, feed = self.joystick()
            event = [feed(TARGETS[zone]) for _ in range(5)][-1]
            self.assertEqual(joystick.zone, zone)
            self.assertEqual(tuple((value > 0) - (value < 0) for value in (event.dx, event.dy)), expected)

    def test_looking_outside_the_pad_keeps_pointer_still(self):
        joystick, feed = self.joystick()
        for _ in range(4):
            feed(TARGETS["right"])
        self.assertEqual(joystick.zone, "right")
        for _ in range(6):
            self.assertIsNone(feed((2.2, .5)))  # varias veces más allá del borde: fuera de la pantalla
        self.assertEqual(joystick.zone, "outside")
        self.assertIn("fuera de la pantalla", joystick.reason)
        self.assertEqual(joystick.movement, (0., 0.))
        self.assertTrue(joystick.armed)
        self.assertGreater([feed(TARGETS["right"]) for _ in range(4)][-1].dx, 0)

    def test_speed_grows_while_held_and_blink_keeps_the_ramp(self):
        joystick, feed = self.joystick()
        steps = [feed(TARGETS["right"]) for _ in range(30)]
        first, last = steps[3].dx, steps[-1].dx
        self.assertGreater(last, first * 2)
        self.assertIsNone(feed(TARGETS["right"], ratio=.01))  # parpadeo
        self.assertEqual(joystick.movement, (0., 0.))
        resumed = [feed(TARGETS["right"]) for _ in range(4)]
        self.assertGreater(resumed[-1].dx, first * 2)

    def test_zones_are_recognised_even_when_signal_axes_are_skewed(self):
        # Medido con webcam real: al mirar arriba el iris también se corre de costado,
        # y mirar a la izquierda sube casi tanto como mirar arriba.
        offsets = dict(center=(0., 0.), up=(.0159, -.0094), down=(.0112, .0062),
                       left=(-.0244, -.0088), right=(.0321, .0017))
        record = self.record()
        candidate = record["candidates"]["local_both"]
        candidate["centers"] = {name: (.5 + dx, .5 + dy) for name, (dx, dy) in offsets.items()}
        candidate["noise"] = (.0047, .0013)
        self.assertTrue(all(calibration_quality(record, EyeTrackingConfig())[3]))
        for zone in ("up", "down", "left", "right"):
            joystick, feed = self.joystick(record)
            for _ in range(5):
                feed(candidate["centers"][zone])
            self.assertEqual(joystick.zone, zone)
        joystick, feed = self.joystick(record)
        feed((.5 - .0244 * 5, .5 - .0088 * 5))
        self.assertEqual(joystick.zone, "outside")

    def test_uneven_reach_partial_gaze_and_rest_drift_from_a_real_session(self):
        # Sesión real por bordes, en unidades de ruido: abajo recorre la mitad que arriba.
        record = self.record()
        candidate = record["candidates"]["local_both"]
        zones = dict(left=(-25.7, 5.1), right=(24.3, -6.4), up=(-2.9, -16.8), down=(-4.2, 10.1))
        candidate["centers"] = {"center": (.5, .5)} | {k: (.5 + x/1000, .5 + y/1000) for k, (x, y) in zones.items()}
        candidate["noise"] = (.001, .001)
        def seen(x, y, joystick=None):
            joystick = joystick or self.joystick(record)[0]
            return joystick._classify((x, y))
        self.assertEqual(seen(-17.8, 10.4), "left")    # a medio camino hacia el borde
        self.assertEqual(seen(-17.8, 27.4), "left")    # el vertical inflado no le gana al horizontal
        self.assertEqual(seen(-12.5, 5.3), "center")   # todavía cerca del centro, y no «abajo»
        self.assertEqual(seen(1.4, 28.7), "down")      # más abajo que el punto calibrado
        self.assertEqual(seen(-0.5, 10.4), "down")
        self.assertEqual(seen(-1.7, -16.6), "up")
        self.assertEqual(seen(-0.4, -13.2), "up")
        self.assertEqual(seen(21.9, -10.2), "right")
        # El descanso real quedó corrido hacia arriba y con saltos hacia abajo: no tiene que mover.
        for rest in ((0.6, -9.1), (-1.1, -5.9), (6.3, 7.4), (5.8, 6.6)):
            self.assertEqual(seen(*rest), "center")
        self.assertEqual(seen(-3., 63.), "outside")    # ojos casi cerrados o mirando el teclado

    def test_voice_freeze_keeps_pointer_still_until_released(self):
        joystick, feed = self.joystick()
        joystick.frozen = True
        for _ in range(6):
            self.assertIsNone(feed(TARGETS["right"]))
        self.assertIn("quieto por voz", joystick.reason)
        self.assertTrue(joystick.armed)
        joystick.frozen = False
        self.assertGreater([feed(TARGETS["right"]) for _ in range(4)][-1].dx, 0)

    def test_pointer_goes_to_where_you_look_and_stays_when_you_look_at_it(self):
        joystick, feed = self.joystick()
        right = TARGETS["right"]              # se mira cerca del borde derecho (~93 % con el estirado)
        joystick.cursor = (.3, .5)            # puntero lejos, a la izquierda de la mirada
        self.assertGreater([feed(right) for _ in range(5)][-1].dx, 0)
        joystick.cursor = (.96, .5)           # el puntero llegó: mirarlo no lo mueve
        for _ in range(5):
            self.assertIsNone(feed(right))
        self.assertIn("ya está donde mirás", joystick.reason)
        self.assertEqual(joystick.movement, (0., 0.))
        joystick.cursor = (.9, .5)            # falta muy poco: no rearranca por un temblor
        for _ in range(5):
            self.assertIsNone(feed(right))
        # Con el horizontal resuelto, el vertical sigue disponible: abajo a la derecha.
        joystick.cursor = (.96, .2)
        corner = (TARGETS["right"][0], TARGETS["down"][1])
        event = [feed(corner) for _ in range(5)][-1]
        self.assertEqual((event.dx, event.dy > 0), (0., True))
        # Cerca de llegar va más despacio que lejos.
        def speed(cursor_x):
            joystick, feed = self.joystick()
            joystick.cursor = (cursor_x, .5)
            return [feed(right) for _ in range(40)][-1].dx
        self.assertLess(speed(.8), speed(.2))

    def test_summary_explains_where_the_session_spent_its_time(self):
        joystick, feed = self.joystick()
        for point in (TARGETS["center"],)*3 + (TARGETS["right"],)*5 + ((2.2,.5),)*2:
            feed(point)
        summary = joystick.summary()
        self.assertEqual(summary["samples_by_zone"], dict(center=7, right=5, outside=2))
        self.assertEqual(len(joystick.trace), 14)
        self.assertGreater(summary["movement_events"], 0)
        self.assertGreater(summary["pixels_moved"], 0)
        self.assertIn("Centro · puntero quieto", summary["seconds_by_state"])
        self.assertEqual(summary["usable_axes"], [True, True])

    def test_one_outlier_in_center_fixation_does_not_block_the_axis(self):
        record = self.record()
        record["candidates"]["local_both"]["center_extent"] = (.3, .3)
        self.assertTrue(all(calibration_quality(record, EyeTrackingConfig())[3]))

    def test_safety_requires_an_axis_with_usable_range_and_center(self):
        record = self.record()
        candidate = record["candidates"]["local_both"]
        self.assertTrue(all(calibration_quality(record, EyeTrackingConfig())[3]))
        candidate["noise"] = (.0, .3)
        horizontal, vertical = calibration_quality(record, EyeTrackingConfig())[3]
        self.assertIsNotNone(horizontal)
        self.assertIsNone(vertical)
        candidate["noise"] = (.3, .3)
        self.assertFalse(any(calibration_quality(record, EyeTrackingConfig())[3]))

    def test_candidate_selection_prefers_usable_axes_then_cleanest_signal(self):
        record = self.record()
        candidate = record["candidates"]["local_both"]
        candidate["noise"] = (.3, .3)
        record["candidates"]["weighted"] = deepcopy(candidate) | {"noise": (.01, .3)}
        record["candidates"]["hybrid_both"] = deepcopy(candidate) | {"noise": (.03, .3)}
        selected = select_usable_candidate(record, EyeTrackingConfig())
        self.assertEqual(selected["selected"], "weighted")
        self.assertEqual(tuple(bool(axis) for axis in calibration_quality(selected, EyeTrackingConfig())[3]), (True, False))
        self.assertEqual(record["selected"], "local_both")

    def test_both_eyes_fall_back_to_the_single_eye_that_sees_both_axes(self):
        record = self.record()
        candidate = record["candidates"]["local_both"]
        candidate["noise"] = (.3, .0)
        record["candidates"]["local_right"] = deepcopy(candidate) | {"noise": (.01, .01)}
        selected = select_usable_candidate(record, EyeTrackingConfig())
        self.assertEqual(selected["selected"], "local_right")
        self.assertTrue(all(calibration_quality(selected, EyeTrackingConfig())[3]))

    def test_small_pose_drift_is_allowed_but_outside_pose_stops(self):
        joystick = GeometricJoystick(Mock(_frame_size=(640,480)), self.record(), EyeTrackingConfig(), .25, lambda: 100.)
        face = FaceData(True, timestamp_ms=99990, nose_x=.505, nose_y=.5, face_scale=math.exp(-1.4),
                        head_pitch=1., head_yaw=0., head_roll=0., eye_left_ratio=.12, eye_right_ratio=.12)
        self.assertTrue(joystick._posture_ok(face))
        self.assertTrue(joystick._posture_ok(replace(face, nose_x=.56, head_yaw=8., face_scale=math.exp(-1.3))))
        far = replace(face, nose_x=.7)
        joystick.armed = True
        with patch("geometric_joystick.signals", return_value={"local_both": TARGETS["right"]}):
            self.assertIsNone(joystick.update(far, 100.))
        self.assertFalse(joystick.armed)
        self.assertIn("Postura fuera", joystick.reason)
        self.assertEqual(joystick.summary()["posture_out_of_range"], {"nariz_x": 1})

    def test_movement_preferences_survive_switching_between_both_ocular_modes(self):
        direct = load_config(overrides={"ui":{"tracking_method":"eye_absolute","unified_eyes":True}})
        edited = asdict(direct)
        edited["ui"].update(tracking_method="eye_joystick", ocular_engine="eye_joystick")
        joystick = settings_for_save(direct, edited)
        edited = asdict(joystick)
        edited["eye"]["sensitivity"] = 73
        edited["ui"].update(tracking_method="eye_absolute", ocular_engine="eye_absolute")
        restored = settings_for_save(joystick, edited)
        self.assertEqual(restored.eye.sensitivity, direct.eye.sensitivity)
        edited = asdict(restored)
        edited["ui"].update(tracking_method="eye_joystick", ocular_engine="eye_joystick")
        self.assertEqual(settings_for_save(restored, edited).eye.sensitivity, 73)

    def test_recenter_is_bounded_and_retains_original(self):
        record = self.record()
        record["validation"] = {"fingerprint": "histórico"}
        session = GeometricSession(lambda: 0., record["context"], "recenter", saved=record)
        with self.assertRaisesRegex(ValueError, "cambió demasiado"):
            session._recenter(samples((.9,.9)))
        self.assertIsNone(session.checkpoint)
        session._recenter(samples((.53,.48)))
        self.assertEqual(session.checkpoint["previous"], record)
        self.assertNotIn("validation", session.checkpoint)
        before = record["candidates"]["local_both"]["centers"]
        after = session.checkpoint["candidates"]["local_both"]["centers"]
        self.assertEqual(after["center"], (.53,.48))
        self.assertAlmostEqual(after["right"][0] - after["center"][0], before["right"][0] - before["center"][0])


@unittest.skipUnless(test_gui.QT_AVAILABLE, "Requiere PySide6")
class GeometricGuiTests(unittest.TestCase):
    setUpClass = classmethod(test_gui.GUITests.setUpClass.__func__)
    setUp = test_gui.GUITests.setUp
    tearDown = test_gui.GUITests.tearDown
    wait = test_gui.GUITests.wait
    select_calibrated = test_gui.GUITests.select_calibrated

    def test_home_switches_modes_and_joystick_calibration_never_acquires_mouse(self):
        self.select_calibrated()
        self.bridge.request("select_ocular_mode", mode="eye_joystick")
        self.wait(lambda: self.bridge.snapshot()["settings"]["ui"]["tracking_method"] == "eye_joystick")
        self.window.refresh()
        self.assertEqual(self.window.home_ocular.currentData(), "eye_joystick")
        self.assertFalse(self.window.activate_button.isEnabled())
        self.window.open_eye_calibration()
        self.window.start_public_ocular_movement()
        self.wait(lambda: self.bridge.snapshot().get("direction_diagnostic") is not None)
        self.assertEqual(self.bridge.snapshot()["direction_diagnostic"]["total"], 5)
        self.wait(lambda: self.bridge.snapshot()["direction_diagnostic"]["state"] != "await_target")
        panel = self.window.direction_panel
        self.assertIs(self.window.ocular_content.currentWidget(), panel)
        self.assertFalse(self.window.eye_preview.isVisible())
        from joystick_pad import pad_rect
        pad = self.window.joystick_pad
        self.wait(pad.isVisible)
        rect = pad_rect(self.window.screen_context())
        self.assertEqual([pad.x(), pad.y(), pad.width(), pad.height()], rect)
        self.assertEqual(pad.geometry(), self.window.screen().geometry())
        self.assertIsNotNone(pad.target)
        self.window.stop_immediately()
        self.wait(lambda: not self.bridge.snapshot().get("camera"))
        self.window.refresh()
        self.assertEqual(self.window.ocular_content.currentIndex(), 0)
        self.assertFalse(pad.isVisible())
        self.bridge.request("select_ocular_mode", mode="eye_absolute")
        self.wait(lambda: self.bridge.snapshot()["settings"]["ui"]["tracking_method"] == "eye_absolute")
        self.assertEqual(self.manager.store.load("julian")["settings"]["ui"]["tracking_method"], "eye_absolute")
        self.backend_factory.assert_not_called()

    def test_five_targets_save_and_offer_control_directly(self):
        import json
        from PySide6.QtWidgets import QMessageBox
        from screen_mapping import screen_display
        from test_eye_tracking import eye_face

        self.select_calibrated()
        self.bridge.request("select_ocular_mode", mode="eye_joystick")
        self.wait(lambda: self.bridge.snapshot()["settings"]["ui"]["tracking_method"] == "eye_joystick")
        self.controller.session_guard = lambda: True
        self.controller.global_stop_available = True
        gaze_x, gaze_y = .5, .5
        def gaze():
            return eye_face(x=gaze_x, y=gaze_y, timestamp_ms=int(self.controller.clock()*1000),
                            eye_left_ratio=.12, eye_right_ratio=.12, face_scale=math.exp(-1.4),
                            nose_x=.5, nose_y=.5, head_pitch=0., head_yaw=0., head_roll=0.)
        class EyeVision(test_gui.FakeVision):
            def get_face_data(self):
                return gaze()
        self.controller.vision_factory = EyeVision
        self.window.refresh()
        self.assertEqual(self.window.home_action.text(), "Calibrar joystick · 5 puntos")
        self.window.home_action.click()
        self.wait(lambda: self.bridge.snapshot()["direction_diagnostic"] is not None)
        self.controller.direction_diagnostic.fixation_s = .65
        targets = ("center", "left", "right", "up", "down")
        for target in targets:
            self.wait(lambda: self.bridge.snapshot()["direction_diagnostic"]["target"] == target)
            gaze_x, gaze_y = TARGETS[target]
            self.assertFalse(self.window.direction_panel.activate.isVisible())
        self.wait(lambda: self.window.direction_panel.activate.isVisible())
        session = self.bridge.snapshot()["direction_diagnostic"]
        self.assertEqual((session["done"], session["total"]), (5, 5))
        self.assertFalse(self.window.joystick_pad.isVisible())
        self.assertTrue(self.window.activate_button.isEnabled())
        record = json.loads(self.controller._geometric_path.read_bytes())
        self.assertEqual(len(record["training_counts"]), 5)
        from joystick_pad import pad_rect
        self.assertEqual(record["context"]["pad"], pad_rect(self.window.screen_context()))
        evidence = list((self.controller.data_dir / "logs").glob("joystick-calibration-*.json"))
        self.assertEqual(len(evidence), 1)
        self.assertTrue(all(calibration_quality(record, self.controller.config.eye)[3]))
        self.backend_factory.assert_not_called()
        with patch("desktop.window.QMessageBox.question", return_value=QMessageBox.StandardButton.No):
            self.window.direction_panel.activate.click()
        self.backend_factory.assert_not_called()
        x, y, width, height = screen_display(self.window.screen_context())["physical_rect"]
        self.backend.position.return_value = (x + 10, y + 10)
        self.backend.size.return_value = (width, height)
        vision = self.controller.vision
        gaze_x, gaze_y = TARGETS["center"]
        with patch("desktop.window.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
            self.window.direction_panel.activate.click()
        self.wait(lambda: self.bridge.snapshot()["control_enabled"])
        self.assertIs(self.controller.vision, vision)
        self.assertIsNone(self.bridge.snapshot()["direction_diagnostic"])
        self.backend_factory.assert_called_once()
        self.backend.moveRel.assert_not_called()
        pad = self.window.joystick_pad
        self.wait(lambda: pad.isVisible() and pad.zone == "center")
        self.wait(lambda: self.controller.geometric_joystick.ready)
        self.assertIsNone(pad.target)
        # Mirar la zona derecha del recuadro mueve el puntero real; volver al centro lo frena.
        gaze_x, gaze_y = TARGETS["right"]
        self.wait(lambda: self.backend.moveRel.called)
        self.assertGreater(self.backend.moveRel.call_args.args[0], 0)
        self.assertEqual(self.backend.moveRel.call_args.args[1], 0)
        self.wait(lambda: pad.zone == "right")
        gaze_x, gaze_y = TARGETS["center"]
        self.wait(lambda: self.controller.geometric_joystick.zone == "center")
        moved = self.backend.moveRel.call_count
        self.wait(lambda: pad.zone == "center")
        self.assertEqual(self.backend.moveRel.call_count, moved)
        self.window.stop_immediately()
        self.wait(lambda: not self.bridge.snapshot()["camera"])
