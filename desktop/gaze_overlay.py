"""Objetivos sobre la pantalla primaria; preview dibujado, sin salida al mouse."""
from PySide6.QtCore import Qt, QPoint, QPointF, QTimer, Signal
from PySide6.QtGui import QPainter, QColor, QPen
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QComboBox, QScrollArea
from desktop.widgets import CameraPreview


class GazeOverlay(QWidget):
    cancel = Signal()
    save = Signal()
    repeat = Signal(int)
    review_training = Signal()
    export_attempt = Signal()
    viewport_measured = Signal(dict)
    geometry_failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setWindowTitle("HeadMouse · Mirada · Sin control real")
        self.setAccessibleName("Calibración y diagnóstico ocular seguro en pantalla completa")
        self.session, self.prediction = None, None
        self._point_key = None
        self._viewport_key = None
        self._geometry_failed = False
        self.camera_preview=CameraPreview()
        self.camera_preview.setParent(self)
        self.camera_preview.setMinimumSize(0,0)
        self.camera_caption=QLabel(self)
        self.camera_caption.setWordWrap(True)
        self.camera_caption.setStyleSheet("font-size:14px;")
        layout = QVBoxLayout(self)
        self.info = QLabel("Preparando cámara. Control real desactivado.")
        self.info.setWordWrap(True)
        self.info.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.info.setStyleSheet("font-size:14px;")
        self.info_area = QScrollArea()
        self.info_area.setWidgetResizable(True)
        self.info_area.setFrameShape(QScrollArea.Shape.NoFrame)
        self.info_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.info_area.setWidget(self.info)
        layout.addWidget(self.info_area)
        layout.addStretch()
        row = QHBoxLayout()
        self.points = QComboBox()
        self.points.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.points.setMinimumContentsLength(12)
        self.points.setMaximumWidth(270)
        self.points.currentIndexChanged.connect(lambda _index:(self._place_camera(),self.update()))
        self.repeat_button = QPushButton("Repetir punto")
        self.repeat_button.setEnabled(False)
        self.repeat_button.clicked.connect(lambda: self.repeat.emit(self.points.currentData()))
        self.save_button = QPushButton("Guardar calibración validada")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self.save.emit)
        self.review_button = QPushButton("Revisar aprendizaje")
        self.review_button.clicked.connect(self.review_training.emit)
        self.export_button = QPushButton("Guardar diagnóstico")
        self.export_button.clicked.connect(self.export_attempt.emit)
        close = QPushButton("Salir · Escape / F8")
        close.clicked.connect(self.close)
        for widget in (self.points, self.repeat_button, self.review_button, self.export_button, self.save_button, close):
            widget.setStyleSheet("font-size:14px;")
            row.addWidget(widget)
        layout.addLayout(row)
        self.setStyleSheet("QWidget { background:#091220;color:#eef3fc;font-size:18px; }"
                          "QPushButton:disabled { color:#8290a6; border-color:#263142; background:#111b2b; }")

    def present(self, session, prediction, reason=""):
        self.session, self.prediction = session, prediction
        for widget in (self.points, self.repeat_button, self.save_button, self.review_button, self.export_button):
            widget.setVisible(session is not None)
        self.repeat_button.setEnabled(session is not None)
        self.review_button.setEnabled(bool(session and session.get("can_review_training")))
        if session:
            if self.points.count() != session["total"]:
                self.points.clear()
                for i in range(session["total"]):
                    self.points.addItem(f"Punto {i+1}", i)
            key = (session["phase"], session["index"], session["total"])
            if self._point_key != key:
                self.points.setCurrentIndex(session["index"])
                self._point_key = key
            training_errors = {p["point_index"]:p["error_mean_px"] for p in (session.get("training_report") or {}).get("points", [])}
            for i in range(session["total"]):
                point = session.get("points", {}).get(i)
                suffix = f" · estabilidad {point['quality']:.0%}" if point else " · pendiente"
                if point and "error_mean_px" in point:
                    suffix += f" · error {point['error_mean_px']:.1f} px"
                if i in session.get("rejected_points", {}) and not point:
                    suffix = " · rechazado: repetir"
                if session["phase"] == "training" and i in training_errors:
                    suffix += f" · ajuste {training_errors[i]:.1f} px"
                self.points.setItemText(i, f"Punto {i+1}"+suffix)
            self.save_button.setEnabled(session["can_save"])
            self.save_button.setText("Guardar movimiento ocular")
            report = session.get("report")
            errors = ""
            if report:
                values = [p["error_mean_px"] for p in report["points"]]
                errors = f" · Error medio: {sum(values)/len(values):.1f} px · Peor zona: {max(values):.1f} px"
            phase = "ajuste" if session["phase"] == "training" else "validación independiente"
            check = session.get("direction_check")
            measured = f"\nReferencia: {session.get('vertical_reference','eyelids')} · Última medición · punto {check['point_index']+1}: ΔX={check['delta'][0]:+.6f} · ΔY={check['delta'][1]:+.6f} · Signos direccionales X/Y={check['expected']} (+Y abajo)" if check else ""
            last = session.get("last_point")
            detail = (f"\nÚltimo objetivo medido {last['point_index']+1}: "
                f"error X {last['error_x_px']:.1f}, Y {last['error_y_px']:.1f}, euclidiano {last['error_mean_px']:.1f} px. "
                "Estabilidad de captura y precisión son medidas distintas.") if last else ""
            progress = "completa 5/5" if session.get("validation_complete") else f"{session.get('capture_number',session['index']+1)}/{session['total']}"
            self.info.setText(f"SIN CONTROL REAL · {session.get('kind','Calibración ocular')} · {session.get('source_label','Ambos ojos')} · {phase} · {progress} · objetivo {session['index']+1} · "
                f"{session['state']} {session['countdown']:.1f} s · Muestras: {session['samples']} · Rechazos: {session['rejected']}\n"
                +session["message"]+measured+errors+detail)
        else:
            self.info.setText("DIAGNÓSTICO SEGURO · El punto celeste es la predicción; el mouse real está desactivado.\n"
                              +(reason or "Mirá distintas zonas de la pantalla. Escape para salir."))
        self._place_camera()
        if session and self.isVisible():
            from PySide6.QtCore import QPoint
            origin = self.mapToGlobal(QPoint(0,0))
            key = (session["phase"],session["index"],session.get("revision",0),origin.x(),origin.y(),self.width(),self.height(),self.devicePixelRatioF())
            if key != self._viewport_key:
                self._viewport_key = key
                self.viewport_measured.emit(dict(phase=session["phase"],index=session["index"],
                    logical_rect=[origin.x(),origin.y(),self.width(),self.height()],dpr=self.devicePixelRatioF(),
                    target_local_logical=list(self._target_position())))
        self.update()

    def present_camera(self,snapshot):
        camera=dict(snapshot)
        camera["settings"]=dict(snapshot["settings"],ui=dict(snapshot["settings"]["ui"],show_landmarks=True,show_overlay=True))
        self.camera_preview.present(camera)
        available=snapshot.get("eye_availability",{})
        session=self.session or {}
        stable=session.get("head_stable")
        head="estable" if stable is True else "movimiento excesivo" if stable is False else "midiendo"
        signal=bool(snapshot.get("detected") and snapshot.get("used_gaze") is not None)
        face=snapshot.get("face")
        framed=bool(snapshot.get("detected") and face and .12<=face.nose_x<=.88 and .12<=face.nose_y<=.88)
        self.camera_caption.setText(f"{snapshot.get('eye_source_label','Ojos')} · señal {'disponible' if signal else 'pendiente'}\n"
            f"Iris I/D: {available.get('left',False)} / {available.get('right',False)} · Encuadre: {'correcto' if framed else 'revisar'}\n"
            f"Cabeza: {head} · Muestras válidas: {session.get('samples',0)}")
        self._place_camera()

    def _place_camera(self):
        width=min(270,max(150,round(self.width()*.23)))
        height=round(width*.75)
        reviewed = self._review_point()
        tx,ty=reviewed["target"] if reviewed else (self.session or {}).get("target",(.5,.5))
        x=12 if tx>=.5 else self.width()-width-12
        y=self.height()-height-190 if ty<.5 else 12
        self.camera_preview.setGeometry(x,max(12,y),width,height)
        self.camera_caption.setGeometry(x,max(12,y)+height,width,100)
        # Banda entre las filas de objetivos 10% y 50%; no cubrir la fila superior.
        validation = (self.session or {}).get("phase") == "validation"
        top = round(self.height()*(.02 if validation else .18))
        height_limit = round(self.height()*.23)
        if self.session:
            # Dejar margen al objetivo real, incluido el desplazamiento del overlay.
            boundary = self._target_position((.5,.3 if validation else .5))[1]-32
            if not validation:
                top = max(top,round(self._target_position((.5,.1))[1]+32))
            height_limit = max(24,min(height_limit,int(boundary-top)))
        self.layout().setContentsMargins(12, top, 12, 12)
        self.info_area.setFixedHeight(height_limit)
        self.info_area.setFixedWidth(max(250,self.width()-width-48))
        self.layout().setAlignment(self.info_area,Qt.AlignmentFlag.AlignRight if x==12 else Qt.AlignmentFlag.AlignLeft)
        self.camera_preview.raise_();self.camera_caption.raise_()

    def resizeEvent(self,event):
        super().resizeEvent(event)
        self._place_camera()

    def _review_point(self):
        if not self.session or self.session["state"] not in ("ready", "invalid", "error"):
            return None
        index = self.points.currentData()
        if self.session["phase"] == "validation":
            return self.session.get("points",{}).get(index)
        return next((p for p in (self.session.get("training_report") or {}).get("points",[]) if p["point_index"] == index),None)

    def _target_position(self, target=None):
        target = self.session["target"] if target is None else target
        if self.session.get("context"):
            from screen_mapping import target_in_viewport
            origin = self.mapToGlobal(QPoint(0,0))
            try:
                return target_in_viewport(target,self.session["context"],(origin.x(),origin.y()),self.devicePixelRatioF())
            except ValueError as exc:
                if not self._geometry_failed:
                    self._geometry_failed = True
                    QTimer.singleShot(0,lambda reason=str(exc):self._close_bad_geometry(reason))
                return -10000.,-10000.
        return target[0]*(self.width()-1),target[1]*(self.height()-1)

    def _close_bad_geometry(self, reason):
        self.close()
        self.geometry_failed.emit(reason)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("#091220"))
        p.setPen(QPen(QColor("#ffd477"), 3))
        if self.session:
            x,y = self.session["target"]
            reviewed = self._review_point()
            center = QPointF(*self._target_position(reviewed["target"] if reviewed else None))
            p.drawEllipse(center, 18, 18)
            p.drawLine(center+QPointF(-28,0), center+QPointF(28,0))
            p.drawLine(center+QPointF(0,-28), center+QPointF(0,28))
            p.setBrush(QColor("#ffffff"))
            p.drawEllipse(center, 4, 4)
            if reviewed and "predicted_mean_px" in reviewed:
                context = self.session.get("context")
                if context:
                    predicted = reviewed["predicted_mean_px"]
                    uv = (predicted[0]/(context["width"]-1),predicted[1]/(context["height"]-1))
                    endpoint = QPointF(*self._target_position(uv))
                    p.setPen(QPen(QColor("#6df4e0"),2))
                    p.drawLine(center,endpoint)
                    p.drawEllipse(endpoint,12,12)
                    font = p.font(); font.setPixelSize(14); p.setFont(font)
                    p.drawText(20,self.height()-60,
                        f"Revisión punto {reviewed['point_index']+1} · Amarillo: objetivo · Celeste: predicción · "
                        f"Distancia media {reviewed['error_mean_px']:.1f} px")
                    captured = self.session.get("points",{}).get(reviewed["point_index"],{})
                    quality = f" · Estabilidad {captured['quality']:.0%}" if "quality" in captured else ""
                    p.drawText(20,self.height()-40,
                        f"Error X {reviewed['error_x_px']:.1f} px · Y {reviewed['error_y_px']:.1f} px"+quality+f" · {self.session['state']}")
        elif self.prediction:
            p.setPen(QPen(QColor("#6df4e0"), 3))
            p.setBrush(QColor("#24715c"))
            p.drawEllipse(QPointF(self.prediction[0]*(self.width()-1), self.prediction[1]*(self.height()-1)), 15, 15)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_F8):
            self.close()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        self.cancel.emit()
        super().closeEvent(event)
