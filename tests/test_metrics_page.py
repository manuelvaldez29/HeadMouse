"""Métricas: tasas por minuto por sesión con control, gráficos y tabla legible."""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from application_controller import ApplicationController
from metrics_summary import control_sessions, duration_text, totals
from profile_manager import ProfileManager
from profiles import ProfileStore


def session(started, duration, clicks=0, scrolls=0, pauses=0, losses=0, profile="user_a", actions=True, typed=0):
    executed = dict(CURSOR_MOVE=100, PAUSE=pauses) if actions else {}
    return dict(profile_id=profile, started_at=started, duration_s=duration, clicks=clicks, scrolls=scrolls,
                tracking_losses=losses, actions_executed=executed, fps_mean=22.4, processing_ms_mean=12,
                dictations=dict(typed=typed))


HISTORY = [session("2026-10-12T20:00:00+00:00", 120, clicks=10, scrolls=4, pauses=2, losses=1, typed=1),
           session("2026-10-11T20:00:00+00:00", 60, clicks=3, pauses=6),
           session("2026-10-13T20:00:00+00:00", 300, clicks=30, profile="user_b"),
           session("2026-10-14T20:00:00+00:00", 600, actions=False),   # vista previa / diagnóstico
           session("2026-10-14T21:00:00+00:00", 10, clicks=5)]           # demasiado corta


class SummaryTests(unittest.TestCase):
    def test_only_control_sessions_in_time_order_with_rates(self):
        rows = control_sessions(HISTORY, "user_a")
        self.assertEqual([r["clicks"] for r in rows], [3, 10])
        self.assertAlmostEqual(rows[1]["clicks_per_min"], 5)
        self.assertAlmostEqual(rows[0]["pauses_per_min"], 6)
        self.assertAlmostEqual(rows[1]["losses_per_min"], .5)
        self.assertEqual(rows[1]["dictations"], 1)
        self.assertEqual(len(control_sessions(HISTORY)), 3)

    def test_totals_are_weighted_by_duration(self):
        summary = totals(control_sessions(HISTORY, "user_a"))
        self.assertEqual(summary["sessions"], 2)
        self.assertAlmostEqual(summary["minutes"], 3)
        self.assertAlmostEqual(summary["clicks_per_min"], 13 / 3)  # no el promedio de 3 y 5
        self.assertIsNone(totals([])["clicks_per_min"])

    def test_duration_text(self):
        self.assertEqual(duration_text(.5), "30 s")
        self.assertEqual(duration_text(5.6), "5 min 36 s")
        self.assertEqual(duration_text(68.2), "1 h 08 min")


@unittest.skipUnless(importlib.util.find_spec("PySide6"), "requiere PySide6")
class ChartAndPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_nice_ticks(self):
        from desktop.widgets import nice_ticks
        self.assertEqual(nice_ticks(12, 4), [0, 5, 10, 15])
        self.assertEqual(nice_ticks(0), [0, 1])
        self.assertEqual(nice_ticks(3.6, 4), [0, 1, 2, 3, 4])

    def test_x_labels_never_overlap_and_last_is_shown(self):
        from PySide6.QtGui import QFontMetrics
        from desktop.widgets import LineChart
        chart = LineChart(facets=True)
        chart.resize(700, 300)
        labels = [f"{d:02d}/10 19:{d:02d}" for d in range(1, 28)]
        chart.set_data(labels, [dict(name="Clicks", color="#3987e5", values=[1.0] * 27)])
        plot, metrics = chart._plot(), QFontMetrics(chart.font())
        shown = chart._shown_labels(plot, metrics)
        self.assertEqual(shown[-1], 26)
        width = max(metrics.horizontalAdvance(l) for l in labels)
        xs = [chart._x(plot, i) for i in shown]
        self.assertTrue(all(b - a >= width for a, b in zip(xs, xs[1:])))
        chart.grab()  # dibuja sin errores, también vacío
        chart.set_data([], [])
        chart.grab()

    def test_page_shows_rates_and_newest_session_first(self):
        from render_gui import ReviewBridge
        from desktop.window import MainWindow
        with tempfile.TemporaryDirectory() as temp:
            snapshot = ApplicationController(ProfileManager(ProfileStore(Path(temp) / "p")), data_dir=temp).snapshot()
        snapshot.update(profiles=[], history=HISTORY, profile={"user_id": "user_a", "display_name": "Ana"})
        window = MainWindow(ReviewBridge(snapshot))
        self.addCleanup(window.close)
        window.refresh()
        self.assertEqual(window.metric_labels["Sesiones con control"].text(), "2")
        self.assertEqual(window.metric_labels["Clicks por minuto"].text(), "4,3")
        self.assertEqual(window.metric_labels["Pausas por minuto"].text(), "2,7")
        self.assertEqual(window.sessions.rowCount(), 2)
        self.assertEqual(window.sessions.item(0, 2).text(), "10")  # la más reciente arriba
        self.assertIn("2 sesiones de vista previa", window.metrics_note.text())
        window.metrics_scope.setCurrentIndex(window.metrics_scope.findData("all"))
        self.assertEqual(window.metric_labels["Sesiones con control"].text(), "3")
        self.assertEqual(len(window.actions_chart.labels), 3)


if __name__ == "__main__": unittest.main()
