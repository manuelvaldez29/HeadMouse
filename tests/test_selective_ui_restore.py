"""La navegación original permanece; sólo se añaden herramientas oculares."""
import unittest
from unittest.mock import patch
import test_gui
from test_eye_gui import EyeVision
from vertical_diagnostic import VerticalDiagnosticSession


@unittest.skipUnless(test_gui.QT_AVAILABLE,"Requiere PySide6")
class SelectiveUIRestoreTests(unittest.TestCase):
    setUpClass=classmethod(test_gui.GUITests.setUpClass.__func__)
    setUp=test_gui.GUITests.setUp
    tearDown=test_gui.GUITests.tearDown
    wait=test_gui.GUITests.wait
    select_calibrated=test_gui.GUITests.select_calibrated

    def test_original_navigation_controls_and_tracking_choices_remain(self):
        self.select_calibrated();self.window.refresh()
        self.assertEqual(self.window.stack.count(),8)
        self.assertEqual([b.text() for b in self.window.nav],
            ["Inicio","Perfiles","Calibración","Diagnóstico","Configuración","Gestos y acciones","Experimentos","Métricas"])
        self.assertEqual(self.window.activate_button.text(),"Activar control")
        self.assertFalse(hasattr(self.window,"eye_setup_dialog"))
        self.assertEqual([self.window.home_method.itemData(i) for i in range(2)],["nose","eyes"])
        self.assertEqual([self.window.tracking_combo.itemData(i) for i in range(2)],["nose","eyes"])
        self.assertEqual([self.window.calibration_tabs.tabText(i) for i in range(2)],["Nariz","Ojos"])
        self.backend_factory.assert_not_called()

    def test_vertical_tool_uses_existing_overlay_and_never_offers_calibration_save(self):
        self.select_calibrated()
        self.controller.vision_factory=EyeVision
        def quick(*args,**kw):return VerticalDiagnosticSession(*args,**kw,settle_s=.05,duration_s=.2,min_samples=5)
        errors=[]
        with patch("vertical_diagnostic.VerticalDiagnosticSession",side_effect=quick),patch("sys.excepthook",lambda k,e,t:errors.append(str(e))):
            self.window.start_vertical_diagnostic()
            self.wait(lambda:self.bridge.snapshot().get("vertical_diagnostic") is not None)
            self.wait(lambda:self.bridge.snapshot()["vertical_diagnostic"]["state"]=="ready")
            self.window.refresh()
            self.assertFalse(self.window.gaze_overlay.save_button.isVisible())
            self.assertIn("sin mover el mouse",self.window.gaze_overlay.info.text())
            self.window.gaze_overlay.close()
            self.wait(lambda:self.bridge.snapshot()["state"]=="PREVIEW")
        self.assertEqual(errors,[])
        self.backend_factory.assert_not_called()
