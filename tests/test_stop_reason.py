"""El motivo de una parada pedida desde la GUI sobrevive aunque el worker detenga primero."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from application_controller import ApplicationController
from profile_manager import ProfileManager
from profiles import ProfileStore


class StopReasonTests(unittest.TestCase):
    def controller(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        return ApplicationController(ProfileManager(ProfileStore(Path(temp.name) / "p")), data_dir=temp.name)

    def test_worker_tick_before_queued_command_keeps_reason(self):
        c = self.controller()
        control = Mock()
        c.control, c.state = control, "CONTROL"
        c.emergency_stop("Cambió el DPI: control detenido")  # lo que hace bridge.stop(reason)
        c.step()                                             # el ciclo corre antes que el comando encolado
        self.assertIsNone(c.control)
        control.stop.assert_called_once()
        self.assertEqual(c.message, "Cambió el DPI: control detenido")
        c.stop_control(reason="Cambió el DPI: control detenido")  # el comando encolado llega después
        self.assertEqual(c.message, "Cambió el DPI: control detenido")

    def test_reason_is_consumed_once(self):
        c = self.controller()
        c.control = Mock()
        c.emergency_stop("motivo")
        c.step()
        c.control = Mock()
        c.stop_control()
        self.assertEqual(c.message, "Control del sistema desactivado.")


if __name__ == "__main__": unittest.main()
