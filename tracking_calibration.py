"""Calibración de tracking ocular independiente de GestureCalibration."""
import time
from dataclasses import asdict, dataclass
from statistics import median
from config import bounded
from gaze_source import gaze_position, selected_eyes_open, validate_source, SOURCE_LABELS


@dataclass(frozen=True)
class TrackingCalibration:
    method: str = "eye"
    schema_version: int = 1
    neutral_x: float = .5
    neutral_y: float = .5
    left_range: float = .2
    right_range: float = .2
    up_range: float = .2
    down_range: float = .2
    # Los rangos de esta etapa son nominales, no extremos medidos.
    ranges_measured: bool = False
    eye_source: str = "both"
    vertical_reference: str = "eyelids"
    camera_context: dict | None = None

    def __post_init__(self):
        from gaze_source import validate_vertical_reference
        validate_vertical_reference(self.vertical_reference)
        validate_source(self.eye_source)
        if self.camera_context is not None:
            if not isinstance(self.camera_context, dict) or set(self.camera_context) != {"camera_index", "frame_width", "frame_height"}:
                raise ValueError("Contexto de cámara ocular inválido")
            for key, value in self.camera_context.items():
                bounded(key, value, 0 if key == "camera_index" else 2, 100 if key == "camera_index" else 100000, integer=True)
        if self.method != "eye" or type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("Calibración de tracking desconocida")
        if type(self.ranges_measured) is not bool:
            raise ValueError("ranges_measured debe ser booleano")
        for key in ("neutral_x", "neutral_y"):
            bounded(key, getattr(self, key), .05, .95)
        for key in ("left_range", "right_range", "up_range", "down_range"):
            bounded(key, getattr(self, key), .02, 1)

    @classmethod
    def from_record(cls, record):
        if not isinstance(record, dict):
            raise ValueError("Calibración ocular inválida")
        try:
            if not {"method", "schema_version", "neutral_x", "neutral_y"} <= record.keys():
                raise ValueError("Falta neutral ocular")
            return cls(**record)
        except TypeError as exc:
            raise ValueError("Campos de calibración ocular inválidos") from exc

    def record(self):
        return asdict(self)


class EyeTrackingCalibrationSession:
    """Neutral binocular estable, único por timestamp; timeout y reloj inyectables."""
    def __init__(self, clock=time.monotonic, duration_s=2., timeout_s=20., min_samples=20,
                 stale_after_s=.25, max_spread=.06, eye_source="both", camera_context=None,
                 eye_limits=(.045, .045),vertical_reference="eyelids"):
        from gaze_source import validate_vertical_reference
        self.vertical_reference=validate_vertical_reference(vertical_reference)
        self.eye_source = validate_source(eye_source)
        self.camera_context, self.eye_limits = camera_context, eye_limits
        self.clock, self.duration_s, self.timeout_s = clock, duration_s, timeout_s
        self.min_samples, self.stale_after_s, self.max_spread = min_samples, stale_after_s, max_spread
        self.started = clock()
        self.state, self.message = "capturing", f"{SOURCE_LABELS[self.eye_source]}: mirá al centro con la cabeza cómoda. No hace falta cerrar el otro ojo."
        self.samples = []
        self.last_timestamp = 0
        self.candidate = None
        self.head_stable=None

    def update(self, face):
        if self.state != "capturing":
            return
        if self.clock()-self.started >= self.timeout_s:
            self.state, self.message = "error", "Tiempo agotado: reintentá con la fuente ocular visible y mirada estable."
            return
        position = gaze_position(face, self.eye_source,self.vertical_reference)
        if not face.fresh(self.stale_after_s, self.clock()) or position is None or not selected_eyes_open(face, self.eye_source, self.eye_limits):
            self.samples.clear()
            self.head_stable=None
            self.message = f"{SOURCE_LABELS[self.eye_source]}: esperando señal válida. Mirá al centro."
            return
        if face.timestamp_ms <= self.last_timestamp:
            return
        if self.last_timestamp and face.timestamp_ms-self.last_timestamp > self.stale_after_s*1000:
            self.samples.clear()
        self.last_timestamp = face.timestamp_ms
        self.samples.append((face.timestamp_ms, *position,face.nose_x,face.nose_y))
        # Conservar también el frame justo ANTES del borde de ventana (30 FPS
        # no divide exactamente 2 s); de otro modo nunca se completa la duración.
        # A pocos FPS, conservar al menos el mínimo de muestras aunque supere 2 s.
        cutoff = face.timestamp_ms-self.duration_s*1000
        while len(self.samples)>self.min_samples and self.samples[1][0] <= cutoff:
            self.samples.pop(0)
        self.message = "Capturando neutral ocular. Mantené la mirada al centro."
        if len(self.samples) < self.min_samples or self.samples[-1][0]-self.samples[0][0] < self.duration_s*1000-1:
            return
        xs, ys = [r[1] for r in self.samples], [r[2] for r in self.samples]
        self.head_stable=all(max(r[i] for r in self.samples)-min(r[i] for r in self.samples)<=.03 for i in (3,4))
        if not self.head_stable:
            self.message="La cabeza se mueve demasiado. Mantenela quieta mientras mirás al centro."
            return
        if max(max(xs)-min(xs), max(ys)-min(ys)) > self.max_spread:
            self.message = "La mirada varía demasiado. Mantenela al centro para repetir la ventana."
            return
        try:
            self.candidate = TrackingCalibration(neutral_x=median(xs), neutral_y=median(ys),
                eye_source=self.eye_source, camera_context=self.camera_context,vertical_reference=self.vertical_reference)
        except ValueError:
            self.state, self.message = "error", "Neutral fuera del rango utilizable. Reubicá la cámara y reintentá."
            return
        self.state, self.message = "ready", "Neutral ocular listo. Guardá y probalo en Diagnóstico."

    def snapshot(self):
        elapsed = (self.samples[-1][0]-self.samples[0][0])/1000 if len(self.samples)>1 else 0
        return dict(state=self.state, message=self.message, samples=len(self.samples),
                    head_stable=self.head_stable,
                    eye_source=self.eye_source,
                    progress=min(1., elapsed/self.duration_s, len(self.samples)/self.min_samples),
                    can_save=self.state=="ready")

    def result(self):
        if self.state != "ready" or self.candidate is None:
            raise ValueError("Completá la calibración ocular antes de guardar")
        return self.candidate.record()
