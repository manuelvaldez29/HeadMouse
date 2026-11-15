from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class ExportTests(unittest.TestCase):
    def test_export_has_numbers_and_logs_but_no_images(self):
        from application_controller import ApplicationController
        from profile_manager import ProfileManager
        from profiles import ProfileStore
        from test_gui import FakeVision
        with tempfile.TemporaryDirectory() as folder:
            manager = ProfileManager(ProfileStore(Path(folder) / "profiles"))
            controller = ApplicationController(manager, FakeVision, lambda: None, folder)
            logs = Path(folder) / "logs"
            logs.mkdir()
            (logs / "joystick-trace-1.json").write_text("{}")
            (logs / "headmouse.log").write_text("linea")
            (Path(folder) / "foto.png").write_bytes(b"x")
            out = Path(folder) / "diag.zip"
            controller.export_diagnostic(out)
            names = zipfile.ZipFile(out).namelist()
            self.assertIn("acerca.json", names)
            self.assertIn("logs/joystick-trace-1.json", names)
            self.assertFalse(any(name.endswith(".png") for name in names))


if __name__ == "__main__":
    unittest.main()
