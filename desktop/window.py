"""Ventana desktop: presentación, formularios y comandos; sin inferencia ni acciones SO."""
import json
from copy import deepcopy
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QShortcut, QKeySequence, QCursor
from PySide6.QtWidgets import (QMainWindow, QWidget, QFrame, QVBoxLayout, QHBoxLayout,
    QGridLayout, QPushButton, QStackedWidget, QScrollArea, QComboBox, QInputDialog,
    QMessageBox, QFormLayout, QDoubleSpinBox, QSpinBox, QCheckBox, QProgressBar,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView)
from action_mapping import ACTIONS, DEFAULT_MAPPING
from desktop.widgets import CameraPreview, ExperimentCanvas, label, card

GESTURE_LABELS = dict(LEFT_WINK="Guiño izquierdo", RIGHT_WINK="Guiño derecho", LEFT_BROW="Ceja izquierda",
                      RIGHT_BROW="Ceja derecha", BOTH_BROWS="Ambas cejas", MOUTH_OPEN="Boca abierta")
ACTION_LABELS = dict(LEFT_CLICK="Click izquierdo",RIGHT_CLICK="Click derecho",DOUBLE_CLICK="Doble click",
                     SCROLL_UP="Scroll arriba",SCROLL_DOWN="Scroll abajo",PAUSE="Pausar / reanudar",
                     KEY_ENTER="Enter",KEY_ESCAPE="Escape",KEY_SPACE="Espacio",
                     OPEN_START_MENU="Abrir Inicio",NONE="Sin acción")


def button(text, fn, style=""):
    b=QPushButton(text)
    if style: b.setObjectName(style)
    b.setAccessibleName(text)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.clicked.connect(lambda checked=False: fn())
    return b


class MainWindow(QMainWindow):
    def __init__(self, bridge):
        super().__init__()
        self.bridge=bridge
        self.snapshot={}
        self._profiles_key=None
        self._settings_key=None
        self._history_key=None
        self._status_style=None
        self._closing=False
        self._allow_close=False
        self.setWindowTitle("HeadMouse v0.3 — Desktop Accessibility Application")
        self.resize(1240,850)
        self.setMinimumSize(980,700)
        shell=QWidget()
        self.setCentralWidget(shell)
        outer=QHBoxLayout(shell)
        outer.setContentsMargins(0,0,0,0)
        outer.setSpacing(0)
        sidebar=QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(215)
        nav=QVBoxLayout(sidebar)
        nav.setContentsMargins(18,26,18,20)
        nav.addWidget(label("HeadMouse","Brand"))
        nav.addWidget(label("TU MOVIMIENTO.\nTU AUTONOMÍA.","Subtitle"))
        nav.addSpacing(24)
        self.stack=QStackedWidget()
        self.nav=[]
        names=["Inicio","Perfiles","Calibración","Diagnóstico","Configuración","Gestos y acciones","Experimentos","Métricas"]
        for i,name in enumerate(names):
            b=button(name,lambda index=i:self.show_page(index),"Nav")
            b.setCheckable(True)
            nav.addWidget(b)
            self.nav.append(b)
        nav.addStretch()
        nav.addWidget(label("LOCAL Y PRIVADO\nSin guardar imágenes","Subtitle"))
        nav.addWidget(button("Salir",self.close))
        nav.addWidget(label("v0.3 · UNSTA 2026","Subtitle"))
        outer.addWidget(sidebar)
        content=QVBoxLayout()
        content.setContentsMargins(26,20,26,18)
        top=QHBoxLayout()
        self.control_status=label("CONTROL DEL SISTEMA\nDESACTIVADO","Subtitle")
        top.addWidget(self.control_status,1)
        self.activate_button=button("Activar control",self.activate,"Primary")
        top.addWidget(self.activate_button)
        top.addWidget(button("DETENER CONTROL · F8",self.bridge.stop,"Danger"))
        content.addLayout(top)
        self.banner=label("Preparando HeadMouse…","Subtitle")
        self.banner.setMinimumHeight(42)
        content.addWidget(self.banner)
        content.addWidget(self.stack,1)
        outer.addLayout(content,1)
        self._home()
        self._profiles()
        self._calibration()
        self._diagnostic()
        self._settings()
        self._mapping()
        self._experiments()
        self._metrics()
        self.show_page(0)
        for key in ("F8","Escape"):
            shortcut=QShortcut(QKeySequence(key),self)
            shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
            shortcut.activated.connect(self.bridge.stop)
        self.bridge.error.connect(self.show_error)
        self.bridge.closed.connect(self._closed)
        self.timer=QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()

    def page(self,title,subtitle):
        widget=QWidget()
        layout=QVBoxLayout(widget)
        layout.setContentsMargins(0,6,0,0)
        layout.setSpacing(14)
        layout.addWidget(label(title,"Title"))
        layout.addWidget(label(subtitle,"Subtitle"))
        self.stack.addWidget(widget)
        return layout

    def show_page(self,index):
        self.stack.setCurrentIndex(index)
        for i,b in enumerate(self.nav): b.setChecked(i==index)
        if index==7: self.bridge.request("refresh_metrics")

    def command_page(self,name,index,**kwargs):
        self.show_page(index)
        self.bridge.request(name,**kwargs)

    def _home(self):
        layout=self.page("Tu espacio de control","Prepará tu perfil, probá tus gestos y activá el control cuando estés listo.")
        self.home_profile=label("Sin perfil seleccionado","BigInstruction")
        layout.addWidget(self.home_profile)
        row=QHBoxLayout()
        self.preview=CameraPreview()
        row.addWidget(self.preview,3)
        status=QVBoxLayout()
        self.live_labels={}
        for name in ("Cámara","MediaPipe","Rostro","FPS","Procesamiento"):
            box,value=card(name)
            status.addWidget(box)
            self.live_labels[name]=value
        row.addLayout(status,1)
        layout.addLayout(row,1)
        self.live_events=label("Gesto: —  ·  Acción: —","Subtitle")
        layout.addWidget(self.live_events)
        actions=QGridLayout()
        options=[("Nuevo perfil",self.new_profile), ("Abrir perfil",lambda:self.show_page(1)),
                 ("Calibrar",lambda:self.command_page("start_calibration",2)),
                 ("Probar HeadMouse",lambda:self.command_page("start_diagnostic",3)),
                 ("Abrir cámara",lambda:self.bridge.request("start_camera")),
                 ("Cerrar cámara",lambda:self.bridge.request("stop_camera")),
                 ("Configuración",lambda:self.show_page(4)),("Métricas",lambda:self.show_page(7))]
        for i,(name,fn) in enumerate(options): actions.addWidget(button(name,fn),i//4,i%4)
        layout.addLayout(actions)

    def _profiles(self):
        layout=self.page("Tus perfiles","Cada persona tiene su propia calibración. Cambiar de perfil detiene el control.")
        self.profile_combo=QComboBox()
        self.profile_combo.setAccessibleName("Elegir perfil")
        layout.addWidget(self.profile_combo)
        self.profile_detail=label("Todavía no seleccionaste un perfil.","BigInstruction")
        layout.addWidget(self.profile_detail)
        row=QHBoxLayout()
        for title,fn in (("Nuevo perfil",self.new_profile),("Seleccionar",self.select_profile),
                         ("Renombrar",self.rename_profile),("Eliminar",self.delete_profile)):
            row.addWidget(button(title,fn))
        layout.addLayout(row)
        layout.addWidget(button("Calibrar / recalibrar",lambda:self.command_page("start_calibration",2),"Primary"))
        layout.addWidget(button("Validar calibración existente",lambda:self.command_page("validate_calibration",2)))
        layout.addWidget(label("Renombrar cambia el nombre visible y conserva la identidad de tus resultados.\nEliminar un perfil no borra las sesiones ni los experimentos históricos.","Subtitle"))
        layout.addStretch()

    def new_profile(self):
        name,ok=QInputDialog.getText(self,"Nuevo perfil","¿Cómo querés llamar a este perfil?")
        if ok:
            self.bridge.request("create_profile",name=name)
            self.show_page(1)

    def select_profile(self):
        user_id=self.profile_combo.currentData()
        if user_id: self.bridge.request("select_profile",user_id=user_id)

    def rename_profile(self):
        p=self.snapshot.get("profile")
        if not p: return self.show_error("Primero seleccioná un perfil")
        name,ok=QInputDialog.getText(self,"Renombrar perfil","Nuevo nombre:",text=p.get("display_name",p["user_id"]))
        if ok: self.bridge.request("rename_profile",name=name)

    def delete_profile(self):
        p=self.snapshot.get("profile")
        if not p: return self.show_error("Primero seleccioná un perfil")
        if QMessageBox.question(self,"Eliminar perfil",f"¿Eliminar {p.get('display_name',p['user_id'])}?\nSe perderá su calibración.",
                                QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:
            self.bridge.request("delete_profile",confirmed=True)

    def _calibration(self):
        layout=self.page("Calibración guiada","Seis mediciones, una validación final. Durante este proceso no se controla el sistema.")
        self.wizard_instruction=label("Elegí un perfil y comenzá cuando estés cómodo.","BigInstruction")
        layout.addWidget(self.wizard_instruction)
        self.wizard_progress=QProgressBar()
        self.wizard_progress.setRange(0,100)
        layout.addWidget(self.wizard_progress)
        self.calibration_preview=CameraPreview()
        layout.addWidget(self.calibration_preview,1)
        self.wizard_status=label("Sin iniciar","Subtitle")
        layout.addWidget(self.wizard_status)
        self.validation_labels=label("Validación: aún no realizada","Subtitle")
        layout.addWidget(self.validation_labels)
        row=QHBoxLayout()
        row.addWidget(button("Comenzar / recalibrar",lambda:self.bridge.request("start_calibration")))
        row.addWidget(button("Repetir gesto",lambda:self.bridge.request("repeat_calibration")))
        row.addWidget(button("Validar",lambda:self.bridge.request("validate_calibration")))
        self.save_calibration_button=button("Guardar perfil",lambda:self.bridge.request("save_calibration"),"Primary")
        self.save_calibration_button.setEnabled(False)
        row.addWidget(self.save_calibration_button)
        layout.addLayout(row)
        layout.addWidget(button("Cancelar y cerrar cámara",lambda:self.bridge.request("stop_camera")))

    def _diagnostic(self):
        layout=self.page("Diagnóstico seguro","Observá el comportamiento esperado sin mover el cursor del sistema.")
        row=QHBoxLayout()
        row.addWidget(button("Iniciar diagnóstico",lambda:self.bridge.request("start_diagnostic"),"Primary"))
        row.addWidget(button("Medir estabilidad · 10 s",lambda:self.bridge.request("start_jitter")))
        layout.addLayout(row)
        self.diagnostic_preview=CameraPreview()
        layout.addWidget(self.diagnostic_preview,1)
        self.diagnostic_values=label("Abrí el diagnóstico para consultar las mediciones.","Subtitle")
        layout.addWidget(self.diagnostic_values)
        self.jitter_summary=label("Estabilidad: sin medición","Subtitle")
        layout.addWidget(self.jitter_summary)

    def _settings(self):
        layout=self.page("Configuración","Los cambios se guardan en el perfil seleccionado. Aplicar detiene el control y la cámara.")
        scroll=QScrollArea()
        scroll.setWidgetResizable(True)
        container=QWidget()
        form=QFormLayout(container)
        form.setVerticalSpacing(14)
        self.fields={}
        specs=[("vision.camera_index","Cámara",0,100,0),
               ("gesture.sensitivity_x","Sensibilidad horizontal",0,1000,1),
               ("gesture.sensitivity_y","Sensibilidad vertical",0,1000,1),
               ("gesture.smoothing_alpha","Suavizado (0: directo; 0,95: suave)",0,.95,2),
               ("gesture.dead_zone","Zona muerta",0,.49,3),
               ("control.face_timeout_s","Timeout de rostro · segundos",.1,60,1)]
        for group,title in (("blink","Guiños"),("brow","Cejas"),("both_brows","Ambas cejas"),("mouth","Boca")):
            specs += [(f"gesture.{group}_hold_ms",f"{title}: sostener · ms",0,5000,0),
                      (f"gesture.{group}_cooldown_ms",f"{title}: espera · ms",0,10000,0)]
        for key,title,lo,hi,decimals in specs:
            field=QSpinBox() if decimals==0 else QDoubleSpinBox()
            field.setRange(lo,hi)
            if decimals: field.setDecimals(decimals); field.setSingleStep(.01 if hi<=1 else 1)
            field.setAccessibleName(title)
            form.addRow(title,field)
            self.fields[key]=field
        self.overlay_check=QCheckBox("Mostrar punto de tracking, neutral, zona muerta y dirección")
        self.landmarks_check=QCheckBox("Mostrar landmarks relevantes")
        form.addRow(self.overlay_check)
        form.addRow(self.landmarks_check)
        tracking=QComboBox()
        tracking.addItem("Nariz")
        tracking.setAccessibleName("Método de tracking")
        form.addRow("Método de tracking",tracking)
        scroll.setWidget(container)
        layout.addWidget(scroll,1)
        row=QHBoxLayout()
        row.addWidget(button("Restaurar valores predeterminados",self.restore_defaults))
        row.addWidget(button("Guardar configuración",self.save_settings,"Primary"))
        layout.addLayout(row)
        layout.addWidget(button("Preparar modelo local (requiere Internet una vez)",self.prepare_model))

    def prepare_model(self):
        if QMessageBox.question(self,"Preparar modelo","Se descargará el modelo oficial de MediaPipe.\nNo se enviarán imágenes.",
                                QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:
            self.bridge.request("prepare_model")

    def save_settings(self):
        if not self.snapshot.get("profile"): return self.show_error("Primero elegí un perfil")
        settings=deepcopy(self.snapshot["settings"])
        for key,widget in self.fields.items():
            section,name=key.split(".")
            settings[section][name]=widget.value()
        settings["ui"]["show_overlay"]=self.overlay_check.isChecked()
        settings["ui"]["show_landmarks"]=self.landmarks_check.isChecked()
        self.bridge.request("save_settings",settings=settings)

    def restore_defaults(self):
        if QMessageBox.question(self,"Restaurar configuración","¿Restaurar parámetros y acciones predeterminados de este perfil?",
                                QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:
            self.bridge.request("restore_defaults")

    def _mapping(self):
        layout=self.page("Gestos y acciones","Elegí qué querés hacer con cada gesto. La detección y la acción son independientes.")
        form=QFormLayout()
        form.setVerticalSpacing(18)
        self.mapping_fields={}
        for gesture in DEFAULT_MAPPING:
            combo=QComboBox()
            combo.setAccessibleName(f"Acción para {GESTURE_LABELS[gesture]}")
            for action in ACTIONS: combo.addItem(ACTION_LABELS[action],action)
            self.mapping_fields[gesture]=combo
            form.addRow(GESTURE_LABELS[gesture],combo)
        layout.addLayout(form)
        layout.addWidget(label("El botón DETENER CONTROL y F8 siguen disponibles aunque cambies el gesto de pausa.\nLos cambios se aplican al guardar y detienen el control actual.","Subtitle"))
        layout.addWidget(button("Guardar gestos y acciones",self.save_mapping,"Primary"))
        layout.addStretch()

    def save_mapping(self):
        if not self.snapshot.get("profile"): return self.show_error("Primero elegí un perfil")
        settings=deepcopy(self.snapshot["settings"])
        settings["actions"]["bindings"]={k:v.currentData() for k,v in self.mapping_fields.items()}
        self.bridge.request("save_settings",settings=settings)

    def _experiments(self):
        layout=self.page("Laboratorio de movimiento","Alcanzá cada objetivo y seleccioná con click izquierdo. Se registran tiempos y trayectoria, nunca imágenes.")
        row=QHBoxLayout()
        self.experiment_mode=QComboBox()
        self.experiment_mode.setAccessibleName("Modo experimental")
        self.experiment_mode.addItem("Simulación · HeadMouse",("simulation","headmouse"))
        self.experiment_mode.addItem("Simulación · flechas y espacio",("simulation","keyboard"))
        self.experiment_mode.addItem("Control real · HeadMouse",("real","headmouse"))
        row.addWidget(self.experiment_mode,1)
        row.addWidget(button("Comenzar serie",self.start_experiment,"Primary"))
        row.addWidget(button("Finalizar",lambda:self.bridge.request("cancel_experiment")))
        layout.addLayout(row)
        self.canvas=ExperimentCanvas()
        self.canvas.input.connect(self.experiment_input)
        layout.addWidget(self.canvas,1)
        self.experiment_status=label("5 objetivos · simulación interna disponible sin controlar el SO","Subtitle")
        layout.addWidget(self.experiment_status)
        layout.addWidget(label("Simulación manual: hacé foco en el panel, usá flechas y espacio.\nControl real: activalo primero con el botón superior y mantené esta ventana visible.","Subtitle"))

    def start_experiment(self):
        mode,source=self.experiment_mode.currentData()
        self.bridge.request("start_experiment",mode=mode,source=source)
        self.canvas.setFocus()

    def experiment_input(self,x,y,click,absolute):
        self.bridge.request("experiment_input",x=x,y=y,click=click,absolute=absolute)

    def _metrics(self):
        layout=self.page("Métricas y sesiones","Resultados locales. La latencia mostrada corresponde al procesamiento, no al tiempo físico de pantalla.")
        grid=QGridLayout()
        self.metric_labels={}
        for i,title in enumerate(("FPS actual","FPS promedio","Latencia promedio","Sesiones","Eventos","Pérdidas de tracking","Clicks","Scrolls")):
            box,value=card(title)
            grid.addWidget(box,i//4,i%4)
            self.metric_labels[title]=value
        layout.addLayout(grid)
        self.sessions=QTableWidget(0,5)
        self.sessions.setHorizontalHeaderLabels(["Perfil","Inicio","Duración (s)","FPS","Clicks"])
        self.sessions.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.sessions.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.sessions.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.sessions.setAccessibleName("Historial de sesiones")
        layout.addWidget(self.sessions,1)
        layout.addWidget(button("Actualizar sesiones",lambda:self.bridge.request("refresh_metrics")))

    def activate(self):
        if QMessageBox.question(self,"Activar control","HeadMouse comenzará a controlar el puntero del sistema.",
                                QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:
            self.bridge.activate()

    def show_error(self,message):
        self.banner.setText(str(message))
        # Mensaje inline persistente: evita diálogos repetidos durante errores de captura.
        self.banner.setStyleSheet("color: #ffb4bf;")

    def refresh(self):
        s=self.bridge.snapshot()
        if not s: return
        self.snapshot=s
        self.banner.setText(s["message"])
        enabled=s["control_enabled"]
        self.control_status.setText("CONTROL DEL SISTEMA\n"+("PAUSADO" if s["paused"] else "ACTIVO") if enabled else "CONTROL DEL SISTEMA\nDESACTIVADO")
        style=(s["state"]=="ERROR",enabled)
        if style!=self._status_style:
            self._status_style=style
            self.banner.setStyleSheet("color: #ffb4bf;" if style[0] else "")
            self.control_status.setStyleSheet("color: #8ce5cd;" if enabled else "color: #c4d3e8;")
        p=s["profile"]
        name=p.get("display_name",p["user_id"]) if p else "Sin perfil seleccionado"
        self.home_profile.setText(name+" · "+s["profile_status"])
        self.profile_detail.setText(name+"\n"+s["profile_status"]+"\nCalibración: "+str(p.get("calibrated_at","Pendiente") if p else "Pendiente"))
        self.activate_button.setEnabled(bool(p and p.get("validation",{}).get("passed") and not enabled and s["state"] not in ("CALIBRATING","JITTER")))
        live={"Cámara":"Conectada" if s["camera"] else "Apagada","MediaPipe":s["mediapipe"],
              "Rostro":"Detectado" if s["detected"] else "No detectado","FPS":f"{s['fps']:.0f}","Procesamiento":f"{s['processing_ms']:.1f} ms"}
        for k,v in live.items(): self.live_labels[k].setText(v)
        action=ACTION_LABELS.get(s["action"],s["action"])
        self.live_events.setText(f"Gesto: {GESTURE_LABELS.get(s['gesture'],s['gesture'])}  ·  Acción {'generada' if enabled else 'prevista'}: {action}")
        for index,preview in ((0,self.preview),(2,self.calibration_preview),(3,self.diagnostic_preview)):
            if self.stack.currentIndex()==index: preview.present(s)
        profiles_key=json.dumps(s.get("profiles",[]),sort_keys=True)
        if profiles_key!=self._profiles_key:
            self._profiles_key=profiles_key
            self.profile_combo.clear()
            self.profile_combo.addItem("Elegí un perfil…",None)
            for entry in s.get("profiles",[]):
                self.profile_combo.addItem(entry["display_name"]+" · "+entry["status"],entry["user_id"])
            if p: self.profile_combo.setCurrentIndex(self.profile_combo.findData(p["user_id"]))
        settings_key=(p["user_id"] if p else None,json.dumps(s["settings"],sort_keys=True))
        if settings_key!=self._settings_key:
            self._settings_key=settings_key
            for key,widget in self.fields.items():
                group,field=key.split(".")
                value=s["settings"][group][field]
                if value is None: value=s["settings"]["gesture"]["sensitivity"]
                widget.setValue(value)
            self.overlay_check.setChecked(s["settings"]["ui"]["show_overlay"])
            self.landmarks_check.setChecked(s["settings"]["ui"]["show_landmarks"])
            for k,widget in self.mapping_fields.items(): widget.setCurrentIndex(widget.findData(s["settings"]["actions"]["bindings"][k]))
        wizard=s["wizard"]
        if wizard:
            self.wizard_instruction.setText(wizard["instruction"])
            self.wizard_progress.setValue(int(wizard["progress"]*100))
            state=wizard["state"]
            text=f"Paso {wizard['phase']} / 6 · "
            states={"ready":"Listo para empezar","measuring":"Midiendo","measured":"Listo para validar",
                    "validation":"Validando gestos","validated":"Validación aprobada","error":"Repetir medición"}
            text+=f"Preparáte: {wizard['countdown']}" if state=="countdown" else f"{wizard['samples']} muestras · {states.get(state,state)}"
            self.wizard_status.setText(wizard["error"] or text)
            names={"LEFT_CLICK":"Guiño izq.","RIGHT_CLICK":"Guiño der.","SCROLL_UP":"Ceja izq.","SCROLL_DOWN":"Ceja der.","MOUTH_OPEN":"Boca","BOTH_BROWS":"Ambas cejas"}
            self.validation_labels.setText("  ·  ".join(f"{title}: {'DETECTADO ✓' if key in wizard['recognized'] else 'NO DETECTADO'}" for key,title in names.items()))
            self.save_calibration_button.setEnabled(wizard["can_save"] and s["state"]=="CALIBRATING")
        else:
            self.save_calibration_button.setEnabled(False)
        fd=s["face"]
        d=s["diagnostic"]
        if d:
            t=d["thresholds"]
            self.diagnostic_values.setText(
                f"Facial X / Y: {fd.nose_x:.4f} / {fd.nose_y:.4f}   |   Cursor esperado (panel 800×500): {s['cursor'][0]:.0f} / {s['cursor'][1]:.0f}\n"
                f"Desplazamiento normalizado: {d['normalized_dx']:+.4f} / {d['normalized_dy']:+.4f}   |   FPS: {s['fps']:.0f}   |   Latencia: {s['processing_ms']:.1f} ms\n"
                f"Ojos izq/der: {fd.eye_left_ratio:.4f} / {fd.eye_right_ratio:.4f} (umbrales {t['blink_left']:.4f} / {t['blink_right']:.4f})\n"
                f"Cejas izq/der: {fd.brow_left_lift:.4f} / {fd.brow_right_lift:.4f} (umbrales {t['brow_left']:.4f} / {t['brow_right']:.4f})\n"
                f"Boca: {fd.mouth_open:.4f} (umbral {t['mouth_open']:.4f})   |   Zona muerta: {s['settings']['gesture']['dead_zone']:.3f}   |   Suavizado: {s['settings']['gesture']['smoothing_alpha']:.2f}")
        if s["jitter_remaining"] is not None:
            self.jitter_summary.setText(f"Mantené neutral · {s['jitter_remaining']:.1f} s restantes")
        elif s["jitter"]:
            j=s["jitter"]
            self.jitter_summary.setText((f"Desviación media: {j['mean_deviation']:.5f} · DE: {j['std_deviation']:.5f} · Rango X/Y: {j['range_x']:.5f}/{j['range_y']:.5f}\nJitter RMS: {j['jitter_rms']:.5f} · Salidas de zona muerta: {j['dead_zone_exits']} · Unidades normalizadas" if j["valid"] else j["reason"])+"\nGuardado localmente.")
        e=s["experiment"]
        self.canvas.present(e)
        if e:
            self.experiment_status.setText(f"Objetivo {e['index']}/{e['total']} · Completados: {e['completed']} · {'En curso' if e['active'] else 'Finalizado'}\n"+(f"Resultados: {e['path']}" if e["path"] else "Resultados guardados al finalizar cada objetivo"))
            if e["active"] and e["mode"]=="real" and self.stack.currentIndex()==6:
                self.experiment_input(*self.canvas.logical(self.canvas.mapFromGlobal(QCursor.pos())),False,True)
        m=s["metrics"]
        history=s["history"]
        totals={key:sum(row.get(key,0) or 0 for row in history)+(m.get(key,0) or 0) for key in ("events_total","tracking_losses","clicks","scrolls")}
        frames=sum(row.get("frames_processed",0) for row in history)+m.get("frames_processed",0)
        duration=sum(row.get("duration_s",0) for row in history)+m.get("duration_s",0)
        processing=sum(row.get("processing_ms_mean",0)*row.get("frames_processed",0) for row in history)+m.get("processing_ms_mean",0)*m.get("frames_processed",0)
        values=[f"{s['fps']:.0f}",f"{frames/duration if duration else 0:.1f}",f"{processing/frames if frames else 0:.1f} ms",str(len(history)),str(totals['events_total']),str(totals['tracking_losses']),str(totals['clicks']),str(totals['scrolls'])]
        for out,value in zip(self.metric_labels.values(),values): out.setText(value)
        key=json.dumps(history,sort_keys=True)
        if key!=self._history_key:
            self._history_key=key
            self.sessions.setRowCount(len(history))
            for row,h in enumerate(history):
                for col,value in enumerate((h.get("profile_id","—"),h.get("started_at","—"),f"{h.get('duration_s',0):.1f}",f"{h.get('fps_mean',0):.1f}",h.get("clicks",0))):
                    self.sessions.setItem(row,col,QTableWidgetItem(str(value)))

    def closeEvent(self,event):
        if self._allow_close:
            event.accept()
            return
        event.ignore()
        if not self._closing:
            self._closing=True
            self.banner.setText("Cerrando cámara y guardando resultados…")
            self.bridge.shutdown()

    def _closed(self):
        self.timer.stop()
        self._allow_close=True
        self.close()
