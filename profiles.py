"""Perfiles locales versionados y compatibilidad explícita con calibration.json."""
import json
import logging
import os
import re
import tempfile
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
    if ("neutral" in data) != ("gesture_extremes" in data):
        raise ValueError("neutral y gesture_extremes deben estar juntos")
    if "neutral" in data:
        from calibration_logic import validate_calibration
        errors = validate_calibration(data, settings.calibration)
        if errors:
            raise ValueError("Calibración inválida: " + "; ".join(errors))
    return data


class ProfileStore:
    def __init__(self, directory=None):
        self.directory = Path(directory) if directory is not None else ROOT / "data" / "profiles"

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
            os.replace(temporary, path)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)
        return path


def load_legacy(path):
    with open(path, encoding="utf-8") as stream:
        return validate_profile(json.load(stream))
