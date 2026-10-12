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
