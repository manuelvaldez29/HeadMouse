"""Tema y fuentes del sistema, incluyendo render offscreen en Windows."""
import os
from pathlib import Path
from PySide6.QtGui import QFontDatabase, QFont
from config import ROOT


def apply_style(application):
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
    application.setStyleSheet((ROOT / "desktop" / "theme.qss").read_text(encoding="utf-8"))
