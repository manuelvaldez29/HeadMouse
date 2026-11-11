"""Seeded ocular signals through the same geometry and diagnostic as the webcam."""
import argparse
from collections import deque
from dataclasses import asdict, dataclass, replace
import json
import math
from pathlib import Path
import random
import time
from types import SimpleNamespace

from direction_diagnostic import DIRECTIONS, RAW_CHANNELS, DirectionClassifier, DirectionDiagnostic, analyze
from eye_geometry import EYES, extract_gaze
from face_data import FaceData

SAMPLE_HZ = 30
STEP = 1 / SAMPLE_HZ
BASE_TIME = 100.
VECTORS = dict(center=(0, 0), up=(0, -1), down=(0, 1), left=(-1, 0), right=(1, 0))


@dataclass(frozen=True)
class SimulationConfig:
    horizontal: float = .22
    vertical: float = .22
    noise: float = .009
    natural: float = .012
    offset: float = .005
    head: float = .006
    blink: float = .007
    loss: float = .004
    invalid: float = .004
    asymmetry: float = .10
    delay_ms: int = 60

    def __post_init__(self):
        limits = dict(horizontal=(0., .45), vertical=(0., .45), noise=(0., .35), natural=(0., .2),
                      offset=(0., .2), head=(0., .14), blink=(0., .4), loss=(0., .4),
                      invalid=(0., .4), asymmetry=(0., 5.), delay_ms=(0, 700))
        for key, (low, high) in limits.items():
            value = getattr(self, key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
                raise ValueError(f"Parámetro de simulación fuera de rango: {key}")


IDEAL = SimulationConfig()
SCENARIOS = {
    "ideal": ("A · Ideal", IDEAL),
    "moderate": ("B · Ruido moderado", replace(IDEAL, noise=.038, natural=.035, delay_ms=85)),
    "noisy": ("C · Ruido elevado", replace(IDEAL, noise=.18, natural=.145, offset=.045)),
    "vertical": ("D · Señal vertical débil", replace(IDEAL, vertical=.012, noise=.053, natural=.055)),
    "head": ("E · Movimiento de cabeza", replace(IDEAL, head=.09, offset=.06, noise=.028)),
    "loss": ("F · Pérdida de seguimiento", replace(IDEAL, blink=.035, loss=.075, invalid=.045, delay_ms=120)),
    "asymmetry": ("G · Asimetría ocular", replace(IDEAL, noise=.038, asymmetry=3.6)),
}


class SyntheticVision:
    """Capture and delivery on a logical clock. Each delivered result is a FaceData."""

    def __init__(self, config, seed):
        self.config = config
        self.random = random.Random(seed)
        self.offset = tuple(self.random.uniform(-config.offset, config.offset) for _ in range(2))
        self.queue = deque()
        self.index = self.last_timestamp = self.lost = self.blinking = 0
        self.gaze = [0., 0.]

    def tick(self, now, intent):
        timestamp = max(self.last_timestamp + 1, int(now * 1000))
        self.last_timestamp = timestamp
        frame = self.capture(timestamp, intent)
        self.queue.append((now + self.config.delay_ms / 1000, frame))
        if self.queue[0][0] <= now + 1e-9:
            return self.queue.popleft()[1]
        return None

    def release_intent(self):
        self.queue.clear()
        self.gaze[:] = (0., 0.)

    def capture(self, timestamp, intent):
        c, rng = self.config, self.random
        self.index += 1
        t = self.index * STEP
        dx, dy = VECTORS[intent]
        for axis, goal in enumerate((dx * c.horizontal, dy * c.vertical)):
            self.gaze[axis] += .36 * (goal - self.gaze[axis])
        if not self.lost and rng.random() < c.loss:
            self.lost = rng.randint(4, 12)
        if not self.blinking and rng.random() < c.blink:
            self.blinking = rng.randint(2, 5)
        blink = self.blinking > 0
        self.blinking = max(0, self.blinking - 1)
        capture_time = timestamp / 1000
        if self.lost:
            self.lost -= 1
            return FaceData(False, timestamp_ms=timestamp, detected_at=capture_time)
        width, height = 640, 480
        motion_x = c.head * math.sin(t * 1.13)
        motion_y = c.head * math.sin(t * .83)
        roll = 180 * c.head * math.sin(t * .94)
        angle = math.radians(roll)
        cos_a, sin_a = math.cos(angle), math.sin(angle)
        points = [None] * 478
        for side, ids in enumerate(EYES.values()):
            a, b, upper, lower, iris, ring = ids
            strength = 1. + c.asymmetry * side
            gx, gy = [gaze + bias + c.natural * math.sin(t * freq + side)
                      + rng.gauss(0., c.noise * strength)
                      for gaze, bias, freq in zip(self.gaze, self.offset, (5.1, 4.3))]
            gx += 1.8 * motion_x + side * c.asymmetry * .008
            gy += 2.0 * motion_y - side * c.asymmetry * .007
            origin = ((.32 + .36 * side + motion_x) * width, (.43 + motion_y) * height)
            half_width = 36.
            half_height = 1.2 if blink else 10.5 + math.sin(t * 3.4 + side)
            iris_x, iris_y = gx * 2 * half_width, gy * 2 * half_height
            offsets = [(-half_width, 0.), (half_width, 0.), (0., -half_height), (0., half_height),
                       (iris_x, iris_y), (iris_x - 3., iris_y), (iris_x + 3., iris_y),
                       (iris_x, iris_y - 3.), (iris_x, iris_y + 3.)]
            for index, (x, y) in zip((a, b, upper, lower, iris, *ring), offsets):
                points[index] = SimpleNamespace(x=(origin[0] + x * cos_a - y * sin_a) / width,
                                                y=(origin[1] + x * sin_a + y * cos_a) / height)
            if rng.random() < c.invalid:
                points[iris] = None
        features = extract_gaze(points, width, height)
        return FaceData(True, timestamp_ms=timestamp, detected_at=capture_time,
                        nose_x=.5 + motion_x, nose_y=.52 + motion_y, face_scale=.36,
                        head_pitch=150 * motion_y, head_yaw=150 * motion_x, head_roll=roll,
                        eye_left_ratio=.02 if blink else .27, eye_right_ratio=.02 if blink else .27, **features)


class SyntheticDiagnostic:
    def __init__(self, config, seed, scenario):
        self.config, self.seed, self.scenario = config, seed, scenario
        self.vision = SyntheticVision(config, seed)
        self.now, self.tick_count = BASE_TIME, 0
        self.session = DirectionDiagnostic(lambda: self.now, rng=random.Random(seed ^ 0xABBA))
        self.face = None

    def step(self):
        session = self.session
        self.tick_count += 1
        self.now = BASE_TIME + self.tick_count * STEP
        if session.state == "await_target":
            session.acknowledge(*session.token)
        if session.state == "retry":
            # Allow one more attempt at the same direction in dropout scenarios.
            session.retry(skip=session.attempt >= 1)
        if session.state in ("transition", "fixation"):
            self.face = self.vision.tick(self.now, session.schedule[session.index])
            session.update(self.face, None)

    def record(self):
        report = self.session.record()
        report["source"] = "synthetic"
        report["simulation"] = dict(scenario=self.scenario, seed=self.seed, configuration=asdict(self.config),
                                    logical_sample_hz=SAMPLE_HZ, artificial_delay_ms=self.config.delay_ms)
        metrics = dict(report["metrics"])
        trials = [dict(trial, samples=[dict(row, processing_ms=None) for row in trial["samples"]])
                  for trial in report["trials"]]
        rows = [row for trial in trials for row in trial["samples"]]
        lost = sum(row["rejected"] in ("face_missing", "iris_missing_or_invalid", "blink_or_closed") for row in rows)
        metrics["tracking_loss_percent"] = 100 * lost / len(rows) if rows else None
        metrics["artificial_delay_ms"] = self.config.delay_ms
        metrics["logical_result_hz"] = metrics.pop("observed_result_fps")
        metrics["delivery_age_ms_median"] = metrics.pop("sample_age_ms_median")
        metrics["processing_ms_median"] = None
        return dict(report, trials=trials, metrics=metrics)


def run_simulation(config, seed=42, scenario="custom"):
    run = SyntheticDiagnostic(config, seed, scenario)
    while run.session.state != "ready":
        run.step()
    return run


def train_classifier(session, channel="eyelids_both"):
    """Fit from complete acquisition trials reserved for joystick training."""
    groups = {target: [] for target in DIRECTIONS}
    for trial in session.trials:
        rows = [row["signals"][channel] for row in trial["samples"]
                if row["phase"] == "fixation" and channel in row["signals"]]
        if trial["used"] and len(rows) >= session.min_samples:
            groups[trial["target"]].append(tuple(sum(axis) / len(axis) for axis in zip(*rows)))
    return DirectionClassifier.fit(groups)


def replay_metrics(path):
    """Re-evaluate compatible numeric recordings using the original trial boundaries."""
    from itertools import chain

    report = json.loads(Path(path).read_text(encoding="utf-8"))
    if report.get("experiment") != "ocular_direction" or report.get("schema_version") != 1:
        raise ValueError("Registro ocular incompatible")
    trials = report["trials"]
    if not all(t["target"] in DIRECTIONS and isinstance(t["round"], int) for t in trials):
        raise ValueError("Rondas del registro incompatibles")
    channels = tuple(dict.fromkeys(chain(RAW_CHANNELS, report["configuration"].get("models", {}))))
    original = report.get("source", "webcam")
    metrics = analyze(trials, channels, report["configuration"]["min_samples"])
    if original == "synthetic":
        metrics["logical_result_hz"] = metrics.pop("observed_result_fps")
        metrics["delivery_age_ms_median"] = metrics.pop("sample_age_ms_median")
    return dict(source="replay", original_source=original, metrics=metrics)


def write_report(path, data):
    from user_storage import write_json

    write_json(Path(path), data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--replay", type=Path)
    args = parser.parse_args()
    if args.replay:
        write_report(args.output, replay_metrics(args.replay))
        return
    reports = {}
    for scenario, (_, config) in SCENARIOS.items():
        start = time.perf_counter()
        run = run_simulation(config, args.seed, scenario)
        report = run.record()
        reports[scenario] = dict(report, elapsed_wall_ms=(time.perf_counter()-start)*1000, ticks=run.tick_count)
    write_report(args.output, dict(source="synthetic", seed=args.seed, scenarios=reports))


if __name__ == "__main__":
    main()
