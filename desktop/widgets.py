"""Widgets de dibujo: solo presentación y eventos de entrada, sin motores."""
from PySide6.QtCore import Qt, QRectF, QPointF, Signal
from PySide6.QtGui import QPainter, QColor, QPen, QImage
from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout, QFrame


def label(text, name="", wrap=True):
    item = QLabel(text)
    item.setWordWrap(wrap)
    if name:
        item.setObjectName(name)
    return item


def card(title, value="—"):
    box = QFrame()
    box.setObjectName("Card")
    layout = QVBoxLayout(box)
    layout.setContentsMargins(18,8,18,8)
    layout.setSpacing(2)
    layout.addWidget(label(title, "Subtitle"))
    output = label(value,"MetricValue")
    output.setMinimumHeight(34)
    layout.addWidget(output)
    return box, output


class CameraPreview(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(360, 260)
        self.setAccessibleName("Vista previa de cámara")
        self.snapshot = {}
        self.image = None

    def present(self, snapshot):
        self.snapshot = snapshot
        frame = snapshot.get("frame")
        self.image = None
        if frame is not None:
            h,w = frame.shape[:2]
            self.image = QImage(frame.data,w,h,frame.strides[0],QImage.Format.Format_BGR888).copy()
        self.update()

    def paintEvent(self, event):
        p=QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(),QColor("#091220"))
        if self.image is None:
            p.setPen(QColor("#b1c6df"))
            p.drawText(self.rect(),Qt.AlignmentFlag.AlignCenter,"Cámara apagada\n\nAbrí la cámara para ver tu posición")
            return
        scale=min(self.width()/self.image.width(),self.height()/self.image.height())
        w,h=self.image.width()*scale,self.image.height()*scale
        rect=QRectF((self.width()-w)/2,(self.height()-h)/2,w,h)
        p.drawImage(rect,self.image)
        s=self.snapshot
        if not s.get("detected"):
            return
        settings=s["settings"]
        face=s["face"]
        point=lambda x,y: QPointF(rect.x()+x*w,rect.y()+y*h)
        if settings["ui"]["show_landmarks"]:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#ffd477"))
            for x,y in face.landmarks:
                p.drawEllipse(point(x,y),3,3)
        if settings["ui"]["show_overlay"]:
            profile=s.get("profile") or {}
            nx=profile.get("neutral_nose_x",.5)
            ny=profile.get("neutral_nose_y",.5)
            dz=settings["gesture"]["dead_zone"]
            p.setPen(QPen(QColor("#ffd477"),2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(QRectF(point(nx-dz,ny-dz),point(nx+dz,ny+dz)))
            p.drawEllipse(point(nx,ny),6,6)
            p.setPen(QPen(QColor("#6df4e0"),3))
            p.drawLine(point(nx,ny),point(face.nose_x,face.nose_y))
            p.setBrush(QColor("#6df4e0"))
            p.drawEllipse(point(face.nose_x,face.nose_y),7,7)


class CalibrationMeter(QWidget):
    """Dibuja los valores ya calculados por la sesión; no interpreta gestos."""
    def __init__(self):
        super().__init__()
        self.rows=[]
        self.setMinimumHeight(100)
        self.setAccessibleName("Medidor de señal, neutral, liberación, activación y gesto cómodo")

    def present(self,rows):
        self.rows=rows
        self.setMinimumHeight(max(100,(55 if self.width()<420 else 30)+85*len(rows)))
        self.update()

    def resizeEvent(self,event):
        self.present(self.rows)
        super().resizeEvent(event)

    def paintEvent(self,event):
        p=QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(),QColor("#172337"))
        p.setPen(QColor("#b1c6df"))
        if not self.rows:
            p.drawText(self.rect(),Qt.AlignmentFlag.AlignCenter,"El medidor aparece al comenzar los gestos")
            return
        colors={"neutral":"#b1c6df","release":"#cfb3ff","activation":"#ffd477","comfortable":"#71dfbe"}
        labels={"neutral":"Neutral","release":"Liberación","activation":"Activación","comfortable":"Gesto cómodo"}
        columns=2 if self.width()<420 else 4
        for i,(key,color) in enumerate(colors.items()):
            p.setPen(QColor(color))
            p.drawText(QRectF(12+(i%columns)*self.width()/columns,3+25*(i//columns),self.width()/columns-12,25),Qt.AlignmentFlag.AlignLeft,labels[key])
        for index,row in enumerate(self.rows):
            y=(80 if columns==2 else 55)+85*index
            d=row["direction"]
            values=[d*row[k] for k in (*colors,"value") if row.get(k) is not None]
            if not values: continue
            lo,hi=min(values),max(values)
            padding=max(.005,(hi-lo)*.15)
            lo,hi=lo-padding,hi+padding
            xpos=lambda v: 25+(d*v-lo)/(hi-lo)*(self.width()-50)
            p.setPen(QPen(QColor("#536b8b"),3))
            p.drawLine(QPointF(25,y),QPointF(self.width()-25,y))
            for key,color in colors.items():
                if row.get(key) is not None:
                    x=xpos(row[key])
                    p.setPen(QPen(QColor(color),3))
                    p.drawLine(QPointF(x,y-10),QPointF(x,y+10))
            value=row.get("value")
            if value is not None:
                p.setBrush(QColor("#6df4e0"))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(QPointF(xpos(value),y),6,6)
            p.setPen(QColor("#eef3fc"))
            side={"left":"Izquierda", "right":"Derecha"}.get(row["channel"],"Señal")
            text=f"{side} · Valor actual: {value:.4f}" if value is not None else f"{side} · Esperando señal"
            if row.get("activation") is None: text+=" · Falta una captura válida"
            p.drawText(QRectF(12,y+16,self.width()-24,26),Qt.AlignmentFlag.AlignLeft,text)


class ExperimentCanvas(QWidget):
    input = Signal(float,float,bool,bool)

    def __init__(self):
        super().__init__()
        self.setMinimumSize(500,300)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("Objetivos: flechas para mover, espacio para seleccionar en simulación manual")
        self.data = None

    def present(self,data):
        self.data=data
        self.update()

    def canvas_rect(self):
        scale=min(self.width()/800,self.height()/500)
        return QRectF((self.width()-800*scale)/2,(self.height()-500*scale)/2,800*scale,500*scale)

    def logical(self,pos):
        r=self.canvas_rect()
        return ((pos.x()-r.x())*800/r.width(),(pos.y()-r.y())*500/r.height())

    def paintEvent(self,event):
        p=QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(),QColor("#0b1525"))
        if not self.data:
            p.setPen(QColor("#b1c6df"))
            p.drawText(self.rect(),Qt.AlignmentFlag.AlignCenter,"Elegí un modo y comenzá la serie de 5 objetivos")
            return
        r=self.canvas_rect()
        p.translate(r.x(),r.y())
        p.scale(r.width()/800,r.height()/500)
        p.setPen(QPen(QColor("#1d3049"),1))
        for x in range(0,801,50): p.drawLine(x,0,x,500)
        for y in range(0,501,50): p.drawLine(0,y,800,y)
        x,y=self.data["target"]
        p.setPen(QPen(QColor("#92f6d7"),3))
        p.setBrush(QColor("#24715c"))
        radius=self.data["radius"]
        p.drawEllipse(QPointF(x,y),radius,radius)
        p.setPen(QColor("#ffffff"))
        p.drawText(QRectF(x-radius,y-radius,radius*2,radius*2),Qt.AlignmentFlag.AlignCenter,str(self.data["index"]))
        x,y=self.data["cursor"]
        p.setBrush(QColor("#ffd477"))
        p.setPen(QPen(QColor("#ffffff"),2))
        p.drawEllipse(QPointF(x,y),7,7)

    def keyPressEvent(self,event):
        if not self.data or self.data["source"]!="keyboard" or self.data["mode"]!="simulation":
            return super().keyPressEvent(event)
        moves={Qt.Key.Key_Left:(-10,0),Qt.Key.Key_Right:(10,0),Qt.Key.Key_Up:(0,-10),Qt.Key.Key_Down:(0,10)}
        if event.key() in moves:
            self.input.emit(*moves[event.key()],False,False)
        elif event.key() in (Qt.Key.Key_Space,Qt.Key.Key_Return):
            self.input.emit(0,0,True,False)
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self,event):
        self.setFocus()
        if self.data and self.data["mode"]=="real" and event.button()==Qt.MouseButton.LeftButton:
            self.input.emit(*self.logical(event.position()),True,True)
