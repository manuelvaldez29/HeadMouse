"""Geometría ocular pura. Coordenadas relativas; sin MediaPipe, Qt ni persistencia."""
import math

# Lados históricos del proyecto (en el preview), no lateralidad anatómica.
EYES = {"left": (33, 133, 159, 145, 468, (469, 470, 471, 472)),
        "right": (362, 263, 386, 374, 473, (474, 475, 476, 477))}


def extract_gaze(landmarks, width, height, *, mirrored=True):
    """Normaliza iris en la base comisuras/párpados. +X: derecha del usuario.

    `mirrored` describe la imagen ENTRADA al detector. VisionEngine ya la espeja.
    La confianza expresa cobertura (1 ambos, .5 uno), no probabilidad del modelo.
    """
    result = dict(left_gaze_x=None, left_gaze_y=None, right_gaze_x=None,
                  right_gaze_y=None, gaze_x=None, gaze_y=None,
                  gaze_confidence=0., iris_points=())
    result["gaze_mirrored"] = mirrored
    if not all(isinstance(v, (int, float)) and math.isfinite(v) and v > 0 for v in (width, height)):
        return result
    values, preview, diagnostics = [], [], []
    result.update(left_canthi_y=None,right_canthi_y=None,ocular_geometry=())
    for side, (a, b, upper, lower, center, ring) in EYES.items():
        try:
            def point(index):
                p = landmarks[index]
                if not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                           and math.isfinite(v) and 0 <= v <= 1 for v in (p.x, p.y)):
                    raise ValueError("Landmark ocular inválido")
                return p.x * width, p.y * height
            c1, c2 = sorted((point(a), point(b)))
            top, bottom, iris = point(upper), point(lower), point(center)
            for index in ring:
                point(index)
            h = (c2[0]-c1[0], c2[1]-c1[1])
            v = (bottom[0]-top[0], bottom[1]-top[1])
            cross = lambda p, q: p[0]*q[1]-p[1]*q[0]
            det = cross(h, v)
            size = math.hypot(*h)
            mid=((c1[0]+c2[0])/2,(c1[1]+c2[1])/2)
            canthi=.5+cross(h,(iris[0]-mid[0],iris[1]-mid[1]))/(size*size) if size else None
            lid_y=cross(h,(iris[0]-top[0],iris[1]-top[1]))/det if det else None
            diagnostics.append((side,iris[0],iris[1],top[0],top[1],bottom[0],bottom[1],
                                c1[0],c1[1],c2[0],c2[1],size,det,lid_y,canthi))
            # Ojo cerrado/degenerado: no dividir por una apertura casi nula.
            if size < 2 or det <= .08 * size * size:
                continue
            x = cross((iris[0]-c1[0], iris[1]-c1[1]), v) / det
            y = cross(h, (iris[0]-top[0], iris[1]-top[1])) / det
            if not (0 <= x <= 1 and 0 <= y <= 1):
                continue
            x = x if mirrored else 1-x
            result[f"{side}_gaze_x"], result[f"{side}_gaze_y"] = x, y
            if canthi is not None and 0 <= canthi <= 1:
                result[f"{side}_canthi_y"]=canthi
            values.append((x, y))
            preview.append((iris[0]/width, iris[1]/height))
        except (IndexError, AttributeError, TypeError, ValueError, OverflowError):
            continue
    if values:
        result.update(gaze_x=sum(p[0] for p in values)/len(values),
                      gaze_y=sum(p[1] for p in values)/len(values),
                      gaze_confidence=len(values)/2, iris_points=tuple(preview))
    result["ocular_geometry"]=tuple(diagnostics)
    return result
