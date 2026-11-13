"""Experimental within-direction posture correction for the paired diagnostic."""
from dataclasses import asdict, dataclass
import math

import numpy as np

from direction_diagnostic import DIRECTIONS, DirectionClassifier


FEATURES = ("nose_x", "nose_y", "log_face_scale", "pitch", "yaw", "roll")
VERSION = 1


def pose_features(head):
    if head is None or len(head) != 6 or any(v is None or not math.isfinite(v) for v in head) or head[2] <= 0:
        return None
    return (*head[:2], math.log(head[2]), *head[3:])


def correction_limits(classifier):
    centers = classifier.centers
    return tuple(min(abs(centers[label][axis] - centers["center"][axis]) for label in directions)
                 for axis, directions in enumerate((("left", "right"), ("up", "down"))))


@dataclass(frozen=True)
class PoseAdjustment:
    reference: tuple
    scales: tuple
    lower: tuple
    upper: tuple
    weights: tuple
    limits: tuple
    centers: dict

    def classifier(self):
        return DirectionClassifier(self.centers)

    def correct(self, signal, pose):
        if pose is None or any(not low <= value <= high for value, low, high in zip(pose, self.lower, self.upper)):
            return None
        features = tuple((value - ref) / scale if scale else 0.
                         for value, ref, scale in zip(pose, self.reference, self.scales))
        return tuple(value - max(-limit, min(limit, sum(x * weight for x, weight in zip(features, weights))))
                     for value, limit, weights in zip(signal, self.limits, self.weights))

    @classmethod
    def read(cls, record):
        keys = ("reference", "scales", "lower", "upper", "weights", "limits", "centers")
        if not isinstance(record, dict) or set(record) != set(keys):
            raise ValueError("Ajuste de postura incompleto")
        def vector(values, size):
            if len(values) != size or any(not isinstance(v, (float, int)) or isinstance(v, bool)
                                         or not math.isfinite(v) for v in values):
                raise ValueError("Parámetros de postura inválidos")
            return tuple(map(float, values))
        reference, scales, lower, upper = (vector(record[key], 6) for key in keys[:4])
        weights = tuple(vector(row, 6) for row in record["weights"])
        limits = vector(record["limits"], 2)
        centers = record["centers"]
        if (len(weights) != 2 or set(centers) != set(DIRECTIONS) or any(v < 0 for v in (*scales, *limits))
                or any(not lo <= ref <= hi for lo, ref, hi in zip(lower, reference, upper))):
            raise ValueError("Dominio de postura inválido")
        return cls(reference, scales, lower, upper, weights, limits,
                   {label: vector(centers[label], 2) for label in DIRECTIONS})


def fit_adjustment(train, axis, classifier, minimum):
    # Give each target and round equal influence. Direction-specific centering
    # removes between-target posture differences before estimating drift.
    groups = {}
    for (rnd, label), rows in train.items():
        valid = [(row[axis], row[3]) for row in rows if row[3] is not None]
        if len(valid) < minimum:
            return None
        groups[rnd, label] = tuple(np.asarray(column) for column in zip(*valid))
    centered = {}
    for label in DIRECTIONS:
        selected = [(y, x) for (_, target), (y, x) in groups.items() if target == label]
        y_mean, x_mean = (np.mean([part.mean(axis=0) for part in column], axis=0)
                          for column in zip(*selected))
        centered[label] = y_mean, x_mean
    x_rows, y_rows = [], []
    for (_, label), (y, x) in groups.items():
        y_mean, x_mean = centered[label]
        weight = len(x) ** -.5
        x_rows.append((x - x_mean) * weight)
        y_rows.append((y - y_mean) * weight)
    x, y = np.concatenate(x_rows), np.concatenate(y_rows)
    scales = np.sqrt(np.sum(x * x, axis=0) / len(groups))
    scales[scales < np.finfo(float).eps ** .5] = 0
    if not np.any(scales):
        return None
    x = np.divide(x, scales, out=np.zeros_like(x), where=scales > 0)
    weights = np.linalg.solve(x.T @ x + len(groups) * np.eye(len(FEATURES)), x.T @ y).T
    poses = np.concatenate([x for _, x in groups.values()])
    adjustment = PoseAdjustment(tuple(np.median(poses, axis=0)), tuple(scales), tuple(poses.min(axis=0)),
                                tuple(poses.max(axis=0)), tuple(map(tuple, weights)),
                                tuple(limit / 2 for limit in correction_limits(classifier)), {})
    per_target = {label: [] for label in DIRECTIONS}
    for (_, label), (signals, poses) in groups.items():
        corrected = [adjustment.correct(signal, pose) for signal, pose in zip(signals, poses)]
        per_target[label].append(tuple(np.median(corrected, axis=0)))
    centers = DirectionClassifier.fit(per_target).centers
    return PoseAdjustment.read(asdict(adjustment) | {"centers": centers})
