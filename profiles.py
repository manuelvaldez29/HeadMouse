"""Perfiles locales versionados y compatibilidad explícita con calibration.json."""
from app_paths import data_root, face_model_path
import json
import logging
import os
import re
import tempfile
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from config import ROOT, DEFAULT_THRESHOLDS, bounded, load_config

logger = logging.getLogger(__name__)


def validate_user_id(user_id):
    if not isinstance(user_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", user_id):
        raise ValueError("user_id: usar 1–64 letras ASCII, números, guiones o guiones bajos")
    if user_id.upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(10)),
                           *(f"LPT{i}" for i in range(10))}:
        raise ValueError("user_id reservado en Windows")
    return user_id


def validate_profile(data):
    if not isinstance(data, dict):
        raise ValueError("El perfil debe ser un objeto JSON")
    validate_user_id(data.get("user_id", "default"))
    if "display_name" in data and (not isinstance(data["display_name"], str) or not data["display_name"].strip() or len(data["display_name"]) > 80):
        raise ValueError("Nombre visible inválido")
    if not isinstance(data.get("settings", {}), dict):
        raise ValueError("settings debe ser un objeto JSON")
    if "validation" in data and (not isinstance(data["validation"], dict) or
                                  type(data["validation"].get("passed", False)) is not bool):
        raise ValueError("Estado de validación inválido")
    if type(data.get("schema_version", 1)) is not int or data.get("schema_version", 1) not in (1, 2):
        raise ValueError("Versión de perfil no soportada")
    if "tracking_calibration" in data:
        from tracking_calibration import TrackingCalibration
        TrackingCalibration.from_record(data["tracking_calibration"])
    if "absolute_calibration" in data:
        from gaze_mapping import GazeModel
        GazeModel(data["absolute_calibration"])
    from gaze_source import EYE_SOURCES
    for key in ("tracking_calibration", "absolute_calibration"):
        if key in data and data[key].get("eye_source", "both") != "both":
            raise ValueError("El campo histórico de calibración debe ser binocular")
        if key+"s" not in data:
            continue
        banks = data[key+"s"]
        if not isinstance(banks, dict) or banks.keys() - set(EYE_SOURCES):
            raise ValueError("Banco de fuentes oculares inválido")
        for source, record in banks.items():
            if not isinstance(record, dict) or record.get("eye_source", "both") != source:
                raise ValueError("La fuente del modelo no coincide con su banco")
            if key == "tracking_calibration":
                from tracking_calibration import TrackingCalibration
                TrackingCalibration.from_record(record)
            else:
                from gaze_mapping import GazeModel
                GazeModel(record)
    if "gesture_modes" in data:
        records = data["gesture_modes"]
        if not isinstance(records, dict) or records.keys() - {"nose", "eyes", "eye", "eye_absolute"}:
            raise ValueError("Calibraciones por modalidad inválidas")
        for record in records.values():
            if not isinstance(record, dict) or record.keys() - set(GESTURE_PROFILE_KEYS):
                raise ValueError("Campos de calibración por modalidad inválidos")
            candidate = deepcopy(data)
            candidate.pop("gesture_modes")
            for key in GESTURE_PROFILE_KEYS:
                candidate.pop(key, None)
            candidate.update(deepcopy(record))
            validate_profile(candidate)
    if "gesture_mode_origin" in data:
        origins=data["gesture_mode_origin"]
        if not isinstance(origins,dict) or origins.keys()-{"nose","eyes","eye","eye_absolute"} or any(v!="measured" for v in origins.values()):
            raise ValueError("Origen de calibraciones de gestos inválido")
    if data.get("status") == "draft":
        if "thresholds" in data or data.get("calibrated_at"):
            raise ValueError("Un borrador no puede simular una calibración")
        load_config(overrides=data.get("settings", {}))
        return data
    thresholds = data.get("thresholds")
    if not isinstance(thresholds, dict) or set(thresholds) != set(DEFAULT_THRESHOLDS):
        raise ValueError("El perfil necesita los cinco thresholds")
    for name, value in thresholds.items():
        bounded(name, value, -10 if name.startswith("brow") else 0.000001, 10)
    for name in ("neutral_nose_x", "neutral_nose_y"):
        bounded(name, data.get(name, 0.5), 0, 1)
    if not isinstance(data.get("settings", {}), dict):
        raise ValueError("settings debe ser un objeto JSON")
    settings = load_config(overrides=data.get("settings", {}))
    if "gesture_calibrations" in data:
        from adaptive_calibration import HysteresisGate
        from gesture_signals import GESTURE_SIGNALS, SOURCES
        records = data["gesture_calibrations"]
        if not isinstance(records, dict) or set(records) != set(GESTURE_SIGNALS):
            raise ValueError("La calibración necesita un estado por gesto registrado")
        for gesture_id, spec in GESTURE_SIGNALS.items():
            record = records[gesture_id]
            if not isinstance(record, dict) or record.get("gesture_id") != gesture_id or type(record.get("enabled")) is not bool:
                raise ValueError("Identidad o disponibilidad de gesto inválida")
            if record.get("channels") != list(spec.channels) or record.get("directions") != list(spec.directions):
                raise ValueError("Canales de gesto incompatibles")
            if record.get("source") not in SOURCES or not spec.brow and record["source"] != "GEOMETRIC":
                raise ValueError("Fuente de señal incompatible")
            if record.get("validation_state") not in ("pending", "passed", "repeat", "disabled"):
                raise ValueError("Estado de validación por gesto inválido")
            if record["enabled"]:
                bounded("quality_score", record.get("quality_score"), .85, 1)
                for name in ("activation_threshold", "release_threshold"):
                    if not isinstance(record.get(name), dict) or set(record[name]) != set(spec.channels):
                        raise ValueError("Umbrales de gesto incompletos")
                HysteresisGate(spec.channels, spec.directions, record["activation_threshold"], record["release_threshold"])
            elif record.get("activation_threshold") or record.get("release_threshold"):
                raise ValueError("Un gesto deshabilitado no debe aportar umbrales de activación")
    if ("neutral" in data) != ("gesture_extremes" in data):
        raise ValueError("neutral y gesture_extremes deben estar juntos")
    if "neutral" in data:
        from calibration_logic import validate_calibration
        errors = validate_calibration(data, settings.calibration)
        if errors:
            raise ValueError("Calibración inválida: " + "; ".join(errors))
    return data


def replace_with_retry(source, target, attempts=10, delay_s=.05):
    """os.replace atómico, reintentando si otro proceso tiene el archivo abierto.

    En Windows, OneDrive, el antivirus o el indexador abren el JSON recién
    escrito un instante y os.replace falla con "Acceso denegado" (WinError 5 o
    32). Medido el 2026-10-12: fallaba en alrededor de una de cada dos corridas
    de la suite dentro de la carpeta sincronizada.
    """
    for attempt in range(attempts):
        try:
            return os.replace(source, target)
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay_s * (attempt + 1))


class ProfileStore:
    def __init__(self, directory=None):
        self.directory = Path(directory) if directory is not None else data_root() / "profiles"

    def path(self, user_id):
        return self.directory / f"{validate_user_id(user_id)}.json"

    def load(self, user_id="default", legacy_path=None):
        path = self.path(user_id)
        if not path.exists() and legacy_path is not None:
            path = Path(legacy_path)
        with path.open(encoding="utf-8") as stream:
            data = json.load(stream)
        validate_profile(data)
        if data.get("user_id", "default") != user_id:
            raise ValueError(f"El perfil no corresponde al usuario {user_id}")
        return data

    def save(self, data):
        data = deepcopy(data)
        user_id = validate_user_id(data["user_id"])
        path = self.path(user_id)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        created = now
        if path.exists():
            try:
                created = self.load(user_id).get("created_at", now)
            except ValueError:
                logger.warning("Se reemplazará perfil inválido por nueva calibración validada: %s", path)
        data.update(schema_version=2, created_at=created)
        if data.get("status") != "draft":
            data.setdefault("calibrated_at", now)
        data.setdefault("settings", {})
        validate_profile(data)
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".tmp",
                                             dir=self.directory, delete=False) as stream:
                temporary = stream.name
                json.dump(data, stream, indent=2, ensure_ascii=False, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            # Verificar el JSON realmente escrito antes del reemplazo atómico.
            with open(temporary, encoding="utf-8") as stream:
                written = json.load(stream)
            validate_profile(written)
            if written != data:
                raise ValueError("El perfil escrito no coincide con los datos validados")
            replace_with_retry(temporary, path)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)
        return path


def load_legacy(path):
    with open(path, encoding="utf-8") as stream:
        return validate_profile(json.load(stream))


GESTURE_PROFILE_KEYS = ("status", "thresholds", "neutral_nose_x", "neutral_nose_y", "neutral",
    "gesture_extremes", "gesture_calibrations", "validation", "calibrated_at", "neutral_variability",
    "gesture_variability", "calibration_metadata", "sample_counts", "calibration_version", "calibration_telemetry")


def gesture_profile(profile, method):
    """Vista por modalidad; fallback histórico, sin escribir ni borrar el original."""
    result = deepcopy(profile)
    record = profile.get("gesture_modes", {}).get(method)
    if record is not None:
        for key in GESTURE_PROFILE_KEYS:
            result.pop(key, None)
        result.update(deepcopy(record))
    result.pop("gesture_modes", None)
    return result


def save_gesture_mode(profile, candidate, method):
    if profile is None:
        return deepcopy(candidate)
    result = deepcopy(profile)
    # Los bancos copiados para compatibilidad no equivalen a una medición ocular.
    origins=result.setdefault("gesture_mode_origin",{})
    origins[method]="measured"
    legacy = {key: deepcopy(profile[key]) for key in GESTURE_PROFILE_KEYS if key in profile}
    bank = result.setdefault("gesture_modes", {})
    for name in (("nose",) if method=="eyes" else ("nose", "eye", "eye_absolute")):
        bank.setdefault(name, deepcopy(legacy))
    record = {key: deepcopy(candidate[key]) for key in GESTURE_PROFILE_KEYS if key in candidate}
    bank[method] = record
    if method == "nose":
        for key in GESTURE_PROFILE_KEYS:
            result.pop(key, None)
        result.update(deepcopy(record))
    # Un borrador necesita un perfil raíz válido para contener el banco.
    elif profile.get("status") == "draft":
        for key in GESTURE_PROFILE_KEYS:
            result.pop(key, None)
        result.update(deepcopy(record))
    return result
