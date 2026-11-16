"""HeadMouse pasa a llamarse CONFA (2026-11-13): nadie pierde perfiles, modelos ni el inicio con Windows."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app_paths
from app_paths import APP_NAME, LEGACY_APP_NAME, adopt_legacy_root, data_root, RESOURCE_ROOT


class DataFolderTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.current, self.legacy = self.base / APP_NAME, self.base / LEGACY_APP_NAME

    def test_the_headmouse_folder_is_renamed_with_everything_inside(self):
        (self.legacy / "profiles").mkdir(parents=True)
        (self.legacy / "profiles" / "manu.json").write_text("{}", encoding="utf-8")
        (self.legacy / "models" / "whisper").mkdir(parents=True)
        self.assertEqual(adopt_legacy_root(self.current, self.legacy), self.current)
        self.assertTrue((self.current / "profiles" / "manu.json").is_file())
        self.assertTrue((self.current / "models" / "whisper").is_dir())
        self.assertFalse(self.legacy.exists())

    def test_an_existing_confa_folder_is_never_mixed_or_overwritten(self):
        (self.legacy / "profiles").mkdir(parents=True)
        (self.current / "profiles").mkdir(parents=True)
        self.assertEqual(adopt_legacy_root(self.current, self.legacy), self.current)
        self.assertTrue(self.legacy.is_dir())  # queda intacta; se puede importar a mano

    def test_if_the_old_version_is_still_open_it_keeps_using_the_old_folder(self):
        self.legacy.mkdir()
        with patch.object(Path, "rename", side_effect=PermissionError("en uso")):
            self.assertEqual(adopt_legacy_root(self.current, self.legacy), self.legacy)
        self.assertFalse(self.current.exists())

    def test_a_new_user_starts_in_the_confa_folder(self):
        self.assertEqual(adopt_legacy_root(self.current, self.legacy), self.current)
        self.assertFalse(self.current.exists())  # se crea cuando haga falta, no antes

    def test_data_root_migrates_once_from_localappdata(self):
        (self.legacy / "profiles").mkdir(parents=True)
        env = {k: v for k, v in os.environ.items() if k not in ("CONFA_DATA_DIR", "HEADMOUSE_DATA_DIR")}
        with patch.dict(os.environ, env, clear=True), patch.dict(os.environ, LOCALAPPDATA=str(self.base)), \
                patch.object(sys, "platform", "win32"), patch.dict(app_paths._resolved, clear=True):
            self.assertEqual(data_root(), self.current)
            self.assertEqual(data_root(), self.current)
        self.assertTrue((self.current / "profiles").is_dir())

    def test_both_test_variables_isolate_the_data(self):
        with patch.dict(os.environ, CONFA_DATA_DIR=str(self.base / "a"), HEADMOUSE_DATA_DIR=str(self.base / "b")):
            self.assertEqual(data_root(), (self.base / "a").resolve())
        env = {k: v for k, v in os.environ.items() if k != "CONFA_DATA_DIR"}
        with patch.dict(os.environ, env, clear=True), patch.dict(os.environ, HEADMOUSE_DATA_DIR=str(self.base / "b")):
            self.assertEqual(data_root(), (self.base / "b").resolve())


class VisibleNameTests(unittest.TestCase):
    def test_window_and_installer_say_confa(self):
        iss = (RESOURCE_ROOT / "packaging" / "CONFA.iss").read_text(encoding="utf-8")
        self.assertIn("AppName=CONFA", iss)
        # Mismo AppId: HeadMouse instalado se actualiza en vez de quedar duplicado.
        self.assertIn("AppId={{D8CA3B99-415A-4FA9-90D4-94E3E66B9D67}", iss)
        self.assertIn('Name: "{app}\\HeadMouse.exe"', iss)  # se borra el ejecutable viejo
        self.assertIn("Check: HadLegacyStartup", iss)  # quien iniciaba con Windows lo conserva
        spec = (RESOURCE_ROOT / "packaging" / "CONFA.spec").read_text(encoding="utf-8")
        self.assertIn("name='CONFA'", spec)
        self.assertTrue((RESOURCE_ROOT / "assets" / "confa.ico").is_file())

    def test_startup_entry_reads_the_old_name_and_replaces_it(self):
        from startup_preferences import WindowsStartup
        self.assertEqual((WindowsStartup.NAME, WindowsStartup.LEGACY_NAME), ("CONFA", "HeadMouse"))

    @unittest.skipUnless(sys.platform == "win32", "registro de Windows")
    def test_saving_the_preference_moves_the_registry_entry(self):
        import winreg

        class Fake:
            def __init__(self):
                self.values = {"HeadMouse": r"C:\viejo\HeadMouse.exe --autostart"}

            def OpenKey(self, *_args):
                return self

            CreateKey = OpenKey

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def QueryValueEx(self, _key, name):
                if name not in self.values:
                    raise FileNotFoundError(name)
                return self.values[name], winreg.REG_SZ

            def SetValueEx(self, _key, name, _reserved, _kind, value):
                self.values[name] = value

            def DeleteValue(self, _key, name):
                if name not in self.values:
                    raise FileNotFoundError(name)
                del self.values[name]

        fake = Fake()
        from startup_preferences import WindowsStartup
        with patch.multiple(winreg, OpenKey=fake.OpenKey, CreateKey=fake.CreateKey, QueryValueEx=fake.QueryValueEx,
                            SetValueEx=fake.SetValueEx, DeleteValue=fake.DeleteValue):
            startup = WindowsStartup()
            self.assertEqual(startup.read(), r"C:\viejo\HeadMouse.exe --autostart")
            startup.set(r"C:\nuevo\CONFA.exe --autostart")
            self.assertEqual(fake.values, {"CONFA": r"C:\nuevo\CONFA.exe --autostart"})
            startup.set(None)
            self.assertEqual(fake.values, {})


if __name__ == "__main__":
    unittest.main()
