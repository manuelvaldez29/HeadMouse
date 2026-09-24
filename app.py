"""HEADMOUSE v0.3 — DESKTOP ACCESSIBILITY APPLICATION."""
import argparse
import sys
from config import ROOT, configure_logging


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log-level",choices=("DEBUG","INFO","WARNING","ERROR"),default="INFO")
    parser.add_argument("--check",action="store_true",help="Verificar Qt y construir ventana sin cámara ni control")
    args=parser.parse_args(argv)
    configure_logging(args.log_level)
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer
    from desktop.bridge import DesktopBridge
    from desktop.window import MainWindow
    from desktop.style import apply_style
    application=QApplication.instance() or QApplication(sys.argv[:1])
    application.setApplicationName("HeadMouse")
    apply_style(application)
    bridge=DesktopBridge()
    window=MainWindow(bridge)
    window.show()
    if args.check:
        QTimer.singleShot(600,window.close)
    return application.exec()


if __name__=="__main__":
    raise SystemExit(main())
