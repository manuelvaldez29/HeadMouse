"""Acquisition and analysis for the five-direction ocular diagnostic."""
import math
import random
import time
import uuid
from collections import Counter
from statistics import fmean, median, pstdev

from gaze_source import gaze_position

DIRECTIONS = ("center", "up", "down", "left", "right")
TARGETS = dict(zip(DIRECTIONS, ((.5, .5), (.5, .13), (.5, .87), (.13, .5), (.87, .5))))
SOURCES = ("left", "right", "both")
REFERENCES = ("eyelids", "canthi")
RAW_CHANNELS = tuple(f"{reference}_{source}" for reference in REFERENCES for source in SOURCES)
GEOMETRY = ("iris_x_px", "iris_y_px", "lid_top_x_px", "lid_top_y_px",
            "lid_bottom_x_px", "lid_bottom_y_px", "corner_1_x_px", "corner_1_y_px",
            "corner_2_x_px", "corner_2_y_px", "width_px", "determinant_px2",
            "eyelids_y_raw", "canthi_y_raw")
# Probe thresholds. These mark a subgroup for analysis, without excluding head movement.
HEAD_POSITION_DELTA = .025
HEAD_ANGLE_DELTA = 5.


def _number(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return value
    return None


def _mean_pair(points):
    return tuple(fmean(axis) for axis in zip(*points))


def _head_shift(head, baseline):
    if baseline is None:
        return None
    displacement = math.dist(head[:2], baseline[:2])
    angles = [abs((a - b + 180) % 360 - 180) for a, b in zip(head[3:], baseline[3:])
              if a is not None and b is not None]
    rotation = max(angles, default=None)
    return displacement, rotation


def observe_direction(face, *, fresh, fps, observed_at, phase, limits, models):
    valid_face = fresh and face.detected and face.valid()
    measurements, eyes = {}, {}
    geometry = {item[0]: dict(zip(GEOMETRY, map(_number, item[1:])))
                for item in face.ocular_geometry if len(item) == len(GEOMETRY) + 1}
    for side in SOURCES[:2]:
        channel = side if face.gaze_mirrored else {"left": "right", "right": "left"}[side]
        ratio = _number(getattr(face, f"eye_{channel}_ratio")) if valid_face else None
        blink = ratio <= limits[channel] if ratio is not None else None
        ocular = {}
        for reference in REFERENCES:
            position = gaze_position(face, side, reference) if valid_face else None
            ocular[reference] = position
            if position is not None and not blink:
                measurements[f"{reference}_{side}"] = position
        eyes[side] = dict(available=ocular["eyelids"] is not None, blink=blink, eye_ratio=ratio,
                          geometry=geometry.get(channel), normalized=ocular)
    for reference in REFERENCES:
        left, right = (measurements.get(f"{reference}_{side}") for side in SOURCES[:2])
        if left is not None and right is not None:
            measurements[f"{reference}_both"] = _mean_pair((left, right))
    for name, model in models.items():
        if f"{model.vertical_reference}_{model.eye_source}" in measurements:
            position = model.position(face)
            if position is not None:
                measurements[name] = position
    if not face.detected:
        rejected = "face_missing"
    elif not valid_face:
        rejected = "stale_or_invalid"
    elif measurements:
        rejected = None
    elif any(eye["blink"] for eye in eyes.values()):
        rejected = "blink_or_closed"
    else:
        rejected = "iris_missing_or_invalid"
    head = (face.nose_x, face.nose_y, face.face_scale, face.head_pitch, face.head_yaw, face.head_roll)
    return dict(timestamp_ms=face.timestamp_ms, phase=phase, face_detected=face.detected,
                eyes=eyes, signals=measurements, rejected=rejected,
                eye_coverage=sum(eye["available"] for eye in eyes.values()) / 2,
                head=tuple(map(_number, head)) if valid_face else None,
                processing_ms=_number(face.processing_ms), capture_fps=_number(fps),
                sample_age_ms=(observed_at - face.timestamp_ms / 1000) * 1000)


def analyze(trials, channels, min_samples):
    captured = [row for trial in trials for row in trial["samples"] if row["phase"] == "fixation"]
    accepted = [row for row in captured if row["rejected"] is None]
    counts = Counter(row["rejected"] for row in captured if row["rejected"])
    result = dict(fixation_samples=len(captured), valid_percent=100 * len(accepted) / len(captured) if captured else None,
                  rejected_percent=100 * (len(captured) - len(accepted)) / len(captured) if captured else None,
                  rejection_reasons=dict(counts),
                  transition_samples=sum(row["phase"] == "transition" for trial in trials for row in trial["samples"]),
                  completed_trials=sum(trial["used"] for trial in trials), channels={})
    for field in ("processing_ms", "capture_fps", "sample_age_ms"):
        values = [row[field] for row in captured if row[field] is not None]
        result[field + "_median"] = median(values) if values else None
    elapsed = [(b["timestamp_ms"] - a["timestamp_ms"]) for trial in trials
               for a, b in zip(trial["samples"], trial["samples"][1:]) if b["timestamp_ms"] > a["timestamp_ms"]]
    result["observed_result_fps"] = 1000 / median(elapsed) if elapsed else None
    result["head_motion_samples"] = sum(row.get("head_motion") is True for row in captured)
    result["head_reference_samples"] = sum(row.get("head_motion") is not None for row in captured)
    result["binocular_disagreement"] = {}
    for reference in REFERENCES:
        pairs = [(row["signals"][f"{reference}_left"], row["signals"][f"{reference}_right"])
                 for row in accepted if f"{reference}_both" in row["signals"]]
        result["binocular_disagreement"][reference] = dict(
            n=len(pairs), mean_abs_x=fmean(abs(a[0] - b[0]) for a, b in pairs) if pairs else None,
            mean_abs_y=fmean(abs(a[1] - b[1]) for a, b in pairs) if pairs else None)
    for name in channels:
        metrics = _analyze_channel(trials, name, min_samples)
        present = sum(name in row["signals"] for row in captured)
        metrics["valid_fixation_samples"] = present
        metrics["valid_fixation_percent"] = 100 * present / len(captured) if captured else None
        result["channels"][name] = metrics
    return result


def _analyze_channel(trials, name, min_samples):
    items = []
    for trial in trials:
        rows = [row for row in trial["samples"] if row["phase"] == "fixation"]
        if not trial["used"]:
            continue
        points = [row["signals"][name] for row in rows if name in row["signals"]]
        if len(points) >= min_samples:
            items.append((trial, rows, _mean_pair(points), tuple(pstdev(axis) for axis in zip(*points))))
    by_direction = {target: [item for item in items if item[0]["target"] == target] for target in DIRECTIONS}
    summary = {}
    for target, group in by_direction.items():
        centers = [item[2] for item in group]
        summary[target] = dict(trials=len(group), mean=_mean_pair(centers) if centers else None,
                               between_trials_sd=tuple(pstdev(axis) for axis in zip(*centers)) if len(centers) > 1 else None,
                               fixation_sd=_mean_pair([item[3] for item in group]) if group else None)
    separation = {}
    for axis, pairs in enumerate(((("left", "center"), ("center", "right"), ("left", "right")),
                                  (("up", "center"), ("center", "down"), ("up", "down")))):
        for first, second in pairs:
            a, b = summary[first], summary[second]
            if a["mean"] is None or b["mean"] is None:
                continue
            distance = b["mean"][axis] - a["mean"][axis]
            noise = math.hypot(a["fixation_sd"][axis], b["fixation_sd"][axis]) / math.sqrt(2)
            separation[f"{first}:{second}"] = dict(signed_gap=distance, gap_over_fixation_sd=abs(distance) / noise if noise else None)
    confusion = {actual: dict.fromkeys(DIRECTIONS, 0) for actual in DIRECTIONS}
    folds, head = [], {key: dict(samples=0, correct=0) for key in ("stable", "moved")}
    for held_out in sorted({item[0]["round"] for item in items}):
        groups = {direction: [item for item in group if item[0]["round"] != held_out]
                  for direction, group in by_direction.items()}
        test = [item for item in items if item[0]["round"] == held_out]
        if not all(groups.values()) or {item[0]["target"] for item in test} != set(DIRECTIONS):
            continue
        classifier = DirectionClassifier.fit({direction: [item[2] for item in group] for direction, group in groups.items()})
        folds.append(dict(validation_round=held_out,
                          training_rounds=sorted({item[0]["round"] for group in groups.values() for item in group})))
        for trial, rows, point, _ in test:
            actual = trial["target"]
            predicted, _, _ = classifier.estimate(point)
            if predicted is not None:
                confusion[actual][predicted] += 1
            for row in rows:
                motion = row.get("head_motion")
                if motion is None or name not in row["signals"]:
                    continue
                predicted_row, _, _ = classifier.estimate(row["signals"][name])
                if predicted_row is not None:
                    group = head["moved" if motion else "stable"]
                    group["samples"] += 1
                    group["correct"] += predicted_row == actual
    predictions = sum(sum(row.values()) for row in confusion.values())
    correct = sum(confusion[target][target] for target in DIRECTIONS)
    for group in head.values():
        group["accuracy_percent"] = 100 * group["correct"] / group["samples"] if group["samples"] else None
    per_direction = {}
    for target in DIRECTIONS:
        predicted_count = sum(row[target] for row in confusion.values())
        hits = confusion[target][target]
        per_direction[target] = dict(precision=hits / predicted_count if predicted_count else None,
                                     sensitivity=hits / len(folds) if folds else None)
    return dict(fixation=summary, separation=separation, folds=folds, confusion=confusion,
                per_direction=per_direction,
                evaluated_trials=predictions, unclassified_trials=5 * len(folds) - predictions,
                accuracy_percent=100 * correct / (5 * len(folds)) if folds else None, head_groups=head)


class DirectionClassifier:
    """Learn only from labeled training groups. Estimation accepts an (x, y) signal."""

    def __init__(self, centers):
        self.centers = centers
        self.scales = tuple(max(1e-12, max(axis) - min(axis)) for axis in zip(*centers.values()))

    @classmethod
    def fit(cls, groups):
        if set(groups) != set(DIRECTIONS) or not all(groups.values()):
            raise ValueError("Faltan muestras de entrenamiento para alguna dirección")
        return cls({target: _mean_pair(groups[target]) for target in DIRECTIONS})

    def estimate(self, point):
        distances = sorted((sum(((x - y) / scale)**2 for x, y, scale in zip(point, center, self.scales)), label)
                           for label, center in self.centers.items())
        (first, label), (second, _) = distances[:2]
        if first >= second:
            return None, 0., math.sqrt(first)
        return label, 1 - first / second, math.sqrt(first)


class DirectionDiagnostic:
    def __init__(self, clock=time.monotonic, *, rng=None, rounds=4, settle_s=.7, fixation_s=1.6,
                 min_samples=8, max_age=.25, limits=None, models=None):
        self.clock = clock
        self.session_id = uuid.uuid4().hex
        self.created_at = time.time()
        self.settle_s, self.fixation_s = settle_s, fixation_s
        self.min_samples, self.max_age = min_samples, max_age
        self.limits = limits or dict(left=.045, right=.045)
        self.models = models or {}
        generator = rng if rng is not None else random.Random()
        self.schedule = []
        for _ in range(rounds):
            order = list(DIRECTIONS)
            generator.shuffle(order)
            if self.schedule and order[0] == self.schedule[-1]:
                order[0], order[1] = order[1], order[0]
            self.schedule.extend(order)
        self.index, self.attempt, self.last_timestamp = 0, 0, 0
        self.state = "await_target"
        self.started = self.viewport = None
        self.samples, self.trials = [], []
        self.head_reference = None
        self.report, self.path, self.save_error = None, None, None

    def acknowledge(self, session_id, index, attempt, viewport=None):
        if (session_id, index, attempt) == self.token and self.state == "await_target":
            self.started = self.clock()
            self.viewport = viewport
            self.state = "transition"

    @property
    def token(self):
        return self.session_id, self.index, self.attempt

    def update(self, face, fps):
        if self.state not in ("transition", "fixation"):
            return
        now = self.clock()
        end_transition = self.started + self.settle_s
        end_fixation = end_transition + self.fixation_s
        captured = face.timestamp_ms / 1000 if face is not None else -1.
        if self.started <= captured < end_fixation and face.timestamp_ms > self.last_timestamp:
            self.last_timestamp = face.timestamp_ms
            phase = "transition" if captured < end_transition else "fixation"
            row = observe_direction(face, fresh=0 <= now - captured <= self.max_age, fps=fps, observed_at=now,
                       phase=phase, limits=self.limits, models=self.models)
            self.samples.append(row)
        if now >= end_fixation + self.max_age:
            good = sum(row["phase"] == "fixation" and row["rejected"] is None for row in self.samples)
            if good >= self.min_samples:
                self._archive(used=True, advance=True)
            else:
                self.state = "retry"
        elif now >= end_transition:
            self.state = "fixation"

    def retry(self, *, skip=False):
        if self.state == "retry":
            self._archive(used=False, advance=skip)

    def _archive(self, *, used, advance):
        target = self.schedule[self.index]
        if used and target == "center" and self.head_reference is None:
            heads = [row["head"] for row in self.samples if row["head"] is not None
                     and row["phase"] == "fixation" and row["rejected"] is None]
            if heads:
                self.head_reference = tuple(median(values) if values else None
                                            for values in ([v for v in axis if v is not None] for axis in zip(*heads)))
        self.trials.append(dict(index=self.index, round=self.index // len(DIRECTIONS),
                                attempt=self.attempt, target=target, target_viewport_logical_px=self.viewport,
                                used=used, samples=self.samples))
        self.samples = []
        if advance:
            self.index += 1
            self.attempt = 0
        else:
            self.attempt += 1
        self.state = "await_target"
        if self.index == len(self.schedule):
            self.state = "ready"
            for trial in self.trials:
                for row in trial["samples"]:
                    delta = _head_shift(row["head"], self.head_reference) if row["head"] is not None else None
                    row["head_delta"] = delta
                    row["head_motion"] = None if delta is None else (
                        delta[0] > HEAD_POSITION_DELTA or (delta[1] is not None and delta[1] > HEAD_ANGLE_DELTA))
            channels = RAW_CHANNELS + tuple(self.models)
            self.report = analyze(self.trials, channels, self.min_samples)

    def record(self):
        return dict(experiment="ocular_direction", schema_version=1, source="webcam", recorded_at=self.created_at,
                    configuration=dict(target_positions=TARGETS, rounds=len(self.schedule) // len(DIRECTIONS),
                                       settle_s=self.settle_s, fixation_s=self.fixation_s, min_samples=self.min_samples,
                                       max_sample_age_s=self.max_age, blink_limits=self.limits,
                                       head_position_delta=HEAD_POSITION_DELTA, head_angle_delta=HEAD_ANGLE_DELTA,
                                       models={name: dict(source=model.eye_source, reference=model.vertical_reference)
                                               for name, model in self.models.items()}),
                    head_axes=("nose_x", "nose_y", "face_scale", "pitch_deg", "yaw_deg", "roll_deg"),
                    head_reference=self.head_reference, trials=self.trials, metrics=self.report)

    def snapshot(self):
        current = self.samples[-1] if self.samples else None
        return dict(token=self.token, target=self.schedule[self.index] if self.index < len(self.schedule) else None,
                    done=self.index, total=len(self.schedule), state=self.state, path=self.path, save_error=self.save_error,
                    valid=current["rejected"] is None if current else None, report=self.report)
