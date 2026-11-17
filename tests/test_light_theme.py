"""Modo claro (2026-11-16): mismo diseño que el oscuro, colores legibles sobre blanco."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import re
import unittest

from PySide6.QtWidgets import QApplication

from config import ROOT
from desktop import style


def selectors(name):
    text = re.sub(r"/\*.*?\*/", "", (ROOT / "desktop" / name).read_text(encoding="utf-8"), flags=re.S)
    return {s.strip() for block in re.findall(r"([^{}]+)\{", text) for s in block.split(",")}


def luminance(color):
    r, g, b = (int(color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    lin = [c / 12.92 if c <= .03928 else ((c + .055) / 1.055) ** 2.4 for c in (r, g, b)]
    return .2126 * lin[0] + .7152 * lin[1] + .0722 * lin[2]


def contrast(a, b):
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + .05) / (lb + .05)


class ThemeFilesTests(unittest.TestCase):
    def test_both_themes_style_the_same_widgets(self):
        self.assertEqual(selectors("theme.qss"), selectors("theme_light.qss"))

    def test_light_colors_are_readable_on_white(self):
        light = style.INK["light"]
        for name in ("primary", "secondary", "ok", "bad", "warn", "muted"):
            with self.subTest(name):
                self.assertGreaterEqual(contrast(light[name], light["surface"]), 4.5)
        qss = (ROOT / "desktop" / "theme_light.qss").read_text(encoding="utf-8")
        for selector in ("QLabel#HomeState", "QLabel#SettingsSection", "QLabel#StatusError", "QLabel#Subtitle"):
            color = re.search(re.escape(selector) + r" \{[^}]*?[^-]color: (#[0-9a-f]{6})", qss).group(1)
            with self.subTest(selector):
                self.assertGreaterEqual(contrast(color, "#f3f6fb"), 4.5)

    def test_both_themes_have_every_ink(self):
        self.assertEqual(set(style.INK["dark"]), set(style.INK["light"]))


class ThemeSwitchTests(unittest.TestCase):
    def setUp(self):
        self.app = QApplication.instance() or QApplication([])
        self.addCleanup(style.set_theme, self.app, "dark")

    def test_switching_changes_stylesheet_and_painted_colors(self):
        style.set_theme(self.app, "light")
        self.assertEqual(style.current_theme(), "light")
        self.assertIn("#f3f6fb", self.app.styleSheet())
        self.assertEqual(style.ink("surface"), "#ffffff")
        style.set_theme(self.app, "dark")
        self.assertIn("#101827", self.app.styleSheet())
        style.set_theme(self.app, "rosa")  # una preferencia rara guardada: oscuro
        self.assertEqual(style.current_theme(), "dark")

    def test_button_in_the_top_bar_switches_and_remembers(self):
        import test_gui
        case = test_gui.GUITests("test_window_pages_safe_start_and_no_backend")
        test_gui.GUITests.setUpClass()
        case.setUp()
        self.addCleanup(case.tearDown)
        saved = {}
        case.window.ui_prefs.set = lambda key, value: saved.__setitem__(key, value)  # sin tocar el registro real
        case.window.apply_theme("dark", save=False)
        self.assertEqual(case.window.theme_button.text(), "☀  Modo claro")
        case.window.theme_button.click()
        self.assertEqual(style.current_theme(), "light")
        self.assertEqual(case.window.theme_button.text(), "☾  Modo oscuro")
        self.assertEqual(saved, {"theme": "light"})
        for index in range(case.window.stack.count()):  # todas las páginas se dibujan con el tema claro
            case.window.show_page(index)
            case.window.refresh()
            self.app.processEvents()
        case.window.theme_button.click()
        self.assertEqual(saved, {"theme": "dark"})

    def test_floating_keyboard_stays_dark(self):
        source = (ROOT / "desktop" / "keyboard.py").read_text(encoding="utf-8")
        self.assertIn("QWidget { background: transparent; color: #f1f5f9; }", source)


if __name__ == "__main__":
    unittest.main()
