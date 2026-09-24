"""Adquisición de objetivos y jitter reproducibles, sin Qt/hardware."""
import json
import math
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, pstdev
from config import ROOT


class ResultStore:
    def __init__(self, directory=None):
        self.directory = Path(directory) if directory is not None else ROOT / "data" / "experiments"

    def append(self, session_id, record):
        # IDs los genera el motor; no aceptar rutas en la API de persistencia.
        if not session_id or any(c not in "0123456789abcdef" for c in session_id):
            raise ValueError("ID de experimento inválido")
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{session_id}.jsonl"
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
            stream.flush()
        return str(path)


class ExperimentEngine:
    WIDTH, HEIGHT = 800, 500
    TARGETS = ((640, 120), (160, 380), (650, 380), (150, 120), (400, 250))

    def __init__(self, profile_id, mode="simulation", source="headmouse", store=None,
                 clock=time.monotonic, targets=None, radius=35, timeout_s=60):
        if mode not in ("simulation", "real") or source not in ("headmouse", "keyboard"):
            raise ValueError("Modo o fuente experimental inválida")
        self.profile_id, self.mode, self.source = profile_id, mode, source
        self.clock, self.store = clock, store or ResultStore()
        self.targets = tuple(targets or self.TARGETS)
        self.radius, self.timeout_s = radius, timeout_s
        self.session_id = uuid.uuid4().hex
        self.index = 0
        self.cursor = (400., 250.)
        self.results = []
        self.active = True
        self.path = ""
        self._begin()

    def _begin(self):
        self.started = self.clock()
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.trajectory = [[0., *self.cursor]]
        self.distance = 0.
        self.overshoots = self.failed_clicks = 0
        self.was_inside = self.inside()
        self.fps, self.latencies = [], []

    def inside(self):
        tx, ty = self.targets[min(self.index, len(self.targets)-1)]
        return math.dist(self.cursor, (tx, ty)) <= self.radius

    def observe(self, x, y, fps=None, latency=None):
        if not self.active:
            return
        if not all(math.isfinite(v) for v in (x, y)) or any(
                v is not None and not math.isfinite(v) for v in (fps, latency)):
            raise ValueError("Observación experimental inválida")
        position = (float(x), float(y))
        self.distance += math.dist(self.cursor, position)
        self.cursor = position
        inside = self.inside()
        if self.was_inside and not inside:
            self.overshoots += 1
        self.was_inside = inside
        self.trajectory.append([self.clock()-self.started, *self.cursor])
        if fps is not None:
            self.fps.append(max(0., fps))
        if latency is not None:
            self.latencies.append(max(0., latency))
        self.tick()

    def move(self, dx, dy, fps=None, latency=None):
        if self.mode != "simulation":
            raise ValueError("El movimiento interno solo aplica a simulación")
        x, y = self.cursor
        self.observe(max(0, min(self.WIDTH, x+dx)), max(0, min(self.HEIGHT, y+dy)), fps, latency)

    def click(self):
        if not self.active:
            return
        if self.inside():
            self._finish(True)
        else:
            self.failed_clicks += 1

    def tick(self):
        if self.active and self.clock()-self.started >= self.timeout_s:
            self._finish(False, "timeout")

    def _finish(self, completed, reason="completed", advance=True):
        record = dict(schema_version=1, experiment="target_acquisition", session_id=self.session_id,
                      profile_id=self.profile_id, mode=self.mode, input_source=self.source,
                      tracking_method="nose", trial=self.index+1, target=list(self.targets[self.index]),
                      radius=self.radius, coordinate_space=[self.WIDTH, self.HEIGHT],
                      started_at=self.started_at, ended_at=datetime.now(timezone.utc).isoformat(),
                      duration_s=self.clock()-self.started, trajectory=self.trajectory,
                      distance_px=self.distance, overshoots=self.overshoots, failed_clicks=self.failed_clicks,
                      completed=completed, reason=reason, fps_mean=mean(self.fps) if self.fps else None,
                      processing_ms_mean=mean(self.latencies) if self.latencies else None)
        self.path = self.store.append(self.session_id, record)
        self.results.append(record)
        self.index += 1
        self.active = advance and self.index < len(self.targets)
        if self.active:
            self._begin()

    def cancel(self):
        if self.active:
            self._finish(False, "cancelled", False)

    def snapshot(self):
        return dict(active=self.active, index=min(self.index+1, len(self.targets)), total=len(self.targets),
                    cursor=self.cursor, target=self.targets[min(self.index, len(self.targets)-1)],
                    radius=self.radius, completed=sum(r["completed"] for r in self.results), path=self.path,
                    elapsed_s=self.clock()-self.started, mode=self.mode, source=self.source)


class JitterMeasurement:
    def __init__(self, neutral=(.5,.5), dead_zone=.03, duration_s=10, clock=time.monotonic):
        self.neutral, self.dead_zone, self.duration_s = neutral, dead_zone, duration_s
        self.clock, self.started = clock, clock()
        self.samples = []
        self.last_timestamp = 0
        self.exits = 0
        self.outside = False

    @property
    def done(self):
        return self.clock()-self.started >= self.duration_s

    def add(self, face, max_age_s=.25):
        if self.done or not face.fresh(max_age_s, self.clock()) or face.timestamp_ms <= self.last_timestamp:
            return
        self.last_timestamp = face.timestamp_ms
        dx, dy = face.nose_x-self.neutral[0], face.nose_y-self.neutral[1]
        outside = abs(dx) > self.dead_zone or abs(dy) > self.dead_zone
        if outside and not self.outside:
            self.exits += 1
        self.outside = outside
        self.samples.append((dx, dy))

    def summary(self):
        if len(self.samples) < 2:
            return dict(valid=False, samples=len(self.samples), reason="Muestras insuficientes")
        xs, ys = zip(*self.samples)
        deviations = [math.hypot(x, y) for x, y in self.samples]
        steps = [math.dist(a, b) for a, b in zip(self.samples, self.samples[1:])]
        return dict(valid=True, samples=len(xs), duration_s=self.duration_s, units="normalized_frame",
                    mean_deviation=mean(deviations), std_deviation=pstdev(deviations),
                    std_x=pstdev(xs), std_y=pstdev(ys), range_x=max(xs)-min(xs), range_y=max(ys)-min(ys),
                    jitter_rms=math.sqrt(mean(v*v for v in steps)), dead_zone_exits=self.exits)
