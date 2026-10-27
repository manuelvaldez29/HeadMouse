"""Objetivos sobre la pantalla primaria; preview dibujado, sin salida al mouse."""
from PySide6.QtCore import Qt, QPointF, Signal
from PySide6.QtGui import QPainter, QColor, QPen
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QComboBox
from desktop.widgets import CameraPreview


class GazeOverlay(QWidget):
    cancel = Signal()
    save = Signal()
    repeat = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setWindowTitle("HeadMouse · Mirada · Sin control real")
        self.setAccessibleName("Calibración y diagnóstico ocular seguro en pantalla completa")
        self.session, self.prediction = None, None
        self._point_key = None
        self.camera_preview=CameraPreview()
        self.camera_preview.setParent(self)
        self.camera_preview.setMinimumSize(0,0)
        self.camera_caption=QLabel(self)
        self.camera_caption.setWordWrap(True)
        self.camera_caption.setStyleSheet("font-size:14px;")
        layout = QVBoxLayout(self)
        self.info = QLabel("Preparando cámara. Control real desactivado.")
        self.info.setWordWrap(True)
        layout.addWidget(self.info)
        layout.addStretch()
        row = QHBoxLayout()
        self.points = QComboBox()
        self.repeat_button = QPushButton("Repetir punto")
        self.repeat_button.setEnabled(False)
        self.repeat_button.clicked.connect(lambda: self.repeat.emit(self.points.currentData()))
        self.save_button = QPushButton("Guardar calibración validada")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self.save.emit)
        close = QPushButton("Salir · Escape / F8")
        close.clicked.connect(self.close)
        for widget in (self.points, self.repeat_button, self.save_button, close):
            row.addWidget(widget)
        layout.addLayout(row)
        self.setStyleSheet("QWidget { background:#091220;color:#eef3fc;font-size:18px; }"
                          "QPushButton:disabled { color:#8290a6; border-color:#263142; background:#111b2b; }")

    def present(self, session, prediction, reason=""):
        self.session, self.prediction = session, prediction
        for widget in (self.points, self.repeat_button, self.save_button):
            widget.setVisible(session is not None)
        self.repeat_button.setEnabled(session is not None)
        if session:
            if self.points.count() != session["total"]:
                self.points.clear()
                for i in range(session["total"]):
                    self.points.addItem(f"Punto {i+1}", i)
            key = (session["phase"], session["index"], session["total"])
            if self._point_key != key:
                self.points.setCurrentIndex(session["index"])
                self._point_key = key
            for i in range(session["total"]):
                point = session.get("points", {}).get(i)
                suffix = f" · calidad {point['quality']:.0%}" if point else " · pendiente"
                if i in session.get("rejected_points", {}) and not point:
                    suffix = " · rechazado: repetir"
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
            measured = f"\nÚltima medición · punto {check['point_index']+1}: ΔX={check['delta'][0]:+.6f} · ΔY={check['delta'][1]:+.6f} · Esperado X/Y={check['expected']} (+Y abajo)" if check else ""
            self.info.setText(f"SIN CONTROL REAL · {session.get('kind','Calibración ocular')} · {session.get('source_label','Ambos ojos')} · {phase} · {session['index']+1}/{session['total']} · "
                f"{session['state']} {session['countdown']:.1f} s · Muestras: {session['samples']} · Rechazos: {session['rejected']}\n"
                +session["message"]+measured+errors)
        else:
            self.info.setText("DIAGNÓSTICO SEGURO · El punto celeste es la predicción; el mouse real está desactivado.\n"
                              +(reason or "Mirá distintas zonas de la pantalla. Escape para salir."))
        self._place_camera()
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
        tx,ty=(self.session or {}).get("target",(.5,.5))
        x=12 if tx>=.5 else self.width()-width-12
        y=self.height()-height-190 if ty<.5 else 12
        self.camera_preview.setGeometry(x,max(12,y),width,height)
        self.camera_caption.setGeometry(x,max(12,y)+height,width,100)
        self.info.setMaximumWidth(max(250,self.width()-width-48))
        self.layout().setAlignment(self.info,Qt.AlignmentFlag.AlignRight if x==12 else Qt.AlignmentFlag.AlignLeft)
        self.camera_preview.raise_();self.camera_caption.raise_()

    def resizeEvent(self,event):
        super().resizeEvent(event)
        self._place_camera()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("#091220"))
        p.setPen(QPen(QColor("#ffd477"), 3))
        if self.session:
            x,y = self.session["target"]
            center = QPointF(x*(self.width()-1), y*(self.height()-1))
            p.drawEllipse(center, 18, 18)
            p.drawLine(center+QPointF(-28,0), center+QPointF(28,0))
            p.drawLine(center+QPointF(0,-28), center+QPointF(0,28))
            p.setBrush(QColor("#ffffff"))
            p.drawEllipse(center, 4, 4)
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
