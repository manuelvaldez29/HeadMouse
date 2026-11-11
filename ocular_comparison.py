"""Paired synthetic comparison on fixed input frames and closed-loop courses."""
from collections import Counter
from dataclasses import replace
from itertools import product
import argparse
from pathlib import Path
from statistics import fmean, median
import time

from direction_diagnostic import DIRECTIONS, RAW_CHANNELS
from ocular_joystick import JoystickOptions, VirtualJoystick, make_estimator
from ocular_lab import JoystickCourse
from ocular_simulation import BASE_TIME, IDEAL, SCENARIOS, STEP, SyntheticVision, run_simulation, write_report
from ocular_temporal import WINDOWS

REFERENCE_WINDOW = .24

TUNE_SEEDS = (11, 73)
VALIDATION_SEEDS = (42, 101, 307)
TUNE_SCENARIOS = ("ideal", "moderate", "noisy", "asymmetry")
BASE_PROTOCOL = tuple(segment for target in ("up", "left", "down", "right")
                      for segment in ((target, 2.3, "normal"), ("center", 1.1, "normal")))
STRESS = {
    "rapid": (replace(IDEAL, noise=.032, natural=.027),
              (("up", .24, "rapid"), ("down", .24, "rapid"), ("left", .24, "rapid"),
               ("right", .24, "rapid"), ("center", 1.1, "normal")) * 3),
    "long_blink": (replace(IDEAL, noise=.035, blink=.004),
                   (("left", 1.5, "normal"), ("left", .8, "blink"), ("left", 1.5, "normal"),
                    ("center", 1., "normal"))),
    "outage": (replace(IDEAL, noise=.028, loss=.002, delay_ms=110),
               (("right", 1.5, "normal"), ("right", 1.1, "outage"), ("right", 1.7, "normal"),
                ("center", 1., "normal"))),
}
ABSTAIN = "unavailable"
COLUMNS = (*DIRECTIONS, ABSTAIN)


def fixed_stream(config, seed, segments):
    """Produce one identical input sequence for both methods."""
    source = SyntheticVision(config, seed)
    tick = 0
    intended_at_capture = {}
    for index, (intent, duration, condition) in enumerate(segments):
        count = round(duration / STEP)
        if condition == "blink":
            source.blinking = count
        if condition == "outage":
            source.lost = count
        for offset in range(count):
            now = BASE_TIME + tick * STEP
            frame = source.tick(now, intent)
            intended_at_capture[source.last_timestamp] = intent
            capture_intent = intended_at_capture.pop(frame.timestamp_ms) if frame is not None else None
            yield now, index, offset * STEP, intent, condition, frame, capture_intent
            tick += 1


def evaluate_stream(frames, training, options):
    started = time.process_time()
    try:
        estimator = make_estimator(training, options)
    except ValueError:
        estimator = None
    joystick = VirtualJoystick(options)
    matrix = {actual: dict.fromkeys(COLUMNS, 0) for actual in DIRECTIONS}
    raw_matrix = {actual: dict.fromkeys(COLUMNS, 0) for actual in DIRECTIONS}
    changes, acquisitions, releases, invalid_latencies = [], [], [], []
    false = wrong = still = invalid_movement = rapid = 0
    capture_false = neutral_motion = wrong_motion = 0
    active_before = False
    segment = -1
    got_direction = False
    pending_release = False
    recent_direction = None
    blocks = Counter()
    for now, index, offset, intended, condition, face, capture_intent in frames:
        if index != segment:
            segment = index
            got_direction = False
            pending_release = intended == "center" and joystick.active is not None
        label, confidence, point = estimator.read(face, now) if estimator else (None, 0., None)
        instant = estimator.instant if estimator else None
        if offset >= .55 and condition == "normal":
            matrix[intended][label or ABSTAIN] += 1
            raw_matrix[intended][instant or ABSTAIN] += 1
        if label is None:
            blocks[getattr(estimator, "reason", "lost" if point is None else "separation")] += 1
        before, count = joystick.position, joystick.activations
        joystick.update(now, label, confidence)
        moved = joystick.position != before
        still += not moved
        neutral_motion += moved and intended == "center"
        wrong_motion += moved and intended != "center" and joystick.active != intended
        invalid_movement += point is None and moved
        if point is None and active_before:
            invalid_latencies.append(0. if joystick.active is None else STEP * 1000)
        active_before = joystick.active is not None
        if joystick.activations != count:
            active = joystick.active
            false += intended == "center"
            capture_false += capture_intent == "center"
            wrong += intended != "center" and intended != active
            rapid += condition == "rapid"
            if recent_direction and recent_direction != active:
                changes.append(dict(direction=active, intended=intended, seconds=now - BASE_TIME))
            recent_direction = active
            if not got_direction and active == intended and condition == "normal":
                got_direction = True
                acquisitions.append(dict(direction=active, segment=index, ms=offset * 1000))
        if pending_release and joystick.active is None:
            pending_release = False
            releases.append(offset * 1000)
    total = sum(sum(row.values()) for row in matrix.values())
    hits = sum(matrix[label][label] for label in DIRECTIONS)
    decisions = total - sum(row[ABSTAIN] for row in matrix.values())
    raw_hits = sum(raw_matrix[label][label] for label in DIRECTIONS)
    values = lambda data: dict(n=len(data), median=median(data) if data else None, maximum=max(data) if data else None)
    return dict(confusion=matrix, instantaneous_confusion=raw_matrix, scored_frames=total, correct=hits,
                correct_percent=100 * hits / total if total else None,
                instantaneous_correct_percent=100 * raw_hits / total if total else None,
                conditional_correct_percent=100 * hits / decisions if decisions else None,
                abstained_frames=total-decisions, stopped_percent=100 * still / len(frames),
                acquisitions=acquisitions, acquisition_ms=values([item["ms"] for item in acquisitions]),
                release_ms=values(releases), invalid_delivery_stop_ms=values(invalid_latencies),
                false_activations=false, false_activations_at_capture=capture_false, wrong_activations=wrong,
                neutral_motion_ticks=neutral_motion, wrong_motion_ticks=wrong_motion,
                wrong_direction_changes=sum(item["direction"] != item["intended"] for item in changes),
                rapid_activations=rapid, invalid_movement_ticks=invalid_movement,
                distance_px=joystick.distance, blocks=dict(blocks),
                cpu_ms=(time.process_time()-started)*1000, ticks=len(frames))


class CourseComparison:
    """An incremental pair for the UI. Independent of any manual practice session."""

    def __init__(self, config, seed, scenario, options):
        options = replace(options, selection="ocular")
        self.options = options
        self.config, self.seed, self.scenario = config, seed, scenario
        enhanced = options.algorithm if options.algorithm != "previous" else "weighted"
        self.runs = {method: JoystickCourse(config, seed, scenario, replace(options, algorithm=method))
                     for method in ("previous", enhanced)}
        self.enhanced = enhanced
        self.done = False

    def step(self, batch=32):
        for course in self.runs.values():
            for _ in range(batch):
                if course.done:
                    break
                course.step()
        self.done = all(course.done for course in self.runs.values())

    def progress(self):
        return fmean(1. if run.done else min(.99, run.ticks * STEP / run.timeout) for run in self.runs.values())

    def record(self):
        results = {method: run.record() for method, run in self.runs.items()}
        prior, newer = (results[method]["metrics"] for method in ("previous", self.enhanced))
        keys = ("targets_reached", "elapsed_s", "distance_px", "stationary_percent",
                "accidental_activations", "incorrect_activations", "corrections")
        return dict(source="synthetic", experiment="ocular_temporal_comparison", schema_version=1,
                    scenario=self.scenario, seed=self.seed, enhanced=self.enhanced, runs=results,
                    delta={key: newer[key] - prior[key] for key in keys})


def evaluate(tuning=False, *, window=REFERENCE_WINDOW, courses=False):
    scenarios = {key: (SCENARIOS[key][1], BASE_PROTOCOL)
                 for key in (TUNE_SCENARIOS if tuning else SCENARIOS)}
    if not tuning:
        scenarios.update({key: (config, BASE_PROTOCOL + segments) for key, (config, segments) in STRESS.items()})
    seeds = TUNE_SEEDS if tuning else VALIDATION_SEEDS
    variants = [("previous", window)]
    variants.extend(product(("median", "weighted"), WINDOWS) if tuning else [("weighted", window)])
    results = []
    for name, (config, segments) in scenarios.items():
        for seed in seeds:
            train_seed = seed ^ 0x512AC
            training = run_simulation(config, train_seed, name).session
            frames = tuple(fixed_stream(config, seed, segments))
            channels = ("eyelids_both",) if tuning else RAW_CHANNELS
            streams = {}
            for channel in channels:
                streams[channel] = {method + (f"-{seconds:.2f}" if method != "previous" else ""):
                    evaluate_stream(frames, training, JoystickOptions(mode="continuous", algorithm=method,
                                                                      window=seconds, channel=channel))
                    for method, seconds in variants}
            row = dict(scenario=name, seed=seed, training_seed=train_seed, streams=streams,
                       fixation={channel: training.report["channels"][channel]["fixation"] for channel in channels},
                       separation={channel: training.report["channels"][channel]["separation"] for channel in channels})
            if courses and name in SCENARIOS:
                row["courses"] = {}
                for mode in ("step", "continuous"):
                    pair = CourseComparison(config, seed, name, JoystickOptions(mode=mode, window=window))
                    start = time.process_time()
                    while not pair.done:
                        pair.step()
                    record = pair.record()
                    row["courses"][mode] = dict(delta=record["delta"], cpu_ms=(time.process_time()-start)*1000,
                                               runs={key: data["metrics"] for key, data in record["runs"].items()})
            results.append(row)
    return dict(source="synthetic", split="tuning" if tuning else "validation", seeds=seeds,
                direction_order=DIRECTIONS, prediction_order=COLUMNS, results=results)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tune", action="store_true")
    parser.add_argument("--courses", action="store_true")
    parser.add_argument("--window", type=float, choices=WINDOWS, default=REFERENCE_WINDOW)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    write_report(args.output, evaluate(args.tune, window=args.window, courses=args.courses))


if __name__ == "__main__":
    main()
