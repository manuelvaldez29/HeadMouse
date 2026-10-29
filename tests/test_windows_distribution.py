"""Persistencia y autoarranque con registro, cámara y backend simulados."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

from startup_preferences import StartupPreferences,DEFAULTS,prepared
from startup_safety import StableStartup
from user_storage import migrate_legacy,write_json
from test_core import calibration
import test_gui


class MemoryRegistry:
    def __init__(self):self.value=None
    def read(self):return self.value
    def set(self,value):self.value=value


class DistributionStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.registry=MemoryRegistry()
        self.store=StartupPreferences(self.root/"startup.json",self.registry)
        self.profile=calibration()|dict(validation={"passed":True})

    def test_new_install_defaults_have_no_registration_or_automatic_output(self):
        self.assertEqual(self.store.load(),DEFAULTS);self.assertIsNone(self.registry.value)

    def test_automatic_activation_requires_valid_profile_and_explicit_authorization(self):
        for enabled,profile in ((False,self.profile),(True,dict(user_id="draft",status="draft",settings={}))):
            with self.assertRaises(ValueError):self.store.save(enabled,True,False,profile,confirmed=True)
        with self.assertRaisesRegex(ValueError,"explícita"):self.store.save(True,True,False,self.profile)
        self.assertIsNone(self.registry.value)

    def test_accept_persists_consent_restart_and_disable_removes_only_own_entry(self):
        p=self.store.save(True,True,True,self.profile,confirmed=True)
        self.assertIn("--autostart",self.registry.value)
        self.assertTrue(StartupPreferences(self.store.path,self.registry).authorized(p,self.profile))
        p=self.store.save(False,False,False,self.profile)
        self.assertIsNone(self.registry.value);self.assertIsNone(p["authorization"])

    def test_update_keeps_preferences_but_changed_profile_requires_new_consent(self):
        p=self.store.save(True,True,False,self.profile,confirmed=True)
        changed=deepcopy(self.profile);changed["thresholds"]["blink_left"]+=.001
        self.assertFalse(self.store.authorized(p,changed))
        self.assertTrue(self.store.authorized(p,self.profile))
        with patch('startup_preferences.capture_host_id',return_value='other host'):
            self.assertFalse(self.store.authorized(p,self.profile))

    def test_registration_is_rolled_back_if_preferences_cannot_be_written(self):
        self.registry.value='previous HeadMouse command'
        with patch("startup_preferences.write_json",side_effect=PermissionError("read only")):
            with self.assertRaises(PermissionError):self.store.save(True,False,False,self.profile)
        self.assertEqual(self.registry.value,'previous HeadMouse command')
        self.assertFalse(self.store.path.exists())

    def test_corrupt_authorization_fails_closed(self):
        write_json(self.store.path,dict(DEFAULTS,activate=True))
        with self.assertRaises(ValueError):self.store.load()

    def test_migration_copies_and_preserves_all_original_banks_without_overwrite(self):
        from profiles import ProfileStore
        old=self.root/"legacy";new=self.root/"user"
        ProfileStore(old/"profiles").save(self.profile)
        write_json(old/"last_profile.json",dict(user_id=self.profile["user_id"]))
        source=(old/"profiles"/(self.profile["user_id"]+".json")).read_bytes()
        records=migrate_legacy(old,new)
        self.assertTrue(all(r["result"]=="copied" for r in records))
        self.assertEqual((new/"profiles"/(self.profile["user_id"]+".json")).read_bytes(),source)
        self.assertEqual((old/"profiles"/(self.profile["user_id"]+".json")).read_bytes(),source)
        self.assertEqual(migrate_legacy(old,new),records)

    def test_migration_conflict_and_invalid_source_are_retained_without_activation(self):
        from profiles import ProfileStore
        old=self.root/"old";new=self.root/"new"
        ProfileStore(old/"profiles").save(self.profile)
        other=deepcopy(self.profile);other["thresholds"]["blink_left"]+=.002
        ProfileStore(new/"profiles").save(other)
        target=new/"profiles"/(self.profile["user_id"]+".json");before=target.read_bytes()
        (old/"profiles"/"bad.json").write_text('{}')
        records=migrate_legacy(old,new)
        self.assertIn("invalid",[r["result"] for r in records])
        self.assertIn("conflict_preserved",[r["result"] for r in records])
        self.assertEqual(target.read_bytes(),before)
        self.assertTrue(list((new/"migration-conflicts").glob('*.json')))

    def test_later_legacy_changes_are_detected_without_overwriting_imported_profile(self):
        from profiles import ProfileStore
        old=self.root/'old';new=self.root/'new'
        store=ProfileStore(old/'profiles');store.save(self.profile)
        migrate_legacy(old,new)
        target=new/'profiles'/(self.profile['user_id']+'.json');before=target.read_bytes()
        changed=deepcopy(self.profile);changed['thresholds']['blink_left']+=.001
        store.save(changed)
        records=migrate_legacy(old,new)
        self.assertIn('conflict_preserved',[r['result'] for r in records])
        self.assertEqual(target.read_bytes(),before)

    def test_source_and_frozen_resources_are_separate_from_user_data(self):
        from app_paths import data_root,face_model_path,RESOURCE_ROOT
        with patch.dict('os.environ',HEADMOUSE_DATA_DIR=str(self.root/'isolated')):
            self.assertEqual(data_root(),self.root/'isolated')
            self.assertNotEqual(data_root(),RESOURCE_ROOT)
            self.assertTrue(face_model_path().is_file())

    def test_windows_events_stop_and_require_recheck_before_resume(self):
        from desktop.windows_session import WindowsSession
        stop=Mock();session=Mock()
        with patch('desktop.windows_session.sys.platform','linux'):
            events=WindowsSession(Mock(),stop,session)
        self.assertTrue(events.dispatch(0x312,events.HOTKEY));stop.assert_called_once()
        for msg,value in ((0x2b1,7),(0x218,4),(0x2b1,8),(0x218,18)):events.dispatch(msg,value)
        self.assertEqual([c.args for c in session.call_args_list],[(False,),(False,),(True,),(True,)])

    def test_stability_requires_distinct_fresh_frames_and_resets_after_loss(self):
        from face_data import FaceData
        from dataclasses import replace
        from config import load_config
        from dataclasses import asdict
        gate=StableStartup()
        s=dict(settings=asdict(load_config()),camera_status=dict(ready=True),activation_blockers=[],public_method='nose')
        for stamp in range(1000,1900,100):
            s['face']=FaceData(True,timestamp_ms=stamp)
            self.assertFalse(gate.update(s,stamp/1000))
        s['face']=FaceData(True,timestamp_ms=1900)
        self.assertTrue(gate.update(s,1.9));self.assertFalse(gate.update(s,1.9))
        s['face']=FaceData(False,timestamp_ms=2000)
        self.assertFalse(gate.update(s,2.));self.assertEqual(len(gate.rows),0)


@unittest.skipUnless(test_gui.QT_AVAILABLE,"Requiere PySide6")
class DistributionGUITests(unittest.TestCase):
    setUpClass=classmethod(test_gui.GUITests.setUpClass.__func__)
    setUp=test_gui.GUITests.setUp
    def tearDown(self):
        if hasattr(self,'_resident'):self._resident.close()
        if hasattr(self,'_instance'):self._instance.close()
        test_gui.GUITests.tearDown(self)
    wait=test_gui.GUITests.wait
    select_calibrated=test_gui.GUITests.select_calibrated

    def resident(self):
        from desktop.resident import Resident
        service=StartupPreferences(self.root/"startup.json",MemoryRegistry())
        r=Resident(self.window,service,native=False);r.timer.stop()
        self._resident=r
        self.addCleanup(r.close)
        self.controller.session_guard=lambda:True
        return r

    def test_settings_defaults_and_accept_or_reject_consent_are_real(self):
        from PySide6.QtWidgets import QMessageBox
        self.select_calibrated();r=self.resident();w=r.controls
        self.assertFalse(w.enabled.isChecked());self.assertFalse(w.activate.isChecked())
        w.profiles.setCurrentIndex(w.profiles.findData('julian'));w.enabled.setChecked(True);w.activate.setChecked(True)
        with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.No):self.assertFalse(w.save())
        self.assertIsNone(r.store.registry.value)
        with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes):self.assertTrue(w.save())
        self.assertTrue(r.store.authorized(r.store.load(),self.controller.profile))
        self.backend_factory.assert_not_called()

    def test_autostart_open_only_prepares_camera_but_never_constructs_control(self):
        self.select_calibrated();r=self.resident()
        r.preferences=r.store.save(True,False,False,self.controller.profile)
        with patch('desktop.resident.desktop_unlocked',return_value=True):
            r.begin();r.timer.start(50)
            self.wait(lambda:self.bridge.snapshot()['camera'] and not r.pending)
        self.assertFalse(self.bridge.snapshot()['control_enabled']);self.backend_factory.assert_not_called()

    def test_authorized_start_requires_stability_and_lock_stops_immediately(self):
        self.select_calibrated();r=self.resident()
        r.preferences=r.store.save(True,True,False,self.controller.profile,confirmed=True)
        with patch('desktop.resident.desktop_unlocked',return_value=True):
            r.begin();self.backend_factory.assert_not_called();r.timer.start(50)
            self.wait(lambda:self.bridge.snapshot()['control_enabled'])
            r.session_changed(False)
            self.assertTrue(self.controller.emergency.is_set())
            self.wait(lambda:not self.bridge.snapshot()['camera'])
            r.disarm();r.session_changed(True)
            self.assertFalse(r.rearm);self.assertFalse(r.pending)

    def test_missing_or_changed_profile_cannot_construct_backend(self):
        self.select_calibrated();r=self.resident()
        r.preferences=r.store.save(True,True,False,self.controller.profile,confirmed=True)
        changed=deepcopy(self.controller.profile);changed['thresholds']['blink_left']+=.001
        self.manager.store.save(changed)
        with patch('desktop.resident.desktop_unlocked',return_value=True):r.begin()
        self.assertFalse(r.pending);self.backend_factory.assert_not_called()

    def test_worker_rejects_forged_startup_request_without_saved_authorization(self):
        self.select_calibrated();r=self.resident()
        self.controller.emergency.clear()
        with self.assertRaisesRegex(ValueError,'autorización'):self.controller.activate_startup_control()
        self.backend_factory.assert_not_called()

    def test_unlock_repeats_stability_and_reauthorizes_current_profile(self):
        self.select_calibrated();r=self.resident()
        r.preferences=r.store.save(True,True,False,self.controller.profile,confirmed=True)
        with patch('desktop.resident.desktop_unlocked',return_value=True):
            r.begin();r.timer.start(50)
            self.wait(lambda:self.bridge.snapshot()['control_enabled'])
            r.session_changed(False);self.wait(lambda:not self.bridge.snapshot()['camera'])
            r.session_changed(True)
            self.wait(lambda:self.bridge.snapshot()['control_enabled'])
        self.assertEqual(self.backend_factory.call_count,2)

    def test_camera_unavailable_cannot_activate_autostart(self):
        class BusyVision(test_gui.FakeVision):
            def start(self):
                super().start();self.error=RuntimeError('Cámara ocupada')
        self.select_calibrated();r=self.resident()
        self.controller.vision_factory=BusyVision
        r.preferences=r.store.save(True,True,False,self.controller.profile,confirmed=True)
        with patch('desktop.resident.desktop_unlocked',return_value=True),self.assertLogs(level='ERROR'):
            r.begin();r.timer.start(50)
            self.wait(lambda:self.bridge.snapshot()['state']=='ERROR')
            self.wait(lambda:not r.pending)
        self.backend_factory.assert_not_called()

    def test_resume_while_still_locked_waits_for_the_later_unlock_event(self):
        self.select_calibrated();r=self.resident()
        r.preferences=r.store.save(True,True,False,self.controller.profile,confirmed=True)
        r.rearm=True
        with patch('desktop.resident.desktop_unlocked',return_value=False):
            r.begin()
        self.assertTrue(r.rearm);self.assertFalse(r.pending);self.backend_factory.assert_not_called()
        with patch('desktop.resident.desktop_unlocked',return_value=True):
            r.session_changed(True);r.timer.start(50)
            self.wait(lambda:self.bridge.snapshot()['control_enabled'])
        self.assertFalse(r.rearm)

    def test_single_instance_lock_and_local_show_notification(self):
        from desktop.single_instance import SingleInstance
        show=Mock();first=SingleInstance(show,self.root/'instance');self.addCleanup(first.close)
        self._instance=first
        second=SingleInstance(show,self.root/'instance')
        self.assertTrue(first.primary);self.assertFalse(second.primary)
        self.wait(lambda:show.called)

    def test_tray_contains_stop_and_exit_without_hiding_default_window(self):
        r=self.resident();titles=[a.text() for a in r.menu.actions()]
        self.assertIn('Detener seguimiento',titles);self.assertIn('Salir completamente',titles)
        self.assertFalse(r.minimize_on_close());self.backend_factory.assert_not_called()

    def test_first_valid_save_offers_startup_once_and_now_no_is_persistent(self):
        self.select_calibrated();r=self.resident()
        with patch('desktop.resident.QDialog.exec',return_value=0):r.offer_startup()
        self.assertTrue(r.store.load()['prompted'])
        self.assertFalse(r.store.load()['enabled']);self.assertFalse(r.store.load()['activate'])
        self.controller._saved_calibrations=1
        with patch.object(r,'offer_startup') as prompt:
            r.tick();self.app.processEvents();prompt.assert_not_called()
        self.backend_factory.assert_not_called()

    def test_rejected_calibration_and_manual_stop_do_not_arm_automatic_control(self):
        self.select_calibrated();r=self.resident()
        self.controller.wizard=Mock();self.controller.wizard.result.side_effect=ValueError('Rechazada')
        with self.assertRaises(ValueError):self.controller.save_calibration()
        self.assertEqual(self.controller._saved_calibrations,0)
        r.preferences=r.store.save(True,True,False,self.controller.profile,confirmed=True)
        r.disarm()
        with patch('desktop.resident.desktop_unlocked',return_value=True):r.begin()
        self.assertFalse(r.pending);self.backend_factory.assert_not_called()
