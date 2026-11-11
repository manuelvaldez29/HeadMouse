"""Direction selection and virtual movement. This module has no desktop backend."""
from dataclasses import dataclass
import math

from direction_diagnostic import RAW_CHANNELS
from ocular_simulation import VECTORS, train_classifier
from ocular_temporal import ALGORITHMS, WINDOWS, TemporalGaze, current_point, eye_observation, window_noise

WIDTH, HEIGHT = 640, 420
DIRECTIONS = tuple(key for key in VECTORS if key != "center")
STEPS = (5, 10, 20, 50)


@dataclass(frozen=True)
class JoystickOptions:
    mode: str = "step"
    pixels: int = 10
    dwell: float = .30
    initial_speed: float = 40.
    acceleration: float = 85.
    max_speed: float = 145.
    confidence: float = .48
    position: str = "center"
    algorithm: str = "previous"
    window: float = .24
    channel: str = "eyelids_both"
    selection: str = "ocular"
    continuous_policy: str = "hold"
    pulse_seconds: float = .40
    max_duration: float = 3.
    step_repeat: bool = False
    fine: bool = False
    task_set: str = "classic"

    def __post_init__(self):
        if (self.mode not in ("step", "continuous") or self.pixels not in STEPS
                or not .12 <= self.dwell <= 1.5 or not 0 < self.initial_speed <= self.max_speed <= 300
                or not 0 < self.acceleration <= 400 or not .2 <= self.confidence <= .95
                or self.algorithm not in ALGORITHMS or self.window not in WINDOWS or self.channel not in RAW_CHANNELS
                or self.selection not in ("ocular", "manual")
                or self.continuous_policy not in ("hold", "pulse")
                or not .18 <= self.pulse_seconds <= 1.0 or not .25 <= self.max_duration <= 5.
                or type(self.step_repeat) is not bool or type(self.fine) is not bool
                or self.task_set not in ("classic", "precision")
                or self.position not in ("center", "top_left", "top_right", "bottom_left", "bottom_right")):
            raise ValueError("Opciones del joystick fuera de rango")


class GazeDirection:
    """Turn FaceData into a direction candidate using the shared diagnostic model."""

    def __init__(self, classifier, noise, *, max_age=.25, channel="eyelids_both", limits=None):
        self.classifier = classifier
        self.center = classifier.centers["center"]
        self.noise = noise
        self.max_age, self.channel = max_age, channel
        self.limits = limits or dict(left=.045, right=.045)
        self.filtered = self.instant = None
        self.timestamp = 0
        self.deadzones = tuple(min(.30, max(.10, 2.5 * sigma / scale))
                              for sigma, scale in zip(noise, classifier.scales))
        self.reliable = set()
        for direction, (dx, dy) in VECTORS.items():
            axis = int(dx == 0)
            gap = (classifier.centers[direction][axis] - self.center[axis]) * (dy if axis else dx)
            if gap >= max(.012, 2.5 * noise[axis]):
                self.reliable.add(direction)

    def read(self, face, now):
        return self.observe(eye_observation(face, self.channel, self.limits), now)

    def observe(self, sample, now):
        point = current_point(sample, now, self.max_age)
        if point is None or sample.timestamp_ms < self.timestamp:
            return self._lost()
        self.instant = self.classifier.estimate(point)[0]
        offset = tuple(abs(x-y) / scale for x, y, scale in zip(point, self.center, self.classifier.scales))
        if all(delta <= bound for delta, bound in zip(offset, self.deadzones)):
            self.filtered = point
            self.timestamp = sample.timestamp_ms
            return "center", 1., point
        if self.filtered is None:
            self.filtered = point
        elif sample.timestamp_ms > self.timestamp:
            self.filtered = tuple(.55 * previous + .45 * current for previous, current in zip(self.filtered, point))
        self.timestamp = sample.timestamp_ms
        label, confidence, distance = self.classifier.estimate(self.filtered)
        if distance > .55 or label not in self.reliable | {"center"}:
            return None, 0., point
        return label, confidence, point

    def reset(self):
        self.filtered = self.instant = None

    def _lost(self):
        self.reset()
        return None, 0., None


def make_estimator(training, options):
    model = train_classifier(training, options.channel)
    neutral = training.report["channels"][options.channel]["fixation"]["center"]["fixation_sd"]
    if options.algorithm == "previous":
        return GazeDirection(model, neutral, channel=options.channel)
    sigma = window_noise(training.trials, options.channel, options.window, options.algorithm, neutral)
    return TemporalGaze(model, sigma, window=options.window, method=options.algorithm, channel=options.channel)


class VirtualJoystick:
    def __init__(self, options):
        self.options = options
        self.position = (WIDTH / 2, HEIGHT / 2)
        self.last = None
        self.candidate = self.active = self.latched = self.manual = None
        self.manual_step = False
        self.since = self.active_since = self.speed = self.distance = 0.
        self.stops = self.changes = self.activations = 0
        self.last_direction = None
        self.state = "neutral"
        self.locked = False
        self.neutral_since = None
        self.next_repeat = 0.
        self.eye_operations = self.manual_operations = 0
        self.input_source = None

    def select(self, direction):
        if direction not in DIRECTIONS:
            self.stop()
            return
        self.manual = direction
        self.manual_step = True

    def release(self):
        self.manual = None
        self.manual_step = False
        self.stop()

    def stop(self):
        if self.active:
            self.stops += 1
        self.active = self.candidate = self.latched = self.manual = None
        self.manual_step = False
        self.speed = 0.
        self.state = "neutral"
        self.locked = False
        self.neutral_since = None
        self.input_source = None

    def _clear_active(self):
        if self.active:
            self.stops += 1
        self.active = None
        self.speed = 0.

    def _move(self, direction, distance):
        dx, dy = VECTORS[direction]
        x, y = self.position
        new = (min(WIDTH, max(0., x + dx * distance)), min(HEIGHT, max(0., y + dy * distance)))
        self.distance += math.dist(new, self.position)
        self.position = new

    def _activate(self, now, direction):
        self.active = self.last_direction = direction
        self.active_since = now
        self.state = "active"
        self._operation()

    def _operation(self):
        self.activations += 1
        self.input_source = "manual" if self.manual else "ocular"
        if self.manual:
            self.manual_operations += 1
        else:
            self.eye_operations += 1

    def _lock(self, state):
        self._clear_active()
        self.locked, self.neutral_since, self.state = True, None, state

    def update(self, now, label, confidence, *, fine=False):
        dt = 0. if self.last is None else max(0., min(.1, now - self.last))
        self.last = now
        manual = self.manual
        if self.locked:
            if manual or label != "center":
                self.neutral_since = None
                return
            if self.neutral_since is None:
                self.neutral_since = now
            elif now - self.neutral_since >= .12:
                self.stop()
            return
        # Once selected, use a lower threshold for the same direction. All changes still dwell.
        limit = self.options.confidence * (.72 if label == self.active else 1.)
        direction = manual or (label if label in DIRECTIONS and confidence >= limit else None)
        if direction is None:
            self.stop()
            self.state = "neutral" if label == "center" else "unreliable"
            return
        if direction != self.candidate:
            self._clear_active()
            self.candidate, self.since = direction, now
        if not manual and now - self.since + 1e-9 < self.options.dwell:
            self.state = "selecting"
            return
        if self.options.mode == "step":
            distance = min(5, self.options.pixels) if fine else self.options.pixels
            if self.manual_step or self.latched != direction:
                if self.last_direction and self.last_direction != direction:
                    self.changes += 1
                self._activate(now, direction)
                self._move(direction, distance)
                self.latched = direction
                self.manual_step = False
                self.next_repeat = now + .65
            elif self.options.step_repeat:
                if now - self.active_since >= self.options.max_duration:
                    self._lock("rearm")
                    return
                if now >= self.next_repeat:
                    self._operation()
                    self._move(direction, distance)
                    self.next_repeat = now + .30
            self.state = "step"
        else:
            if self.active != direction:
                if self.last_direction and self.last_direction != direction:
                    self.changes += 1
                self._activate(now, direction)
                dt = 0.
            elapsed = now - self.active_since
            duration = self.options.max_duration
            if self.options.continuous_policy == "pulse":
                duration = min(duration, self.options.pulse_seconds)
            if elapsed >= duration:
                self._lock("boundary" if self.state == "boundary" else "rearm")
                return
            wanted = min(self.options.max_speed, self.options.initial_speed + elapsed * self.options.acceleration)
            if fine:
                wanted = min(40., wanted)
            before = self.distance
            self._move(direction, wanted * dt)
            self.speed = (self.distance - before) / dt if dt else 0.
            self.state = "active" if self.speed or not dt else "boundary"

    def snapshot(self, now):
        return dict(position=self.position, candidate=self.candidate, confirmed=self.active,
                    active=self.active, speed=self.speed,
                    distance=self.distance, activations=self.activations, stops=self.stops, changes=self.changes,
                    dwell_progress=min(1., (now - self.since) / self.options.dwell) if self.candidate else 0.,
                    active_seconds=now - self.active_since if self.active else 0., state=self.state,
                    input_source=self.input_source, locked=self.locked)
