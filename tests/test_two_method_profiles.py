"""Migración pública Nariz/Ojos sin mezclar modelos ni datos personales."""
import unittest
from copy import deepcopy
from dataclasses import asdict
from config import load_config,method_bank,METHOD_SECTIONS
from profiles import gesture_profile,save_gesture_mode
from ocular_profiles import calibration_for
from test_core import calibration
import test_gaze_save


class PublicProfileTests(unittest.TestCase):
    def setUp(self):
        self.fixture=test_gaze_save.SaveControllerRegressionTests()
        self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.c=self.fixture.c

    def test_existing_direction_profile_keeps_response_and_six_models(self):
        before=deepcopy(self.c.profile)
        self.c.select_control_method("eyes")
        self.assertEqual(self.c.config.ui.tracking_method,"eye")
        self.assertEqual(self.c.config.ui.ocular_engine,"eye")
        self.assertEqual(method_bank(self.c.config),"eyes")
        for key in ("tracking_calibration","tracking_calibrations","absolute_calibration"):
            self.assertEqual(self.c.profile[key],before[key])
        self.assertEqual(self.c.profile["user_id"],before["user_id"])
        self.assertEqual(len(self.c.profiles.list_profiles()),1)
        self.assertEqual(self.c.snapshot(False)["public_method"],"eyes")
        self.assertFalse(self.c._actions_ready())

    def test_nose_settings_and_actions_return_exactly_after_eye_edits(self):
        self.c.select_control_method("nose")
        before={k:deepcopy(asdict(self.c.config)[k]) for k in METHOD_SECTIONS}
        original_gestures=deepcopy(gesture_profile(self.c.profile,"nose"))
        self.c.select_control_method("eyes")
        settings=asdict(self.c.config)
        settings["eye"]["sensitivity"]=33
        settings["eye"]["dead_zone_x"]=.12;settings["eye"]["dead_zone_y"]=.23
        settings["actions"]["bindings"]["RIGHT_WINK"]="DOUBLE_CLICK"
        self.c.save_public_settings(settings,"eyes")
        self.c.select_control_method("nose")
        self.assertEqual({k:asdict(self.c.config)[k] for k in METHOD_SECTIONS},before)
        self.assertEqual(gesture_profile(self.c.profile,"nose")["thresholds"],original_gestures["thresholds"])
        self.c.select_control_method("eyes")
        self.assertEqual(self.c.config.eye.sensitivity,33)
        self.assertEqual(self.c.config.actions.bindings["RIGHT_WINK"],"DOUBLE_CLICK")
        self.assertEqual(self.c.config.eye.dead_zone_y,.23)

    def test_legacy_position_profile_remains_position_and_does_not_fallback(self):
        settings=asdict(self.c.config);settings["ui"]["tracking_method"]="eye_absolute"
        self.c.save_settings(settings)
        self.c.select_control_method("eyes")
        self.assertEqual(self.c.config.ui.ocular_engine,"eye_absolute")
        self.c.profile.pop("absolute_calibration")
        self.c.profile.pop("absolute_calibrations",None)
        with self.assertRaises(ValueError):self.c._require_tracking_calibration()
        self.assertEqual(self.c.config.ui.tracking_method,"eye_absolute")
        self.assertIsNotNone(calibration_for(self.c.profile,"eye"))
        self.fixture.factory.assert_not_called()

    def test_measured_ocular_gestures_migrate_but_nasal_approval_does_not(self):
        self.c.profile=save_gesture_mode(self.c.profile,calibration()|dict(validation={"passed":True}),"eye")
        self.c.select_control_method("eyes")
        self.assertTrue(self.c._actions_ready())
        self.assertTrue(self.c.profile["ocular_migration"]["approvals_preserved"])
        self.assertIn("eye",self.c.profile["gesture_modes"])
        self.assertIn("eyes",self.c.profile["gesture_modes"])
        self.assertEqual(self.c.profile["gesture_mode_origin"]["eyes"],"measured")

    def test_eye_gestures_save_to_shared_eye_bank_only(self):
        self.c.select_control_method("eyes")
        legacy=deepcopy(self.c.profile["gesture_modes"].get("eye"))
        nose=deepcopy(gesture_profile(self.c.profile,"nose")["thresholds"])
        self.c.profile=save_gesture_mode(self.c.profile,calibration()|dict(validation={"passed":True}),method_bank(self.c.config))
        self.c.profiles.store.save(self.c.profile)
        self.c.profile=self.c.profiles.store.load(self.c.profile["user_id"])
        self.assertTrue(self.c._actions_ready())
        self.assertEqual(self.c.profile["gesture_modes"].get("eye"),legacy)
        self.assertEqual(gesture_profile(self.c.profile,"nose")["thresholds"],nose)

    def test_source_switch_preserves_other_sources_and_nose(self):
        before=deepcopy(self.c.profile)
        self.c.select_control_method("eyes")
        for source in ("left","right","both"):
            self.c.select_eye_source(source)
            self.assertEqual(self.c.config.ui.eye_source,source)
            self.assertEqual(self.c.profile["tracking_calibrations"],before["tracking_calibrations"])
        self.c.select_control_method("nose")
        self.assertEqual(gesture_profile(self.c.profile,"nose")["thresholds"],before["thresholds"])

    def test_migration_is_idempotent_and_persisted(self):
        self.c.select_control_method("eyes")
        before=deepcopy(self.c.profile)
        self.c.select_control_method("eyes")
        self.assertEqual(self.c.profile,before)
        self.c.select_control_method("nose");self.c.select_control_method("eyes")
        loaded=self.c.profiles.store.load(self.c.profile["user_id"])
        restored=load_config(overrides=loaded["settings"])
        self.assertTrue(restored.ui.unified_eyes)
        self.assertEqual(method_bank(restored),"eyes")
        self.assertEqual(restored.ui.ocular_engine,"eye")

    def test_new_person_defaults_to_position_after_explicit_eyes_selection(self):
        self.c.create_profile("Otra persona")
        self.assertFalse(self.c.config.ui.unified_eyes)
        self.c.select_control_method("eyes")
        self.assertEqual(self.c.config.ui.tracking_method,"eye_absolute")
        self.assertFalse(self.c.snapshot(False)["tracking_calibrated"])
        self.assertFalse(self.c._actions_ready())

    def test_response_upgrade_is_explicit_and_preserves_direction_model(self):
        self.c.select_control_method("eyes")
        before=deepcopy(self.c.profile["tracking_calibrations"])
        with self.assertRaises(ValueError):self.c.upgrade_ocular_response(False)
        self.assertEqual(self.c.config.ui.tracking_method,"eye")
        self.c.upgrade_ocular_response(True)
        self.assertEqual(self.c.config.ui.tracking_method,"eye_absolute")
        self.assertEqual(self.c.profile["tracking_calibrations"],before)
        self.assertEqual(method_bank(self.c.config),"eyes")
        self.fixture.factory.assert_not_called()

    def test_eye_timing_edit_invalidates_shared_eye_approval_without_touching_nose(self):
        self.c.profile=save_gesture_mode(self.c.profile,calibration()|dict(validation={"passed":True}),"eye")
        self.c.select_control_method("eyes")
        before=deepcopy(gesture_profile(self.c.profile,"nose"))
        data=asdict(self.c.config);data["gesture"]["blink_hold_ms"]+=1
        self.c.save_public_settings(data,"eyes")
        self.assertFalse(self.c._actions_ready())
        self.assertEqual(gesture_profile(self.c.profile,"nose")["validation"],before["validation"])


if __name__=="__main__":unittest.main()
