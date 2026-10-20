"""Ventana desktop: presentación, formularios y comandos; sin inferencia ni acciones SO."""
import json
import time
from copy import deepcopy
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QShortcut, QKeySequence, QCursor
from PySide6.QtWidgets import (QMainWindow, QWidget, QFrame, QVBoxLayout, QHBoxLayout,
    QGridLayout, QPushButton, QStackedWidget, QScrollArea, QComboBox, QInputDialog,
    QMessageBox, QFormLayout, QDoubleSpinBox, QSpinBox, QCheckBox, QProgressBar,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView)
from action_mapping import ACTIONS, DEFAULT_MAPPING
from desktop.widgets import CameraPreview, ExperimentCanvas, CalibrationMeter, DictationOverlay, label, card

GESTURE_LABELS = dict(LEFT_WINK="Guiño izquierdo", RIGHT_WINK="Guiño derecho", LEFT_BROW="Ceja izquierda",
                      RIGHT_BROW="Ceja derecha", BOTH_BROWS="Ambas cejas", MOUTH_OPEN="Boca abierta")
CALIBRATION_ORDER = ("LEFT_WINK","RIGHT_WINK","LEFT_BROW","RIGHT_BROW","MOUTH_OPEN","BOTH_BROWS")  # = GESTURE_SIGNALS
EVENT_GESTURE = dict(LEFT_CLICK="LEFT_WINK",RIGHT_CLICK="RIGHT_WINK",SCROLL_UP="LEFT_BROW",SCROLL_DOWN="RIGHT_BROW",
                     MOUTH_OPEN="MOUTH_OPEN",BOTH_BROWS="BOTH_BROWS")
SOURCE_LABELS = dict(GEOMETRIC="Geométrica",BLENDSHAPE="Blendshapes",HYBRID="Híbrida",GEOMETRIC_3D="Geométrica 3D")
GESTURE_ROWS = (("Ojos izq/der",("LEFT_WINK","RIGHT_WINK")),("Cejas izq/der",("LEFT_BROW","RIGHT_BROW")),
                ("Ambas cejas",("BOTH_BROWS",)),("Boca",("MOUTH_OPEN",)))


def gesture_threshold_lines(d):
    """Por gesto: la señal que usa el perfil, su valor y los umbrales vigentes.

    Antes se mostraban los umbrales de compatibilidad del esquema anterior, que
    solo se actualizan para gestos GEOMETRIC de un canal: con cejas GEOMETRIC_3D
    aparecía el 0,29 genérico junto a la señal 2D, aunque el detector usaba otra.
    """
    gates,signals=d.get("gates",{}),d.get("signals",{})
    sources,active,offsets=d.get("sources",{}),d.get("active",{}),d.get("gesture_offsets",{})
    fmt=lambda values:" / ".join(f"{v:.4f}" for v in values)
    lines=[]
    for title,keys in GESTURE_ROWS:
        keys=[k for k in keys if k in gates]
        if not keys: continue
        if not any(gates[k]["enabled"] for k in keys):
            lines.append(f"{title}: no disponible")
            continue
        value,activation,release,notes=[],[],[],[]
        for k in keys:
            if not gates[k]["enabled"]:
                notes.append(f"{GESTURE_LABELS[k].lower()} no disponible")
                continue
            value+=list(signals.get(k) or [])
            activation+=list(gates[k]["activation"].values())
            release+=list(gates[k]["release"].values())
            if active.get(k): notes.append(f"gesto activo: {GESTURE_LABELS[k].lower()}")
            if any(abs(v)>1e-9 for v in offsets.get(k,{}).values()):
                notes.append(f"ajuste por recentrado ({GESTURE_LABELS[k].lower()}): "+" / ".join(f"{v:+.4f}" for v in offsets[k].values()))
        source=SOURCE_LABELS.get(sources.get(keys[0]),sources.get(keys[0],""))
        lines.append(f"{title} · {source}: {fmt(value) if value else 'señal ausente'}   "
                     f"(activación {fmt(activation)} · liberación {fmt(release)})"+(f"   · {', '.join(notes)}" if notes else ""))
    return "\n".join(lines)


ACTION_LABELS = dict(LEFT_CLICK="Click izquierdo",RIGHT_CLICK="Click derecho",DOUBLE_CLICK="Doble click",
                     SCROLL_UP="Scroll arriba",SCROLL_DOWN="Scroll abajo",PAUSE="Pausar / reanudar",
                     KEY_ENTER="Enter",KEY_ESCAPE="Escape",KEY_SPACE="Espacio",
                     OPEN_START_MENU="Abrir Inicio",DICTATE="Dictado por voz",
                     KEY_BACKSPACE="Borrar letra",DELETE_WORD="Borrar palabra",NONE="Sin acción")


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
        self.setWindowTitle("HeadMouse v0.3.1 — Robust Adaptive Facial Calibration")
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
        nav.addWidget(label("v0.3.1 · UNSTA 2026","Subtitle"))
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
        self.dictation_overlay=DictationOverlay()
        self._dictation_message=("",0.)
        self._last_dictation_state="idle"
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
        """Un botón principal que hace el próximo paso; el último perfil ya elegido."""
        layout=self.page("Inicio","Elegí tu perfil y empezá. Todo lo demás está en el menú de la izquierda.")
        row=QHBoxLayout()
        row.setSpacing(24)
        side=QVBoxLayout()
        side.setSpacing(14)
        self.home_profile=label("Sin perfil seleccionado","BigInstruction")
        side.addWidget(self.home_profile)
        self.home_profile_combo=QComboBox()
        self.home_profile_combo.setAccessibleName("Perfil")
        self.home_profile_combo.currentIndexChanged.connect(lambda _index:self._select_profile_from(self.home_profile_combo))
        side.addWidget(self.home_profile_combo)
        self.home_action=button("Iniciar HeadMouse",self.home_primary,"Hero")
        side.addWidget(self.home_action)
        self.home_state=label("","HomeState")
        side.addWidget(self.home_state)
        self.home_hint=label("","Subtitle")
        side.addWidget(self.home_hint)
        self.live_events=label("","Subtitle")
        side.addWidget(self.live_events)
        side.addStretch()
        panel=QWidget()
        panel.setLayout(side)
        panel.setMaximumWidth(460)
        row.addWidget(panel,2)
        self.preview=CameraPreview("Cámara apagada\n\nSe enciende al tocar «Iniciar HeadMouse»")
        row.addWidget(self.preview,3)
        layout.addLayout(row,1)

    def _select_profile_from(self,combo):
        user_id=combo.currentData()
        current=(self.snapshot.get("profile") or {}).get("user_id")
        if user_id and user_id!=current: self.bridge.request("select_profile",user_id=user_id)

    def _home_step(self,s):
        """Próximo paso según el perfil y el control: (texto, estilo, acción)."""
        p=s.get("profile")
        if s["control_enabled"]:
            return "■  Detener HeadMouse","HeroStop",self.bridge.stop
        if not s.get("profiles") and not p:
            return "Crear mi perfil","Hero",self.new_profile
        if not p:
            return "Elegí un perfil","Hero",lambda:self.show_page(1)
        if p.get("status")=="draft":
            return "Calibrar mis gestos","Hero",self.start_calibration
        if not p.get("validation",{}).get("passed"):
            return "Validar mi calibración","Hero",lambda:self.command_page("validate_calibration",2)
        if s["state"] in ("CALIBRATING","EYE_CALIBRATING","JITTER"):
            return "Terminá la medición en curso","Hero",None
        if not s.get("tracking_calibrated",True):
            return "Calibrar tracking ocular","Hero",self.start_eye_tracking_calibration
        return "▶  Iniciar HeadMouse","Hero",self.bridge.activate

    def home_primary(self):
        _text,_style,action=self._home_step(self.snapshot)
        if action: action()

    def _present_home(self,s):
        text,style,action=self._home_step(s)
        if self.home_action.text()!=text:
            self.home_action.setText(text)
            self.home_action.setAccessibleName(text)
        if self.home_action.objectName()!=style:
            self.home_action.setObjectName(style)
            self.home_action.style().unpolish(self.home_action)
            self.home_action.style().polish(self.home_action)
        self.home_action.setEnabled(action is not None)
        p=s.get("profile")
        if s["control_enabled"]:
            state="EN PAUSA" if s["paused"] else "ACTIVO"
            hint=("Levantá ambas cejas para empezar a mover el cursor." if s["paused"] else
                  "Ambas cejas: pausar · Guiños: click · F8 o el botón rojo: detener.")
        elif p and p.get("status")!="draft" and p.get("validation",{}).get("passed"):
            state="Listo"
            hint=("Arranca en pausa: después de iniciar, levantá ambas cejas para mover el cursor. "
                  "Si el centro quedó corrido, pausá, quedate quieto un segundo y reanudá.")
        elif p and p.get("status")=="draft":
            state,hint="Falta calibrar","Son unos minutos: tres repeticiones cómodas de cada gesto."
        elif p:
            state,hint="Falta validar","Una prueba corta de cada gesto antes de controlar la computadora."
        else:
            state,hint="",""
        self.home_state.setText(state)
        self.home_hint.setText(hint)
        camera=("Rostro detectado" if s["detected"] else "No veo tu cara: acomodá la cámara") if s["camera"] else ""
        gesture=GESTURE_LABELS.get(s["gesture"],s["gesture"])
        last=f"   ·   Último gesto: {gesture}" if s["camera"] and s["gesture"]!="—" else ""
        self.live_events.setText(camera+last)

    def _profiles(self):
        layout=self.page("Tus perfiles","Cada persona tiene su propia calibración. Cambiar de perfil detiene el control.")
        self.profile_combo=QComboBox()
        self.profile_combo.setAccessibleName("Elegir perfil")
        self.profile_combo.currentIndexChanged.connect(self.select_profile)
        layout.addWidget(self.profile_combo)
        self.profile_detail=label("Todavía no seleccionaste un perfil.","BigInstruction")
        layout.addWidget(self.profile_detail)
        row=QHBoxLayout()
        for title,fn in (("Nuevo perfil",self.new_profile),
                         ("Renombrar",self.rename_profile),("Eliminar",self.delete_profile)):
            row.addWidget(button(title,fn))
        layout.addLayout(row)
        layout.addWidget(button("Calibrar / recalibrar",self.start_calibration,"Primary"))
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
        """Una lista de gestos con su estado, un botón con el próximo paso y opciones plegadas."""
        page=self.page("Calibración guiada","Tres intentos cómodos por gesto. Después se prueba cada gesto y se guarda el perfil.")
        # Con desplazamiento: al abrir "Más opciones" la página crece en lugar de aplastarse.
        scroll=QScrollArea()
        scroll.setWidgetResizable(True)
        body=QWidget()
        outer=QVBoxLayout(body)
        outer.setContentsMargins(0,0,12,0)
        outer.setSpacing(12)
        scroll.setWidget(body)
        page.addWidget(scroll,1)
        self.wizard_instruction=label("Elegí un perfil y comenzá cuando estés cómodo.","BigInstruction")
        outer.addWidget(self.wizard_instruction)
        self.wizard_progress=QProgressBar()
        self.wizard_progress.setRange(0,100)
        outer.addWidget(self.wizard_progress)
        self.wizard_status=label("Sin iniciar","Subtitle")
        outer.addWidget(self.wizard_status)
        live=QHBoxLayout()
        live.setSpacing(16)
        steps=QFrame()
        steps.setObjectName("Card")
        steps.setFixedWidth(300)
        steps_layout=QVBoxLayout(steps)
        steps_layout.setContentsMargins(16,12,16,12)
        self.calibration_steps_title=label("Gestos","Subtitle")
        steps_layout.addWidget(self.calibration_steps_title)
        self.calibration_steps=label("")
        self.calibration_steps.setTextFormat(Qt.TextFormat.RichText)
        steps_layout.addWidget(self.calibration_steps)
        steps_layout.addStretch()
        live.addWidget(steps)
        self.calibration_preview=CameraPreview("Cámara apagada\n\nSe enciende al comenzar la calibración")
        live.addWidget(self.calibration_preview,3)
        readings=QVBoxLayout()
        self.calibration_meter=CalibrationMeter()
        readings.addWidget(self.calibration_meter)
        self.capture_feedback=label("","Subtitle")
        readings.addWidget(self.capture_feedback)
        self.calibration_quality=label("","Subtitle")
        readings.addWidget(self.calibration_quality)
        readings.addStretch()
        live.addLayout(readings,2)
        outer.addLayout(live,1)
        self.validation_labels=label("","Subtitle")  # resumen accesible; la lista muestra el detalle
        self.validation_labels.hide()
        outer.addWidget(self.validation_labels)
        actions=QHBoxLayout()
        self.calibration_primary=button("Comenzar calibración",self.calibration_primary_action,"Hero")
        actions.addWidget(self.calibration_primary,3)
        self.save_calibration_button=button("Guardar perfil",lambda:self.bridge.request("save_calibration"),"Hero")
        self.save_calibration_button.setEnabled(False)
        self.save_calibration_button.hide()
        actions.addWidget(self.save_calibration_button,3)
        self.calibration_secondary=button("",self.calibration_secondary_action)
        self.calibration_secondary.hide()
        actions.addWidget(self.calibration_secondary,2)
        self.calibration_more=button("Más opciones ▾",self.toggle_calibration_options)
        actions.addWidget(self.calibration_more,1)
        outer.addLayout(actions)
        # ── Opciones avanzadas (plegadas) ──
        self.calibration_options=QFrame()
        self.calibration_options.setObjectName("Card")
        options=QVBoxLayout(self.calibration_options)
        options.setContentsMargins(16,12,16,12)
        self.calibration_options.hide()
        self.calibration_options.toggled_scroll=scroll  # para llevar la vista a las opciones al abrirlas
        options.addWidget(label("Gestos disponibles: desmarcá los que no puedas hacer.","Subtitle"))
        choices=QGridLayout()
        self.calibration_enabled={}
        for index,(key,title) in enumerate(GESTURE_LABELS.items()):
            check=QCheckBox(title)
            check.setChecked(True)
            check.toggled.connect(lambda checked,gesture_id=key:self.calibration_availability(gesture_id,checked))
            self.calibration_enabled[key]=check
            choices.addWidget(check,index//3,index%3)
        options.addLayout(choices)
        source_row=QHBoxLayout()
        source_row.addWidget(label("Señal de cejas"))
        self.calibration_source=QComboBox()
        for title,value in (("Geométrica (predeterminada)","GEOMETRIC"),("Blendshapes · experimental","BLENDSHAPE"),("Híbrida · experimental","HYBRID"),
                            ("Geométrica 3D · experimental","GEOMETRIC_3D")):
            self.calibration_source.addItem(title,value)
        source_row.addWidget(self.calibration_source,1)
        options.addLayout(source_row)
        repeat_row=QHBoxLayout()
        self.repeat_gesture=QComboBox()
        self.repeat_gesture.addItem("Repetir gesto actual / validación actual",None)
        for key,title in GESTURE_LABELS.items(): self.repeat_gesture.addItem("Volver a medir: "+title,key)
        self.repeat_gesture.setAccessibleName("Elegir gesto para repetir sin perder los demás")
        repeat_row.addWidget(self.repeat_gesture,1)
        repeat_row.addWidget(button("Repetir",lambda:self.bridge.request("repeat_calibration",gesture_id=self.repeat_gesture.currentData())))
        options.addLayout(repeat_row)
        extra=QHBoxLayout()
        extra.addWidget(button("Recalibrar desde cero",self.start_calibration))
        extra.addWidget(button("Cancelar y cerrar cámara",lambda:self.bridge.request("stop_camera")))
        options.addLayout(extra)
        outer.addWidget(self.calibration_options)
        # La señal elegida queda visible aunque las opciones estén plegadas.
        self.calibration_options_toggle=self.calibration_more
        show_source=lambda _index=None:self.calibration_more.setText(
            f"Más opciones ▾  ·  cejas: {self.calibration_source.currentText().split(' ·')[0].split(' (')[0]}")
        self.calibration_source.currentIndexChanged.connect(show_source)
        show_source()

    def toggle_calibration_options(self):
        visible=not self.calibration_options.isVisible()
        self.calibration_options.setVisible(visible)
        if visible:
            QTimer.singleShot(0,lambda:self.calibration_options.toggled_scroll.ensureWidgetVisible(self.calibration_options))

    def _calibration_step(self,s):
        """(texto principal, acción, texto secundario, acción secundaria) según el asistente."""
        wizard=s.get("wizard")
        calibrating=s.get("state")=="CALIBRATING"
        if not wizard or not calibrating:
            if wizard and wizard.get("state")=="validated":
                return "Ir a Inicio",lambda:self.show_page(0),None,None
            return "Comenzar calibración",self.start_calibration,None,None
        state=wizard["state"]
        gesture=wizard.get("gesture_id")
        if state=="error":  # falló una medición
            return ("Repetir este gesto",lambda:self.bridge.request("repeat_calibration",gesture_id=None),
                    "No puedo hacer este gesto" if gesture else None,
                    (lambda:self.bridge.request("set_calibration_gesture",gesture_id=gesture,enabled=False)) if gesture else None)
        if state=="validation" and wizard.get("error"):  # falló la prueba de un gesto
            return "Reintentar la prueba",lambda:self.bridge.request("repeat_calibration",gesture_id=None),None,None
        if state in ("validation","measured"):
            return "Probando tus gestos…",None,None,None
        if state=="validated":
            return None,None,None,None  # se muestra Guardar perfil
        return "Midiendo…",None,"Cancelar",lambda:self.bridge.request("stop_camera")

    def calibration_primary_action(self):
        _text,action,_secondary,_other=self._calibration_step(self.snapshot)
        if action: action()

    def calibration_secondary_action(self):
        _text,_action,_secondary,action=self._calibration_step(self.snapshot)
        if action: action()

    def _present_calibration(self,s):
        text,action,secondary,other=self._calibration_step(s)
        wizard=s.get("wizard")
        can_save=bool(wizard and wizard.get("can_save") and s["state"]=="CALIBRATING")
        self.save_calibration_button.setVisible(can_save)
        self.save_calibration_button.setEnabled(can_save)
        self.calibration_primary.setVisible(text is not None)
        if text is not None:
            if self.calibration_primary.text()!=text:
                self.calibration_primary.setText(text)
                self.calibration_primary.setAccessibleName(text)
            self.calibration_primary.setEnabled(action is not None)
        self.calibration_secondary.setVisible(secondary is not None)
        if secondary: self.calibration_secondary.setText(secondary)
        self._present_calibration_steps(wizard)

    def _present_calibration_steps(self,wizard):
        """Lista de gestos: ✓ listo, ● en curso, ✗ repetir, ○ pendiente, — no disponible."""
        if not wizard:
            self.calibration_steps_title.setText("Gestos")
            self.calibration_steps.setText("<br>".join(f"<span style='color:#8192aa'>○</span>&nbsp; {GESTURE_LABELS[k]}"
                                                       for k in CALIBRATION_ORDER))
            return
        enabled,quality=wizard.get("enabled",{}),wizard.get("quality",{})
        current=wizard.get("gesture_id")
        validating=wizard.get("state") in ("validation","validated") or bool(wizard.get("recognized"))
        recognized={EVENT_GESTURE.get(event,event) for event in wizard.get("recognized",[])}
        rows=[]
        for key in CALIBRATION_ORDER:
            title=GESTURE_LABELS[key]
            label_text=quality.get(key,{}).get("label","PENDIENTE")
            if not enabled.get(key,True):
                icon,color,detail="—","#8192aa","no disponible"
            elif validating:
                if key in recognized or wizard.get("state")=="validated":
                    icon,color,detail="✓","#8ce5cd","detectado"
                elif key==current:
                    icon,color,detail="●","#ffd166","probando ahora"
                else:
                    icon,color,detail="○","#8192aa","falta probar"
            elif key==current and wizard.get("state")=="error":
                icon,color,detail="✗","#ff8796","repetir"
            elif key==current:
                attempt=wizard.get("attempt",0)
                icon,color,detail="●","#ffd166",f"intento {attempt} de {wizard.get('repetitions',3)}"
            elif label_text.startswith(("BUENA","ACEPTABLE")) and "provisional" not in label_text:
                icon,color,detail="✓","#8ce5cd",label_text.lower()
            elif label_text.startswith("DÉBIL"):
                icon,color,detail="✗","#ff8796","débil: repetir"
            else:
                icon,color,detail="○","#8192aa","pendiente"
            rows.append(f"<span style='color:{color}'>{icon}</span>&nbsp; {title} "
                        f"<span style='color:#8192aa'>· {detail}</span>")
        self.calibration_steps_title.setText("Prueba de gestos" if validating else "Medición de gestos")
        self.calibration_steps.setText("<br>".join(rows))

    def start_calibration(self):
        self.show_page(2)
        self.calibration_options.hide()
        self.bridge.request("start_calibration",enabled={key:check.isChecked() for key,check in self.calibration_enabled.items()},
                            source=self.calibration_source.currentData())

    def calibration_availability(self,gesture_id,enabled):
        if self.snapshot.get("state")=="CALIBRATING" and self.snapshot.get("wizard"):
            self.bridge.request("set_calibration_gesture",gesture_id=gesture_id,enabled=enabled)

    def _diagnostic(self):
        page=self.page("Diagnóstico seguro","Observá el comportamiento esperado sin mover el cursor del sistema.")
        scroll=QScrollArea()
        scroll.setWidgetResizable(True)
        body=QWidget()
        layout=QVBoxLayout(body)
        layout.setContentsMargins(0,0,12,0)
        scroll.setWidget(body)
        page.addWidget(scroll,1)
        row=QHBoxLayout()
        row.addWidget(button("Iniciar diagnóstico",lambda:self.bridge.request("start_diagnostic"),"Primary"))
        row.addWidget(button("Medir estabilidad · 10 s",lambda:self.bridge.request("start_jitter")))
        layout.addLayout(row)
        self.diagnostic_preview=CameraPreview()
        layout.addWidget(self.diagnostic_preview,1)
        self.diagnostic_values=label("Abrí el diagnóstico para consultar las mediciones.","Subtitle")
        layout.addWidget(self.diagnostic_values)
        self.eye_diagnostic=label("","Subtitle")
        layout.addWidget(self.eye_diagnostic)
        self.jitter_summary=label("Estabilidad: sin medición","Subtitle")
        layout.addWidget(self.jitter_summary)
        advanced=QCheckBox("Mostrar calibración avanzada por gesto")
        self.advanced_diagnostic=label("Sin calibración adaptativa disponible.","Subtitle")
        advanced_scroll=QScrollArea()
        advanced_scroll.setWidgetResizable(True)
        advanced_scroll.setWidget(self.advanced_diagnostic)
        advanced_scroll.setMaximumHeight(190)
        advanced_scroll.hide()
        advanced.toggled.connect(advanced_scroll.setVisible)
        layout.addWidget(advanced)
        layout.addWidget(advanced_scroll)

    def _settings(self):
        layout=self.page("Configuración","Los cambios se guardan en el perfil seleccionado. Aplicar detiene el control y la cámara.")
        layout.addWidget(button("Calibrar tracking ocular · Experimental",self.start_eye_tracking_calibration))
        scroll=QScrollArea()
        self.settings_scroll=scroll
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
               ("control.face_timeout_s","Timeout de rostro · segundos",.1,60,1),
               ("control.scroll_lines","Scroll: muescas de rueda por evento",1,100,0),
               ("gesture.brow_repeat_delay_ms","Scroll continuo: esperar antes de repetir · ms",0,5000,0),
               ("gesture.brow_repeat_ms","Scroll continuo: repetir cada · ms (0 = apagado)",0,5000,0),
               ("gesture.brow_decision_ms","Ventana de decisión de cejas · ms",0,1000,0)]
        specs += [("eye.sensitivity","Ojos: sensibilidad",0,100,1),
                  ("eye.acceleration","Ojos: aceleración",0,100,1),
                  ("eye.dead_zone","Ojos: zona muerta (fracción de rango)",0,.8,3),
                  ("eye.smoothing_alpha","Ojos: suavizado",0,.95,2),
                  ("eye.max_delta","Ojos: delta máximo por detección · px",1,60,1)]
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
        self.voice_check=QCheckBox("Dictado por voz: al hacer click en un campo de texto, escuchar y escribir")
        self.voice_check.setAccessibleName("Dictado por voz")
        form.addRow(self.voice_check)
        self.voice_model=QComboBox()
        for title,value in (("Small · recomendado","small"),("Base · equipos lentos","base"),
                            ("Tiny · muy rápido, menos preciso","tiny"),("Medium · más preciso y lento","medium")):
            self.voice_model.addItem(title,value)
        self.voice_model.setAccessibleName("Modelo de voz")
        form.addRow("Modelo de voz",self.voice_model)
        self.voice_send=QComboBox()
        self.voice_send.setEditable(True)
        self.voice_send.addItems(["","enviar"])
        self.voice_send.setAccessibleName("Palabra final que presiona Enter")
        form.addRow("Palabra final que presiona Enter (vacío: ninguna)",self.voice_send)
        form.addRow(label("Comandos de voz: «borrar», «borrar N palabras», «borrar N letras», «borrar todo», «deshacer». "
                          "Decí solo el comando. La lista completa está en Gestos y acciones.","Subtitle"))
        self.overlay_check=QCheckBox("Mostrar punto de tracking, neutral, zona muerta y dirección")
        self.landmarks_check=QCheckBox("Mostrar landmarks relevantes")
        form.addRow(self.overlay_check)
        form.addRow(self.landmarks_check)
        self.tracking_combo=QComboBox()
        self.tracking_combo.addItem("Nariz","nose")
        self.tracking_combo.addItem("Ojos — Experimental","eye")
        self.tracking_combo.setAccessibleName("Método de tracking")
        form.addRow("Método de tracking",self.tracking_combo)
        self.eye_warning=label("Modo experimental. Guardá la configuración para aplicar el método. "
                               "Requiere neutral ocular; probá primero en Diagnóstico seguro.","Subtitle")
        form.addRow(self.eye_warning)
        self.tracking_combo.currentIndexChanged.connect(
            lambda _index:self.eye_warning.setVisible(self.tracking_combo.currentData()=="eye"))
        self.eye_warning.hide()
        form.addRow(label("Calibrar tracking ocular","Subtitle"))
        form.addRow(label("Mirada al centro durante 2 segundos, ambos ojos abiertos. "
                          "Se guarda solo el neutral; los rangos cómodos son nominales. "
                          "Esta captura es independiente de Calibrar gestos.","Subtitle"))
        eye_actions=QHBoxLayout()
        self.eye_start=button("Calibrar tracking ocular",self.start_eye_tracking_calibration)
        self.eye_save=button("Guardar neutral ocular",lambda:self.bridge.request("save_eye_calibration"),"Primary")
        self.eye_save.setEnabled(False)
        eye_actions.addWidget(self.eye_start)
        eye_actions.addWidget(self.eye_save)
        eye_actions.addWidget(button("Cancelar captura ocular",lambda:self.bridge.request("cancel_eye_calibration")))
        form.addRow(eye_actions)
        self.eye_status=label("Neutral ocular: sin capturar","Subtitle")
        self.eye_progress=QProgressBar()
        self.eye_progress.setRange(0,100)
        self.eye_preview=CameraPreview("La cámara se abre al calibrar el tracking ocular")
        form.addRow(self.eye_status)
        form.addRow(self.eye_progress)
        form.addRow(self.eye_preview)
        scroll.setWidget(container)
        layout.addWidget(scroll,1)
        row=QHBoxLayout()
        row.addWidget(button("Restaurar valores predeterminados",self.restore_defaults))
        row.addWidget(button("Guardar configuración",self.save_settings,"Primary"))
        layout.addLayout(row)
        self.prepare_model_button=button("Preparar modelo facial (requiere Internet una vez)",self.prepare_model)
        self.prepare_voice_button=button("Preparar modelo de voz (requiere Internet una vez)",self.prepare_voice_model)
        layout.addWidget(self.prepare_model_button)
        layout.addWidget(self.prepare_voice_button)

    def start_eye_tracking_calibration(self):
        self.show_page(4)
        self.bridge.request("start_eye_calibration")
        QTimer.singleShot(0,lambda:self.settings_scroll.ensureWidgetVisible(self.eye_status))

    def prepare_voice_model(self):
        model=self.voice_model.currentData()
        sizes=dict(tiny="75 MB",base="145 MB",small="480 MB",medium="1,5 GB")
        text=(f"Se descargará el modelo de voz '{model}' (≈ {sizes[model]}) de Hugging Face (Systran/faster-whisper).\n"
              "Después el dictado funciona sin Internet y el audio nunca sale de la computadora.")
        if QMessageBox.question(self,"Preparar modelo de voz",text,
                                QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:
            self.bridge.request("prepare_voice_model",model=model)

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
        settings["ui"]["tracking_method"]=self.tracking_combo.currentData()
        settings["voice"]["enabled"]=self.voice_check.isChecked()
        settings["voice"]["model"]=self.voice_model.currentData()
        settings["voice"]["send_word"]=self.voice_send.currentText().strip().lower()
        self.bridge.request("save_settings",settings=settings)

    def restore_defaults(self):
        if QMessageBox.question(self,"Restaurar configuración","¿Restaurar parámetros y acciones predeterminados de este perfil?",
                                QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:
            self.bridge.request("restore_defaults")

    def _mapping(self):
        page=self.page("Gestos y acciones","Elegí qué querés hacer con cada gesto. La detección y la acción son independientes.")
        # Con desplazamiento: con la ayuda de voz no entra en pantallas de 820 px de alto.
        scroll=QScrollArea()
        scroll.setWidgetResizable(True)
        body=QWidget()
        layout=QVBoxLayout(body)
        layout.setContentsMargins(0,0,12,0)
        layout.setSpacing(14)
        scroll.setWidget(body)
        page.addWidget(scroll,1)
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
        layout.addWidget(self._voice_commands_help())
        layout.addStretch()

    def _voice_commands_help(self):
        """Los comandos de voz no tienen botón: si no se muestran, nadie los descubre."""
        from dictation import VOICE_COMMANDS
        box=QFrame()
        box.setObjectName("Card")
        inner=QVBoxLayout(box)
        inner.setContentsMargins(18,12,18,12)
        inner.addWidget(label("Comandos de voz para corregir","Subtitle"))
        rows=QGridLayout()
        rows.setHorizontalSpacing(24)
        for index,(phrase,effect,_example) in enumerate(VOICE_COMMANDS):
            rows.addWidget(label(phrase),index,0)
            rows.addWidget(label(effect,"Subtitle"),index,1)
        inner.addLayout(rows)
        self.voice_help_notes=label("","Subtitle")
        inner.addWidget(self.voice_help_notes)
        box.setAccessibleName("Comandos de voz")
        return box

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
        self._present_dictation(s.get("dictation"))
        self._present_models(s.get("models") or {})
        enabled=s["control_enabled"]
        self.control_status.setText("CONTROL DEL SISTEMA\n"+("PAUSADO" if s["paused"] else "ACTIVO") if enabled else "CONTROL DEL SISTEMA\nDESACTIVADO")
        style=(s["state"]=="ERROR",enabled)
        if style!=self._status_style:
            self._status_style=style
            self.banner.setStyleSheet("color: #ffb4bf;" if style[0] else "")
            self.control_status.setStyleSheet("color: #8ce5cd;" if enabled else "color: #c4d3e8;")
        p=s["profile"]
        name=p.get("display_name",p["user_id"]) if p else "Sin perfil seleccionado"
        self.home_profile.setText(f"Hola, {name}" if p else "Bienvenido a HeadMouse")
        self._present_home(s)
        self.profile_detail.setText(name+"\n"+s["profile_status"]+"\nCalibración: "+str(p.get("calibrated_at","Pendiente") if p else "Pendiente"))
        self.activate_button.setEnabled(bool(p and p.get("validation",{}).get("passed") and not enabled
                                            and s.get("tracking_calibrated",True)
                                            and s["state"] not in ("CALIBRATING","EYE_CALIBRATING","JITTER")))
        eye_session=s.get("eye_calibration")
        self.eye_save.setEnabled(bool(eye_session and eye_session["can_save"] and s["state"]=="EYE_CALIBRATING"))
        self.eye_start.setEnabled(bool(p and s["state"]!="CALIBRATING"))
        self.eye_progress.setValue(int(100*eye_session["progress"]) if eye_session else 0)
        self.eye_status.setText(eye_session["message"] if eye_session else
                               "Neutral ocular guardado. Recalibrá si cambia la cámara o tu postura."
                               if (p or {}).get("tracking_calibration") else "Neutral ocular: falta calibrar")
        for index,preview in ((0,self.preview),(2,self.calibration_preview),(3,self.diagnostic_preview),(4,self.eye_preview)):
            if self.stack.currentIndex()==index: preview.present(s)
        profiles_key=json.dumps([s.get("profiles",[]),(s.get("profile") or {}).get("user_id")],sort_keys=True)
        if profiles_key!=self._profiles_key:
            self._profiles_key=profiles_key
            self.profile_combo.blockSignals(True)
            self.profile_combo.clear()
            self.profile_combo.addItem("Elegí un perfil…",None)
            for entry in s.get("profiles",[]):
                self.profile_combo.addItem(entry["display_name"]+" · "+entry["status"],entry["user_id"])
            if p: self.profile_combo.setCurrentIndex(self.profile_combo.findData(p["user_id"]))
            self.profile_combo.blockSignals(False)
            self.home_profile_combo.blockSignals(True)
            self.home_profile_combo.clear()
            if not p: self.home_profile_combo.addItem("Elegí un perfil…",None)
            for entry in s.get("profiles",[]):
                self.home_profile_combo.addItem(f"Perfil: {entry['display_name']} · {entry['status']}",entry["user_id"])
            if p: self.home_profile_combo.setCurrentIndex(self.home_profile_combo.findData(p["user_id"]))
            self.home_profile_combo.setVisible(bool(s.get("profiles")))
            self.home_profile_combo.blockSignals(False)
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
            self.tracking_combo.setCurrentIndex(self.tracking_combo.findData(s["settings"]["ui"]["tracking_method"]))
            self.voice_check.setChecked(s["settings"]["voice"]["enabled"])
            self.voice_model.setCurrentIndex(max(0,self.voice_model.findData(s["settings"]["voice"]["model"])))
            self.voice_send.setCurrentText(s["settings"]["voice"]["send_word"])
            voice=s["settings"]["voice"]
            notes=["Con el dictado activo: hacé click en un campo de texto y decí solo el comando. "
                   "Dentro de una frase más larga se escribe como texto normal."]
            if voice["send_word"]:
                notes.append(f"«{voice['send_word']}» al final de una frase: escribe el texto y presiona Enter.")
            notes.append("Ambas cejas cancelan el dictado. Sin hablar: asigná «Borrar letra» o «Borrar palabra» a un gesto arriba.")
            if not voice["enabled"]:
                notes.insert(0,"El dictado está apagado: activalo en Configuración → Dictado por voz.")
            if not voice["commands"]:
                notes.insert(0,"Los comandos están desactivados en este perfil (voice.commands).")
            self.voice_help_notes.setText("\n".join(notes))
            for k,widget in self.mapping_fields.items(): widget.setCurrentIndex(widget.findData(s["settings"]["actions"]["bindings"][k]))
            self.calibration_source.setCurrentIndex(self.calibration_source.findData(s["settings"]["calibration"]["brow_signal_source"]))
            for key,check in self.calibration_enabled.items():
                enabled=(p or {}).get("gesture_calibrations",{}).get(key,{}).get("enabled",True)
                check.blockSignals(True)
                check.setChecked(enabled)
                check.blockSignals(False)
                self.mapping_fields[key].setEnabled(enabled)
        wizard=s["wizard"]
        self._present_calibration(s)
        if wizard:
            self.calibration_source.setEnabled(s["state"]!="CALIBRATING")
            self.calibration_meter.present(wizard.get("meter",[]))
            quality=wizard.get("quality",{})
            self.calibration_quality.setToolTip("\n".join(GESTURE_LABELS[k]+": "+v["label"] for k,v in quality.items()))
            if s["state"]=="CALIBRATING":
                for key,value in wizard.get("enabled",{}).items():
                    self.calibration_enabled[key].blockSignals(True)
                    self.calibration_enabled[key].setChecked(value)
                    self.calibration_enabled[key].blockSignals(False)
            self.wizard_instruction.setText(wizard["instruction"])
            self.wizard_progress.setValue(int(wizard["progress"]*100))
            state=wizard["state"]
            states={"ready":"Listo para empezar","measuring":"Midiendo","measured":"Listo para probar",
                    "validation":"Probando gestos","validated":"Prueba aprobada: guardá el perfil","error":"Hay que repetir",
                    "settling":"Preparate para la próxima captura","countdown":"Preparate"}
            current=wizard.get("gesture_id")
            parts=[GESTURE_LABELS[current]] if current in GESTURE_LABELS else []
            if wizard.get("attempt"):
                parts.append(f"Intento {wizard['attempt']}/{wizard['repetitions']}")
            parts.append(f"empieza en {wizard['countdown']}" if state=="countdown" else states.get(state,state))
            self.wizard_status.setText(wizard["error"] or "  ·  ".join(parts))
            # Sin repetir la instrucción grande: solo lo que agrega información.
            feedback=wizard.get("feedback","")
            extra=[t for t in (feedback if feedback not in (wizard["instruction"],wizard.get("error")) else "",
                               wizard.get("capture_message","")) if t]
            self.capture_feedback.setText("  ·  ".join(extra))
            names={"LEFT_CLICK":"Guiño izq.","RIGHT_CLICK":"Guiño der.","SCROLL_UP":"Ceja izq.","SCROLL_DOWN":"Ceja der.","MOUTH_OPEN":"Boca","BOTH_BROWS":"Ambas cejas"}
            self.validation_labels.setText("  ·  ".join(f"{title}: "+("NO DISPONIBLE" if not wizard.get("enabled",{}).get(EVENT_GESTURE[key],True) else "DETECTADO ✓" if key in wizard['recognized'] else "NO DETECTADO") for key,title in names.items()))
        else:
            self.calibration_source.setEnabled(True)
        fd=s["face"]
        d=s["diagnostic"]
        tracking=d.get("tracking",{})
        fmt=lambda v:f"{v:.4f}" if v is not None else "ausente"
        eye_available=s["detected"] and fd.gaze_available
        self.eye_diagnostic.setText(
            f"Estrategia activa: {s['settings']['ui']['tracking_method']}"
            +(" · Modo experimental" if s["settings"]["ui"]["tracking_method"]=="eye" else "")+"\n"
            f"left_gaze_x/y: {fmt(fd.left_gaze_x)} / {fmt(fd.left_gaze_y)} · "
            f"right_gaze_x/y: {fmt(fd.right_gaze_x)} / {fmt(fd.right_gaze_y)}\n"
            f"gaze_x/y: {fmt(fd.gaze_x)} / {fmt(fd.gaze_y)} · Disponible: {eye_available} · "
            f"Confianza (cobertura): {fd.gaze_confidence:.1f}\n"
            + (f"Neutral gaze: {fmt(tracking.get('neutral_x'))} / {fmt(tracking.get('neutral_y'))} · "
               f"Delta X/Y (rango): {fmt(tracking.get('delta_x'))} / {fmt(tracking.get('delta_y'))} · "
               f"Zona muerta ocular: {s['settings']['eye']['dead_zone']:.3f}\n"
               if s["settings"]["ui"]["tracking_method"]=="eye" else "")
            +f"Head yaw / pitch: {fmt(fd.head_yaw)} / {fmt(fd.head_pitch)} · Sin compensación de pose")
        if d:
            advanced=[]
            for key,record in d.get("gesture_calibrations",{}).items():
                if not record["enabled"]:
                    advanced.append(GESTURE_LABELS[key]+": no disponible")
                    continue
                numbers=lambda values:" / ".join(f"{v:.4f}" for v in values)
                values=d.get("signals",{}).get(key)
                gate=d.get("gates",{}).get(key,{})
                current=(f" · Vigente {numbers(gate['activation'].values())} / {numbers(gate['release'].values())}"
                         if gate and gate["activation"]!=record["activation_threshold"] else "")
                advanced.append(f"{GESTURE_LABELS[key]} · {SOURCE_LABELS.get(record['source'],record['source'])} · señal {numbers(values) if values else 'ausente'}\n"
                                f"Calibrado: activación {numbers(record['activation_threshold'].values())} · liberación {numbers(record['release_threshold'].values())}{current} · Calidad {record['quality_score']:.2f} · Repeticiones {record.get('repetitions_valid',0)}")
            self.advanced_diagnostic.setText("\n".join(advanced) or "Perfil anterior: umbral único geométrico; ambas cejas usan los umbrales unilaterales.")
            self.diagnostic_values.setText(
                f"Facial X / Y: {fd.nose_x:.4f} / {fd.nose_y:.4f}   |   Cursor esperado (panel 800×500): {s['cursor'][0]:.0f} / {s['cursor'][1]:.0f}\n"
                f"Desplazamiento normalizado: {d['normalized_dx']:+.4f} / {d['normalized_dy']:+.4f}   |   FPS: {s['fps']:.0f}   |   Latencia: {s['processing_ms']:.1f} ms\n"
                f"Centro X / Y vigente: {d.get('neutral_x',0):.4f} / {d.get('neutral_y',0):.4f}   (calibrado: "
                f"{d.get('calibrated_neutral',(0,0))[0]:.4f} / {d.get('calibrated_neutral',(0,0))[1]:.4f})   |   "
                +("tracking ocular: neutral independiente\n" if s["settings"]["ui"]["tracking_method"]=="eye" else "ambas cejas recentran\n")
                +gesture_threshold_lines(d)+"\n"
                f"Zona muerta: {s['settings']['gesture']['dead_zone']:.3f}   |   Suavizado: {s['settings']['gesture']['smoothing_alpha']:.2f}")
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

    def _present_models(self,models):
        """Los botones de descarga solo hacen falta si el modelo todavía no está."""
        sizes=dict(tiny="75 MB",base="145 MB",small="480 MB",medium="1,5 GB")
        face=models.get("face")
        text="Modelo facial instalado ✓" if face else "Preparar modelo facial (≈ 4 MB, requiere Internet una vez)"
        if self.prepare_model_button.text()!=text:
            self.prepare_model_button.setText(text)
            self.prepare_model_button.setEnabled(not face)
        model=self.voice_model.currentData()
        voice=models.get("voice",{}).get(model)
        text=(f"Modelo de voz '{model}' instalado ✓" if voice else
              f"Preparar modelo de voz '{model}' (≈ {sizes.get(model,'?')}, requiere Internet una vez)")
        if self.prepare_voice_button.text()!=text:
            self.prepare_voice_button.setText(text)
            self.prepare_voice_button.setEnabled(not voice)

    def _present_dictation(self,dictation):
        """Aviso flotante; al terminar muestra el resultado durante 2,5 s."""
        state=(dictation or {}).get("state","idle")
        now=time.monotonic()
        if state in ("listening","transcribing"):
            self._dictation_message=("",0.)
        elif state=="idle" and self._last_dictation_state!="idle" and dictation and dictation.get("message"):
            self._dictation_message=(dictation["message"],now+2.5)
        self._last_dictation_state=state
        message=self._dictation_message[0] if now<self._dictation_message[1] else ""
        self.dictation_overlay.present(dictation,message,self.screen())

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
        self.dictation_overlay.close()
        self._allow_close=True
        self.close()
