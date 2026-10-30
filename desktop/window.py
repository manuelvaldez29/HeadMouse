"""Ventana desktop: presentación, formularios y comandos; sin inferencia ni acciones SO."""
import json
import time
from desktop.lifecycle import release_overlays
from copy import deepcopy
from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import QShortcut, QKeySequence, QCursor
from PySide6.QtWidgets import (QMainWindow, QWidget, QFrame, QVBoxLayout, QHBoxLayout,
    QGridLayout, QPushButton, QStackedWidget, QScrollArea, QComboBox, QInputDialog,
    QMessageBox, QFormLayout, QDoubleSpinBox, QSpinBox, QCheckBox, QProgressBar,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QApplication, QLineEdit, QTabWidget)
from action_mapping import ACTIONS, DEFAULT_MAPPING
from gaze_source import SOURCE_LABELS as EYE_SOURCE_LABELS, eye_coordinates
from desktop.widgets import (CameraPreview, ExperimentCanvas, CalibrationMeter, DictationOverlay, LineChart, MiniCameraWindow,
    GestureMeters, gesture_progress, CHART_SERIES, CHART_NEUTRAL, label, card)

GESTURE_LABELS = dict(LEFT_WINK="Guiño izquierdo", RIGHT_WINK="Guiño derecho", LEFT_BROW="Ceja izquierda",
                      RIGHT_BROW="Ceja derecha", BOTH_BROWS="Ambas cejas", MOUTH_OPEN="Boca abierta")
CALIBRATION_ORDER = ("LEFT_WINK","RIGHT_WINK","LEFT_BROW","RIGHT_BROW","MOUTH_OPEN","BOTH_BROWS")  # = GESTURE_SIGNALS
EVENT_GESTURE = dict(LEFT_CLICK="LEFT_WINK",RIGHT_CLICK="RIGHT_WINK",SCROLL_UP="LEFT_BROW",SCROLL_DOWN="RIGHT_BROW",
                     MOUTH_OPEN="MOUTH_OPEN",BOTH_BROWS="BOTH_BROWS")
SOURCE_LABELS = dict(GEOMETRIC="Geométrica",BLENDSHAPE="Blendshapes",HYBRID="Híbrida",GEOMETRIC_3D="Geométrica 3D")
GESTURE_ROWS = (("Ojos izq/der",("LEFT_WINK","RIGHT_WINK")),("Cejas izq/der",("LEFT_BROW","RIGHT_BROW")),
                ("Ambas cejas",("BOTH_BROWS",)),("Boca",("MOUTH_OPEN",)))


# Condiciones internas (ApplicationController.snapshot) → próximo paso en lenguaje simple.
# None = no es un bloqueo para el usuario (la cámara se enciende al iniciar; "falta
# confirmación" sólo significa que no está activado; la pausa la muestra el indicador).
CONDITION_STEPS = (
    ("Seleccioná un perfil", "Elegí un perfil en Perfiles para empezar."),
    ("Gestos pendientes de validar para este método; sólo movimiento", "Ojos: sólo movimiento hasta que valides los gestos en Calibración → Ojos."),
    ("Gestos pendientes de validar", "Falta calibrar y probar tus gestos: andá a Calibración."),
    ("Sin calibración para el método", "Ojos: falta calibrar el movimiento en Calibración → Ojos."),
    ("Calibración incompatible con la cámara", "La calibración de Ojos es de otra cámara o resolución: volvé a calibrar."),
    ("La calibración no identifica este equipo", "La calibración de Ojos es de otra computadora: volvé a calibrar."),
    ("Calibración incompatible o sin comprobación", "Ojos: hay que volver a calibrar y comprobar el movimiento."),
    ("Iris seleccionado no detectado", "No se ven tus ojos: acomodate frente a la cámara."),
    ("Terminá o cancelá la medición en curso", "Terminá o cancelá la medición en curso antes de activar."),
    ("Cámara no iniciada", None),
    ("Falta confirmación explícita", None),
    ("Control pausado", None),
)


def status_message(s,event=None):
    """(texto, es_error) para la línea de estado: error > aviso reciente > próximo paso."""
    if s.get("state")=="ERROR":
        return s.get("message",""),True
    if event:
        return event[0],event[2]
    if s.get("control_enabled"):
        if not s.get("paused") and s.get("dragging"):
            return "Click izquierdo sostenido: mové la nariz para arrastrar; abrí el ojo para soltar.",False
        return (("Levantá ambas cejas para empezar a mover el cursor." if s.get("paused") else
                 "Ambas cejas: pausar · F8 o el botón rojo: detener."),False)
    for condition in s.get("activation_conditions",[]):
        if condition.startswith("Iris") and not s.get("camera"):
            continue  # con la cámara apagada no se puede saber
        for prefix,text in CONDITION_STEPS:
            if condition.startswith(prefix):
                if text: return text,False
                break
        else:
            return condition,False  # una condición nueva se muestra tal cual
    if not s.get("profile"):
        return "Elegí un perfil en Perfiles para empezar.",False
    return "Listo para empezar: tocá «Iniciar HeadMouse» en Inicio.",False


class UIPreferences:
    """Preferencias de presentación de esta computadora (no del perfil): cambiarlas no
    reinicia el control. Se guardan con QSettings (en Windows, el registro del usuario)."""

    def __init__(self):
        from PySide6.QtCore import QSettings
        self._settings=QSettings("UNSTA","HeadMouse")

    def get(self,key,default):
        value=self._settings.value(key,default)
        return value.lower()=="true" if isinstance(value,str) else bool(value)

    def set(self,key,value):
        self._settings.setValue(key,bool(value))


def friendly_date(value):
    """'2026-10-11T23:48:20+00:00' → '11/10/2026 20:48' en la hora local."""
    from datetime import datetime
    try:
        moment=datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return "pendiente"
    if moment.tzinfo is not None:
        moment=moment.astimezone()
    return moment.strftime("%d/%m/%Y %H:%M")


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
                     LEFT_DRAG_START="Click sostenido",LEFT_DRAG_END="Soltar click",
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
        self.gaze_overlay = None
        self._gaze_preview = False
        self._vertical_preview=False
        self._history_key=None
        self._closing=False
        self._allow_close=False
        from app_paths import VERSION
        self.setWindowTitle(f"HeadMouse v{VERSION} — Tesis V0.2")
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
        nav.addWidget(button("Salir",self.exit_application))
        nav.addWidget(label(f"v{VERSION} · UNSTA 2026","Subtitle"))
        outer.addWidget(sidebar)
        content=QVBoxLayout()
        content.setContentsMargins(26,20,26,18)
        top=QHBoxLayout()
        top.setSpacing(14)
        self.control_status=label("●  DESACTIVADO","StatusOff",wrap=False)
        self.control_status.setAccessibleName("Estado del control")
        top.addWidget(self.control_status)
        # Un único mensaje: error > aviso reciente (8 s) > próximo paso. Ver status_message().
        self.banner=label("Preparando HeadMouse…","StatusMessage")
        self.banner.setAccessibleName("Mensaje de estado")
        top.addWidget(self.banner,1)
        self.activate_button=button("Activar control",self.activate,"Primary")
        top.addWidget(self.activate_button)
        top.addWidget(button("DETENER CONTROL · F8",self.stop_immediately,"Danger"))
        content.addLayout(top)
        content.addSpacing(8)
        # Lista completa de condiciones: tooltip de Activar control (no se muestra como renglón).
        self.activation_requirements=label("", "Subtitle")
        self.activation_requirements.hide()
        self._status_event=None   # (texto, vence, es_error)
        self._status_seen=None
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
            shortcut.activated.connect(self.stop_immediately)
        self.bridge.error.connect(self.show_error)
        signal=getattr(self.bridge,"snapshot_ready",None)
        if signal is not None:signal.connect(self.update_live_preview)
        self.bridge.closed.connect(self._closed)
        # Ventanas independientes, sin dueña: Windows esconde las ventanas con dueña
        # cuando se minimiza la principal, y estas tienen que verse sobre otras apps
        # (dictar en el navegador, guiarse con la zona quieta). Se cierran en _closed.
        self.dictation_overlay=DictationOverlay()
        self.mini_camera=MiniCameraWindow()
        # Sin dueño Qt no se destruyen solas: la ventana las lleva registradas y las
        # libera al cerrarse (y dispose_window), como pedía la corrección de ciclo de vida.
        self.owned_overlays=(self.dictation_overlay,self.mini_camera)
        self.ui_prefs=UIPreferences()
        mini=self.ui_prefs.get("mini_camera",True)  # predeterminado: visible
        for check in (self.mini_camera_check,self.mini_camera_settings_check):
            check.setChecked(mini)
            check.toggled.connect(self.set_mini_camera)
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
        self.update_live_preview()

    @Slot()
    def update_live_preview(self):
        s=self.bridge.snapshot()
        if not s or not hasattr(self,"calibration_tabs"):return
        key=(id(s),self.stack.currentIndex(),self.calibration_tabs.currentIndex(),
             self.ocular_content.currentIndex(),bool(self.gaze_overlay and self.gaze_overlay.isVisible()))
        if key==getattr(self,"_preview_key",None):return
        self._preview_key=key
        index=self.stack.currentIndex()
        preview=self.preview if index==0 else self.diagnostic_preview if index==3 else None
        if index==2:
            preview=self.eye_preview if self.calibration_tabs.currentIndex()==1 and self.ocular_content.currentIndex()==0 else self.calibration_preview
        if preview:
            camera=s
            if index==2 and self.calibration_tabs.currentIndex()==1:
                camera=dict(s,settings=dict(s["settings"],ui=dict(s["settings"]["ui"],show_landmarks=True,show_overlay=True)))
            preview.present(camera)
        if self.gaze_overlay and self.gaze_overlay.isVisible():self.gaze_overlay.present_camera(s)

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
        side.addWidget(label("¿Cómo querés controlar el mouse?","Subtitle"))
        self.home_method=QComboBox()
        self.home_method.addItem("Nariz","nose")
        self.home_method.addItem("Ojos","eyes")
        self.home_method.setAccessibleName("Método de control: Nariz u Ojos")
        self.home_method.activated.connect(lambda _index:self.select_public_method(self.home_method.currentData()))
        side.addWidget(self.home_method)
        self.home_action=button("Iniciar HeadMouse",self.home_primary,"Hero")
        side.addWidget(self.home_action)
        self.home_state=label("","HomeState")
        side.addWidget(self.home_state)
        self.home_hint=label("","Subtitle")
        side.addWidget(self.home_hint)
        self.mini_camera_check=QCheckBox("Mostrar mini cámara mientras controlo con la nariz")
        self.mini_camera_check.setToolTip("Una ventana chica abajo a la derecha con tu nariz, el centro y la zona quieta. "
                                          "No recibe clicks: los guiños hacen click en lo que está debajo.")
        side.addWidget(self.mini_camera_check)
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
            return "■  Detener HeadMouse","HeroStop",self.stop_immediately
        if s["state"]=="CAMERA_STARTING":
            return "Iniciando cámara…","Hero",None
        if not s.get("profiles") and not p:
            return "Crear mi perfil","Hero",self.new_profile
        if not p:
            return "Elegí un perfil","Hero",lambda:self.show_page(1)
        if s["settings"]["ui"]["tracking_method"]!="nose":
            if s["state"] in ("CALIBRATING","EYE_CALIBRATING","GAZE_CALIBRATING","VERTICAL_DIAGNOSTIC","JITTER"):
                return "Terminá la medición en curso","Hero",None
            if not s.get("tracking_calibrated"):
                return "Calibrar Ojos","Hero",self.open_eye_calibration
            return "▶  Iniciar HeadMouse","Hero",self.activate
        if p.get("status")=="draft":
            return "Calibrar mis gestos","Hero",self.start_calibration
        if not p.get("validation",{}).get("passed"):
            return "Validar mi calibración","Hero",lambda:self.command_page("validate_calibration",2)
        if s["state"] in ("CALIBRATING","EYE_CALIBRATING","GAZE_CALIBRATING","JITTER"):
            return "Terminá la medición en curso","Hero",None
        if not s.get("tracking_calibrated",True):
            if s["settings"]["ui"]["tracking_method"] == "eye_absolute":
                return "Calibrar nueve puntos", "Hero", self.start_absolute_calibration
            return "Calibrar tracking ocular","Hero",self.start_eye_tracking_calibration
        return "▶  Iniciar HeadMouse","Hero",self.activate

    def home_primary(self):
        _text,_style,action=self._home_step(self.snapshot)
        if action: action()

    def _present_home(self,s):
        self.home_method.blockSignals(True)
        self.home_method.setCurrentIndex(0 if s["settings"]["ui"]["tracking_method"]=="nose" else 1)
        self.home_method.blockSignals(False)
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
        elif s["state"]=="CAMERA_STARTING":
            state,hint="Iniciando",s["message"]+" · Detener/F8 cancela el inicio."
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
        if s["settings"]["ui"]["tracking_method"]!="nose":
            if s["control_enabled"]:
                state="Ojos · EN PAUSA" if s["paused"] else "Ojos · ACTIVO"
                hint="F8 o Detener control para salir. "
            elif not s.get("tracking_calibrated"):
                state,hint="Ojos: movimiento pendiente o incompatible","Calibración → Ojos: revisá el movimiento de la fuente seleccionada. "
            elif s.get("activation_blockers"):
                state,hint="Ojos: requisitos pendientes"," · ".join(s["activation_blockers"])+". "
            else:
                state,hint="Ojos: listo para confirmar","Pulsá Iniciar HeadMouse o Activar control y confirmá Sí. "
            self.home_state.setText(state)
            self.home_hint.setText(hint+("Sólo se ejecutan los gestos habilitados y validados." if s.get("actions_ready") else "Sólo movimiento; clics y acciones faciales deshabilitados."))

    def select_public_method(self,method):
        latest=self.bridge.snapshot() or self.snapshot
        if not latest.get("profile"):
            return self.show_error("Primero elegí tu perfil personal")
        self.bridge.request("select_control_method",method=method)

    def open_eye_calibration(self):
        self.show_page(2)
        if self.calibration_tabs.currentIndex()!=1:self.calibration_tabs.setCurrentIndex(1)
        elif not self.snapshot.get("settings",{}).get("ui",{}).get("unified_eyes"):
            self.select_public_method("eyes")

    def _profiles(self):
        """Una tarjeta por perfil: nombre, estado de Nariz y Ojos, fecha y sus acciones."""
        layout=self.page("Perfiles","Cada persona tiene su propia calibración. Cambiar de perfil detiene el control.")
        top=QHBoxLayout()
        top.addWidget(label("Elegí quién va a usar HeadMouse en esta computadora.","Subtitle"),1)
        top.addWidget(button("+  Nuevo perfil",self.new_profile,"Primary"))
        layout.addLayout(top)
        scroll=QScrollArea()
        scroll.setWidgetResizable(True)
        body=QWidget()
        self.profile_cards=QVBoxLayout(body)
        self.profile_cards.setContentsMargins(0,4,12,4)
        self.profile_cards.setSpacing(12)
        self.profile_cards.addStretch()
        scroll.setWidget(body)
        layout.addWidget(scroll,1)
        layout.addWidget(label("Renombrar cambia el nombre visible y conserva la identidad de tus resultados. "
                               "Eliminar un perfil no borra las sesiones ni los experimentos históricos.","Subtitle"))

    def _render_profile_cards(self,s):
        while self.profile_cards.count()>1:  # el último ítem es el stretch
            widget=self.profile_cards.takeAt(0).widget()
            if widget: widget.deleteLater()
        current=(s.get("profile") or {}).get("user_id")
        entries=s.get("profiles",[])
        if not entries:
            empty=QFrame()
            empty.setObjectName("ProfileCard")
            box=QVBoxLayout(empty)
            box.setContentsMargins(20,18,20,18)
            box.addWidget(label("Todavía no hay perfiles","ProfileName"))
            box.addWidget(label("Creá uno con «Nuevo perfil». Después calibrás tus gestos en unos minutos.","Subtitle"))
            self.profile_cards.insertWidget(0,empty)
            return
        for index,entry in enumerate(sorted(entries,key=lambda e:(e["user_id"]!=current,e["display_name"].lower()))):
            self.profile_cards.insertWidget(index,self._profile_card(entry,entry["user_id"]==current))

    def _profile_card(self,entry,in_use):
        card=QFrame()
        card.setObjectName("ProfileCardActive" if in_use else "ProfileCard")
        row=QHBoxLayout(card)
        row.setContentsMargins(20,16,20,16)
        row.setSpacing(16)
        info=QVBoxLayout()
        info.setSpacing(4)
        name=entry["display_name"]
        info.addWidget(label(("●  " if in_use else "")+name,"ProfileName"))
        if entry.get("error"):
            info.addWidget(label("No se pudo leer este perfil: "+entry["error"],"ProfileError"))
        else:
            info.addWidget(label(f"Nariz: {entry['status']}   ·   Ojos: {entry.get('eyes','—')}"))
            info.addWidget(label("Última calibración: "+friendly_date(entry.get("calibrated_at")),"Subtitle"))
        row.addLayout(info,1)
        actions=QHBoxLayout()
        actions.setSpacing(8)
        if in_use:
            actions.addWidget(label("En uso","ProfileInUse"))
            calibrate=button("Calibrar",lambda:self.show_page(2))
            calibrate.setAccessibleName(f"Calibrar el perfil {name}")
            actions.addWidget(calibrate)
            rename=button("Renombrar",self.rename_profile)
            rename.setAccessibleName(f"Renombrar el perfil {name}")
            actions.addWidget(rename)
            delete=button("Eliminar",self.delete_profile)
            delete.setAccessibleName(f"Eliminar el perfil {name}")
            actions.addWidget(delete)
        elif not entry.get("error"):
            use=button("Usar este perfil",lambda checked=False,user_id=entry["user_id"]:self.use_profile(user_id),"Primary")
            use.setAccessibleName(f"Usar el perfil {name}")
            actions.addWidget(use)
        row.addLayout(actions)
        return card

    def use_profile(self,user_id):
        self.bridge.request("select_profile",user_id=user_id)

    def new_profile(self):
        name,ok=QInputDialog.getText(self,"Nuevo perfil","¿Cómo querés llamar a este perfil?")
        if ok:
            self.bridge.request("create_profile",name=name)
            self.show_page(1)

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
        """Una lista de gestos con su estado, vista previa y botón principal en una misma pantalla."""
        page_widget=QWidget()
        page=QVBoxLayout(page_widget)
        page.setContentsMargins(0,2,0,0)
        page.setSpacing(4)
        header=QHBoxLayout()
        header.setContentsMargins(0,0,0,0)
        header.setSpacing(14)
        header.addWidget(label("Calibración","Title",wrap=False))
        header.addWidget(label("Nariz conserva su calibración original. Ojos reúne movimiento, gestos y diagnóstico.","Subtitle"),1)
        page.addLayout(header)
        self.stack.addWidget(page_widget)
        self.calibration_tabs=QTabWidget()
        self.nose_calibration_tab=QWidget()
        self.eyes_calibration_tab=QWidget()
        self.nose_calibration_layout=QVBoxLayout(self.nose_calibration_tab)
        self.nose_calibration_layout.setContentsMargins(0,4,0,0)
        self.nose_calibration_layout.setSpacing(4)
        self.eyes_calibration_layout=QVBoxLayout(self.eyes_calibration_tab)
        self.eyes_calibration_layout.setContentsMargins(0,4,0,0)
        self.eyes_calibration_layout.setSpacing(4)
        self.calibration_tabs.addTab(self.nose_calibration_tab,"Nariz")
        self.calibration_tabs.addTab(self.eyes_calibration_tab,"Ojos")
        page.addWidget(self.calibration_tabs,1)
        # Con desplazamiento sólo al abrir "Más opciones"; la vista normal entra en una sola pantalla.
        scroll=QScrollArea()
        scroll.setWidgetResizable(True)
        body=QWidget()
        outer=QVBoxLayout(body)
        outer.setContentsMargins(0,2,8,2)
        outer.setSpacing(6)
        scroll.setWidget(body)
        self.gesture_calibration_scroll=scroll
        self.nose_calibration_layout.addWidget(scroll,1)
        self.wizard_instruction=label("Elegí un perfil y comenzá cuando estés cómodo.","CalibrationInstruction")
        outer.addWidget(self.wizard_instruction)
        status_row=QHBoxLayout()
        status_row.setContentsMargins(0,0,0,0)
        status_row.setSpacing(12)
        self.wizard_status=label("Sin iniciar","Subtitle")
        status_row.addWidget(self.wizard_status,3)
        self.wizard_progress=QProgressBar()
        self.wizard_progress.setRange(0,100)
        self.wizard_progress.setMinimumHeight(18)
        self.wizard_progress.setMaximumHeight(20)
        status_row.addWidget(self.wizard_progress,2)
        outer.addLayout(status_row)
        live=QHBoxLayout()
        live.setSpacing(12)
        steps=QFrame()
        steps.setObjectName("Card")
        steps.setFixedWidth(255)
        steps_layout=QVBoxLayout(steps)
        steps_layout.setContentsMargins(12,8,12,8)
        steps_layout.setSpacing(4)
        self.calibration_steps_title=label("Gestos","Subtitle")
        steps_layout.addWidget(self.calibration_steps_title)
        self.calibration_steps=label("")
        self.calibration_steps.setTextFormat(Qt.TextFormat.RichText)
        steps_layout.addWidget(self.calibration_steps)
        steps_layout.addStretch()
        live.addWidget(steps)
        self.calibration_preview=CameraPreview("Cámara apagada\n\nSe enciende al comenzar la calibración")
        self.calibration_preview.setMinimumSize(280,175)
        live.addWidget(self.calibration_preview,3)
        readings=QVBoxLayout()
        readings.setSpacing(4)
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
        actions.setSpacing(10)
        self.calibration_primary=button("Comenzar calibración",self.calibration_primary_action,"CalibrationHero")
        actions.addWidget(self.calibration_primary,3)
        self.save_calibration_button=button("Guardar perfil",lambda:self.bridge.request("save_calibration"),"CalibrationHero")
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
        self._build_ocular_calibration()
        self.calibration_tabs.currentChanged.connect(self.calibration_tab_changed)

    def _build_ocular_calibration(self):
        self.ocular_back=button("Volver a movimiento ocular",lambda:self.ocular_content.setCurrentIndex(0))
        self.eyes_calibration_layout.addWidget(self.ocular_back)
        self.ocular_back.hide()
        self.ocular_content=QStackedWidget()
        self.ocular_content.currentChanged.connect(lambda index:self.ocular_back.setVisible(index==1))
        self.eyes_calibration_layout.addWidget(self.ocular_content,1)
        movement=QWidget();body=QVBoxLayout(movement)
        self.ocular_source_combo=QComboBox()
        for source,title in EYE_SOURCE_LABELS.items():self.ocular_source_combo.addItem(title,source)
        self.ocular_source_combo.activated.connect(lambda _index:self.bridge.request("select_eye_source",source=self.ocular_source_combo.currentData()))
        body.addWidget(label("Fuente ocular"));body.addWidget(self.ocular_source_combo)
        self.ocular_readiness=label("Seleccioná tu perfil y prepará el movimiento.","Subtitle")
        body.addWidget(self.ocular_readiness)
        self.eye_preview=CameraPreview("La cámara se abre al iniciar la calibración ocular")
        live=QHBoxLayout();live.addWidget(self.eye_preview,1)
        controls=QWidget();row=QVBoxLayout(controls)
        row.addWidget(button("Calibrar movimiento",self.start_public_ocular_movement,"Primary"))
        row.addWidget(button("Calibrar gestos",self.start_ocular_gestures))
        row.addWidget(button("Probar movimiento · seguro",self.preview_public_eyes))
        center=QHBoxLayout()
        self.eye_start=button("Capturar centro",self.start_eye_tracking_calibration)
        self.eye_save=button("Guardar centro",lambda:self.bridge.request("save_eye_calibration"),"Primary")
        self.eye_save.setEnabled(False)
        center.addWidget(self.eye_start);center.addWidget(self.eye_save)
        row.addLayout(center)
        row.addWidget(button("Cancelar captura",lambda:self.bridge.request("cancel_eye_calibration")))
        self.eye_status=label("Centro ocular: sin capturar","Subtitle")
        self.eye_progress=QProgressBar();self.eye_progress.setRange(0,100)
        row.addWidget(self.eye_status);row.addWidget(self.eye_progress)
        row.addWidget(button("Diagnóstico vertical",self.start_vertical_diagnostic))
        row.addStretch()
        controls_scroll=QScrollArea();controls_scroll.setWidgetResizable(True);controls_scroll.setWidget(controls)
        controls_scroll.setMinimumWidth(300)
        live.addWidget(controls_scroll,1);body.addLayout(live,1)
        self.ocular_content.addWidget(movement)
        gestures=QWidget();self.ocular_gesture_layout=QVBoxLayout(gestures)
        self.ocular_gesture_layout.setContentsMargins(0,2,0,0)
        self.ocular_gesture_layout.setSpacing(4)
        self.ocular_content.addWidget(gestures)

    def calibration_tab_changed(self,index):
        target=self.nose_calibration_layout if index==0 else self.ocular_gesture_layout
        target.addWidget(self.gesture_calibration_scroll,1)
        self.gesture_calibration_scroll.show()
        self.select_public_method("nose" if index==0 else "eyes")

    def start_public_ocular_movement(self):
        self.select_public_method("eyes")
        latest=self.bridge.snapshot() or self.snapshot
        method=latest.get("settings",{}).get("ui",{}).get("ocular_engine","eye_absolute")
        if not latest.get("settings",{}).get("ui",{}).get("unified_eyes"):
            old=latest.get("settings",{}).get("ui",{}).get("tracking_method")
            if old in ("eye","eye_absolute"):method=old
        self.start_absolute_calibration(relative=method=="eye")

    def preview_public_eyes(self):
        if self.snapshot.get("settings",{}).get("ui",{}).get("tracking_method")=="eye_absolute":self.preview_absolute()
        else:self.command_page("start_diagnostic",2)

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
        """Arriba lo que el usuario necesita saber; los números técnicos, plegados."""
        page=self.page("Diagnóstico","Probá la cámara y tus gestos sin mover el mouse de la computadora.")
        scroll=QScrollArea()
        scroll.setWidgetResizable(True)
        body=QWidget()
        layout=QVBoxLayout(body)
        layout.setContentsMargins(0,0,12,0)
        layout.setSpacing(12)
        scroll.setWidget(body)
        page.addWidget(scroll,1)
        row=QHBoxLayout()
        row.addWidget(button("Iniciar diagnóstico",lambda:self.bridge.request("start_diagnostic"),"Primary"),2)
        row.addWidget(button("Medir estabilidad · 10 s",lambda:self.bridge.request("start_jitter")),1)
        self.vertical_diagnostic_button=button("Diagnóstico vertical de Ojos",self.start_vertical_diagnostic)
        row.addWidget(self.vertical_diagnostic_button,1)
        layout.addLayout(row)
        live=QHBoxLayout()
        live.setSpacing(14)
        self.diagnostic_preview=CameraPreview("Cámara apagada\n\nTocá «Iniciar diagnóstico»")
        self.diagnostic_preview.setMinimumHeight(330)
        live.addWidget(self.diagnostic_preview,3)
        side=QFrame()
        side.setObjectName("Card")
        side.setMinimumWidth(420)
        panel=QVBoxLayout(side)
        panel.setContentsMargins(18,14,18,14)
        panel.setSpacing(8)
        self.diag_face=label("Cámara apagada","DiagState")
        panel.addWidget(self.diag_face)
        self.diag_cursor=label("","Subtitle")
        panel.addWidget(self.diag_cursor)
        panel.addWidget(label("Gestos · la marca amarilla es donde se activa","ChartTitle"))
        self.gesture_meters=GestureMeters()
        panel.addWidget(self.gesture_meters)
        self.diag_last=label("Último gesto: —","Subtitle")
        panel.addWidget(self.diag_last)
        self.jitter_summary=label("Estabilidad: sin medición","Subtitle")
        panel.addWidget(self.jitter_summary)
        panel.addStretch()
        live.addWidget(side,2)
        layout.addLayout(live)
        # ── Detalles técnicos (plegados): el texto completo de siempre ──
        self.diagnostic_details_toggle=QCheckBox("Mostrar detalles técnicos (coordenadas, umbrales, cámara y ojos)")
        layout.addWidget(self.diagnostic_details_toggle)
        details=QWidget()
        inner=QVBoxLayout(details)
        inner.setContentsMargins(0,0,0,0)
        self.diagnostic_values=label("Abrí el diagnóstico para consultar las mediciones.","Subtitle")
        inner.addWidget(self.diagnostic_values)
        self.eye_diagnostic=label("","Subtitle")
        inner.addWidget(self.eye_diagnostic)
        inner.addWidget(label("Calibración avanzada por gesto","ChartTitle"))
        self.advanced_diagnostic=label("Sin calibración adaptativa disponible.","Subtitle")
        inner.addWidget(self.advanced_diagnostic)
        details.hide()
        self.diagnostic_details_toggle.toggled.connect(details.setVisible)
        layout.addWidget(details)
        layout.addStretch()

    def set_mini_camera(self,visible):
        """Una sola preferencia, dos casillas (Inicio y Configuración) sincronizadas."""
        self.ui_prefs.set("mini_camera",visible)
        for check in (self.mini_camera_check,self.mini_camera_settings_check):
            check.blockSignals(True)
            check.setChecked(visible)
            check.blockSignals(False)
        if self.snapshot: self._present_mini_camera(self.snapshot)

    def _present_mini_camera(self,s):
        wanted=(s.get("control_enabled") and s["settings"]["ui"]["tracking_method"]=="nose"
                and self.mini_camera_check.isChecked())
        if wanted:
            self.mini_camera.present(s,self.screen())
        elif self.mini_camera.isVisible():
            self.mini_camera.hide()

    def _present_diagnostic(self,s):
        """Estado en lenguaje simple: rostro, hacia dónde iría el cursor y cada gesto."""
        from gesture_signals import GESTURE_SIGNALS
        d=s.get("diagnostic") or {}
        method=s["settings"]["ui"]["tracking_method"]
        self.vertical_diagnostic_button.setVisible(method!="nose")
        if not s.get("camera"):
            face,face_style="Cámara apagada","DiagState"
        elif s.get("detected"):
            face,face_style=f"✓  Te veo la cara  ·  {s['fps']:.0f} FPS","DiagStateOk"
        else:
            face,face_style="✗  No te veo la cara: acomodate frente a la cámara o mejorá la luz","DiagStateBad"
        self.diag_face.setText(face)
        if self.diag_face.objectName()!=face_style:
            self.diag_face.setObjectName(face_style)
            self.diag_face.style().unpolish(self.diag_face)
            self.diag_face.style().polish(self.diag_face)
        if not d or not s.get("detected"):
            cursor=""
        elif method!="nose":
            cursor="Cursor con los ojos: el detalle está en «Mostrar detalles técnicos»."
        else:
            dz=s["settings"]["gesture"]["dead_zone"]
            dx,dy=d.get("normalized_dx",0),d.get("normalized_dy",0)
            parts=[("→ derecha" if dx>0 else "← izquierda") if abs(dx)>dz else "",
                   ("↓ abajo" if dy>0 else "↑ arriba") if abs(dy)>dz else ""]
            moving=" y ".join(x for x in parts if x)
            cursor=(f"Cursor: se movería {moving}" if moving else
                    "Cursor: quieto, tu nariz está dentro de la zona quieta")
            if not d.get("head_still",True) and moving:
                cursor+="  ·  cejas en pausa mientras se mueve"
        self.diag_cursor.setText(cursor)
        rows=[]
        calibrations,gates=d.get("gesture_calibrations",{}),d.get("gates",{})
        for key in CALIBRATION_ORDER:
            gate=gates.get(key)
            available=bool(gate and gate.get("enabled",True))
            value=gesture_progress(d.get("signals",{}).get(key),calibrations.get(key),gate,
                                   GESTURE_SIGNALS[key].directions) if available else None
            rows.append((GESTURE_LABELS[key],value,bool(d.get("active",{}).get(key)),available or not d))
        self.gesture_meters.present(rows)
        gesture,action=s.get("gesture","—"),s.get("action","—")
        self.diag_last.setText("Último gesto: —" if gesture in (None,"—") else
                               f"Último gesto: {GESTURE_LABELS.get(gesture,gesture)}  →  "
                               f"{ACTION_LABELS.get(action,action)} (sin ejecutar)")

    def _settings(self):
        """Pestañas: lo que un usuario cambia en Básico; lo técnico separado por tema.

        Antes era una sola lista de ~40 controles (cámara técnica, ojos, tiempos,
        voz, modelos). Los nombres internos de los campos no cambian.
        """
        layout=self.page("Configuración","Los cambios se guardan en el perfil seleccionado. Guardar detiene el control y la cámara.")
        self.settings_tabs=QTabWidget()
        self.settings_tabs.setDocumentMode(True)
        self.settings_tabs.tabBar().setDrawBase(False)
        layout.addWidget(self.settings_tabs,1)
        self.fields={}
        self.settings_tab_index={}

        def tab(title,intro):
            scroll=QScrollArea()
            scroll.setWidgetResizable(True)
            body=QWidget()
            form=QFormLayout(body)
            form.setVerticalSpacing(14)
            form.setContentsMargins(4,14,12,8)
            form.addRow(label(intro,"Subtitle"))
            scroll.setWidget(body)
            self.settings_tab_index[title]=self.settings_tabs.addTab(scroll,title)
            return form,scroll

        def number(form,key,title,lo,hi,decimals,hint=None):
            field=QSpinBox() if decimals==0 else QDoubleSpinBox()
            field.setRange(lo,hi)
            if decimals: field.setDecimals(decimals); field.setSingleStep(.01 if hi<=1 else 1)
            field.setAccessibleName(title)
            if hint: field.setToolTip(hint)
            form.addRow(title,field)
            self.fields[key]=field

        def section(form,title):
            form.addRow(label(title,"SettingsSection"))

        # ── Básico ──
        form,_=tab("Básico","Lo que vas a querer ajustar. Lo demás está en las otras pestañas.")
        self.startup_settings_layout=form
        section(form,"Control")
        self.tracking_combo=QComboBox()
        self.tracking_combo.addItem("Nariz","nose")
        self.tracking_combo.addItem("Ojos","eyes")
        self.tracking_combo.setAccessibleName("Método de tracking")
        form.addRow("Mover el cursor con",self.tracking_combo)
        self.tracking_combo.activated.connect(lambda _index:self.select_public_method(self.tracking_combo.currentData()))
        number(form,"vision.camera_index","Cámara (0 = la integrada)",0,100,0)
        section(form,"Cursor con la nariz")
        number(form,"gesture.sensitivity_x","Velocidad horizontal",0,1000,1,"Más alto: el cursor se mueve más rápido hacia los costados")
        number(form,"gesture.sensitivity_y","Velocidad vertical",0,1000,1,"Más alto: el cursor se mueve más rápido hacia arriba y abajo")
        number(form,"gesture.dead_zone","Zona quieta alrededor del centro",0,.49,3,
               "Cuánto podés mover la cabeza sin que se mueva el cursor")
        number(form,"gesture.smoothing_alpha","Suavizado (0 directo · 0,95 muy suave)",0,.95,2)
        section(form,"Dictado por voz")
        self.voice_check=QCheckBox("Al hacer click en un campo de texto, escuchar y escribir")
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
        form.addRow(label("Comandos: «borrar», «borrar N palabras», «borrar N letras», «borrar todo», «deshacer». "
                          "Decí solo el comando. La lista completa está en Gestos y acciones.","Subtitle"))
        section(form,"Vista de cámara")
        self.overlay_check=QCheckBox("Mostrar punto de tracking, centro, zona quieta y dirección")
        self.landmarks_check=QCheckBox("Mostrar puntos de la cara")
        form.addRow(self.overlay_check)
        form.addRow(self.landmarks_check)
        self.mini_camera_settings_check=QCheckBox("Mini cámara al controlar con la nariz (se aplica al instante)")
        form.addRow(self.mini_camera_settings_check)

        # ── Gestos y scroll ──
        form,_=tab("Gestos y scroll","Cuánto hay que sostener cada gesto y cuánto esperar antes de repetirlo. "
                                     "Cambiarlos invalida la prueba de gestos del método editado.")
        section(form,"Tiempos de los gestos")
        for group,title in (("blink","Guiños"),("brow","Cejas"),("both_brows","Ambas cejas"),("mouth","Boca")):
            number(form,f"gesture.{group}_hold_ms",f"{title}: sostener · ms",0,5000,0)
            number(form,f"gesture.{group}_cooldown_ms",f"{title}: espera · ms",0,10000,0)
        number(form,"gesture.brow_decision_ms","Cejas: tiempo para distinguir una de ambas · ms",0,1000,0)
        section(form,"Click sostenido y arrastre")
        self.hold_click_check=QCheckBox("Mantener apretado el click izquierdo al sostener el guiño (modo Nariz)")
        self.hold_click_check.setAccessibleName("Click izquierdo sostenido al mantener guiño")
        form.addRow(self.hold_click_check)
        number(form,"control.drag_hold_ms","Guiño sostenido para empezar a arrastrar · ms",100,3000,0,
               "Un guiño más corto hace click normal al abrir el ojo; uno más largo mantiene presionado el botón mientras movés la nariz")
        section(form,"Scroll")
        number(form,"control.scroll_lines","Muescas de rueda por gesto",1,100,0)
        number(form,"gesture.brow_repeat_delay_ms","Ceja sostenida: esperar antes de repetir · ms",0,5000,0)
        number(form,"gesture.brow_repeat_ms","Ceja sostenida: repetir cada · ms (0 = apagado)",0,5000,0)
        section(form,"Seguridad")
        number(form,"control.face_timeout_s","Pausar si no se ve la cara durante · s",.1,60,1)

        # ── Ojos ──
        form,eyes_scroll=tab("Ojos","Opciones del control con los ojos (experimental). La calibración y los gestos "
                                    "están en Calibración → Ojos.")
        self.settings_scroll=eyes_scroll
        self.eye_unused_note=label("Ahora el cursor se mueve con la nariz: estas opciones se usan cuando elegís "
                                   "«Ojos» en la pestaña Básico.","SettingsNote")
        form.addRow(self.eye_unused_note)
        self.eye_source_label=label("Ojo que se sigue")
        self.eye_source_combo=QComboBox()
        for source,title in EYE_SOURCE_LABELS.items():
            self.eye_source_combo.addItem(title,source)
        self.eye_source_combo.setAccessibleName("Fuente ocular: ambos ojos, izquierdo o derecho")
        form.addRow(self.eye_source_label,self.eye_source_combo)
        self.eye_source_hint=label("Podés mantener ambos ojos abiertos. Izquierdo y derecho son tus lados. "
                                   "Las marcas I/D del preview permiten verificarlos. Guardá antes de calibrar.","Subtitle")
        form.addRow(self.eye_source_hint)
        self.eye_warning=label("La respuesta guardada se mantiene; no se cambia automáticamente de algoritmo.","Subtitle")
        form.addRow(self.eye_warning)
        section(form,"Movimiento por dirección (joystick)")
        number(form,"eye.sensitivity","Sensibilidad",0,100,1)
        number(form,"eye.acceleration","Aceleración",0,100,1)
        number(form,"eye.dead_zone","Zona quieta (fracción del rango)",0,.8,3)
        number(form,"eye.smoothing_alpha","Suavizado",0,.95,2)
        number(form,"eye.max_delta","Movimiento máximo por detección · px",1,60,1)
        self.eye_axis_zones=QCheckBox("Definir zona quieta horizontal y vertical por separado")
        self.eye_dead_zone_x=QDoubleSpinBox();self.eye_dead_zone_y=QDoubleSpinBox()
        for widget in (self.eye_dead_zone_x,self.eye_dead_zone_y):widget.setRange(0,.8);widget.setDecimals(3);widget.setSingleStep(.01)
        self.eye_axis_zones.toggled.connect(lambda value:[w.setEnabled(value) for w in (self.eye_dead_zone_x,self.eye_dead_zone_y)])
        form.addRow(self.eye_axis_zones)
        form.addRow("Zona quieta horizontal",self.eye_dead_zone_x)
        form.addRow("Zona quieta vertical",self.eye_dead_zone_y)
        self.eye_vertical_reference=QComboBox()
        self.eye_vertical_reference.addItem("Párpados · referencia original","eyelids")
        self.eye_vertical_reference.addItem("Comisuras · prueba vertical; requiere calibrar rangos","canthi")
        self.eye_vertical_reference.setAccessibleName("Referencia vertical del joystick ocular")
        form.addRow("Referencia vertical",self.eye_vertical_reference)
        section(form,"Movimiento por posición en pantalla")
        number(form,"absolute.smoothing_alpha","Suavizado",0,.95,2)
        number(form,"absolute.max_step_px","Paso máximo · px",1,100,1)
        number(form,"absolute.jitter_px","Tolerancia de vibración · px",0,30,1)
        self.ocular_upgrade=button("Preparar seguimiento por zonas de pantalla",self.confirm_ocular_upgrade)
        form.addRow(self.ocular_upgrade)
        form.addRow(label("Usa sólo la pantalla principal, aunque haya otros monitores. Cambiar pantalla, DPI o cámara "
                          "requiere recalibrar. Las acciones pertenecen a la modalidad guardada.","Subtitle"))
        self.tracking_combo.currentIndexChanged.connect(self._show_eye_source)

        # ── Cámara ──
        form,_=tab("Cámara","Ajustes técnicos de captura. Cambialos sólo si la cámara no arranca o va lenta.")
        self.capture_backend_combo=QComboBox()
        for title,value in (("DirectShow · Webcams USB en Windows","dshow"),
                            ("Automático · OpenCV", "auto"),("Media Foundation · Windows", "msmf")):
            self.capture_backend_combo.addItem(title,value)
        self.capture_backend_combo.setAccessibleName("Backend de captura de cámara")
        form.addRow("Backend de cámara",self.capture_backend_combo)
        number(form,"vision.frame_width","Ancho solicitado · 0 automático",0,8192,0)
        number(form,"vision.frame_height","Alto solicitado · 0 automático",0,8192,0)
        number(form,"vision.target_fps","FPS solicitados",1,240,0)
        number(form,"vision.startup_timeout_s","Espera inicial máxima · s",.1,120,1)
        number(form,"vision.shutdown_timeout_s","Espera de cierre por intento · s",.05,30,2)
        form.addRow(button("Preparar captura USB · DirectShow · 640 × 480 · 15 FPS",self.usb_camera_preset))
        form.addRow(label("El preset se aplica al guardar y detiene la cámara. Una resolución nueva puede exigir "
                          "recalibrar el tracking ocular.","Subtitle"))

        # ── Modelos ──
        form,_=tab("Modelos","Archivos que se descargan una sola vez. Después HeadMouse funciona sin Internet.")
        self.prepare_model_button=button("Preparar modelo facial (requiere Internet una vez)",self.prepare_model)
        self.prepare_voice_button=button("Preparar modelo de voz (requiere Internet una vez)",self.prepare_voice_model)
        form.addRow(self.prepare_model_button)
        form.addRow(self.prepare_voice_button)

        self._show_eye_source()
        row=QHBoxLayout()
        row.addWidget(button("Restaurar valores predeterminados",self.restore_defaults))
        row.addWidget(button("Guardar configuración",self.save_settings,"Primary"))
        layout.addLayout(row)

    def start_eye_tracking_calibration(self):
        self.open_eye_calibration()
        self.select_public_method("eyes")
        self.ocular_content.setCurrentIndex(0)
        self.bridge.request("start_eye_calibration")

    def confirm_ocular_upgrade(self):
        text=("Se conservarán las calibraciones anteriores. Ojos pasará a requerir aprendizaje y comprobación "
              "de posición en pantalla antes de controlar el cursor. No se cambiará de respuesta durante el uso. ¿Continuar?")
        if QMessageBox.question(self,"Actualizar respuesta de Ojos",text,
            QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:
            self.bridge.request("upgrade_ocular_response",confirmed=True)

    def start_ocular_gestures(self):
        self.open_eye_calibration()
        self.select_public_method("eyes")
        self.ocular_gesture_layout.addWidget(self.gesture_calibration_scroll,1)
        self.gesture_calibration_scroll.show()
        self.ocular_content.setCurrentIndex(1)
        self.calibration_options.hide()
        self.bridge.request("start_calibration")

    def start_vertical_diagnostic(self):
        self.bridge.stop()
        self._vertical_preview=True
        self._gaze_preview=False
        self._open_gaze_overlay()
        self.bridge.request("start_vertical_diagnostic")

    def _show_eye_source(self, index=None):
        visible=self.tracking_combo.currentData()!="nose"
        for widget in (self.eye_source_label,self.eye_source_combo,self.eye_source_hint,self.eye_warning):
            widget.setVisible(visible)
        if hasattr(self,"settings_tabs"):
            index=self.settings_tab_index["Ojos"]
            self.settings_tabs.setTabText(index,"Ojos" if visible else "Ojos · sin usar")
            self.settings_tabs.setTabToolTip(index,"" if visible else "Elegí «Ojos» en Básico para activar estas opciones")
            self.eye_unused_note.setVisible(not visible)
        engine=self.snapshot.get("settings",{}).get("ui",{}).get("tracking_method")
        for key,widget in self.fields.items():
            if key.startswith("eye."):widget.setEnabled(visible and engine=="eye")
            elif key.startswith("absolute."):widget.setEnabled(visible and engine=="eye_absolute")
        self.eye_vertical_reference.setEnabled(visible and engine=="eye")
        self.eye_axis_zones.setEnabled(visible and engine=="eye")
        for widget in (self.eye_dead_zone_x,self.eye_dead_zone_y):widget.setEnabled(visible and engine=="eye" and self.eye_axis_zones.isChecked())

    def screen_context(self):
        import os
        from screen_mapping import primary_context,windows_monitors
        screens = QApplication.screens()
        screen = QApplication.primaryScreen()
        rect, dpr = screen.geometry(), screen.devicePixelRatio()
        return primary_context(dict(rect=[rect.x(),rect.y(),rect.width(),rect.height()],dpr=dpr,
            screen=screen.name() or "primary",monitor_count=len(screens),primary=True),
            windows_monitors() if os.name=="nt" and QApplication.platformName()!="offscreen" else None)

    def _open_gaze_overlay(self):
        from desktop.gaze_overlay import GazeOverlay
        if self.gaze_overlay:
            self.gaze_overlay.blockSignals(True)
            self.gaze_overlay.close()
            self.gaze_overlay.deleteLater()
        overlay = self.gaze_overlay = GazeOverlay(self)
        overlay.cancel.connect(self.cancel_gaze_overlay)
        overlay.repeat.connect(lambda index:self.bridge.request("repeat_vertical_point" if self._vertical_preview else "repeat_gaze_point", index=index))
        overlay.geometry_failed.connect(self.show_error)
        overlay.viewport_measured.connect(lambda data:self.bridge.request("record_gaze_viewport", **data))
        overlay.export_attempt.connect(lambda:self.bridge.request("export_gaze_attempt"))
        overlay.review_training.connect(lambda:self.bridge.request("review_gaze_training"))
        overlay.save.connect(lambda:self.bridge.request("save_gaze_calibration"))
        overlay.setGeometry(QApplication.primaryScreen().geometry())
        overlay.winId()
        overlay.windowHandle().setScreen(QApplication.primaryScreen())
        overlay.showFullScreen()

    def start_absolute_calibration(self, checked=False, relative=False):
        self._vertical_preview=False
        try:
            context=self.screen_context()
        except ValueError as exc:
            return self.show_error(str(exc))
        self._gaze_preview = False
        self.bridge.stop()
        self._open_gaze_overlay()
        self.bridge.request("start_gaze_calibration", screen_context=context, relative=relative)

    def preview_absolute(self):
        self._vertical_preview=False
        if self.snapshot.get("settings", {}).get("ui", {}).get("tracking_method") != "eye_absolute":
            return self.show_error("Esta prueba requiere una calibración de posición ocular guardada y compatible")
        self._gaze_preview = True
        self.bridge.stop()
        self._open_gaze_overlay()
        self.bridge.request("start_diagnostic")

    def cancel_gaze_overlay(self):
        self.bridge.stop()
        self.bridge.request("cancel_vertical_diagnostic" if self._vertical_preview else "cancel_gaze_calibration")
        self._vertical_preview=False
        self._gaze_preview = False

    def stop_immediately(self):
        resident=getattr(self,"resident",None)
        if resident:resident.disarm()
        self.bridge.stop()
        self.bridge.request("stop_camera")
        self._gaze_preview=False
        self._vertical_preview=False
        if self.gaze_overlay and self.gaze_overlay.isVisible():
            self.gaze_overlay.blockSignals(True)
            self.gaze_overlay.close()
            self.gaze_overlay.blockSignals(False)

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
        settings["control"]["hold_click_enabled"]=self.hold_click_check.isChecked()
        public_method=self.tracking_combo.currentData()
        settings["ui"]["eye_source"]=self.eye_source_combo.currentData()
        settings["eye"]["vertical_reference"]=self.eye_vertical_reference.currentData()
        settings["eye"]["dead_zone_x"]=self.eye_dead_zone_x.value() if self.eye_axis_zones.isChecked() else None
        settings["eye"]["dead_zone_y"]=self.eye_dead_zone_y.value() if self.eye_axis_zones.isChecked() else None
        settings["vision"]["capture_backend"]=self.capture_backend_combo.currentData()
        settings["voice"]["enabled"]=self.voice_check.isChecked()
        settings["voice"]["model"]=self.voice_model.currentData()
        settings["voice"]["send_word"]=self.voice_send.currentText().strip().lower()
        self.bridge.request("save_public_settings",settings=settings,method=public_method)

    def usb_camera_preset(self):
        self.capture_backend_combo.setCurrentIndex(self.capture_backend_combo.findData("dshow"))
        for key,value in (("frame_width",640),("frame_height",480),("target_fps",15),("startup_timeout_s",20)):
            self.fields["vision."+key].setValue(value)
        self.show_error("Ajustes de captura USB preparados. Guardá para aplicarlos antes de abrir la cámara.")

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
        self.experiment_mode.addItem("Mouse convencional · Sin HeadMouse",("real","mouse"))
        row.addWidget(self.experiment_mode,1)
        row.addWidget(button("Comenzar serie",self.start_experiment,"Primary"))
        self.experiment_conditions = QLineEdit()
        self.experiment_conditions.setMaxLength(500)
        self.experiment_conditions.setPlaceholderText("Condiciones: webcam, luz, distancia (cm), sesión y fatiga previa 0–10")
        self.experiment_conditions.setAccessibleName("Condiciones experimentales registradas por el operador")
        layout.addWidget(self.experiment_conditions)
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
        self.bridge.request("start_experiment",mode=mode,source=source,
            conditions=dict(notes=self.experiment_conditions.text(), screen=self.screen_context()))
        self.canvas.setFocus()

    def experiment_input(self,x,y,click,absolute):
        self.bridge.request("experiment_input",x=x,y=y,click=click,absolute=absolute)

    def _metrics(self):
        """Tasas por minuto por sesión: comparables aunque las sesiones duren distinto."""
        page=self.page("Métricas","Cómo se usó HeadMouse en cada sesión con control activo. Todo queda en esta computadora.")
        filters=QHBoxLayout()
        self.metrics_scope=QComboBox()
        self.metrics_scope.addItem("Sesiones de este perfil","profile")
        self.metrics_scope.addItem("Sesiones de todos los perfiles","all")
        self.metrics_scope.setAccessibleName("Qué sesiones mostrar")
        self.metrics_scope.currentIndexChanged.connect(lambda _index:self._present_metrics(self.snapshot,force=True))
        filters.addWidget(self.metrics_scope)
        filters.addStretch()
        filters.addWidget(button("Actualizar",lambda:self.bridge.request("refresh_metrics")))
        page.addLayout(filters)
        scroll=QScrollArea()
        scroll.setWidgetResizable(True)
        body=QWidget()
        layout=QVBoxLayout(body)
        layout.setContentsMargins(0,4,12,4)
        layout.setSpacing(14)
        scroll.setWidget(body)
        page.addWidget(scroll,1)
        grid=QGridLayout()
        self.metric_labels={}
        for i,title in enumerate(("Sesiones con control","Tiempo de uso","Clicks por minuto","Pausas por minuto")):
            box,value=card(title)
            grid.addWidget(box,0,i)
            self.metric_labels[title]=value
        layout.addLayout(grid)
        charts=QHBoxLayout()
        charts.setSpacing(14)
        self.actions_chart,box=self._chart_card("Acciones por minuto en cada sesión",
                                               "Clicks, scrolls y pausas, divididos por la duración de la sesión · misma escala",
                                               facets=True)
        charts.addWidget(box,3)
        self.losses_chart,box=self._chart_card("Pérdidas de rostro por minuto",
                                              "Veces que la cámara dejó de ver la cara; menos es mejor")
        charts.addWidget(box,2)
        layout.addLayout(charts)
        self.metrics_note=label("","Subtitle")
        layout.addWidget(self.metrics_note)
        self.sessions=QTableWidget(0,8)
        self.sessions.setHorizontalHeaderLabels(["Fecha","Duración","Clicks","Scrolls","Pausas","Pérdidas de rostro","FPS","Dictados"])
        self.sessions.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.sessions.verticalHeader().hide()
        self.sessions.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.sessions.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.sessions.setAccessibleName("Historial de sesiones con control")
        self.sessions.setMinimumHeight(240)
        layout.addWidget(self.sessions)

    def _chart_card(self,title,subtitle,facets=False):
        box=QFrame()
        box.setObjectName("Card")
        inner=QVBoxLayout(box)
        inner.setContentsMargins(16,12,16,12)
        inner.addWidget(label(title,"ChartTitle"))
        inner.addWidget(label(subtitle,"Subtitle"))
        chart=LineChart(unit="/min",empty="Todavía no hay sesiones con control activo",facets=facets)
        chart.setAccessibleName(title)
        inner.addWidget(chart,1)
        return chart,box

    def _present_metrics(self,s,force=False):
        from metrics_summary import control_sessions, totals, duration_text, MIN_DURATION_S
        if not s: return
        scope=self.metrics_scope.currentData()
        profile=(s.get("profile") or {}).get("user_id") if scope=="profile" else None
        key=json.dumps([s.get("history",[]),profile],sort_keys=True,default=str)
        if key==self._history_key and not force: return
        self._history_key=key
        sessions=control_sessions(s.get("history",[]),profile)
        summary=totals(sessions)
        rate=lambda value:"—" if value is None else f"{value:.1f}".replace(".",",")
        for title,value in (("Sesiones con control",str(summary["sessions"])),
                            ("Tiempo de uso",duration_text(summary["minutes"]) if sessions else "—"),
                            ("Clicks por minuto",rate(summary["clicks_per_min"])),
                            ("Pausas por minuto",rate(summary["pauses_per_min"]))):
            self.metric_labels[title].setText(value)
        labels=[x["started"].strftime("%d/%m %H:%M") for x in sessions]
        self.actions_chart.set_data(labels,[
            dict(name="Clicks",color=CHART_SERIES[0],values=[x["clicks_per_min"] for x in sessions]),
            dict(name="Scrolls",color=CHART_SERIES[1],values=[x["scrolls_per_min"] for x in sessions]),
            dict(name="Pausas",color=CHART_SERIES[2],values=[x["pauses_per_min"] for x in sessions])] if sessions else [])
        self.losses_chart.set_data(labels,[dict(name="Pérdidas de rostro",color=CHART_NEUTRAL,
                                                values=[x["losses_per_min"] for x in sessions])] if sessions else [])
        skipped=len([r for r in s.get("history",[]) if not profile or r.get("profile_id")==profile])-len(sessions)
        self.metrics_note.setText(f"Se muestran las sesiones con control activo de al menos {MIN_DURATION_S} s. "
                                  f"{skipped} sesiones de vista previa, diagnóstico, calibración o muy cortas no entran en las tasas."
                                  if skipped else f"Se muestran las sesiones con control activo de al menos {MIN_DURATION_S} s.")
        self.sessions.setRowCount(len(sessions))
        for row,x in enumerate(reversed(sessions)):  # la más reciente arriba
            values=(x["started"].strftime("%d/%m/%Y %H:%M"),duration_text(x["minutes"]),x["clicks"],x["scrolls"],
                    x["pauses"],x["losses"],f"{x['fps']:.0f}",x["dictations"])
            for col,value in enumerate(values):
                item=QTableWidgetItem(str(value))
                if col: item.setTextAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter)
                self.sessions.setItem(row,col,item)

    def activate(self):
        if QMessageBox.question(self,"Activar control","HeadMouse comenzará a controlar el puntero del sistema.",
                                QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:
            self.bridge.activate(screen_context=self.screen_context())

    def show_error(self,message):
        # Mensaje en la línea de estado (sin diálogos repetidos durante errores de captura).
        self._status_event=(str(message),time.monotonic()+8,True)
        self._set_status_message(str(message),True)

    def _set_status_message(self,text,error):
        self.banner.setText(text)
        name="StatusError" if error else "StatusMessage"
        if self.banner.objectName()!=name:
            self.banner.setObjectName(name)
            self.banner.style().unpolish(self.banner)
            self.banner.style().polish(self.banner)

    def _present_status(self,s):
        enabled=s["control_enabled"]
        if enabled:
            if s["paused"]:
                state,name="EN PAUSA","StatusPaused"
            elif s.get("dragging"):
                state,name="ARRASTRANDO","StatusDrag"
            else:
                state,name="ACTIVO","StatusOn"
        else:
            state,name="DESACTIVADO","StatusOff"
        self.control_status.setText("●  "+state)
        if self.control_status.objectName()!=name:
            self.control_status.setObjectName(name)
            self.control_status.style().unpolish(self.control_status)
            self.control_status.style().polish(self.control_status)
        now=time.monotonic()
        if s["message"]!=self._status_seen:
            if self._status_seen is not None:  # el mensaje inicial no es una novedad
                self._status_event=(s["message"],now+8,s["state"]=="ERROR")
            self._status_seen=s["message"]
        event=self._status_event if self._status_event and now<self._status_event[1] else None
        text,error=status_message(s,event)
        self._set_status_message(text,error)

    def refresh(self):
        s=self.bridge.snapshot()
        if not s: return
        self.snapshot=s
        self._present_status(s)
        self._present_dictation(s.get("dictation"))
        self._present_models(s.get("models") or {})
        enabled=s["control_enabled"]
        p=s["profile"]
        if enabled and s["settings"]["ui"]["tracking_method"] == "eye_absolute":
            from screen_mapping import same_context, capture_host_id
            saved = (p or {}).get("absolute_calibration", {}).get("context", {})
            try:
                context=dict(self.screen_context(), capture_host=capture_host_id(), **(s.get("capture_context") or {}))
                compatible=same_context(saved,context)
            except ValueError:
                compatible=False
            if not compatible:
                reason="Cambió el equipo, pantalla, DPI o cámara: control detenido; revisá la calibración de Ojos"
                self.bridge.stop(reason=reason)
                self.show_error(reason)
        name=p.get("display_name",p["user_id"]) if p else "Sin perfil seleccionado"
        self.home_profile.setText(f"Hola, {name}" if p else "Bienvenido a HeadMouse")
        self._present_home(s)
        method_key=((p or {}).get("user_id"),s["settings"]["ui"]["tracking_method"]=="nose")
        if method_key!=getattr(self,"_calibration_method_key",None):
            self._calibration_method_key=method_key
            index=0 if method_key[1] else 1
            self.calibration_tabs.blockSignals(True);self.calibration_tabs.setCurrentIndex(index);self.calibration_tabs.blockSignals(False)
            target=self.nose_calibration_layout if index==0 else self.ocular_gesture_layout
            target.addWidget(self.gesture_calibration_scroll,1)
            self.gesture_calibration_scroll.show()
        self.ocular_source_combo.setCurrentIndex(self.ocular_source_combo.findData(s["settings"]["ui"]["eye_source"]))
        self.ocular_readiness.setText("Movimiento: "+("preparado" if s.get("tracking_calibrated") and not method_key[1] else "pendiente")+
            " · Gestos: "+("validados" if s.get("actions_ready") and not method_key[1] else "pendientes; clics deshabilitados")+
            "\nRespuesta guardada: "+s.get("ocular_response","posición en pantalla")+
            ". La calibración nunca cambia de respuesta automáticamente.")
        self.activation_requirements.setText(" · ".join(s.get("activation_conditions", [])))
        self.activate_button.setToolTip(self.activation_requirements.text())
        self.activate_button.setEnabled(bool(p and (s["settings"]["ui"]["tracking_method"]!="nose" or p.get("validation",{}).get("passed")) and not enabled
                                            and s.get("tracking_calibrated",True)
                                            and s["state"] not in ("CAMERA_STARTING","CALIBRATING","EYE_CALIBRATING","GAZE_CALIBRATING","VERTICAL_DIAGNOSTIC","JITTER")))
        eye_session=s.get("eye_calibration")
        self.eye_save.setEnabled(bool(eye_session and eye_session["can_save"] and s["state"]=="EYE_CALIBRATING"))
        self.eye_start.setEnabled(bool(p and s["state"]!="CALIBRATING" and s["settings"]["ui"]["tracking_method"]=="eye"))
        self.eye_start.setToolTip("El centro se captura automáticamente en Calibrar movimiento para la respuesta por posición.")
        self.ocular_upgrade.setVisible(s["settings"]["ui"]["tracking_method"]=="eye")
        self.eye_progress.setValue(int(100*eye_session["progress"]) if eye_session else 0)
        self.eye_status.setText(eye_session["message"] if eye_session else
                               "Neutral ocular guardado. Recalibrá si cambia la cámara o tu postura."
                               if (p or {}).get("tracking_calibration") else "Neutral ocular: falta calibrar")
        if not eye_session and s["settings"]["ui"]["tracking_method"]=="eye_absolute":
            self.eye_status.setText("El centro se aprende automáticamente dentro de Calibrar movimiento.")
        self.update_live_preview()
        profiles_key=json.dumps([s.get("profiles",[]),(s.get("profile") or {}).get("user_id")],sort_keys=True)
        if profiles_key!=self._profiles_key:
            self._profiles_key=profiles_key
            self._render_profile_cards(s)
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
            self.hold_click_check.setChecked(s["settings"]["control"].get("hold_click_enabled",True))
            self.tracking_combo.setCurrentIndex(self.tracking_combo.findData("nose" if s["settings"]["ui"]["tracking_method"]=="nose" else "eyes"))
            self.capture_backend_combo.setCurrentIndex(self.capture_backend_combo.findData(s["settings"]["vision"].get("capture_backend","auto")))
            self.eye_source_combo.setCurrentIndex(self.eye_source_combo.findData(s["settings"]["ui"].get("eye_source","both")))
            self.eye_vertical_reference.setCurrentIndex(self.eye_vertical_reference.findData(s["settings"]["eye"].get("vertical_reference","eyelids")))
            eye=s["settings"]["eye"]
            self.eye_axis_zones.setChecked(eye.get("dead_zone_x") is not None or eye.get("dead_zone_y") is not None)
            self.eye_dead_zone_x.setValue(eye["dead_zone"] if eye.get("dead_zone_x") is None else eye["dead_zone_x"])
            self.eye_dead_zone_y.setValue(eye["dead_zone"] if eye.get("dead_zone_y") is None else eye["dead_zone_y"])
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
        session = s.get("vertical_diagnostic") if self._vertical_preview else s.get("gaze_calibration")
        if self.gaze_overlay and self.gaze_overlay.isVisible():
            self.gaze_overlay.present(session, tracking.get("prediction"),
                tracking.get("block_reason") or tracking.get("model_reason", ""))
            if self._vertical_preview:self.gaze_overlay.save_button.hide()
            if s["state"] == "ERROR" or (not self._gaze_preview and not session and s["state"] == "DIAGNOSTIC"):
                self.gaze_overlay.close()
        fmt=lambda v:f"{v:.4f}" if v is not None else "ausente"
        source=s["settings"]["ui"].get("eye_source","both")
        eye_available=s["detected"] and eye_coordinates(fd,source) is not None
        availability=s.get("eye_availability",{})
        self.eye_diagnostic.setText(
            f"Estrategia activa: {s['settings']['ui']['tracking_method']}"
            +(" · Modo experimental" if s["settings"]["ui"]["tracking_method"]=="eye" else "")+"\n"
            +f"Fuente ocular: {EYE_SOURCE_LABELS[source]} · Iris izquierdo: {availability.get('left',False)} · "
             f"Iris derecho: {availability.get('right',False)} · Señal utilizada: {s.get('used_gaze')}\n"
            +f"Calibración de esta fuente: {'disponible' if s.get('tracking_calibrated') else 'ausente o incompatible'}\n"
            +f"left_gaze_x/y: {fmt(fd.left_gaze_x)} / {fmt(fd.left_gaze_y)} · "
            f"right_gaze_x/y: {fmt(fd.right_gaze_x)} / {fmt(fd.right_gaze_y)}\n"
            f"gaze_x/y: {fmt(fd.gaze_x)} / {fmt(fd.gaze_y)} · Disponible: {eye_available} · "
            f"Confianza (cobertura): {fd.gaze_confidence:.1f}\n"
            + (f"Neutral gaze: {fmt(tracking.get('neutral_x'))} / {fmt(tracking.get('neutral_y'))} · "
               f"Delta X/Y (rango): {fmt(tracking.get('delta_x'))} / {fmt(tracking.get('delta_y'))} · "
               f"Zona muerta ocular: {s['settings']['eye']['dead_zone']:.3f}\n"
               if s["settings"]["ui"]["tracking_method"]=="eye" else "")
            +(f"Referencia vertical: {s['settings']['eye'].get('vertical_reference','eyelids')}\n" if s["settings"]["ui"]["tracking_method"]=="eye" else "")
            +f"Head yaw / pitch: {fmt(fd.head_yaw)} / {fmt(fd.head_pitch)} · Sin compensación de pose\n"
            +f"Predicción: {tracking.get('prediction')} · Delta calculado: {tracking.get('cursor_delta')}\n"
            +f"Control: {'activo' if enabled else 'desactivado'} · Pausa: {s['paused']} · "
            +f"Bloqueo: {tracking.get('block_reason') or tracking.get('model_reason') or 'ninguno'}")
        vertical=s.get("vertical_trace",{})
        if self._vertical_preview:
            from gaze_source import gaze_position
            lines=[f"Referencia {ref} · I/D/ambos: "+str([gaze_position(fd,source,ref) for source in ("left","right","both")]) for ref in ("eyelids","canthi")]
            lines.append("Medición cruda en píxeles (iris, párpados, comisuras): "+str(fd.ocular_geometry))
            lines.append("Filtrado / delta calculado / envío simulado: "+str(vertical))
            lines.append("Resultados centro/arriba/abajo: "+str((s.get("vertical_report") or {}).get("comparison",{})))
            self.eye_diagnostic.setText(self.eye_diagnostic.text()+"\n"+"\n".join(lines))
        camera=s.get("camera_status",{})
        face_status_labels=dict(WAITING="Esperando resultado facial",NO_LANDMARKS="MediaPipe no detecta rostro",
            EXTRACTION_REJECTED="Landmarks recibidos; geometría inválida",INVALID_FACE_DATA="Señales faciales inválidas",
            VALID_FACE="Rostro válido")
        self.eye_diagnostic.setText(self.eye_diagnostic.text()+
            f"\nCámara: {camera.get('stage','sin datos')} · Operación: {camera.get('operation','—')} · "
            f"Backend: {camera.get('backend_effective') or camera.get('backend_requested','—')} · "
            f"Frames/resultados: {camera.get('captured_frames',0)}/{camera.get('processed_results',0)} · "
            f"FPS procesados: {camera.get('processing_fps',0)}\nAceptado por driver: {camera.get('accepted',{})}\n"
            f"{face_status_labels.get(camera.get('face_status','WAITING'))} · Resultados con rostro: "
            f"{camera.get('raw_face_results',0)} · Válidos: {camera.get('valid_face_results',0)} · "
            f"Descartados: {camera.get('rejected_face_results',0)}")
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
            if j["valid"]:
                self.jitter_summary.setText(f"Estabilidad: temblor {j['jitter_rms']:.4f} · {j['dead_zone_exits']} salidas de la zona quieta en 10 s".replace(".",","))
                self.jitter_summary.setToolTip(f"Jitter RMS {j['jitter_rms']:.5f} · desviación media {j['mean_deviation']:.5f} · DE {j['std_deviation']:.5f} · "
                                               f"rango X/Y {j['range_x']:.5f}/{j['range_y']:.5f} (unidades normalizadas). Guardado localmente.")
            else:
                self.jitter_summary.setText("Estabilidad: "+j["reason"])
        e=s["experiment"]
        self.canvas.present(e)
        if e:
            self.experiment_status.setText(f"Objetivo {e['index']}/{e['total']} · Completados: {e['completed']} · {'En curso' if e['active'] else 'Finalizado'}\n"+(f"Resultados: {e['path']}" if e["path"] else "Resultados guardados al finalizar cada objetivo"))
            if e["active"] and e["mode"]=="real" and self.stack.currentIndex()==6:
                self.experiment_input(*self.canvas.logical(self.canvas.mapFromGlobal(QCursor.pos())),False,True)
        self._present_metrics(s)
        self._present_diagnostic(s)
        self._present_mini_camera(s)

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
        resident=getattr(self,"resident",None)
        if not self._allow_close and not self._closing and resident and resident.minimize_on_close():
            event.ignore();self.hide();return
        if self._allow_close:
            event.accept()
            return
        event.ignore()
        if not self._closing:
            if resident:
                resident.quitting=True
                resident.disarm()
            self._closing=True
            self.banner.setText("Cerrando cámara y guardando resultados…")
            self.bridge.shutdown()

    def exit_application(self):
        resident=getattr(self,"resident",None)
        if resident:resident.quitting=True
        self.close()

    def _closed(self):
        self.timer.stop()
        if self.gaze_overlay:
            self.gaze_overlay.blockSignals(True)
            self.gaze_overlay.close()
        release_overlays(self)
        self._allow_close=True
        self.close()
