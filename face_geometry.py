"""Geometría facial pura sobre landmarks de MediaPipe; sin cámara ni numpy.

Los landmarks llegan normalizados: x por el ancho, y por el alto (hacia abajo)
y z con aproximadamente la escala de x (menor = más cerca de la cámara).
`brow_lift_2d` es la señal GEOMETRIC histórica. `brow_lift_3d` mide lo mismo
en el sistema de referencia de la propia cara, construido con puntos rígidos
(comisuras de los ojos y tabique nasal), por lo que no depende de cuánto se
inclina o gira la cabeza respecto de la cámara.
"""
import math

BROW_LEFT = (70, 63, 105, 66, 107)
BROW_RIGHT = (336, 296, 334, 293, 300)
EYE_LEFT = (33, 133)    # comisura externa, interna (mismo lado que BROW_LEFT)
EYE_RIGHT = (263, 362)
MOUTH_POINTS = (61, 291, 13, 14, 0, 17)  # comisuras y centro superior/inferior de labios
MOUTH_HALF_WIDTH_REF = 0.255  # semiancho mínimo de referencia (sobre IOD) para exigir arrastre de comisura opuesta
NOSE_BRIDGE, SUBNASALE = 6, 2
EAR_LEFT, EAR_RIGHT = 234, 454


def _sub(a, b): return (a[0]-b[0], a[1]-b[1], a[2]-b[2])
def _dot(a, b): return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]
def _scale(a, k): return (a[0]*k, a[1]*k, a[2]*k)
def _norm(a): return math.sqrt(_dot(a, a))
def _cross(a, b): return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


def _mean(points):
    n = len(points)
    return tuple(sum(p[i] for p in points) / n for i in range(3))


def brow_lift_2d(lms):
    """Señal GEOMETRIC: comisura externa menos ceja, en y de imagen, sobre la
    distancia horizontal entre orejas. Cambia con pitch y yaw."""
    scale = abs(lms[EAR_LEFT].x - lms[EAR_RIGHT].x)
    if scale <= 1e-6:
        return None
    left = (lms[EYE_LEFT[0]].y - sum(lms[i].y for i in BROW_LEFT) / len(BROW_LEFT)) / scale
    right = (lms[EYE_RIGHT[0]].y - sum(lms[i].y for i in BROW_RIGHT) / len(BROW_RIGHT)) / scale
    return float(left), float(right)


def face_frame(lms, width, height):
    """Ejes de la cara (derecha de la imagen, arriba, normal) y distancia
    interocular, en un espacio con x, y, z en la misma escala (píxeles)."""
    def point(i):
        p = lms[i]
        return (p.x * width, p.y * height, p.z * width)
    across = _sub(point(EYE_RIGHT[0]), point(EYE_LEFT[0]))
    iod = _norm(across)
    up = _sub(point(NOSE_BRIDGE), point(SUBNASALE))  # y de imagen crece hacia abajo
    if iod <= 1e-6 or _norm(up) <= 1e-6:
        return None
    x_axis = _scale(across, 1 / iod)
    up = _sub(up, _scale(x_axis, _dot(up, x_axis)))
    if _norm(up) <= 1e-6:
        return None
    y_axis = _scale(up, 1 / _norm(up))
    return point, x_axis, y_axis, _cross(x_axis, y_axis), iod


def brow_lift_3d(lms, width, height):
    """Elevación de cada ceja sobre el centro del ojo del mismo lado, medida
    sobre el eje vertical de la cara y dividida por la distancia interocular 3D."""
    frame = face_frame(lms, width, height)
    if frame is None:
        return None
    point, _, y_axis, _, iod = frame
    def lift(brow, eye):
        delta = _sub(_mean([point(i) for i in brow]), _mean([point(i) for i in eye]))
        return _dot(delta, y_axis) / iod
    return float(lift(BROW_LEFT, EYE_LEFT)), float(lift(BROW_RIGHT, EYE_RIGHT))


def head_pose(lms, width, height):
    """Pitch, yaw y roll aproximados en grados. Pitch positivo = mirar hacia
    arriba (la frente se aleja de la cámara). El pitch se mide sobre la línea
    del tabique, que tiene una inclinación anatómica propia: usarlo relativo al
    reposo. Solo se registran; el cursor sigue usando la nariz."""
    frame = face_frame(lms, width, height)
    if frame is None:
        return None
    _, x_axis, y_axis, _, _ = frame
    pitch = math.degrees(math.atan2(y_axis[2], -y_axis[1]))
    yaw = math.degrees(math.atan2(x_axis[2], x_axis[0]))
    roll = math.degrees(math.atan2(x_axis[1], x_axis[0]))
    return pitch, yaw, roll


def mouth_shift(lms, width=1.0, height=1.0):
    """Desplazamiento lateral de los labios (izquierda, derecha del usuario >= 0)
    respecto al centro rígido entre ambos ojos, normalizado por la distancia
    interocular. En el frame espejado de VisionEngine, mover los labios hacia la
    izquierda del usuario desplaza la boca hacia -x_axis (dx < 0)."""
    eyes = EYE_LEFT + EYE_RIGHT
    indices = eyes + (NOSE_BRIDGE, SUBNASALE) + MOUTH_POINTS
    has_3d = all(isinstance(getattr(lms[i], "z", None), (int, float))
                 and not isinstance(getattr(lms[i], "z", None), bool)
                 and math.isfinite(lms[i].z) for i in indices)
    if has_3d:
        frame = face_frame(lms, width, height)
        if frame is not None:
            point, x_axis, _, _, iod = frame
            eye_mid = _mean([point(i) for i in eyes])
            mouth_mid = _mean([point(i) for i in MOUTH_POINTS])
            dx = _dot(_sub(mouth_mid, eye_mid), x_axis) / iod
            # Exigir también desplazamiento interno de la comisura opuesta: al guiñar
            # un ojo la mejilla estira solo la comisura ipsilateral sin mover toda la boca.
            c_left = _dot(_sub(point(61), eye_mid), x_axis) / iod
            c_right = _dot(_sub(point(291), eye_mid), x_axis) / iod
            left = min(max(0.0, -dx), max(0.0, MOUTH_HALF_WIDTH_REF - c_right))
            right = min(max(0.0, dx), max(0.0, c_left + MOUTH_HALF_WIDTH_REF))
            return float(left), float(right)
    ax = (lms[EYE_RIGHT[0]].x - lms[EYE_LEFT[0]].x) * width
    ay = (lms[EYE_RIGHT[0]].y - lms[EYE_LEFT[0]].y) * height
    iod2d = math.hypot(ax, ay)
    if iod2d <= 1e-6:
        return None
    ux, uy = ax / iod2d, ay / iod2d
    ex = sum(lms[i].x for i in eyes) / len(eyes) * width
    ey = sum(lms[i].y for i in eyes) / len(eyes) * height
    mx = sum(lms[i].x for i in MOUTH_POINTS) / len(MOUTH_POINTS) * width
    my = sum(lms[i].y for i in MOUTH_POINTS) / len(MOUTH_POINTS) * height
    dx = ((mx - ex) * ux + (my - ey) * uy) / iod2d
    c_left = ((lms[61].x * width - ex) * ux + (lms[61].y * height - ey) * uy) / iod2d
    c_right = ((lms[291].x * width - ex) * ux + (lms[291].y * height - ey) * uy) / iod2d
    left = min(max(0.0, -dx), max(0.0, MOUTH_HALF_WIDTH_REF - c_right))
    right = min(max(0.0, dx), max(0.0, c_left + MOUTH_HALF_WIDTH_REF))
    return float(left), float(right)
