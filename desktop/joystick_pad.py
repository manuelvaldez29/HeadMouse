"""Marcas del joystick ocular sobre toda la pantalla: se calibra y se usa mirando los mismos lugares."""
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from direction_diagnostic import TARGETS

LABELS = dict(center="Centro", up="Arriba", down="Abajo", left="Izquierda", right="Derecha")
ARROWS = dict(left=(-1, 0), right=(1, 0), up=(0, -1), down=(0, 1))


class JoystickPad(QWidget):
    """Transparente, sin foco y sin clics: solo dibuja cuatro marcas y el punto de calibración."""
    displayed = Signal(str, int, int, int, int)

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus |
                         Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle("HeadMouse · marcas del joystick")
        self.setAccessibleName("Marcas del joystick ocular")
        self.target = self.token = self.painted = None
        self.zone = None
        self.usable = (True, True)
        self.caption = ""

    def place(self, rect):
        if [self.x(), self.y(), self.width(), self.height()] != list(rect):
            self.setGeometry(*rect)

    def present_target(self, target, token, caption):
        """Calibración: un punto amarillo en el lugar que se está midiendo."""
        state = (target, token, None, (True, True), caption)
        if state != (self.target, self.token, self.zone, self.usable, self.caption):
            self.target, self.token, self.zone, self.usable, self.caption = state
            self.setAccessibleName(f"Objetivo de mirada: {LABELS[target]}")
            self.update()

    def present_live(self, zone, usable, caption):
        """Uso: resalta la dirección que el joystick está reconociendo."""
        state = (None, None, zone, tuple(usable), caption)
        if state != (self.target, self.token, self.zone, self.usable, self.caption):
            self.target, self.token, self.zone, self.usable, self.caption = state
            self.setAccessibleName("Marcas del joystick ocular · " + caption)
            self.update()

    def _point(self, name):
        x, y = TARGETS[name]
        return QPointF(x * self.width(), y * self.height())

    def _label(self, painter, text, center):
        font = QFont(painter.font())
        font.setPixelSize(15)
        font.setBold(True)
        painter.setFont(font)
        width = painter.fontMetrics().horizontalAdvance(text) + 28
        box = QRectF(center.x() - width / 2, center.y() - 16, width, 32)
        box.moveLeft(max(8., min(self.width() - width - 8., box.left())))
        painter.setPen(QPen(QColor("#30465b"), 1))
        painter.setBrush(QColor(9, 18, 32, 225))
        painter.drawRoundedRect(box, 16, 16)
        painter.setPen(QColor("#eaf4ff"))
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)

    def paintEvent(self, event):
        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            if self.target is not None:
                point = self._point(self.target)
                painter.setPen(QPen(QColor(9, 18, 32, 230), 7))
                painter.setBrush(QColor(9, 18, 32, 200))
                painter.drawEllipse(point, 30, 30)
                painter.setPen(QPen(QColor("#ffd477"), 3))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(point, 22, 22)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor("#ffd477"))
                painter.drawEllipse(point, 10, 10)
                if self.caption:
                    below = self.target != "down"
                    self._label(painter, self.caption, point + QPointF(0, 58 if below else -58))
            else:
                radius = 26.
                for name, (dx, dy) in ARROWS.items():
                    point = self._point(name)
                    enabled = self.usable[name in ("up", "down")]
                    active = name == self.zone
                    painter.setPen(QPen(QColor("#57d4c3" if active else "#3d566e" if enabled else "#26323f"), 2))
                    painter.setBrush(QColor(87, 212, 195, 235) if active else QColor(9, 18, 32, 150 if enabled else 70))
                    painter.drawEllipse(point, radius, radius)
                    tip, back, side = radius * .5, radius * .28, radius * .4
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor("#071f26" if active else "#c4d3e8" if enabled else "#4a5868"))
                    painter.drawPolygon(QPolygonF([
                        point + QPointF(dx * tip, dy * tip),
                        point + QPointF(-dx * back - dy * side, -dy * back - dx * side),
                        point + QPointF(-dx * back + dy * side, -dy * back + dx * side)]))
                if self.caption:
                    self._label(painter, self.caption, QPointF(self.width() / 2, self.height() - 68))
        if self.token is not None and self.target is not None and self.token != self.painted:
            self.painted = self.token
            self.displayed.emit(*self.token, self.width(), self.height())
