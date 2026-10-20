"""Calibración de tracking ocular independiente de GestureCalibration."""
import time
from dataclasses import asdict, dataclass
from statistics import median
from config import bounded


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

    def __post_init__(self):
        if self.method != "eye" or type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("Calibración de tracking desconocida")
        if self.ranges_measured is not False:
            raise ValueError("Esta versión solo captura neutral ocular")
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
                 stale_after_s=.25, max_spread=.06):
        self.clock, self.duration_s, self.timeout_s = clock, duration_s, timeout_s
        self.min_samples, self.stale_after_s, self.max_spread = min_samples, stale_after_s, max_spread
        self.started = clock()
        self.state, self.message = "capturing", "Mirá al centro, con ambos ojos abiertos y la cabeza cómoda."
        self.samples = []
        self.last_timestamp = 0
        self.candidate = None

    def update(self, face):
        if self.state != "capturing":
            return
        if self.clock()-self.started >= self.timeout_s:
            self.state, self.message = "error", "Tiempo agotado: reintentá con ambos iris visibles y mirada estable."
            return
        if not face.fresh(self.stale_after_s, self.clock()) or not face.gaze_available or face.gaze_confidence < 1:
            self.samples.clear()
            self.message = "Esperando ambos iris válidos. Mirá al centro."
            return
        if face.timestamp_ms <= self.last_timestamp:
            return
        if self.last_timestamp and face.timestamp_ms-self.last_timestamp > self.stale_after_s*1000:
            self.samples.clear()
        self.last_timestamp = face.timestamp_ms
        self.samples.append((face.timestamp_ms, face.gaze_x, face.gaze_y))
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
        if max(max(xs)-min(xs), max(ys)-min(ys)) > self.max_spread:
            self.message = "La mirada varía demasiado. Mantenela al centro para repetir la ventana."
            return
        try:
            self.candidate = TrackingCalibration(neutral_x=median(xs), neutral_y=median(ys))
        except ValueError:
            self.state, self.message = "error", "Neutral fuera del rango utilizable. Reubicá la cámara y reintentá."
            return
        self.state, self.message = "ready", "Neutral ocular listo. Guardá y probalo en Diagnóstico."

    def snapshot(self):
        elapsed = (self.samples[-1][0]-self.samples[0][0])/1000 if len(self.samples)>1 else 0
        return dict(state=self.state, message=self.message, samples=len(self.samples),
                    progress=min(1., elapsed/self.duration_s, len(self.samples)/self.min_samples),
                    can_save=self.state=="ready")

    def result(self):
        if self.state != "ready" or self.candidate is None:
            raise ValueError("Completá la calibración ocular antes de guardar")
        return self.candidate.record()
