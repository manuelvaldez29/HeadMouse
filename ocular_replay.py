"""Replay numeric diagnostic records through the live, virtual-only estimators."""
from dataclasses import asdict, dataclass, replace
import json
import math
from pathlib import Path
from types import SimpleNamespace

from direction_diagnostic import DIRECTIONS, analyze
from ocular_joystick import VirtualJoystick, make_estimator
from ocular_simulation import BASE_TIME, STEP
from ocular_temporal import EyeObservation

MAX_FILE_BYTES = 64 * 1024 * 1024
PREDICTIONS = (*DIRECTIONS, "unavailable")


@dataclass(frozen=True)
class ReplayEvent:
    delivery: float
    sample: EyeObservation
    requested: str
    phase: str


def _point(value):
    if (isinstance(value, list) and len(value) == 2 and
            all(type(x) in (int, float) and math.isfinite(x) and 0 <= x <= 1 for x in value)):
        return tuple(value)
    return None


def load_record(path, channel):
    path = Path(path)
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("El registro supera el tamaño de reproducción")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return _prepare(data, channel)
    except (AttributeError, KeyError, TypeError, OverflowError) as exc:
        raise ValueError("Formato de diagnóstico ocular incompatible") from exc


def _prepare(data, channel):
    if data["experiment"] != "ocular_direction" or data["schema_version"] != 1:
        raise ValueError("Se requiere un diagnóstico ocular con esquema 1")
    origin = data.get("source", "unmarked")
    if origin not in ("synthetic", "webcam", "unmarked"):
        raise ValueError("Origen del registro incompatible")
    minimum = data["configuration"]["min_samples"]
    if type(minimum) is not int or not 1 <= minimum <= 1000:
        raise ValueError("Cantidad mínima de muestras incompatible")
    trials = []
    last = 0
    first = None
    for trial in data["trials"]:
        if (trial["target"] not in DIRECTIONS or type(trial["round"]) is not int
                or trial["round"] < 0 or type(trial["used"]) is not bool):
            raise ValueError("Ensayo ocular incompatible")
        rows = []
        for row in trial["samples"]:
            stamp, delay, phase = row["timestamp_ms"], row["sample_age_ms"], row["phase"]
            if (type(stamp) is not int or stamp <= last or phase not in ("transition", "fixation")
                    or type(delay) not in (int, float) or not math.isfinite(delay) or abs(delay) > 10000):
                raise ValueError("Timestamps o fases inválidos")
            last = stamp
            if first is None:
                first = stamp
            if last-first > 900000:
                raise ValueError("El registro supera los 15 minutos")
            signals = {}
            if row["rejected"] is None:
                for reference in ("eyelids", "canthi"):
                    left, right = (_point(row["signals"].get(f"{reference}_{side}")) for side in ("left", "right"))
                    if left is not None:
                        signals[f"{reference}_left"] = left
                    if right is not None:
                        signals[f"{reference}_right"] = right
                    both = _point(row["signals"].get(f"{reference}_both"))
                    if both is not None and left is not None and right is not None:
                        signals[f"{reference}_both"] = both
            rows.append(dict(timestamp_ms=stamp, phase=phase, signals=signals,
                             rejected=None if signals else "invalid", sample_age_ms=delay,
                             processing_ms=None, capture_fps=None))
        trials.append(dict(round=trial["round"], target=trial["target"], used=trial["used"], samples=rows))
    qualified = {}
    for trial in trials:
        good = sum(row["phase"] == "fixation" and channel in row["signals"] for row in trial["samples"])
        if trial["used"] and good >= minimum:
            qualified.setdefault(trial["round"], set()).add(trial["target"])
    train_round = next((index for index in sorted(qualified) if qualified[index] == set(DIRECTIONS)), None)
    if train_round is None:
        raise ValueError("El registro necesita una ronda inicial completa para la fuente elegida")
    training_trials = [trial for trial in trials if trial["round"] == train_round]
    training = SimpleNamespace(trials=training_trials, min_samples=minimum,
                               report=analyze(training_trials, (channel,), minimum))
    held_out = [trial for trial in trials if trial["round"] > train_round and trial["samples"]]
    if not held_out:
        raise ValueError("Hace falta otra ronda posterior para evaluar")
    zero = held_out[0]["samples"][0]["timestamp_ms"]
    events = []
    last_delivery = BASE_TIME
    for trial in held_out:
        for row in trial["samples"]:
            relative = row["timestamp_ms"] - zero
            observation = EyeObservation(round(BASE_TIME*1000) + relative, row["signals"].get(channel))
            delivery = max(last_delivery, observation.timestamp_ms / 1000 + max(0., row["sample_age_ms"]) / 1000)
            last_delivery = delivery
            events.append(ReplayEvent(delivery, observation, trial["target"], row["phase"]))
    return origin, training, train_round, tuple(sorted({t["round"] for t in held_out})), events


class ReplayMethod:
    def __init__(self, training, options):
        self.estimator = make_estimator(training, options)
        self.joystick = VirtualJoystick(options)
        self.confusion = {direction: dict.fromkeys(PREDICTIONS, 0) for direction in DIRECTIONS}
        self.invalid_ticks = self.invalid_motion = 0
        self.trace = (None, 0.)

    def update(self, sample, now):
        label, confidence, point = self.estimator.observe(sample, now)
        position = self.joystick.position
        self.joystick.update(now, label, confidence)
        self.invalid_ticks += point is None
        self.invalid_motion += point is None and self.joystick.position != position
        self.trace = (label, confidence)

    def score(self, requested):
        # Requested directions are used only by the scorer, after inference and movement.
        label = self.trace[0] or "unavailable"
        self.confusion[requested][label] += 1

    def record(self):
        n = sum(sum(row.values()) for row in self.confusion.values())
        correct = sum(self.confusion[k][k] for k in DIRECTIONS)
        return dict(confusion=self.confusion, frames=n, correct_percent=100*correct/n if n else None,
                    invalid_ticks=self.invalid_ticks, invalid_motion_ticks=self.invalid_motion,
                    operations=self.joystick.eye_operations, distance_px=self.joystick.distance)


class ReplayComparison:
    def __init__(self, path, options):
        self.options = replace(options, selection="ocular")
        origin, training, train_round, held_out, events = load_record(path, options.channel)
        self.origin, self.train_round, self.held_out, self.events = origin, train_round, held_out, events
        newer = options.algorithm if options.algorithm != "previous" else "weighted"
        self.methods = {name: ReplayMethod(training, replace(self.options, algorithm=name))
                        for name in ("previous", newer)}
        self.index = 0
        self.now = BASE_TIME
        self.last = None
        self.done = False

    def step(self):
        if self.done:
            return
        end = self.now + STEP
        while self.index < len(self.events) and self.events[self.index].delivery <= end:
            event = self.events[self.index]
            self.index += 1
            self.last = event
            for method in self.methods.values():
                method.update(event.sample, event.delivery)
                if event.phase == "fixation":
                    method.score(event.requested)
        self.now = end
        if self.index == len(self.events):
            self.done = True
            for method in self.methods.values():
                method.joystick.stop()
        elif self.last is None or self.last.delivery < end:
            sample = self.last.sample if self.last and end-self.last.delivery <= .12 else None
            for method in self.methods.values():
                method.update(sample, end)

    def record(self):
        return dict(experiment="ocular_virtual_replay", schema_version=1, origin=self.origin,
                    playback="offline", training_round=self.train_round, evaluation_rounds=self.held_out,
                    options=asdict(self.options), methods={name: method.record() for name, method in self.methods.items()})

    def snapshot(self):
        return dict(origin=self.origin, progress=self.index/len(self.events), completed=self.done,
                    requested=self.last.requested if self.last else None,
                    labels={key: method.trace[0] for key, method in self.methods.items()},
                    result=self.record() if self.done else None)
