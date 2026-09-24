"""Estadística de calibración independiente de OpenCV/NumPy y del SO."""
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from statistics import median
from config import CalibrationConfig

CHANNELS = {
    "blink_left": ("eye_left", "eye_left_min", -1),
    "blink_right": ("eye_right", "eye_right_min", -1),
    "brow_left": ("brow_left", "brow_left_max", 1),
    "brow_right": ("brow_right", "brow_right_max", 1),
    "mouth_open": ("mouth", "mouth_max", 1),
}


@dataclass
class Samples:
    eye_left: list = field(default_factory=list)
    eye_right: list = field(default_factory=list)
    brow_left: list = field(default_factory=list)
    brow_right: list = field(default_factory=list)
    mouth: list = field(default_factory=list)
    nose_x: list = field(default_factory=list)
    nose_y: list = field(default_factory=list)
    _last_timestamp: int = field(default=0, init=False)

    def add(self, fd, max_age_s=0.25, now=None):
        if not fd.fresh(max_age_s, now) or fd.timestamp_ms <= self._last_timestamp:
            return False
        self._last_timestamp = fd.timestamp_ms
        for name, value in zip(("eye_left", "eye_right", "brow_left", "brow_right",
                                "mouth", "nose_x", "nose_y"),
                               (fd.eye_left_ratio, fd.eye_right_ratio, fd.brow_left_lift,
                                fd.brow_right_lift, fd.mouth_open, fd.nose_x, fd.nose_y)):
            getattr(self, name).append(value)
        return True

    def median(self, key):
        values = getattr(self, key)
        if not values:
            raise ValueError(f"Sin muestras: {key}")
        return float(median(values))

    def percentile(self, key, p):
        values = sorted(getattr(self, key))
        if not values:
            raise ValueError(f"Sin muestras: {key}")
        index = (len(values) - 1) * p / 100
        low, high = math.floor(index), math.ceil(index)
        return values[low] + (values[high] - values[low]) * (index - low)

    def mad(self, key):
        center = self.median(key)
        return float(median(abs(x - center) for x in getattr(self, key)))


def compute_thresholds(data, config=None):
    config = config or CalibrationConfig()
    return {key: round(data["neutral"][channel] + config.threshold_fraction *
                       (data["gesture_extremes"][extreme] - data["neutral"][channel]), 4)
            for key, (channel, extreme, _) in CHANNELS.items()}


def validate_calibration(data, config=None):
    config = config or CalibrationConfig()
    if (not isinstance(data, dict) or
            any(not isinstance(data.get(key, {}), dict)
                for key in ("neutral", "gesture_extremes", "thresholds", "neutral_variability"))):
        return ["Estructura de calibración inválida"]
    errors = []
    for key, (channel, extreme, direction) in CHANNELS.items():
        try:
            n = data["neutral"][channel]
            e = data["gesture_extremes"][extreme]
            t = data["thresholds"][key]
            mad = data.get("neutral_variability", {}).get(channel, 0)
            if not all(type(v) in (int, float) and math.isfinite(v) for v in (n, e, t, mad)):
                raise ValueError("valor no finito")
            if mad < 0 or (direction < 0 or channel == "mouth") and min(n, e) < 0:
                raise ValueError("ratio o variabilidad negativos")
            margin = max(config.min_separation, config.noise_multiplier * 1.4826 * mad)
            if direction * (t - n) <= margin or direction * (e - t) <= 0:
                errors.append(f"{key}: umbral sin separación suficiente del neutral/extremo")
        except (KeyError, TypeError, ValueError):
            errors.append(f"{key}: datos incompletos o inválidos")
    return errors


def build_calibration(user_id, phases, config=None):
    config = config or CalibrationConfig()
    required = ("neutral", "wink_left", "wink_right", "brow_left", "brow_right", "mouth")
    if any(name not in phases or len(phases[name].eye_left) < config.min_samples for name in required):
        raise ValueError("Muestras insuficientes: repetir las fases")
    neutral = phases["neutral"]
    channels = ("eye_left", "eye_right", "brow_left", "brow_right", "mouth", "nose_x", "nose_y")
    data = dict(user_id=user_id, calibrated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                neutral_nose_x=neutral.median("nose_x"), neutral_nose_y=neutral.median("nose_y"),
                neutral={key: neutral.median(key) for key in channels},
                neutral_variability={key: neutral.mad(key) for key in channels},
                sample_counts={key: len(phases[key].eye_left) for key in required},
                gesture_extremes={
                    "eye_left_min": phases["wink_left"].percentile("eye_left", 10),
                    "eye_right_min": phases["wink_right"].percentile("eye_right", 10),
                    "brow_left_max": phases["brow_left"].percentile("brow_left", 90),
                    "brow_right_max": phases["brow_right"].percentile("brow_right", 90),
                    "mouth_max": phases["mouth"].percentile("mouth", 90)})
    data["thresholds"] = compute_thresholds(data, config)
    errors = validate_calibration(data, config)
    if errors:
        raise ValueError("; ".join(errors))
    return data
