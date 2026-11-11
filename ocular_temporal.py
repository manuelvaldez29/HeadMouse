"""Causal ocular direction estimation over recent, independently acquired FaceData."""
from collections import deque
from dataclasses import dataclass
from statistics import fmean, median, pstdev

from direction_diagnostic import observe_direction

VECTORS = dict(up=(0, -1), down=(0, 1), left=(-1, 0), right=(1, 0))
ALGORITHMS = ("previous", "median", "weighted")
WINDOWS = (.24, .36, .48)
MAX_GAP = .12
MIN_GAP = .012


@dataclass(frozen=True)
class EyeObservation:
    """Numeric observation shared by FaceData input and recorded diagnostic samples."""

    timestamp_ms: int
    point: tuple[float, float] | None


def eye_observation(face, channel, limits):
    if face is None:
        return None
    point = observe_direction(face, fresh=True, fps=None, observed_at=face.timestamp_ms / 1000,
                              phase="joystick", limits=limits, models={})["signals"].get(channel)
    return EyeObservation(face.timestamp_ms, point)


def current_point(sample, now, max_age):
    if sample is not None and 0 <= now - sample.timestamp_ms / 1000 <= max_age:
        return sample.point
    return None


def filtered_point(points, method):
    if method == "median":
        return tuple(median(axis) for axis in zip(*points))
    # Trim one extreme per side for short windows, then use a mean of the remaining values.
    result = []
    for axis in zip(*points):
        ordered = sorted(axis)
        trim = len(ordered) // 7
        result.append(fmean(ordered[trim:len(ordered) - trim]))
    return tuple(result)


def window_noise(trials, channel, window, method, fallback):
    """Estimate dispersion of the filtered neutral signal from training trials only."""
    centers = []
    for trial in trials:
        if not trial["used"] or trial["target"] != "center":
            continue
        points = []
        for row in trial["samples"]:
            if row["phase"] != "fixation":
                continue
            stamp = row["timestamp_ms"] / 1000
            point = row["signals"].get(channel)
            if point is None or (points and stamp - points[-1][0] > MAX_GAP):
                points.clear()
            if point is None:
                continue
            points.append((stamp, point))
            if len(points) >= 5 and stamp - points[0][0] >= window * .75:
                centers.append(filtered_point([value for _, value in points], method))
                points.clear()
    return tuple(pstdev(axis) for axis in zip(*centers)) if len(centers) >= 3 else fallback


class TemporalGaze:
    def __init__(self, classifier, noise, *, window=.36, method="weighted",
                 channel="eyelids_both", max_age=.25, limits=None):
        self.classifier, self.window, self.method = classifier, window, method
        self.channel, self.max_age = channel, max_age
        self.limits = limits or dict(left=.045, right=.045)
        self.center = classifier.centers["center"]
        self.deadzone = tuple(min(.30, max(.10, 2.5 * sigma / scale))
                              for sigma, scale in zip(noise, classifier.scales))
        self.displacements = {}
        for label, (x, y) in VECTORS.items():
            axis = int(x == 0)
            sign = y if axis else x
            gap = sign * (classifier.centers[label][axis] - self.center[axis])
            if gap >= max(MIN_GAP, 2.5 * noise[axis]):
                self.displacements[label] = (axis, sign, gap)
        self.reliable = set(self.displacements)
        self.samples = deque()
        self.timestamp = 0
        self.instant = self.accepted = None
        self.confidence = 0.
        self.reason = "warming"
        self.last_support = float("-inf")
        self.last_result = (None, 0., None)

    def reset(self):
        self.samples.clear()
        self.instant = self.accepted = None
        self.confidence = 0.
        self.reason = "lost"
        self.last_support = float("-inf")
        self.last_result = (None, 0., None)

    def _result(self, label, confidence, point, reason):
        self.confidence, self.reason = confidence, reason
        self.last_result = (label, confidence, point)
        return self.last_result

    def _classify(self, point):
        offset = (abs(x-y) / scale for x, y, scale in zip(point, self.center, self.classifier.scales))
        if all(delta <= bound for delta, bound in zip(offset, self.deadzone)):
            return "center", 1., 0.
        return self.classifier.estimate(point)

    def _reaches(self, point, label, fraction):
        axis, sign, gap = self.displacements[label]
        return sign * (point[axis] - self.center[axis]) >= fraction * gap

    def read(self, face, now):
        return self.observe(eye_observation(face, self.channel, self.limits), now)

    def observe(self, sample, now):
        point = current_point(sample, now, min(self.max_age, .18))
        if point is None or sample.timestamp_ms < self.timestamp:
            self.reset()
            return self.last_result
        if sample.timestamp_ms == self.timestamp:
            return self.last_result
        t = sample.timestamp_ms / 1000
        if self.samples and t - self.samples[-1][0] > MAX_GAP:
            self.reset()
        self.timestamp = sample.timestamp_ms
        self.instant = self.classifier.estimate(point)[0]
        self.samples.append((t, point))
        while self.samples and t - self.samples[0][0] > self.window + .002:
            self.samples.popleft()
        if len(self.samples) < 5 or t - self.samples[0][0] < self.window * .64:
            return self._result(None, 0., point, "warming")

        values = [value for _, value in self.samples]
        aggregate = filtered_point(values, self.method)
        label, margin, distance = self._classify(aggregate)
        # A coherent recent change can veto old votes before a new direction is eligible.
        recent = [value for stamp, value in self.samples if t - stamp <= .135]
        if self.accepted in VECTORS and len(recent) >= 4:
            tail, tail_margin, tail_distance = self._classify(filtered_point(recent, "median"))
            votes = sum(self._classify(value)[0] == tail for value in recent)
            if tail != self.accepted and tail is not None and tail_margin >= .68 and tail_distance <= .45 and votes >= 3:
                self.reset()
                self.instant = self.classifier.estimate(point)[0]
                return self._result("center" if tail == "center" else None, 0., point, "transition")
        if distance > .55 or label not in self.reliable | {"center"}:
            self.accepted = None
            return self._result(None, 0., point, "separation")

        support = 1.
        if self.method == "weighted" and label != "center":
            # Votes on short robust subwindows. Newer evidence carries more weight.
            scores, total = 0., 0.
            for index in range(2, len(values)):
                vote, confidence, _ = self._classify(filtered_point(values[index-2:index+1], "median"))
                weight = 1. + (self.samples[index][0] - self.samples[0][0]) / self.window
                total += weight
                if vote == label:
                    scores += weight * (.5 + .5 * confidence)
            support = scores / total
            if support < .48:
                self.accepted = None
                return self._result(None, 0., point, "disagreement")
        if label in VECTORS:
            # A direction needs recent support even when older samples agree.
            recent_point = filtered_point(recent[-3:], "median")
            tail, tail_margin, tail_distance = self._classify(recent_point)
            required = .57 if self.accepted == label else .63
            agrees = (tail == label and tail_margin >= .55 and tail_distance <= .48
                      and self._reaches(recent_point, label, required)
                      and self._reaches(aggregate, label, .57))
            if not agrees:
                if label != self.accepted or t - self.last_support > .08:
                    self.accepted = None
                    return self._result(None, 0., point, "recent_disagreement")
            else:
                self.last_support = t
        self.accepted = label
        return self._result(label, margin * (.78 + .22 * support), point, "evidence")
