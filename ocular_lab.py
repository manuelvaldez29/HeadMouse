"""Synthetic course and live session shared by the lab and automated evaluations."""
from dataclasses import asdict
import argparse
import math
from pathlib import Path
import time

from ocular_joystick import JoystickOptions, VirtualJoystick, make_estimator
from ocular_simulation import BASE_TIME, SCENARIOS, STEP, SyntheticVision, SyntheticDiagnostic, write_report

COURSE = ((320, 90, 22), (320, 330, 22), (140, 330, 22), (500, 330, 22),
          (500, 180, 14), (320, 180, 22))
COURSE_TIMEOUT = 100.
PRECISION_COURSE = ((320, 85, 35), (105, 85, 20), (105, 335, 12), (535, 335, 9),
                    (535, 95, 18), (425, 95, 8))
PRECISION_TIMEOUT = 165.


class JoystickCourse:
    def __init__(self, config, seed, scenario, options, *, automatic=True):
        self.config, self.seed, self.scenario = config, seed, scenario
        self.options, self.automatic = options, automatic
        self.training_seed = seed ^ 0x512AC
        self.vision = SyntheticVision(config, seed)
        self.joystick = VirtualJoystick(options)
        self.selection = options.selection
        self.course = PRECISION_COURSE if options.task_set == "precision" else COURSE
        self.timeout = PRECISION_TIMEOUT if options.task_set == "precision" else COURSE_TIMEOUT
        self.training = (SyntheticDiagnostic(config, self.training_seed, scenario)
                         if self.selection == "ocular" else None)
        self.estimator = None
        self.training_error = None
        self.now, self.ticks = BASE_TIME, 0
        self.intent, self.estimate, self.confidence, self.point = "center", None, 0., None
        self.manual_intent = "center"
        self.target_index, self.target_since = 0, None
        self.anchor = self.joystick.position
        self.path = [self.anchor]
        self.missions = []
        self.incorrect = self.accidental = self.corrections = 0
        self.error_sum = self.outside_px = self.overshoot_px = 0.
        self.moved_samples = self.stopped_ticks = 0
        self.pulse_until = 0.
        self.done = False
        self.insufficient_ticks = self.invalid_ticks = 0
        self.rejected_confirms = 0
        self.previous_operations = 0
        self.release_started = None
        self.release_times = []
        self.was_active = False

    @property
    def target(self):
        return self.course[self.target_index] if self.target_index < len(self.course) else None

    @property
    def fine(self):
        target = self.target
        return bool(self.options.fine and target and math.dist(self.joystick.position, target[:2]) <= max(42, 2.5*target[2]))

    def command(self, action, direction=None):
        if action == "intent" and self.selection == "ocular":
            self.automatic = False
            self.manual_intent = direction
        elif action == "press":
            if self.done or self.training is not None:
                return
            self.automatic = False
            self.selection = "manual"
            self.stop_motion()
            before = self.joystick.position
            self.joystick.select(direction)
            if self.options.mode == "step":
                self.joystick.update(self.now, None, 0., fine=self.fine)
                self._measure(before, self.joystick.position)
        elif action == "release":
            # An explicit manual tap may authorize one bounded pulse after releasing.
            if not (self.selection == "manual" and self.options.mode == "continuous"
                    and self.options.continuous_policy == "pulse" and self.joystick.manual):
                self.stop_motion()
        elif action == "neutral":
            self.stop_motion()
        elif action == "confirm" and self.options.task_set == "precision":
            if not self._confirm("manual"):
                self.rejected_confirms += 1
        elif action == "auto" and self.estimator is not None:
            self.stop_motion()
            self.selection = "ocular"
            self.automatic = True

    def stop_motion(self):
        self.manual_intent = "center"
        self.joystick.stop()
        self.vision.release_intent()
        if self.estimator is not None:
            self.estimator.reset()

    def _pilot(self, position, target):
        if (self.joystick.locked or math.dist(position, target[:2]) <= target[2] * .64
                or self.now < self.pulse_until):
            return "center"
        dx, dy = target[0] - position[0], target[1] - position[1]
        if abs(dx) > abs(dy):
            return "right" if dx > 0 else "left"
        return "down" if dy > 0 else "up"

    def step(self):
        if self.done:
            return
        if self.training is not None:
            # Limit work per event-loop turn during the separate training acquisition.
            for _ in range(45):
                self.training.step()
                if self.training.session.state == "ready":
                    try:
                        self.estimator = make_estimator(self.training.session, self.options)
                    except ValueError:
                        self.training_error = "Faltan señales de las cinco direcciones para entrenar."
                    self.training = None
                    break
            return
        self.ticks += 1
        self.now = BASE_TIME + self.ticks * STEP
        previous = self.joystick.position
        ocular = self.selection == "ocular"
        expected = self._pilot(previous, self.target) if ocular and self.automatic else self.manual_intent
        self.intent = expected
        face = self.vision.tick(self.now, expected) if ocular else None
        self.estimate, self.confidence, self.point = self.estimator.read(face, self.now) if ocular and self.estimator else (None, 0., None)
        if ocular and self.was_active and expected == "center" and self.release_started is None:
            self.release_started = self.now
        elif expected != "center":
            self.release_started = None
        activations, previous_direction = self.joystick.activations, self.joystick.last_direction
        deliberate = bool(self.joystick.manual)
        self.joystick.update(self.now, self.estimate, self.confidence, fine=self.fine)
        if ocular:
            self.invalid_ticks += self.point is None
            self.insufficient_ticks += (self.point is None or self.estimate is None
                                        or (self.estimate != "center" and self.confidence < self.options.confidence))
        if self.release_started is not None and self.joystick.active is None:
            self.release_times.append(round((self.now-self.release_started)*1000, 3))
            self.release_started = None
        self.was_active = self.joystick.active is not None
        new_activation = self.joystick.activations > activations
        if new_activation:
            direction = self.joystick.active
            if self.automatic and self.options.mode == "step":
                self.pulse_until = self.now + .27
            if not deliberate and self.automatic:
                self.accidental += expected == "center"
                self.incorrect += expected != "center" and direction != expected
            axis = ("left", "right") if direction in ("left", "right") else ("up", "down")
            self.corrections += previous_direction in axis and previous_direction != direction
        self._measure(previous, self.joystick.position)
        self.stopped_ticks += previous == self.joystick.position
        if self.target_index == len(self.course) or self.ticks * STEP >= self.timeout:
            self.done = True
            self.joystick.stop()

    def _measure(self, old, new):
        tx, ty, radius = self.target
        inside = math.dist(new, (tx, ty)) <= radius
        distance = math.dist(old, new)
        if distance:
            self.path.append(new)
            self.moved_samples += 1
            self.outside_px += distance if not inside else 0.
            ax, ay = self.anchor
            ux, uy = tx - ax, ty - ay
            segment = math.hypot(ux, uy)
            if segment:
                self.error_sum += abs(ux * (new[1] - ay) - uy * (new[0] - ax)) / segment
                progress = (ux * (new[0] - ax) + uy * (new[1] - ay)) / segment
                self.overshoot_px += distance if progress > segment + radius else 0.
        if inside and not distance and self.joystick.active is None:
            if self.target_since is None:
                self.target_since = self.now
            if self.now - self.target_since >= .24:
                if self.options.task_set == "classic" or self.automatic:
                    self._confirm("synthetic_auto" if self.automatic else "virtual_dwell")
        else:
            self.target_since = None

    def _confirm(self, source):
        if (self.done or self.target is None or self.target_since is None
                or self.now - self.target_since < .24 or self.joystick.active is not None):
            return False
        operations = self.joystick.activations - self.previous_operations
        self.previous_operations = self.joystick.activations
        self.missions.append(dict(target=self.target, position=self.joystick.position,
                                  reached_s=self.ticks * STEP, operations=operations, confirmation=source))
        self.target_index += 1
        self.anchor = self.joystick.position
        self.target_since = None
        if self.target is None:
            self.done = True
            self.joystick.stop()
        return True

    def snapshot(self):
        return dict(joystick=self.joystick.snapshot(self.now), target=self.target, target_index=self.target_index,
                    targets=len(self.course), path=self.path[-480:], estimate=self.estimate, intent=self.intent,
                    selection=self.selection, fine=self.fine, task_set=self.options.task_set,
                    can_auto=self.estimator is not None, operations=self.joystick.activations + len(self.missions),
                    ready_to_confirm=self.target_since is not None and self.now-self.target_since >= .24,
                    invalid=self.point is None and self.selection == "ocular" and self.training is None,
                    confidence=self.confidence, point=self.point, elapsed_s=self.ticks * STEP,
                    instantaneous=self.estimator.instant if self.estimator else None,
                    evidence=getattr(self.estimator, "reason", None), algorithm=self.options.algorithm,
                    automatic=self.automatic, training=self.training.session.index if self.training else None,
                    training_error=self.training_error, done=self.done,
                    accidental=self.accidental, incorrect=self.incorrect, corrections=self.corrections)

    def record(self):
        return dict(source="synthetic", experiment="ocular_virtual_joystick", schema_version=1,
                    scenario=self.scenario, seed=self.seed, training_seed=self.training_seed,
                    simulation=asdict(self.config), options=asdict(self.options),
                    course=self.course, reached=self.missions, trajectory=self.path, finished=self.done,
                    outcome=("completed" if self.target_index == len(self.course) else "timeout" if self.done else "partial"),
                    metrics=dict(elapsed_s=self.ticks * STEP, targets_reached=self.target_index,
                                 distance_px=self.joystick.distance, stops=self.joystick.stops,
                                 stationary_percent=100 * self.stopped_ticks / self.ticks if self.ticks else None,
                                 direction_changes=self.joystick.changes, incorrect_activations=self.incorrect,
                                 eye_operations=self.joystick.eye_operations, manual_operations=self.joystick.manual_operations,
                                 operations=self.joystick.activations + len(self.missions),
                                 rejected_confirmations=self.rejected_confirms,
                                 insufficient_signal_s=self.insufficient_ticks * STEP,
                                 invalid_signal_s=self.invalid_ticks * STEP,
                                 neutral_stop_ms=self.release_times[:],
                                 accidental_activations=self.accidental, corrections=self.corrections,
                                 distance_outside_targets_px=self.outside_px, overshoot_distance_px=self.overshoot_px,
                                 mean_cross_track_px=self.error_sum / self.moved_samples if self.moved_samples else None))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    reports = {}
    for scenario, (_, config) in SCENARIOS.items():
        reports[scenario] = {}
        for mode in ("step", "continuous"):
            start = time.perf_counter()
            course = JoystickCourse(config, args.seed, scenario, JoystickOptions(mode=mode))
            while not course.done:
                course.step()
            reports[scenario][mode] = dict(course.record(), elapsed_wall_ms=(time.perf_counter()-start)*1000)
    write_report(args.output, dict(source="synthetic", seed=args.seed, scenarios=reports))


if __name__ == "__main__":
    main()
