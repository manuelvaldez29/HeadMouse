"""Preferencias, bandeja y arranque consentido; conserva las pantallas originales."""
import logging
import time
from PySide6.QtCore import QTimer,Signal
from PySide6.QtGui import QAction,QIcon
from PySide6.QtWidgets import (QApplication,QCheckBox,QComboBox,QDialog,QDialogButtonBox,
    QFormLayout,QGroupBox,QLabel,QMessageBox,QPushButton,QSystemTrayIcon,QMenu,QVBoxLayout,QFileDialog)
from app_paths import RESOURCE_ROOT
from startup_preferences import StartupPreferences,prepared
from startup_safety import StableStartup
from desktop.windows_session import WindowsSession,desktop_unlocked


class StartupControls(QGroupBox):
    saved=Signal()
    def __init__(self,resident):
        super().__init__("Inicio con Windows")
        self.resident=resident;form=QFormLayout(self)
        self.enabled=QCheckBox("Iniciar HeadMouse automáticamente con Windows")
        self.activate=QCheckBox("Activar automáticamente el seguimiento")
        self.minimized=QCheckBox("Iniciar minimizado en la bandeja del sistema")
        self.profiles=QComboBox();self.profiles.setAccessibleName("Perfil de inicio")
        for w in (self.enabled,self.activate,self.minimized):form.addRow(w)
        form.addRow("Perfil de inicio",self.profiles)
        self.note=QLabel("Ambas opciones de inicio están apagadas inicialmente. Si elegís bandeja, X minimiza; Salir termina la aplicación.")
        self.note.setWordWrap(True);form.addRow(self.note)
        save=QPushButton("Guardar preferencias de inicio");save.clicked.connect(self.save);form.addRow(save)
        migrate=QPushButton("Importar perfiles anteriores…");migrate.clicked.connect(self.import_profiles);form.addRow(migrate)
        self.enabled.toggled.connect(self.update_availability)
        self.profiles.currentIndexChanged.connect(self.update_availability)
        self.restore()

    def restore(self):
        p=self.resident.preferences
        self.enabled.setChecked(p["enabled"]);self.activate.setChecked(p["activate"]);self.minimized.setChecked(p["minimized"])
        self.refresh_profiles();self.update_availability()

    def refresh_profiles(self):
        entries=self.resident.bridge.snapshot().get("profiles",[])
        key=tuple((p["user_id"],p["display_name"]) for p in entries)
        if key==getattr(self,"_profiles_key",None):return
        self._profiles_key=key
        selected=self.profiles.currentData() or self.resident.preferences.get("profile_id")
        self.profiles.blockSignals(True);self.profiles.clear();self.profiles.addItem("Elegí un perfil",None)
        for p in entries:self.profiles.addItem(p["display_name"],p["user_id"])
        self.profiles.setCurrentIndex(max(0,self.profiles.findData(selected)));self.profiles.blockSignals(False)
        self.update_availability()

    def profile(self):
        user_id=self.profiles.currentData()
        return self.resident.bridge.controller.profiles.store.load(user_id) if user_id else None

    def update_availability(self,*args):
        try:p=self.profile()
        except (OSError,ValueError):p=None
        available=bool(self.enabled.isChecked() and p and prepared(p))
        self.activate.setEnabled(available)
        if not available:self.activate.setChecked(False)

    def save(self):
        try:
            profile=self.profile();activate=self.activate.isChecked()
            if activate:
                answer=QMessageBox.question(self,"Autorizar activación automática",
                    "Autorizo que este perfil controle el puntero y sus acciones validadas al iniciar sesión, sólo con calibración compatible y seguimiento estable. F8 o Detener lo detienen. ¿Autorizar?",
                    QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)
                if answer!=QMessageBox.StandardButton.Yes:return False
            self.resident.preferences=self.resident.store.save(self.enabled.isChecked(),activate,self.minimized.isChecked(),profile,confirmed=activate)
            self.resident.disarm()
            self.note.setText("Preferencias guardadas. Se aplicarán al próximo inicio de sesión. X minimiza sólo si elegiste bandeja; Salir termina completamente.")
            self.saved.emit()
            return True
        except (OSError,ValueError) as exc:
            self.note.setText("No se guardaron las preferencias: "+str(exc));return False

    def import_profiles(self):
        from pathlib import Path
        from user_storage import migrate_legacy
        path=QFileDialog.getExistingDirectory(self,"Elegí la carpeta anterior de HeadMouse o su carpeta data")
        if not path:return
        source=Path(path)
        if (source/"data"/"profiles").is_dir():source=source/"data"
        if not (source/"profiles").is_dir():
            self.note.setText("La carpeta elegida no contiene profiles. Elegí la carpeta de HeadMouse o data.");return
        try:
            records=migrate_legacy(source)
            count=lambda result:sum(r["result"]==result for r in records)
            self.note.setText(f"Importación: {count('copied')} copiados; {count('conflict_preserved')} conflictos conservados; {count('invalid')} inválidos. Revisá Perfiles. Los originales no se modificaron.")
            self.resident.bridge.request("refresh_metrics")
        except (OSError,ValueError) as exc:self.note.setText("Importación no completada: "+str(exc))


class Resident:
    def __init__(self,window,store=None,autostart=False,native=True):
        self.window=window;self.bridge=window.bridge;window.resident=self
        self.store=store or StartupPreferences();self.quitting=False;self.pending=False
        self.manual_stop=False;self.rearm=False;self.gate=StableStartup();self.started=0.;self.stage=None
        try:self.preferences=self.store.load()
        except (OSError,ValueError) as exc:
            logging.exception("Preferencias de inicio no válidas")
            from startup_preferences import DEFAULTS
            self.preferences=dict(DEFAULTS);window.show_error(str(exc))
        self.controls=StartupControls(self);window.startup_settings_layout.addRow(self.controls)
        window.setWindowIcon(QIcon(str(RESOURCE_ROOT/"assets"/"headmouse.ico")))
        self.tray=QSystemTrayIcon(window.windowIcon(),window);self.menu=QMenu(window)
        for title,action in (("Abrir HeadMouse",self.show),("Ver estado",self.status),
            ("Activar seguimiento",self.activate),("Pausar seguimiento",lambda:self.bridge.request("pause_control")),
            ("Detener seguimiento",window.stop_immediately),("Abrir Configuración",self.settings),
            ("Salir completamente",window.exit_application)):
            item=QAction(title,self.menu);item.triggered.connect(lambda checked=False,fn=action:fn());self.menu.addAction(item)
        self.tray.setContextMenu(self.menu);self.tray.activated.connect(lambda reason:self.show() if reason==QSystemTrayIcon.ActivationReason.DoubleClick else None)
        self.tray_available=QSystemTrayIcon.isSystemTrayAvailable()
        if self.tray_available:self.tray.show()
        self.native=WindowsSession(window,window.stop_immediately,self.session_changed) if native else None
        if self.native:
            QApplication.instance().installNativeEventFilter(self.native)
            self.bridge.controller.session_guard=desktop_unlocked
        self.timer=QTimer(window);self.timer.setInterval(100);self.timer.timeout.connect(self.tick);self.timer.start()
        self.last_revision=0;self.prompt_open=False
        if autostart and self.preferences["enabled"]:QTimer.singleShot(0,self.begin)

    def minimize_on_close(self):return not self.quitting and self.tray_available and self.preferences["minimized"]
    def show(self):self.window.showNormal();self.window.raise_();self.window.activateWindow()
    def settings(self):self.show();self.window.show_page(4)
    def status(self):QMessageBox.information(self.window,"Estado de HeadMouse",self.window.control_status.text()+"\n"+self.window.banner.text()+"\n"+("F8 global registrado." if self.native and self.native.hotkey else "F8 requiere foco; usá Detener en bandeja."))
    def activate(self):
        self.disarm();s=self.bridge.snapshot()
        if s.get("control_enabled") and s.get("paused"):
            if QMessageBox.question(self.window,"Reanudar control","¿Reanudar el perfil actual?",QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:
                self.bridge.controller.emergency.clear();self.bridge.request("resume_control",confirmed=True,screen_context=self.window.screen_context())
        else:self.window.activate()

    def disarm(self):self.manual_stop=True;self.rearm=False;self.pending=False;self.gate.reset()

    def session_changed(self,available):
        if not available:
            self.rearm=bool(self.preferences["activate"] and not self.manual_stop)
            self.pending=False;self.gate.reset()
            self.bridge.stop(reason="Sesión bloqueada o suspendida: cámara y control detenidos")
            self.bridge.request("stop_camera")
        elif self.rearm:
            QTimer.singleShot(1000,self.begin)

    def begin(self):
        if self.manual_stop or self.pending:return  # F8 también revoca un desbloqueo pendiente.
        try:
            self.preferences=self.store.load()
            p=self.preferences
            if not p["enabled"] or not p.get("profile_id"):return
            if not desktop_unlocked():
                self.rearm=True;return  # El aviso de energía puede preceder al desbloqueo real.
            profile=self.bridge.controller.profiles.store.load(p["profile_id"])
            if p["activate"] and not self.store.authorized(p,profile):raise ValueError("El perfil cambió o falta autorización; revisá Inicio con Windows")
            self.manual_stop=False;self.pending=True;self.started=time.monotonic();self.stage="profile";self.gate.reset()
            self.rearm=False
            self.bridge.request("select_profile",user_id=p["profile_id"])
        except (OSError,ValueError) as exc:self.pending=False;self.window.show_error("Inicio automático detenido: "+str(exc));self.show()

    def tick(self):
        if self.quitting:return
        s=self.bridge.snapshot()
        if not s:return
        self.controls.refresh_profiles()
        self.tray.setToolTip("HeadMouse · "+("pausado" if s.get("paused") else "activo") if s.get("control_enabled") else "HeadMouse · control desactivado")
        revision=s.get("calibration_saved_revision",0)
        if revision>self.last_revision:
            self.last_revision=revision
            if not self.preferences["prompted"] and s.get("profile") and prepared(s["profile"]) and not self.prompt_open:
                self.prompt_open=True;QTimer.singleShot(0,self.offer_startup)
        if not s.get("profile"):
            self.window.home_hint.setText("Creá tu perfil → elegí Nariz u Ojos → Calibración → guardá la prueba válida → Iniciar HeadMouse. F8 o Detener apagan el control y la cámara.")
        if not self.pending:return
        if time.monotonic()-self.started>45 or s.get("state")=="ERROR":
            self.disarm();self.bridge.stop();self.bridge.request("stop_camera")
            self.window.show_error("Inicio automático detenido: cámara o seguimiento no preparados. Revisá Diagnóstico.");self.show();return
        if not desktop_unlocked():self.session_changed(False);return
        if self.stage=="profile":
            if (s.get("profile") or {}).get("user_id")==self.preferences["profile_id"] and s.get("state")=="HOME":
                self.stage="camera";self.bridge.request("start_camera")
            return
        if (s.get("profile") or {}).get("user_id")!=self.preferences["profile_id"]:
            self.disarm();return
        if self.preferences["activate"]:
            blocked=[text for text in s.get("activation_blockers",[]) if "calibraci" in text.lower() or "Gestos pendientes" in text]
            if blocked:
                self.disarm();self.bridge.stop();self.bridge.request("stop_camera")
                self.window.show_error("Inicio automático detenido: "+" · ".join(blocked));self.show();return
        if s.get("camera_status",{}).get("ready") and not self.preferences["activate"]:
            self.pending=False;return
        if self.gate.update(s,time.monotonic()):
            try:
                profile=self.bridge.controller.profiles.store.load(self.preferences["profile_id"])
                if not self.store.authorized(self.store.load(),profile):raise ValueError("La autorización del perfil cambió")
                self.pending=False
                self.bridge.controller.emergency.clear()
                self.bridge.request("activate_startup_control",screen_context=self.window.screen_context())
                self.tray.showMessage("HeadMouse","Perfil autorizado: activando seguimiento. F8 o Detener para salir.")
            except (ValueError,OSError) as exc:self.disarm();self.window.show_error(str(exc));self.show()

    def offer_startup(self):
        try:
            dialog=QDialog(self.window);dialog.setWindowTitle("¿Querés que HeadMouse se inicie automáticamente con Windows?")
            layout=QVBoxLayout(dialog);text=QLabel("HeadMouse puede abrirse cuando ingreses a Windows. La activación del perfil requiere autorización independiente. Ambas opciones empiezan desactivadas.")
            text.setWordWrap(True);layout.addWidget(text)
            controls=StartupControls(self);layout.addWidget(controls)
            controls.saved.connect(dialog.accept)
            controls.profiles.setCurrentIndex(controls.profiles.findData((self.bridge.snapshot().get("profile") or {}).get("user_id")))
            # Una pregunta por usuario/equipo. Ahora no mantiene ambas opciones apagadas.
            buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Close);buttons.button(QDialogButtonBox.StandardButton.Close).setText("Ahora no")
            buttons.rejected.connect(dialog.reject);layout.addWidget(buttons)
            self.preferences=self.store.save(False,False,False,profile=self.bridge.controller.profile,prompted=True)
            dialog.exec();self.controls.restore()
        finally:self.prompt_open=False

    def close(self):
        if getattr(self,"_closed",False):return
        self._closed=True
        self.quitting=True;self.timer.stop();self.tray.hide()
        if self.native:
            QApplication.instance().removeNativeEventFilter(self.native);self.native.close()
