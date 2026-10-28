"""Widgets de dibujo: solo presentación y eventos de entrada, sin motores."""
from PySide6.QtCore import Qt, QRectF, QPointF, Signal
from PySide6.QtGui import QPainter, QColor, QPen, QImage, QFontMetrics
from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout, QFrame
from gaze_source import iris_markers


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
    def __init__(self, empty_text="Cámara apagada\n\nAbrí la cámara para ver tu posición"):
        super().__init__()
        self.empty_text = empty_text
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
            p.drawText(self.rect(),Qt.AlignmentFlag.AlignCenter,self.empty_text)
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
            source=settings["ui"].get("eye_source","both")
            for side,x,y in iris_markers(face,source):
                used = source == "both" or side == source
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(QColor("#6df4e0" if used else "#b1c6df"),2))
                p.drawEllipse(point(x,y),7 if used else 5,7 if used else 5)
                p.drawText(point(x,y)+QPointF(9,-9), "I" if side=="left" else "D")
        if settings["ui"]["show_overlay"]:
            profile=s.get("profile") or {}
            diagnostic=s.get("diagnostic") or {}
            # El neutral vigente puede venir del recentrado automático.
            nx=diagnostic.get("neutral_x",profile.get("neutral_nose_x",.5))
            ny=diagnostic.get("neutral_y",profile.get("neutral_nose_y",.5))
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


class DictationOverlay(QWidget):
    """Aviso flotante del dictado. Nunca toma el foco: el texto debe ir al campo
    que el usuario eligió, no a HeadMouse. Tampoco recibe clicks."""
    COLORS = {"arming": "#c4d3e8", "listening": "#ff6b81", "transcribing": "#ffd166", "done": "#8ce5cd"}

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus |
                         Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.text, self.kind = "", "listening"
        self.resize(760, 64)

    def present(self, dictation, done_message="", screen=None):
        state = (dictation or {}).get("state", "idle")
        if state in ("listening", "transcribing"):
            text, kind = dictation["message"], state
        elif done_message:
            text, kind = done_message, "done"
        else:
            if self.isVisible():
                self.hide()
            return
        if (text, kind) != (self.text, self.kind):
            self.text, self.kind = text, kind
            self.update()
        if not self.isVisible():
            if screen is not None:
                area = screen.availableGeometry()
                self.move(area.center().x() - self.width() // 2, area.bottom() - self.height() - 40)
            self.show()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(self.COLORS.get(self.kind, "#c4d3e8"))
        painter.setBrush(QColor(15, 23, 36, 235))
        painter.setPen(QPen(color, 2))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 16, 16)
        painter.setBrush(color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(30, self.height() / 2), 9, 9)
        painter.setPen(QColor("#eef3fb"))
        font = painter.font()
        font.setPointSize(12)
        painter.setFont(font)
        width = self.width() - 64
        painter.drawText(QRectF(52, 0, width, self.height()),
                         Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextSingleLine,
                         painter.fontMetrics().elidedText(self.text, Qt.TextElideMode.ElideRight, width))


# Colores validados con la guía de visualización (dataviz/validate_palette.js) sobre
# el fondo de tarjeta #172337: tres series pasan CVD ΔE 9,4 y contraste >= 3:1.
CHART_SERIES = ("#3987e5", "#d95926", "#199e70")
CHART_NEUTRAL = "#b2c1d7"  # serie única: el título ya la nombra, no necesita identidad
CHART_INK = dict(surface="#172337", primary="#eef3fc", secondary="#b2c1d7", muted="#8192aa",
                 grid="#26364d", axis="#405670")


def nice_ticks(maximum, count=4):
    """0 y pasos redondos (1, 2, 2,5 o 5 × 10^n) que cubren `maximum`."""
    import math
    if maximum <= 0:
        return [0, 1]
    raw = maximum / count
    power = 10 ** math.floor(math.log10(raw))
    step = next(m * power for m in (1, 2, 2.5, 5, 10) if m * power >= raw)
    top = step * math.ceil(maximum / step - 1e-9)
    return [round(step * i, 6) for i in range(int(round(top / step)) + 1)]


class LineChart(QWidget):
    """Líneas por sesión con un solo eje Y.

    Con `facets=True` cada serie va en su propia franja, todas con la misma escala
    y el mismo eje X (small multiples): con muchas sesiones, varias líneas
    superpuestas se cruzan y no se leen. El recuadro al pasar el mouse muestra los
    valores de todas las series en esa sesión.
    """

    def __init__(self, unit="", empty="Todavía no hay datos", facets=False):
        super().__init__()
        self.unit, self.empty, self.facets = unit, empty, facets
        self.labels, self.series = [], []
        self.hover = None
        self.setMouseTracking(True)
        self.setMinimumHeight(270 if facets else 220)

    def set_data(self, labels, series):
        """labels: texto del eje X por punto; series: [dict(name, color, values)]."""
        self.labels, self.series = list(labels), [dict(s) for s in series]
        self.hover = None
        self.setAccessibleDescription("; ".join(
            f"{s['name']}: " + ", ".join(f"{label} {value:.1f}" for label, value in zip(self.labels, s["values"]))
            for s in self.series))
        self.update()

    def _plot(self):
        legend = 30 if len(self.series) > 1 and not self.facets else 6
        right = 64 if self.facets else 104
        return QRectF(48, legend + 8, max(10, self.width() - 48 - right), max(10, self.height() - legend - 8 - 30))

    def _bands(self, plot):
        if not self.facets or len(self.series) < 2:
            return [plot] * len(self.series)
        gap, n = 24, len(self.series)
        height = (plot.height() - gap * (n - 1)) / n
        return [QRectF(plot.left(), plot.top() + i * (height + gap), plot.width(), height) for i in range(n)]

    def _x(self, plot, index):
        n = len(self.labels)
        return plot.left() + (plot.width() / 2 if n == 1 else plot.width() * index / (n - 1))

    def _shown_labels(self, plot, metrics):
        """Índices del eje X que entran sin pisarse; el último siempre se muestra."""
        n = len(self.labels)
        if n == 1:
            return [0]
        widest = max(metrics.horizontalAdvance(label) for label in self.labels) + 14
        spacing = plot.width() / (n - 1)
        every = max(1, int(widest / spacing) + (widest % spacing > 0))
        shown = list(range(0, n, every))
        if shown[-1] != n - 1:
            if (n - 1 - shown[-1]) * spacing < widest:
                shown[-1] = n - 1  # el último reemplaza al anterior si no entran los dos
            else:
                shown.append(n - 1)
        return shown

    def mouseMoveEvent(self, event):
        if not self.labels:
            return
        plot = self._plot()
        n = len(self.labels)
        x = event.position().x()
        index = 0 if n == 1 else round((x - plot.left()) / plot.width() * (n - 1))
        index = max(0, min(n - 1, index))
        if index != self.hover:
            self.hover = index
            self.update()

    def leaveEvent(self, event):
        self.hover = None
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        ink = {k: QColor(v) for k, v in CHART_INK.items()}
        metrics = QFontMetrics(p.font())
        if not self.labels or not self.series:
            p.setPen(ink["secondary"])
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.empty)
            return
        plot = self._plot()
        bands = self._bands(plot)
        faceted = self.facets and len(self.series) > 1
        ticks = nice_ticks(max(max(s["values"]) for s in self.series), 2 if faceted else 4)
        scale = ticks[-1] or 1
        n = len(self.labels)
        # Grilla y eje por franja: recesivos, hairline continuo.
        for band in (bands if faceted else bands[:1]):  # sin franjas, todas comparten el mismo rectángulo
            y = lambda value, band=band: band.bottom() - band.height() * value / scale
            for tick in ticks:
                yy = y(tick)
                p.setPen(QPen(ink["axis" if tick == 0 else "grid"], 1))
                p.drawLine(QPointF(band.left(), yy), QPointF(band.right(), yy))
                if faceted and tick not in (ticks[0], ticks[-1]):
                    continue  # en franjas, sólo 0 y el máximo: las etiquetas no chocan entre franjas
                p.setPen(ink["muted"])
                p.drawText(QRectF(0, yy - 9, band.left() - 8, 18),
                           Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"{tick:g}".replace(".", ","))
        p.setPen(ink["muted"])
        for index in self._shown_labels(plot, metrics):
            xx = self._x(plot, index)
            p.drawText(QRectF(xx - 45, plot.bottom() + 6, 90, 18), Qt.AlignmentFlag.AlignHCenter, self.labels[index])
        # Leyenda sólo cuando las series comparten franja (en franjas, cada una lleva su nombre).
        if len(self.series) > 1 and not faceted:
            xx = plot.left()
            for serie in self.series:
                p.setPen(QPen(QColor(serie["color"]), 2))
                p.drawLine(QPointF(xx, 15), QPointF(xx + 16, 15))
                p.setPen(ink["secondary"])
                p.drawText(QPointF(xx + 22, 20), serie["name"])
                xx += 22 + metrics.horizontalAdvance(serie["name"]) + 22
        ends = []
        for serie, band in zip(self.series, bands):
            color = QColor(serie["color"])
            y = lambda value, band=band: band.bottom() - band.height() * value / scale
            points = [QPointF(self._x(plot, i), y(v)) for i, v in enumerate(serie["values"])]
            pen = QPen(color, 2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            for a, b in zip(points, points[1:]):
                p.drawLine(a, b)
            p.setPen(QPen(ink["surface"], 2))
            p.setBrush(color)
            for index, point in enumerate(points):
                if n <= 24 or index == n - 1 or index == self.hover:
                    p.drawEllipse(point, 4, 4)
            if faceted:
                # Nombre de la franja con su muestra de color; texto en tinta de texto.
                p.setPen(QPen(color, 2))
                p.drawLine(QPointF(band.left() + 6, band.top() + 2), QPointF(band.left() + 20, band.top() + 2))
                p.setPen(ink["secondary"])
                p.drawText(QPointF(band.left() + 26, band.top() + 7), serie["name"])
                last = serie["values"][-1]
                p.drawText(QRectF(band.right() + 8, points[-1].y() - 9, 60, 18), Qt.AlignmentFlag.AlignVCenter,
                           f"{last:.1f}".replace(".", ","))
            ends.append((points[-1].y(), serie["name"]))
        if len(self.series) > 1 and not faceted:
            ends.sort()
            if all(b[0] - a[0] >= 16 for a, b in zip(ends, ends[1:])):
                p.setPen(ink["secondary"])
                for yy, name in ends:
                    p.drawText(QRectF(plot.right() + 10, yy - 9, 100, 18), Qt.AlignmentFlag.AlignVCenter, name)
        if self.hover is not None:
            xx = self._x(plot, self.hover)
            p.setPen(QPen(ink["axis"], 1))
            p.drawLine(QPointF(xx, plot.top()), QPointF(xx, plot.bottom()))
            rows = [(s["color"], f"{s['name']}: {s['values'][self.hover]:.1f}".replace(".", ",") + self.unit)
                    for s in self.series]
            width = max(metrics.horizontalAdvance(t) for _, t in rows + [("", self.labels[self.hover])]) + 34
            height = 24 + 20 * len(rows)
            left = xx + 12 if xx + 12 + width < self.width() else xx - 12 - width
            box = QRectF(left, plot.top(), width, height)
            p.setPen(QPen(ink["axis"], 1))
            p.setBrush(QColor("#0f1a2b"))
            p.drawRoundedRect(box, 8, 8)
            p.setPen(ink["primary"])
            p.drawText(QPointF(box.left() + 12, box.top() + 17), self.labels[self.hover])
            for i, (color, text) in enumerate(rows):
                yy = box.top() + 24 + 20 * i
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(color))
                p.drawEllipse(QPointF(box.left() + 16, yy + 9), 4, 4)
                p.setPen(ink["secondary"])
                p.drawText(QPointF(box.left() + 26, yy + 13), text)


def gesture_progress(signal, record, gate, directions):
    """Cuánto falta para activar: 0 = reposo, 1 = umbral de activación (puede pasar de 1).

    Se mide desde el reposo calibrado de ese gesto hasta su activación vigente, canal
    por canal; un gesto de dos canales (ambas cejas) avanza lo que avance el más atrasado.
    """
    if not signal or not gate:
        return None
    neutral = (record or {}).get("neutral_statistics", {})
    fractions = []
    for value, (channel, activation), d in zip(signal, gate["activation"].items(), directions):
        rest = neutral.get(channel, {}).get("median")
        if rest is None or d * (activation - rest) <= 0:
            return None
        fractions.append(max(0., d * (value - rest) / (d * (activation - rest))))
    return min(fractions) if fractions else None


class GestureMeters(QWidget):
    """Una barra por gesto: el relleno avanza hacia la marca de activación."""
    ROW = 30

    def __init__(self):
        super().__init__()
        self.rows = []
        self.setMinimumHeight(self.ROW * 6 + 4)

    def present(self, rows):
        """rows: [(etiqueta, progreso 0..1+ o None, activo, disponible)]."""
        if rows != self.rows:
            self.rows = rows
            self.setAccessibleDescription("; ".join(
                f"{label}: {'no disponible' if not available else 'activo' if active else 'sin datos' if value is None else f'{min(value, 1):.0%} del umbral'}"
                for label, value, active, available in rows))
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        label_w = 132
        track_w = max(40, self.width() - label_w - 74)
        for i, (label, value, active, available) in enumerate(self.rows):
            y = i * self.ROW + 4
            p.setPen(QColor("#eef3fc" if available else "#8192aa"))
            p.drawText(QRectF(0, y, label_w, 20), Qt.AlignmentFlag.AlignVCenter, label)
            track = QRectF(label_w, y + 6, track_w, 8)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#26364d"))
            p.drawRoundedRect(track, 4, 4)
            if available and value is not None:
                fill = track.adjusted(0, 0, -track.width() * (1 - min(value, 1.25) / 1.25), 0)
                p.setBrush(QColor("#57d4c3" if active else "#3f7f86"))
                p.drawRoundedRect(fill, 4, 4)
            mark = track.left() + track.width() / 1.25  # la activación queda al 80 % del ancho
            p.setPen(QPen(QColor("#ffd166"), 2))
            p.drawLine(QPointF(mark, y + 2), QPointF(mark, y + 18))
            p.setPen(QColor("#8ce5cd" if active else "#8192aa"))
            status = "no disponible" if not available else "● activo" if active else "—" if value is None else ""
            p.drawText(QRectF(track.right() + 10, y, 70, 20), Qt.AlignmentFlag.AlignVCenter, status)

