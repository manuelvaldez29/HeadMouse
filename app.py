"""HeadMouse 0.4.0 — aplicación Windows, tesis V0.2."""
import argparse
import sys
from config import ROOT, configure_logging
from app_paths import data_root,VERSION


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log-level",choices=("DEBUG","INFO","WARNING","ERROR"),default="INFO")
    parser.add_argument("--check",action="store_true",help="Verificar Qt y construir ventana sin cámara ni control")
    parser.add_argument("--autostart",action="store_true",help="Inicio de sesión con preferencias autorizadas")
    parser.add_argument("--verify-runtime",action="store_true",help="Verificar bibliotecas y modelo con imagen sintética, sin webcam")
    parser.add_argument("--check-resident",action="store_true",help="Verificar bandeja y sesión nativas sin autoactivar ni abrir webcam")
    args=parser.parse_args(argv)
    configure_logging(args.log_level)
    from runtime_diagnostics import install
    install(data_root() / "logs")
    if args.verify_runtime:
        from distribution_check import run
        return run()
    from desktop.qt_runtime import prepare_qt_platform_plugins
    prepare_qt_platform_plugins()
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer
    from desktop.bridge import DesktopBridge
    from desktop.window import MainWindow
    from desktop.style import apply_style
    application=QApplication.instance() or QApplication(sys.argv[:1])
    application.setApplicationName("HeadMouse")
    application.setApplicationVersion(VERSION)
    apply_style(application)
    from user_storage import migrate_legacy
    instance=None
    if not args.check:
        from desktop.single_instance import SingleInstance
        def show_existing():
            if "window" in locals():window.showNormal()
            else:
                for widget in application.topLevelWidgets():
                    if isinstance(widget,MainWindow):widget.showNormal();widget.raise_();widget.activateWindow()
        instance=SingleInstance(show_existing)
        if not instance.primary:return 0
        migrate_legacy()
        if getattr(sys,"frozen",False):
            from pathlib import Path
            migrate_legacy(Path(sys.executable).parent/"data")
    bridge=DesktopBridge()
    from runtime_diagnostics import register_emergency_handler
    register_emergency_handler(bridge.controller.emergency_stop)
    application.aboutToQuit.connect(bridge.finish_shutdown)
    window=MainWindow(bridge)
    resident=None
    if not args.check:
        from desktop.resident import Resident
        resident=Resident(window,autostart=args.autostart and not args.check_resident)
    window.show()
    if args.check_resident:
        from user_storage import write_json
        assert bridge.controller.vision is None and bridge.controller.control is None
        write_json(data_root()/"logs"/"resident-check.json",dict(result="passed",camera=False,control=False,
            tray_available=resident.tray_available,global_f8=resident.native.hotkey,
            session_notifications=resident.native.registered,version=VERSION))
        QTimer.singleShot(800,window.exit_application)
    elif args.check:
        QTimer.singleShot(600,window.close)
    elif resident.preferences["minimized"] and resident.tray_available:
        window.hide()
    try:
        return application.exec()
    finally:
        if resident:resident.close()
        # El worker termina antes de destruir widgets, y QApplication sigue viva.
        bridge.finish_shutdown()
        from desktop.lifecycle import dispose_window
        dispose_window(window)
        register_emergency_handler(None)
        if instance:instance.close()


if __name__=="__main__":
    try:
        raise SystemExit(main())
    except Exception:
        import logging
        logging.exception("No se pudo iniciar HeadMouse")
        if any(flag in sys.argv for flag in ("--check","--verify-runtime","--check-resident")):
            raise SystemExit(1)
        raise
