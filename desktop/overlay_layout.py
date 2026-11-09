"""Geometría lógica compartida del teclado y la cámara, fuera del tracking."""
import math
import time

from PySide6.QtCore import QObject, QPoint, QRect, QSize, QTimer, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid


def overlap(first, second):
    rect = first.intersected(second)
    return max(0, rect.width()) * max(0, rect.height())


def bounded(rect, area):
    width, height = min(rect.width(), area.width()), min(rect.height(), area.height())
    return QRect(max(area.left(), min(rect.x(), area.right()-width+1)),
                 max(area.top(), min(rect.y(), area.bottom()-height+1)), width, height)


def logical_field(bounds, screens):
    """UIA entrega píxeles físicos. En Windows Qt conserva el origen de cada monitor."""
    if not bounds or len(bounds) != 4 or not all(math.isfinite(v) for v in bounds):
        return None, None
    field = QRect(*map(round, bounds))
    if field.width() <= 0 or field.height() <= 0:
        return None, None
    physical = [QRect(screen.geometry().topLeft(),
                      QSize(round(screen.geometry().width()*screen.devicePixelRatio()),
                            round(screen.geometry().height()*screen.devicePixelRatio()))) for screen in screens]
    if not physical:
        return None, None
    index = max(range(len(screens)), key=lambda i: overlap(field, physical[i]))
    if not overlap(field, physical[index]):
        return None, None
    screen, native = screens[index], physical[index]
    dpr, origin = screen.devicePixelRatio(), screen.geometry().topLeft()
    return screen, QRect(round(origin.x()+(field.x()-native.x())/dpr),
                         round(origin.y()+(field.y()-native.y())/dpr),
                         max(1, round(field.width()/dpr)), max(1, round(field.height()/dpr)))


def resolve_keyboard_size(area, field=None, requested="auto"):
    """Determina la densidad efectiva (compact, normal, large) según resolución y espacio libre."""
    free_vertical = area.height()
    if field is not None:
        above = max(0, field.top() - area.top())
        below = max(0, area.bottom() - field.bottom())
        free_vertical = max(above, below)
    if requested in ("compact", "normal", "large"):
        if field is not None and requested != "compact":
            if free_vertical < 275:
                return "compact"
            if requested == "large" and free_vertical < 330:
                return "normal"
        return requested
    # Modo adaptativo ("auto")
    if area.height() <= 760 or area.width() <= 1366 or (field is not None and free_vertical < 305):
        return "compact"
    return "normal"


def keyboard_rect(area, size, field=None, mode="auto", manual_pos=None):
    """Prueba espacio real arriba/abajo/lateral, y luego minimiza la superposición."""
    safe = area.adjusted(8, 8, -8, -8)
    width, height = min(size.width(), safe.width()), min(size.height(), safe.height())
    center_left = safe.center().x() - width // 2
    if field is not None:
        left = max(safe.left(), min(field.center().x() - width // 2, safe.right() - width + 1))
    else:
        left = center_left
    top = QRect(left, safe.top(), width, height)
    bottom = QRect(left, safe.bottom()-height+1, width, height)
    if mode == "top":
        return top
    if mode == "bottom" or (field is None and mode != "manual"):
        return QRect(center_left, safe.bottom()-height+1, width, height) if field is None else bottom
    if mode == "manual" and manual_pos is not None:
        pt = manual_pos if isinstance(manual_pos, QPoint) else QPoint(int(manual_pos[0]), int(manual_pos[1]))
        manual_rect = bounded(QRect(pt.x(), pt.y(), width, height), safe)
        if field is None:
            return manual_rect
        protected = field.adjusted(-8, -12, 8, 12).intersected(safe)
        if overlap(manual_rect, protected) == 0:
            return manual_rect
    if field is None:
        return QRect(center_left, safe.bottom()-height+1, width, height)
    protected = field.adjusted(-8, -12, 8, 12).intersected(safe)
    above, below = protected.top()-safe.top(), safe.bottom()-protected.bottom()
    candidates = [bottom, top]
    # En campos centrales puede haber un hueco accesible entre el borde y el campo.
    if above >= height:
        candidates.append(QRect(left, protected.top()-height, width, height))
    if below >= height:
        candidates.append(QRect(left, protected.bottom()+1, width, height))
    if above < height and below < height:
        left_space = protected.left() - safe.left()
        right_space = safe.right() - protected.right()
        v_mid = max(safe.top(), min(protected.center().y() - height // 2, safe.bottom() - height + 1))
        if left_space >= width:
            candidates.append(QRect(protected.left() - width, v_mid, width, height))
        if right_space >= width:
            candidates.append(QRect(protected.right() + 1, v_mid, width, height))
        candidates.append(QRect(safe.left(), safe.bottom()-height+1, width, height))
        candidates.append(QRect(safe.right()-width+1, safe.bottom()-height+1, width, height))
    return min(candidates, key=lambda r: (overlap(r, protected),
               -(below if r.center().y() > protected.center().y() else above),
               min(abs(r.top()-safe.top()), abs(safe.bottom()-r.bottom()))))


CORNERS = ("bottom_right", "top_left", "top_right", "bottom_left")
OPPOSITE = dict(bottom_right="top_left", top_left="bottom_right", top_right="bottom_left", bottom_left="top_right")


class CameraPlacement:
    def __init__(self):
        self.current = None
        self.clear_since = None
        self.last_move = -math.inf
        self.context = None

    def place(self, area, size, preferred, intelligent, delay, cursor, obstacles, now):
        context = (area.getRect(), size.width(), size.height(), preferred, intelligent)
        if context != self.context:
            self.context, self.current, self.clear_since = context, preferred, None
        safe = area.adjusted(12, 12, -12, -12)
        width, height = min(size.width(), safe.width()), min(size.height(), safe.height())
        corners = {name: QRect(safe.left() if name.endswith("left") else safe.right()-width+1,
                              safe.top() if name.startswith("top") else safe.bottom()-height+1,
                              width, height) for name in CORNERS}
        def blocked(name, margin=24):
            return corners[name].adjusted(-margin,-margin,margin,margin).contains(cursor)
        def obstruction(name):
            return sum(overlap(corners[name], rect.adjusted(-8,-8,8,8)) * 100**(len(obstacles)-i-1)
                       for i,rect in enumerate(obstacles))
        if not intelligent:
            self.current = min([preferred,*CORNERS], key=obstruction)
            return corners[self.current]
        home_clear = not blocked(preferred, 48) and obstruction(preferred) == 0
        if home_clear:
            if self.clear_since is None:
                self.clear_since = now
        else:
            self.clear_since = None
        current_blocked = blocked(self.current) or obstruction(self.current) > 0
        returning = self.current != preferred and home_clear and now-self.clear_since >= delay
        if (current_blocked or returning) and now-self.last_move >= .6:
            order = [preferred] if returning else [OPPOSITE[preferred], *CORNERS]
            candidate = min(order, key=lambda name: (obstruction(name), blocked(name), order.index(name)))
            if candidate != self.current:
                self.current, self.last_move = candidate, now
        return corners[self.current]


class OverlayCoordinator(QObject):
    """Un único árbitro. El teclado reserva su rectángulo y la cámara lo respeta."""
    WIDTH_SPECS = {
        "compact": (0.60, 480, 800),
        "normal":  (0.68, 520, 920),
        "large":   (0.82, 580, 1140),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.keyboard = self.camera = None
        self.field = None
        self.keyboard_screen = None
        self.camera_screen = None
        self.camera_options = {}
        self.keyboard_key = None
        self.last_bounds = None
        self.manual_pos = None
        self.effective_size = "normal"
        self.camera_placement = CameraPlacement()
        self.camera_moves = 0
        self.keyboard_moves = 0
        self.camera_target = None
        self.animation = None
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.update_camera)

    def set_manual_position(self, pos):
        self.manual_pos = (int(pos.x()), int(pos.y())) if hasattr(pos, "x") else (int(pos[0]), int(pos[1]))
        self.keyboard_key = None

    def place_keyboard(self, widget, state):
        self.keyboard = widget
        screens = QApplication.screens()
        screen, field = logical_field(state.get("bounds"), screens)
        screen = screen or self.keyboard_screen or QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        if screen not in screens:
            screen = QApplication.primaryScreen()
        bounds = field.getRect() if field else None
        # Ignorar el pequeño jitter de providers UIA. No se usa el cursor de texto para mover el teclado.
        stable = (bounds is not None and self.last_bounds is not None and
                  max(abs(a-b) for a,b in zip(bounds,self.last_bounds)) < 24)
        if stable:
            bounds = self.last_bounds
            field = QRect(*bounds)
        area = screen.availableGeometry()
        effective = resolve_keyboard_size(area, field, state.get("size", "auto"))
        preview_expanded = getattr(widget, "is_preview_expanded", lambda: False)()
        key = (state.get("target"), bounds, screen.geometry().getRect(), area.getRect(),
               screen.devicePixelRatio(), state.get("size"), effective, state.get("position"),
               state.get("show_preview"), state.get("preview_mode"), preview_expanded,
               state.get("suggestions", True), self.manual_pos)
        if key != self.keyboard_key or not widget.isVisible():
            self.keyboard_key, self.last_bounds = key, bounds
            self.field, self.keyboard_screen = field, screen
            self.effective_size = effective
            if hasattr(widget, "apply_effective_size"):
                widget.apply_effective_size(effective)
            ratio, min_w, max_w = self.WIDTH_SPECS.get(effective, self.WIDTH_SPECS["normal"])
            desired_w = min(max_w, max(min_w, round(area.width() * ratio)))
            width = min(area.width()-16, max(widget.minimumSizeHint().width(), desired_w))
            height = min(area.height()-16, widget.sizeHint().height())
            pos_mode = state.get("position", "auto")
            rect = keyboard_rect(area, QSize(width,height), field, pos_mode, self.manual_pos)
            # Si aún hay superposición en modo normal/large, probar densidad compacta automáticamente
            if field and overlap(field, rect) and effective != "compact" and hasattr(widget, "apply_effective_size"):
                effective = "compact"
                self.effective_size = effective
                widget.apply_effective_size(effective)
                ratio, min_w, max_w = self.WIDTH_SPECS["compact"]
                desired_w = min(max_w, max(min_w, round(area.width() * ratio)))
                width = min(area.width()-16, max(widget.minimumSizeHint().width(), desired_w))
                height = min(area.height()-16, widget.sizeHint().height())
                rect = keyboard_rect(area, QSize(width,height), field, pos_mode, self.manual_pos)
            if widget.geometry() != rect:
                widget.setGeometry(rect)
                self.keyboard_moves += 1
            widget.setToolTip("El campo ocupa la zona disponible. La vista previa muestra sólo tu composición." if
                              field and overlap(field,rect) else "")
        self.update_camera()

    def present_camera(self, camera, screen, options):
        changed = self.camera_screen != screen or self.camera_options != options
        self.camera, self.camera_screen, self.camera_options = camera, screen, options
        if changed or not self.timer.isActive():self.update_camera()
        if not self.timer.isActive():
            self.timer.start()

    def update_camera(self):
        if self.camera is None or not isValid(self.camera):
            self.camera=None
            self.timer.stop()
            return
        if not self.camera.isVisible():
            self.timer.stop()
            return
        screens = QApplication.screens()
        screen = self.camera_screen if self.camera_screen in screens else QApplication.primaryScreen()
        options = self.camera_options
        area = screen.availableGeometry()
        size = QSize(*{"compact":(280,240),"normal":(304,268),"large":(384,320)}.get(options.get("size"),(304,268)))
        obstacles = []
        if self.keyboard is not None and isValid(self.keyboard):
            if self.keyboard.isVisible():
                obstacles.append(self.keyboard.geometry())
            handle = getattr(self.keyboard,"restore_handle",None)
            if handle is not None and isValid(handle) and handle.isVisible():
                obstacles.append(handle.geometry())
            if self.field:
                obstacles.append(self.field)
        rect = self.camera_placement.place(area, size, options.get("corner","bottom_right"),
                options.get("avoid",True), options.get("delay",1.), QCursor.pos(), obstacles, time.monotonic())
        if self.camera_target != rect:
            first = self.camera_target is None or self.camera.size()!=rect.size()
            self.camera_target=QRect(rect)
            if self.animation is None:
                self.animation=QPropertyAnimation(self.camera,b"pos",self)
                self.animation.setDuration(120)
                self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            self.animation.stop()
            self.camera.resize(rect.size())
            if first:
                self.camera.move(rect.topLeft())
            else:
                self.animation.setStartValue(self.camera.pos())
                self.animation.setEndValue(rect.topLeft())
                self.animation.start()
            self.camera_moves += 1

    def stop(self):
        self.timer.stop()
        if self.animation is not None and isValid(self.animation):self.animation.stop()
        self.camera=self.keyboard=None
        self.field=None
