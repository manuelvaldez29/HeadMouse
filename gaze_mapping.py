"""Calibración local: extracción, ajuste, validación independiente y predicción.

No importa Qt, cámara ni backend del mouse. Los datos de fijación viven en RAM;
el perfil conserva coeficientes, dominios y estadísticas, nunca imágenes.
"""
from copy import deepcopy
import math
import time
import numpy as np
from config import bounded
from gaze_source import (eye_coordinates, feature_gaze, selected_eyes_open, validate_source, SOURCE_LABELS)

TRAIN_TARGETS = tuple((x, y) for y in (.1, .5, .9) for x in (.1, .5, .9))
VALIDATION_TARGETS = ((.3, .3), (.7, .3), (.3, .7), (.7, .7), (.5, .3))
CONTEXT_KEYS = ("width", "height", "dpr", "screen", "camera_index", "frame_width", "frame_height")


def validate_context(context):
    if not isinstance(context, dict) or not set(CONTEXT_KEYS) <= set(context) or set(context)-set(CONTEXT_KEYS)-{"display"}:
        raise ValueError("Faltan condiciones de pantalla/cámara")
    for key in ("width", "height", "frame_width", "frame_height"):
        bounded(key, context[key], 2, 100000, integer=True)
    bounded("dpr", context["dpr"], .5, 8)
    bounded("camera_index", context["camera_index"], 0, 100, integer=True)
    if not isinstance(context["screen"], str) or not context["screen"]:
        raise ValueError("Falta identificar la pantalla")
    if "display" in context:
        from screen_mapping import screen_display
        screen_display(context)
    return context


def features(face, eye_source="both",vertical_reference="eyelids"):
    """Iris seleccionados + envolvente facial, sin dependencia del ojo descartado."""
    ocular = eye_coordinates(face, eye_source,vertical_reference)
    if ocular is None:
        return None
    return np.array([*ocular, face.nose_x, face.nose_y, face.face_scale,
                     *(v if v is not None else 0. for v in
                       (face.head_yaw, face.head_pitch, face.head_roll))], dtype=float)


def design(values, degree):
    x, y = values[..., 0], values[..., 1]
    columns = [np.ones_like(x), x, y]
    if degree == 2:
        columns += [x*x, x*y, y*y]
    return np.stack(columns, axis=-1)


class GazeModel:
    def __init__(self, record):
        try:
            self.record = deepcopy(record)
            if type(record["schema_version"]) is not int or record["schema_version"] not in (1, 2) or record["method"] != "eye_absolute":
                raise ValueError("Modelo ocular desconocido")
            self.eye_source = validate_source(record.get("eye_source", "both"))
            if record["schema_version"] == 1 and self.eye_source != "both":
                raise ValueError("Un modelo histórico es exclusivamente binocular")
            if record["schema_version"] == 2 and "eye_source" not in record:
                raise ValueError("Falta fuente ocular del modelo")
            self.feature_count = 10 if self.eye_source == "both" else 8
            validate_context(record["context"])
            self.degree = record["degree"]
            if type(self.degree) is not int or self.degree not in (1, 2):
                raise ValueError("Grado inválido")
            self.center = np.asarray(record["center"], dtype=float)
            self.scale = np.asarray(record["scale"], dtype=float)
            self.coefficients = np.asarray(record["coefficients"], dtype=float)
            self.lower = np.asarray(record["lower"], dtype=float)
            self.upper = np.asarray(record["upper"], dtype=float)
            if (self.center.shape != (2,) or self.scale.shape != (2,) or
                self.coefficients.shape != (3 if self.degree == 1 else 6, 2) or
                self.lower.shape != (self.feature_count,) or self.upper.shape != (self.feature_count,) or
                np.any(self.scale < .01) or np.any(self.lower > self.upper) or
                not all(np.isfinite(a).all() for a in
                        (self.center, self.scale, self.coefficients, self.lower, self.upper))):
                raise ValueError("Coeficientes/dominio inválidos")
            if type(record.get("validated")) is not bool:
                raise ValueError("Falta estado de validación")
            if record["validated"]:
                report = record["validation"]
                if not isinstance(report, dict) or report.get("passed") is not True or len(report["points"]) != len(VALIDATION_TARGETS):
                    raise ValueError("Falta validación independiente")
                for point, target in zip(report["points"], VALIDATION_TARGETS):
                    if tuple(point["target"]) != target:
                        raise ValueError("Objetivos de validación incompatibles")
                    for key in ("error_mean_px", "error_x_px", "error_y_px", "jitter_rms_px", "drift_px", "latency_ms"):
                        bounded(key, point[key], 0, 1000000)
                diagonal = math.hypot(record["context"]["width"], record["context"]["height"])
                if np.mean([p["error_mean_px"] for p in report["points"]]) > .10*diagonal or max(p["error_mean_px"] for p in report["points"]) > .18*diagonal:
                    raise ValueError("El error de validación supera el límite")
        except (KeyError, TypeError, OverflowError) as exc:
            raise ValueError("Modelo ocular incompleto") from exc

    @classmethod
    def fit(cls, point_features, targets, context, eye_source="both"):
        validate_context(context)
        validate_source(eye_source)
        ocular_count = 4 if eye_source == "both" else 2
        rows, targets = np.asarray(point_features, dtype=float), np.asarray(targets, dtype=float)
        if rows.shape != (9, ocular_count+6) or targets.shape != (9, 2) or not np.isfinite(rows).all() or not np.isfinite(targets).all():
            raise ValueError("Se requieren nueve fijaciones válidas")
        if not np.allclose(targets, TRAIN_TARGETS):
            raise ValueError("Objetivos de ajuste incompatibles")
        gaze = feature_gaze(rows, eye_source)
        center, scale = np.mean(gaze, axis=0), np.ptp(gaze, axis=0)/2
        if np.any(scale < .025):
            raise ValueError("Rango ocular insuficiente: repetí la calibración")
        z = (gaze-center)/scale
        candidates = []
        # Elegir complejidad por leave-one-target-out; no por error de entrenamiento.
        for degree in (1, 2):
            matrix = design(z, degree)
            if np.linalg.matrix_rank(matrix) < matrix.shape[1]:
                continue
            penalty = np.eye(matrix.shape[1])*.01
            penalty[0, 0] = 0
            errors = []
            for i in range(9):
                mask = np.arange(9) != i
                a, b = matrix[mask], targets[mask]
                coeff = np.linalg.solve(a.T@a+penalty, a.T@b)
                errors.append(float(np.sum((matrix[i]@coeff-targets[i])**2)))
            candidates.append((float(np.mean(errors)), degree, matrix, penalty))
        if not candidates:
            raise ValueError("Fijaciones degeneradas: repetí posiciones")
        best = min(candidates, key=lambda c: c[0])
        linear = next((c for c in candidates if c[1] == 1), best)
        # Exigir una mejora de 10% para justificar el término cuadrático.
        if best[1] == 2 and best[0] >= .9*linear[0]:
            best = linear
        score, degree, matrix, penalty = best
        coeff = np.linalg.solve(matrix.T@matrix+penalty, matrix.T@targets)
        # Márgenes de abstención, no coeficientes de compensación inventados.
        margin = np.array([.06]*ocular_count+[.06, .06, max(.02, float(np.median(rows[:, ocular_count+2]))*.25), 10., 10., 10.])
        record = dict(schema_version=2, method="eye_absolute", degree=degree, eye_source=eye_source,
                      center=center.tolist(), scale=scale.tolist(), coefficients=coeff.tolist(),
                      lower=(rows.min(axis=0)-margin).tolist(), upper=(rows.max(axis=0)+margin).tolist(),
                      context=deepcopy(context), validated=False, validation=None,
                      cross_validation_rmse_normalized=math.sqrt(score), ridge=.01)
        return cls(record)

    def predict_features(self, row):
        row = np.asarray(row, dtype=float)
        if row.shape != (self.feature_count,) or not np.isfinite(row).all() or np.any(row < self.lower) or np.any(row > self.upper):
            return None
        gaze = feature_gaze(row, self.eye_source)
        prediction = design((gaze-self.center)/self.scale, self.degree)@self.coefficients
        if not np.isfinite(prediction).all() or np.any(prediction < -.05) or np.any(prediction > 1.05):
            return None
        return tuple(float(v) for v in np.clip(prediction, 0, 1))

    def predict(self, face):
        row = features(face, self.eye_source)
        return self.predict_features(row) if row is not None else None


class GazeCalibrationSession:
    """9 puntos de ajuste + 5 objetivos independientes. Reloj inyectable."""
    def __init__(self, context, clock=time.monotonic, stale_after_s=.25,
                 countdown_s=1.5, settle_s=.6, duration_s=1., min_samples=20,
                 eye_limits=(.045, .045), relative=False, eye_source="both",vertical_reference="eyelids"):
        from gaze_source import validate_vertical_reference
        self.vertical_reference=validate_vertical_reference(vertical_reference) if relative else "eyelids"
        self.eye_source = validate_source(eye_source)
        self.ocular_count = 4 if eye_source == "both" else 2
        self.context = deepcopy(validate_context(context))
        self.clock, self.stale_after_s = clock, stale_after_s
        self.countdown_s, self.settle_s, self.duration_s = countdown_s, settle_s, duration_s
        self.min_samples, self.eye_limits, self.relative = min_samples, eye_limits, relative
        self.targets = ((.5, .5), (.1, .5), (.9, .5), (.5, .1), (.5, .9)) if relative else TRAIN_TARGETS
        self.points, self.validation_points = {}, {}
        self.rows, self.last_timestamp, self.rejected = [], 0, 0
        # Capturar primero el neutral, también en el ajuste absoluto. Los índices
        # siguen siendo los de TRAIN_TARGETS para el ajuste y la persistencia.
        self.center_index = 0 if relative else 4
        self.index, self.phase = self.center_index, "training"
        self.model = None
        self.rejected_points = {}
        self.last_check = None
        self.head_stable=None
        self.revision = 0
        self.accept_after = 0
        self.state, self.message = "countdown", "Mirá el objetivo. Control real desactivado."
        self.started = clock()

    def repeat(self, index=None):
        targets = self.targets if self.phase == "training" else VALIDATION_TARGETS
        index = self.index if index is None else index
        if type(index) is not int or not 0 <= index < len(targets):
            raise ValueError("Punto inválido")
        self.index = index
        self.revision += 1
        (self.points if self.phase == "training" else self.validation_points).pop(index, None)
        if self.phase == "training":
            self.model = None
            self.validation_points.clear()
        elif self.model:
            self.model.record.update(validated=False, validation=None)
        self.rows, self.rejected = [], 0
        self.head_stable=None
        self.last_timestamp = 0
        self.started = self.clock()
        self.state, self.message = "countdown", "Repetí la fijación en el objetivo."

    def _point_problem(self, index, point, validation=False):
        """Convención de pantalla: +X derecha, +Y abajo; nunca corregir con abs()."""
        center = point if not validation and index == self.center_index else self.points.get(self.center_index)
        if center is None:
            return "Falta el neutral: repetí primero el punto central."
        row = np.asarray(point["features"], dtype=float)
        base = np.asarray(center["features"], dtype=float)
        gaze, neutral = feature_gaze(row, self.eye_source), feature_gaze(base, self.eye_source)
        delta = gaze-neutral
        expected = np.sign(np.asarray(point["target"])-.5)
        # El mínimo .02 pertenece exclusivamente a TrackingCalibration.
        # En absoluto la excursión global se comprueba en GazeModel.fit (.025
        # de semirrango); cada fijación debe superar su propia dispersión.
        minimum = max(.02 if self.relative else np.finfo(float).eps,
                      point["spread"], center["spread"])
        point["direction_check"] = dict(gaze=gaze.tolist(), neutral=neutral.tolist(),
            delta=delta.tolist(), expected=expected.tolist(), minimum=minimum,
            target=point["target"], point_index=index, phase="validation" if validation else "training",
            selected_coordinates=row[:self.ocular_count].tolist(),
            selected_delta=(row[:self.ocular_count]-base[:self.ocular_count]).tolist())
        self.last_check = deepcopy(point["direction_check"])
        if self.relative and np.any((neutral < .05) | (neutral > .95)):
            return "Neutral fuera del dominio válido [0.05, 0.95]. Repetí el punto central."
        # Misma envolvente de postura que el dominio absoluto: no atribuir a
        # los ojos un desplazamiento importante de cabeza/escala.
        head = row[self.ocular_count:]-base[self.ocular_count:]
        limits = np.array([.06, .06, max(.02, float(base[self.ocular_count+2])*.25), 10., 10., 10.])
        if np.any(np.abs(head) > limits):
            self.head_stable=False
            return "La cabeza cambió respecto del neutral. Repetí este punto manteniendo la cabeza estable."
        for axis, names in enumerate((("izquierda", "derecha"), ("arriba", "abajo"))):
            sign = expected[axis]
            if not sign:
                continue
            direction = names[int(sign > 0)]
            measured = float(sign*delta[axis])
            if measured < 0:
                return f"La señal hacia {direction} no coincide con la dirección esperada (Δ{'XY'[axis]}={delta[axis]:+.6f}). Repetí este punto con la cabeza estable."
            if measured < minimum:
                return f"Movimiento hacia {direction} insuficiente ({measured:.6f}; mínimo {minimum:.6f}). Repetí este punto manteniendo la cabeza estable."
        return None

    def _relative_result(self):
        from tracking_calibration import TrackingCalibration
        gaze = [feature_gaze(np.asarray(self.points[i]["features"]), self.eye_source) for i in range(5)]
        x, y = gaze[0]
        return TrackingCalibration(neutral_x=float(x), neutral_y=float(y),
            left_range=float(x-gaze[1][0]), right_range=float(gaze[2][0]-x),
            up_range=float(y-gaze[3][1]), down_range=float(gaze[4][1]-y), ranges_measured=True,
            eye_source=self.eye_source,
            vertical_reference=self.vertical_reference,
            camera_context={key:self.context[key] for key in ("camera_index", "frame_width", "frame_height")}).record()

    def _reject_point(self, index, point, message):
        self.rejected_points[index] = deepcopy(point) | dict(reason=message)
        self.index, self.state, self.message = index, "invalid", message

    def update(self, face):
        if self.state in ("ready", "error", "invalid"):
            return
        elapsed = self.clock()-self.started
        if elapsed < self.countdown_s:
            self.state = "countdown"
            return
        if elapsed < self.countdown_s+self.settle_s:
            self.state = "settling"
            return
        self.state = "capturing"
        if elapsed > self.countdown_s+self.settle_s+15:
            self.state, self.message = "error", f"Tiempo agotado para este objetivo. {self.message} Repetí sólo este punto."
            return
        if face.timestamp_ms <= self.last_timestamp:
            self.message="Esperando frames nuevos de la cámara. Si no llegan, revisá la conexión y repetí este objetivo."
            return
        gap = self.last_timestamp and face.timestamp_ms-self.last_timestamp > self.stale_after_s*1000
        self.last_timestamp = face.timestamp_ms
        row = features(face, self.eye_source,self.vertical_reference)
        if (gap or not face.fresh(self.stale_after_s, self.clock()) or row is None or
            not selected_eyes_open(face, self.eye_source, self.eye_limits)):
            self.rows.clear()
            self.head_stable=None
            self.rejected += 1
            self.accept_after = face.timestamp_ms+180
            if gap or not face.fresh(self.stale_after_s,self.clock()):
                self.message="Los datos de cámara están atrasados. Esperando frames recientes."
            elif row is None:
                self.message="No veo el iris seleccionado. Mirá al objetivo con la cara dentro de la imagen."
            else:
                self.message="Parpadeo detectado. Mantené los ojos elegidos abiertos; la captura se reinicia sola."
            return
        if face.timestamp_ms < self.accept_after:
            return
        self.rows.append((face.timestamp_ms, row, face.processing_ms))
        while len(self.rows) > self.min_samples and self.rows[1][0] < face.timestamp_ms-self.duration_s*1000:
            self.rows.pop(0)
        if len(self.rows)>=5:
            head=np.array([r[1][self.ocular_count:] for r in self.rows])
            limits=np.array([.06,.06,max(.02,float(np.median(head[:,2]))*.25),10.,10.,10.])
            self.head_stable=bool(np.all(np.percentile(head,90,axis=0)-np.percentile(head,10,axis=0)<=limits))
        if len(self.rows) < self.min_samples or self.rows[-1][0]-self.rows[0][0] < self.duration_s*1000-1:
            return
        rows = np.array([r[1] for r in self.rows])
        spread = float(np.max(np.percentile(rows[:, :self.ocular_count], 90, axis=0)-np.percentile(rows[:, :self.ocular_count], 10, axis=0)))
        if spread > .10:
            self.message = "Fijación inestable: mantené la mirada; podés repetir el punto."
            return
        head_rows = rows[:, self.ocular_count:]
        head_limits = np.array([.06, .06, max(.02, float(np.median(head_rows[:, 2]))*.25), 10., 10., 10.])
        self.head_stable=bool(np.all(np.percentile(head_rows, 90, axis=0)-np.percentile(head_rows, 10, axis=0) <= head_limits))
        if not self.head_stable:
            self.message = "Cabeza inestable durante la fijación: mantenela quieta o repetí este punto."
            return
        target = (self.targets if self.phase == "training" else VALIDATION_TARGETS)[self.index]
        point = dict(target=list(target), features=np.median(rows, axis=0).tolist(),
                     samples=len(rows), spread=spread, quality=max(0., 1-spread/.10), rejected=self.rejected,
                     first_timestamp_ms=self.rows[0][0], last_timestamp_ms=self.rows[-1][0])
        if self.phase == "training":
            problem = self._point_problem(self.index, point)
            if problem:
                self._reject_point(self.index, point, problem)
                return
            self.points[self.index] = point
            self.rejected_points.pop(self.index, None)
            if self.index == self.center_index:
                # Un neutral repetido puede volver incompatibles fijaciones
                # previas. Retener únicamente las que todavía cumplen.
                for index, previous in list(self.points.items()):
                    problem = self._point_problem(index, previous)
                    if problem:
                        self.rejected_points[index] = deepcopy(previous) | dict(reason=problem)
                        del self.points[index]
        else:
            problem = self._point_problem(self.index, point, validation=True)
            if problem:
                self._reject_point(self.index, point, problem)
                return
            predicted = [self.model.predict_features(row) for row in rows]
            if any(p is None for p in predicted):
                self.state, self.message = "error", "Validación fuera del dominio calibrado. Repetí o recalibrá."
                return
            pixels = np.array([self.context["width"]-1, self.context["height"]-1])
            predicted = np.array(predicted)*pixels
            delta = predicted-np.array(target)*pixels
            radial = np.linalg.norm(delta, axis=1)
            n = max(1, len(rows)//4)
            point.update(error_x_px=float(np.mean(np.abs(delta[:, 0]))),
                         error_y_px=float(np.mean(np.abs(delta[:, 1]))), error_mean_px=float(np.mean(radial)),
                         error_p95_px=float(np.percentile(radial, 95)),
                         jitter_rms_px=float(np.sqrt(np.mean(np.sum((predicted-predicted.mean(axis=0))**2, axis=1)))),
                         drift_px=float(np.linalg.norm(predicted[-n:].mean(axis=0)-predicted[:n].mean(axis=0))),
                         latency_ms=float(np.mean([r[2] for r in self.rows])))
            point.pop("features")
            self.validation_points[self.index] = point
        self._advance()

    def _advance(self):
        points = self.points if self.phase == "training" else self.validation_points
        targets = self.targets if self.phase == "training" else VALIDATION_TARGETS
        order = [self.center_index]+[i for i in range(len(targets)) if i != self.center_index] if self.phase == "training" else range(len(targets))
        missing = [i for i in order if i not in points]
        if missing:
            self.index = missing[0]
        elif self.phase == "training" and self.relative:
            try:
                self._relative_result()
            except ValueError as exc:
                self.state, self.message = "invalid", f"Rangos incompatibles: {exc}. Repetí el punto afectado."
                return
            self.state, self.message = "ready", "Direcciones medidas. Guardá el movimiento ocular."
            return
        elif self.phase == "training":
            try:
                self.model = GazeModel.fit([self.points[i]["features"] for i in range(9)], self.targets, self.context, self.eye_source)
            except ValueError as exc:
                self.state, self.message = "error", str(exc)
                return
            self.phase, self.index = "validation", 0
        else:
            points = [self.validation_points[i] for i in range(len(VALIDATION_TARGETS))]
            diagonal = math.hypot(self.context["width"], self.context["height"])
            passed = np.mean([p["error_mean_px"] for p in points]) <= .10*diagonal and max(p["error_mean_px"] for p in points) <= .18*diagonal
            self.model.record.update(validated=bool(passed), validation=dict(passed=bool(passed), points=points))
            self.state = "ready" if passed else "invalid"
            self.message = "Validación aprobada. Guardá y probá la predicción sin mover el mouse." if passed else "Precisión insuficiente. Repetí los objetivos o la calibración; el control permanece deshabilitado."
            return
        self.rows, self.rejected = [], 0
        self.head_stable=None
        self.last_timestamp = 0
        self.started = self.clock()
        self.state = "countdown"
        self.message = "Mirá el objetivo de validación independiente." if self.phase == "validation" else "Mirá el siguiente objetivo."

    def snapshot(self):
        targets = self.targets if self.phase == "training" else VALIDATION_TARGETS
        return dict(state=self.state, phase=self.phase, index=self.index, total=len(targets),
                    eye_source=self.eye_source, source_label=SOURCE_LABELS[self.eye_source],
                    head_stable=self.head_stable,
                    method="eye" if self.relative else "eye_absolute",
                    kind="Calibración de Ojos · captura direccional" if self.relative else "Calibración de Ojos · aprendizaje y comprobación",
                    direction_check=deepcopy(self.last_check), rejected_points=deepcopy(self.rejected_points),
                    target=targets[self.index], message=self.message, samples=len(self.rows), rejected=self.rejected,
                    progress=min(1., len(self.rows)/self.min_samples,
                        (self.rows[-1][0]-self.rows[0][0])/(self.duration_s*1000) if len(self.rows)>1 else 0.),
                    countdown=max(0., self.countdown_s-(self.clock()-self.started)),
                    can_save=self.state == "ready", points=deepcopy(self.points if self.phase == "training" else self.validation_points),
                    report=deepcopy(self.model.record["validation"]) if self.model else None)

    def result(self):
        if self.state != "ready":
            raise ValueError("Completá y validá la calibración antes de guardar")
        if self.relative:
            for index, point in self.points.items():
                problem = self._point_problem(index, point)
                if problem:
                    self._reject_point(index, point, problem)
                    raise ValueError(problem)
            return self._relative_result()
        return deepcopy(GazeModel(self.model.record).record)
