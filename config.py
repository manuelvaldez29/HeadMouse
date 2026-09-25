"""Configuración validada; precedencia: defaults < archivo < perfil < CLI."""
import json
import logging
import math
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from action_mapping import DEFAULT_MAPPING, ActionMapping

ROOT = Path(__file__).resolve().parent
DEFAULT_THRESHOLDS = dict(blink_left=0.045, blink_right=0.045,
                          brow_left=0.290, brow_right=0.290, mouth_open=0.180)


def bounded(name, value, low, high, *, integer=False, inclusive_high=True):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value < low
            or (value > high if inclusive_high else value >= high)
            or (integer and not isinstance(value, int))):
        raise ValueError(f"{name}: valor fuera de rango [{low}, {high}]: {value!r}")


@dataclass
class GestureConfig:
    sensitivity: float = 80.0
    acceleration: float = 600.0
    dead_zone: float = 0.03
    smoothing_alpha: float = 0.35
    neutral_x: float = 0.5
    neutral_y: float = 0.5
    blink_hold_ms: float = 60
    blink_cooldown_ms: float = 600
    brow_hold_ms: float = 120
    brow_cooldown_ms: float = 220
    mouth_hold_ms: float = 150
    mouth_cooldown_ms: float = 800
    both_brows_hold_ms: float = 180
    both_brows_cooldown_ms: float = 1000
    screen_w: int = 1920
    screen_h: int = 1080
    stale_after_s: float = 0.25
    sensitivity_x: float | None = None
    sensitivity_y: float | None = None

    def __post_init__(self):
        for name in ("sensitivity", "acceleration"):
            bounded(name, getattr(self, name), 0, 10000)
        for name in ("sensitivity_x", "sensitivity_y"):
            if getattr(self, name) is not None:
                bounded(name, getattr(self, name), 0, 10000)
        bounded("dead_zone", self.dead_zone, 0, 0.5, inclusive_high=False)
        bounded("smoothing_alpha", self.smoothing_alpha, 0, 1, inclusive_high=False)
        for name in ("neutral_x", "neutral_y"):
            bounded(name, getattr(self, name), 0, 1)
        for f in fields(self):
            if f.name.endswith("_ms"):
                bounded(f.name, getattr(self, f.name), 0, 60000)
        for name in ("screen_w", "screen_h"):
            bounded(name, getattr(self, name), 1, 100000, integer=True)
        bounded("stale_after_s", self.stale_after_s, 0.01, 2)


@dataclass
class ControlConfig:
    scroll_lines: int = 3
    face_timeout_s: float = 2.0
    max_cursor_delta: float = 60.0
    loop_hz: float = 60.0

    def __post_init__(self):
        bounded("scroll_lines", self.scroll_lines, 1, 100, integer=True)
        bounded("face_timeout_s", self.face_timeout_s, 0.01, 60)
        bounded("max_cursor_delta", self.max_cursor_delta, 1, 1000)
        bounded("loop_hz", self.loop_hz, 1, 240)


@dataclass
class VisionConfig:
    camera_index: int = 0
    target_fps: int = 30
    model_path: str = "models/face_landmarker.task"
    detection_confidence: float = 0.5
    presence_confidence: float = 0.5
    tracking_confidence: float = 0.5
    startup_timeout_s: float = 10.0
    capture_failure_limit: int = 30

    def __post_init__(self):
        bounded("camera_index", self.camera_index, 0, 100, integer=True)
        bounded("target_fps", self.target_fps, 1, 240, integer=True)
        bounded("startup_timeout_s", self.startup_timeout_s, 0.1, 120)
        bounded("capture_failure_limit", self.capture_failure_limit, 1, 1000, integer=True)
        for name in ("detection_confidence", "presence_confidence", "tracking_confidence"):
            bounded(name, getattr(self, name), 0, 1)
        if not isinstance(self.model_path, str) or not self.model_path.strip():
            raise ValueError("model_path debe ser una ruta no vacía")


@dataclass
class CalibrationConfig:
    countdown_s: float = 3
    measuring_s: float = 4
    min_samples: int = 20
    threshold_fraction: float = 0.6
    min_separation: float = 0.002
    noise_multiplier: float = 1.5
    validation_timeout_s: float = 30
    validation_neutral_s: float = 2

    def __post_init__(self):
        for name in ("countdown_s", "measuring_s", "validation_timeout_s", "validation_neutral_s"):
            bounded(name, getattr(self, name), 0.1, 120)
        if self.validation_neutral_s >= self.validation_timeout_s:
            raise ValueError("validation_neutral_s debe ser menor que validation_timeout_s")
        bounded("min_samples", self.min_samples, 3, 10000, integer=True)
        bounded("threshold_fraction", self.threshold_fraction, 0.1, 0.9)
        bounded("min_separation", self.min_separation, 0.0001, 1)
        bounded("noise_multiplier", self.noise_multiplier, 1, 10)


@dataclass
class UIConfig:
    show_overlay: bool = True
    show_landmarks: bool = True
    tracking_method: str = "nose"

    def __post_init__(self):
        if type(self.show_overlay) is not bool or type(self.show_landmarks) is not bool:
            raise ValueError("Overlays y landmarks deben ser booleanos")
        if self.tracking_method != "nose":
            raise ValueError("Por ahora solo está disponible tracking de nariz")


@dataclass
class MappingConfig:
    bindings: dict = field(default_factory=lambda: DEFAULT_MAPPING.copy())

    def __post_init__(self):
        ActionMapping(self.bindings)


@dataclass
class AppConfig:
    vision: VisionConfig = field(default_factory=VisionConfig)
    gesture: GestureConfig = field(default_factory=GestureConfig)
    control: ControlConfig = field(default_factory=ControlConfig)
    calibration: CalibrationConfig = field(default_factory=CalibrationConfig)
    ui: UIConfig = field(default_factory=UIConfig)
    actions: MappingConfig = field(default_factory=MappingConfig)
    log_level: str = "INFO"
    metrics_enabled: bool = True

    def __post_init__(self):
        if self.log_level not in ("DEBUG", "INFO", "WARNING", "ERROR"):
            raise ValueError("log_level inválido")
        if not isinstance(self.metrics_enabled, bool):
            raise ValueError("metrics_enabled debe ser booleano")


SECTIONS = dict(vision=VisionConfig, gesture=GestureConfig, control=ControlConfig,
                calibration=CalibrationConfig, ui=UIConfig, actions=MappingConfig)


def load_config(path=None, overrides=None):
    data = asdict(AppConfig())
    layers = []
    if path is not None:
        with open(path, encoding="utf-8") as stream:
            layers.append(json.load(stream))
    if overrides is not None:
        layers.append(overrides)
    for layer in layers:
        if not isinstance(layer, dict) or layer.keys() - data.keys():
            raise ValueError("Secciones de configuración inválidas")
        for name, value in layer.items():
            if name in SECTIONS:
                if not isinstance(value, dict) or value.keys() - data[name].keys():
                    raise ValueError(f"Parámetros inválidos en {name}")
                data[name].update(value)
            else:
                data[name] = value
    return AppConfig(**{k: SECTIONS[k](**v) if k in SECTIONS else v
                        for k, v in data.items()})


def configure_logging(level):
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
