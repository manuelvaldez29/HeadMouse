"""Tema (oscuro o claro) y fuentes del sistema, incluyendo render offscreen en Windows.

Los colores de la ventana principal están en theme.qss (oscuro) y theme_light.qss
(claro), con los mismos selectores (lo verifica tests/test_light_theme.py). Los widgets
que se dibujan a mano (gráficos, medidores) piden sus colores a `ink()` al pintar.
Las ventanas que flotan sobre otras aplicaciones (teclado virtual, mini cámara, aviso
del dictado, mapa del joystick) y la vista de la cámara quedan oscuras en los dos temas:
se distinguen igual sobre una app clara u oscura.
"""
import os
from pathlib import Path
from PySide6.QtGui import QFontDatabase, QFont
from config import ROOT

THEMES = {"dark": "theme.qss", "light": "theme_light.qss"}

INK = {
    "dark": dict(
        surface="#172337", primary="#eef3fc", secondary="#b2c1d7", muted="#8192aa", grid="#26364d",
        axis="#405670", tooltip="#0f1a2b", neutral="#b2c1d7",
        meter_bg="#172337", meter_text="#b1c6df", meter_track="#536b8b", meter_value="#6df4e0",
        meter_neutral="#b1c6df", meter_release="#cfb3ff", meter_activation="#ffd477", meter_comfortable="#71dfbe",
        ok="#8ce5cd", warn="#ffd166", bad="#ff8796", pending="#8192aa",
        bar_track="#26364d", bar_fill="#57d4c3", bar_idle="#3f7f86"),
    # Sobre blanco los acentos van más oscuros: el turquesa claro y el amarillo del tema
    # oscuro no se leen (contraste < 2:1).
    "light": dict(
        surface="#ffffff", primary="#172235", secondary="#46566e", muted="#5f6e84", grid="#e1e7ef",
        axis="#9aabc2", tooltip="#ffffff", neutral="#5a6b84",
        meter_bg="#ffffff", meter_text="#46566e", meter_track="#b2c0d3", meter_value="#0f9a89",
        meter_neutral="#5a6b84", meter_release="#7a4fc4", meter_activation="#a86f00", meter_comfortable="#13866f",
        ok="#0b7a6d", warn="#8f6200", bad="#b3263c", pending="#5f6e84",
        bar_track="#e1e7ef", bar_fill="#1aa894", bar_idle="#8fcfc6"),
}

_current = "dark"


def apply_style(application, theme="dark"):
    # La plataforma Qt offscreen de Windows puede enumerar cero fuentes.
    # Registrar la fuente local evita cuadrados en tests/capturas, sin distribuirla.
    if "Segoe UI" not in QFontDatabase.families() and os.name == "nt":
        fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        for filename in ("segoeui.ttf", "segoeuib.ttf", "seguisb.ttf", "seguisym.ttf"):
            path = fonts / filename
            if path.is_file():
                QFontDatabase.addApplicationFont(str(path))
    application.setFont(QFont("Segoe UI", 11))
    application.setStyle("Fusion")
    set_theme(application, theme)


def set_theme(application, theme):
    """Cambia el tema de toda la aplicación al instante; no toca el control ni la cámara."""
    global _current
    if theme not in THEMES:
        theme = "dark"
    sheet = (ROOT / "desktop" / THEMES[theme]).read_text(encoding="utf-8")
    _current = theme
    # Cambiar la hoja de estilos vuelve a pulir todos los widgets de la aplicación: con el
    # mismo tema no se toca (cada ventana nueva la pedía y los tests tardaban 30 veces más).
    if application.styleSheet() != sheet:
        application.setStyleSheet(sheet)


def current_theme():
    return _current


def ink(name):
    """Color para los widgets dibujados a mano, según el tema vigente."""
    return INK[_current][name]
