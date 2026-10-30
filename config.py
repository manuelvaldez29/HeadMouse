"""Configuración validada; precedencia: defaults < archivo < perfil < CLI."""
from __future__ import annotations
import json
import logging
import math
import sys
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
    brow_decision_ms: float = 200
    # Las cejas solo actúan con la cabeza dentro de la zona muerta (cursor
    # quieto): al mirar hacia arriba la señal geométrica de cejas sube sola.
    brow_motion_gate: bool = True
    # Scroll continuo: con la ceja sostenida, repetir cada brow_repeat_ms
    # después de brow_repeat_delay_ms. 0 = un solo scroll por elevación.
    brow_repeat_delay_ms: float = 500
    brow_repeat_ms: float = 250
    # Al reanudar (ambas cejas), tomar como neutral la postura quieta previa:
    # la cámara puede estar más arriba o abajo que al calibrar.
    auto_recenter: bool = True

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
        bounded("brow_decision_ms", self.brow_decision_ms, 0, 1000)
        for name in ("brow_motion_gate", "auto_recenter"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} debe ser true o false")


@dataclass
class ControlConfig:
    scroll_lines: int = 3  # muescas de rueda por evento (Windows: 3 líneas cada una)
    face_timeout_s: float = 2.0
    max_cursor_delta: float = 60.0
    loop_hz: float = 60.0
    hold_click_enabled: bool = True
    drag_hold_ms: float = 400.0
    drag_release_ms: float = 50.0

    def __post_init__(self):
        bounded("scroll_lines", self.scroll_lines, 1, 100, integer=True)
        bounded("face_timeout_s", self.face_timeout_s, 0.01, 60)
        bounded("max_cursor_delta", self.max_cursor_delta, 1, 1000)
        bounded("loop_hz", self.loop_hz, 1, 240)
        if type(self.hold_click_enabled) is not bool:
            raise ValueError("hold_click_enabled debe ser true o false")
        bounded("drag_hold_ms", self.drag_hold_ms, 100, 3000)
        bounded("drag_release_ms", self.drag_release_ms, 0, 1000)


@dataclass
class VisionConfig:
    camera_index: int = 0
    target_fps: int = 30
    model_path: str = "models/face_landmarker.task"
    detection_confidence: float = 0.5
    presence_confidence: float = 0.5
    tracking_confidence: float = 0.5
    startup_timeout_s: float = 20.0
    capture_failure_limit: int = 30
    capture_backend: str = "dshow" if sys.platform == "win32" else "auto"
    frame_width: int = 0  # cero conserva la negociación del dispositivo
    frame_height: int = 0
    shutdown_timeout_s: float = 3.0

    def __post_init__(self):
        bounded("camera_index", self.camera_index, 0, 100, integer=True)
        bounded("target_fps", self.target_fps, 1, 240, integer=True)
        bounded("startup_timeout_s", self.startup_timeout_s, 0.1, 120)
        bounded("shutdown_timeout_s", self.shutdown_timeout_s, .05, 30)
        if self.capture_backend not in ("auto", "dshow", "msmf"):
            raise ValueError("Backend de cámara inválido: auto, dshow o msmf")
        for name in ("frame_width", "frame_height"):
            bounded(name, getattr(self, name), 0, 8192, integer=True)
        if bool(self.frame_width) != bool(self.frame_height):
            raise ValueError("Ancho y alto deben indicarse juntos, o ambos en cero")
        bounded("capture_failure_limit", self.capture_failure_limit, 1, 1000, integer=True)
        for name in ("detection_confidence", "presence_confidence", "tracking_confidence"):
            bounded(name, getattr(self, name), 0, 1)
        if not isinstance(self.model_path, str) or not self.model_path.strip():
            raise ValueError("model_path debe ser una ruta no vacía")


@dataclass
class CalibrationConfig:
    countdown_s: float = 4
    measuring_s: float = 6
    min_samples: int = 20
    threshold_fraction: float = 0.6
    min_separation: float = 0.002
    noise_multiplier: float = 1.5
    validation_timeout_s: float = 30
    validation_neutral_s: float = 2
    repetitions: int = 3
    active_window_s: float = 1.0  # tope del gesto sostenido; termina antes al soltarlo
    neutral_window_s: float = 3.0
    transition_s: float = 2
    min_window_samples: int = 8
    validation_noise_s: float = 0.15
    validation_wrong_s: float = 0.35
    brow_signal_source: str = "GEOMETRIC"

    def __post_init__(self):
        for name in ("countdown_s", "measuring_s", "validation_timeout_s", "validation_neutral_s"):
            bounded(name, getattr(self, name), 0.1, 120)
        if self.validation_neutral_s >= self.validation_timeout_s:
            raise ValueError("validation_neutral_s debe ser menor que validation_timeout_s")
        bounded("min_samples", self.min_samples, 3, 10000, integer=True)
        bounded("threshold_fraction", self.threshold_fraction, 0.1, 0.9)
        bounded("min_separation", self.min_separation, 0.0001, 1)
        bounded("noise_multiplier", self.noise_multiplier, 1, 10)
        bounded("repetitions", self.repetitions, 1, 10, integer=True)
        bounded("min_window_samples", self.min_window_samples, 3, 1000, integer=True)
        for name in ("active_window_s", "neutral_window_s", "transition_s", "validation_noise_s", "validation_wrong_s"):
            bounded(name, getattr(self, name), .05, 10)
        if self.validation_noise_s >= self.validation_wrong_s:
            raise ValueError("La tolerancia de ruido debe ser menor que el tiempo de gesto incorrecto")
        from gesture_signals import SOURCES
        if self.brow_signal_source not in SOURCES:
            raise ValueError("Fuente de cejas desconocida")


WHISPER_MODELS = ("tiny", "base", "small", "medium")


@dataclass
class VoiceConfig:
    """Dictado local al enfocar un campo de texto con un click de HeadMouse."""
    enabled: bool = False             # requiere preparar el modelo una vez
    model: str = "small"              # faster-whisper; "base" para equipos lentos
    language: str = "es"
    focus_window_ms: float = 800      # espera tras el click para que cambie el foco
    silence_s: float = 1.2            # silencio que termina el dictado
    max_utterance_s: float = 20
    no_speech_timeout_s: float = 6
    append_space: bool = True
    send_word: str = ""               # p. ej. "enviar": si es la última palabra, se quita y se presiona Enter
    sound_cues: bool = True
    commands: bool = True             # "borrar", "borrar palabra", "deshacer"… dichos solos
    after_dictation_ms: float = 600   # gestos bloqueados al terminar (cola del habla)

    def __post_init__(self):
        for name in ("enabled", "append_space", "sound_cues", "commands"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} debe ser true o false")
        if self.model not in WHISPER_MODELS:
            raise ValueError("Modelo de voz desconocido")
        if not isinstance(self.language, str) or not 2 <= len(self.language) <= 5:
            raise ValueError("Idioma de voz inválido")
        if not isinstance(self.send_word, str) or len(self.send_word) > 30:
            raise ValueError("send_word debe ser una palabra corta o vacío")
        bounded("focus_window_ms", self.focus_window_ms, 100, 5000)
        bounded("silence_s", self.silence_s, .3, 5)
        bounded("max_utterance_s", self.max_utterance_s, 2, 120)
        bounded("no_speech_timeout_s", self.no_speech_timeout_s, 1, 60)
        bounded("after_dictation_ms", self.after_dictation_ms, 0, 5000)


@dataclass
class EyeTrackingConfig:
    sensitivity: float = 12.0
    acceleration: float = 8.0
    dead_zone: float = .15  # fracción del rango cómodo nominal
    smoothing_alpha: float = .65
    max_delta: float = 20.0
    vertical_reference: str = "eyelids"
    dead_zone_x: float | None = None
    dead_zone_y: float | None = None

    def __post_init__(self):
        from gaze_source import validate_vertical_reference
        validate_vertical_reference(self.vertical_reference)
        bounded("eye.sensitivity", self.sensitivity, 0, 100)
        bounded("eye.acceleration", self.acceleration, 0, 100)
        bounded("eye.dead_zone", self.dead_zone, 0, .8)
        bounded("eye.smoothing_alpha", self.smoothing_alpha, 0, 1, inclusive_high=False)
        bounded("eye.max_delta", self.max_delta, 1, 60)
        for key in ("dead_zone_x","dead_zone_y"):
            if getattr(self,key) is not None:bounded("eye."+key,getattr(self,key),0,.8)


@dataclass
class UIConfig:
    show_overlay: bool = True
    show_landmarks: bool = True
    tracking_method: str = "nose"
    eye_source: str = "both"
    ocular_engine: str = "eye_absolute"  # implementación interna; no selector público
    unified_eyes: bool = False  # migración explícita al banco público Ojos

    def __post_init__(self):
        from gaze_source import validate_source
        validate_source(self.eye_source)
        if type(self.show_overlay) is not bool or type(self.show_landmarks) is not bool:
            raise ValueError("Overlays y landmarks deben ser booleanos")
        if self.tracking_method not in ("nose", "eye", "eye_absolute"):
            raise ValueError("Método de tracking desconocido")
        if self.ocular_engine not in ("eye","eye_absolute") or type(self.unified_eyes) is not bool:
            raise ValueError("Configuración interna de Ojos inválida")


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
    voice: VoiceConfig = field(default_factory=VoiceConfig)
    eye: EyeTrackingConfig = field(default_factory=EyeTrackingConfig)
    absolute: AbsoluteTrackingConfig = field(default_factory=lambda: AbsoluteTrackingConfig())
    methods: dict = field(default_factory=dict)
    log_level: str = "INFO"
    metrics_enabled: bool = True

    def __post_init__(self):
        if not isinstance(self.methods, dict) or self.methods.keys() - {"nose", "eyes", "eye", "eye_absolute"}:
            raise ValueError("Configuraciones por modalidad inválidas")
        for record in self.methods.values():
            if not isinstance(record, dict) or record.keys() - set(METHOD_SECTIONS):
                raise ValueError("Secciones por modalidad inválidas")
            for section, values in record.items():
                if not isinstance(values, dict):
                    raise ValueError("Parámetros por modalidad inválidos")
                try:
                    SECTIONS[section](**values)
                except TypeError as exc:
                    raise ValueError("Parámetros por modalidad desconocidos") from exc
        if self.log_level not in ("DEBUG", "INFO", "WARNING", "ERROR"):
            raise ValueError("log_level inválido")
        if not isinstance(self.metrics_enabled, bool):
            raise ValueError("metrics_enabled debe ser booleano")


@dataclass
class AbsoluteTrackingConfig:
    smoothing_alpha: float = .65
    max_step_px: float = 35.
    jitter_px: float = 3.

    def __post_init__(self):
        bounded("absolute.smoothing_alpha", self.smoothing_alpha, 0, 1, inclusive_high=False)
        bounded("absolute.max_step_px", self.max_step_px, 1, 100)
        bounded("absolute.jitter_px", self.jitter_px, 0, 30)


SECTIONS = dict(vision=VisionConfig, gesture=GestureConfig, control=ControlConfig,
                calibration=CalibrationConfig, ui=UIConfig, actions=MappingConfig, voice=VoiceConfig,
                eye=EyeTrackingConfig, absolute=AbsoluteTrackingConfig)
METHOD_SECTIONS = ("gesture", "control", "calibration", "actions", "eye", "absolute")


def method_bank(config):
    return "eyes" if config.ui.unified_eyes and config.ui.tracking_method!="nose" else config.ui.tracking_method


def settings_for_save(current, incoming):
    """Editar el modo vigente y recuperar otro banco al cambiar el selector.

    Los perfiles históricos se copian en memoria en tres bancos independientes.
    La lectura no migra ni reescribe archivos.
    """
    from copy import deepcopy
    data = deepcopy(incoming)
    old = asdict(current)
    banks = deepcopy(old["methods"])
    for method in ("nose", "eye", "eye_absolute"):
        banks.setdefault(method, {key: deepcopy(old[key]) for key in METHOD_SECTIONS})
    banks[method_bank(current)] = {key: deepcopy(data[key]) for key in METHOD_SECTIONS}
    selected = "eyes" if data["ui"].get("unified_eyes") and data["ui"]["tracking_method"]!="nose" else data["ui"]["tracking_method"]
    if selected=="eyes" and selected not in banks:
        banks[selected]=deepcopy(banks[data["ui"]["tracking_method"]])
    if selected not in banks:
        raise ValueError("Método de tracking desconocido")
    data.update(deepcopy(banks[selected]))
    data["methods"] = banks
    return load_config(overrides=data)


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
                if name=="ui" and "ocular_engine" not in value and value.get("tracking_method") in ("eye","eye_absolute"):
                    data[name]["ocular_engine"]=value["tracking_method"]
            else:
                data[name] = value
    return AppConfig(**{k: SECTIONS[k](**v) if k in SECTIONS else v
                        for k, v in data.items()})


def configure_logging(level):
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
