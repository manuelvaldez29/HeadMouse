"""Bancos de calibración por fuente; los campos históricos siguen siendo binocular."""
from copy import deepcopy
from gaze_source import EYE_SOURCES, validate_source


def calibration_for(profile, method, eye_source="both"):
    validate_source(eye_source)
    if not profile:
        return None
    key = "absolute_calibration" if method == "eye_absolute" else "tracking_calibration"
    banks = profile.get(key+"s", {})
    record = banks.get(eye_source)
    if record is None and eye_source == "both":
        record = profile.get(key)
    if record is not None and record.get("eye_source", "both") != eye_source:
        return None
    return record


def with_calibration(profile, record):
    result = deepcopy(profile)
    source = validate_source(record.get("eye_source", "both"))
    key = "absolute_calibration" if record["method"] == "eye_absolute" else "tracking_calibration"
    banks = result.setdefault(key+"s", {})
    if key in result:
        banks.setdefault("both", deepcopy(result[key]))
    banks[source] = deepcopy(record)
    if source == "both":
        result[key] = deepcopy(record)
    return result


def selected_profile(profile, eye_source):
    result = deepcopy(profile)
    for method, key in (("eye", "tracking_calibration"), ("eye_absolute", "absolute_calibration")):
        record = calibration_for(profile, method, eye_source)
        result.pop(key, None)
        if record is not None:
            result[key] = deepcopy(record)
    return result


def migrate_public_eyes(profile,engine):
    """Copiar sólo el banco elegido; nunca convertir ni fusionar modelos."""
    if engine not in ("eye","eye_absolute"):
        raise ValueError("Implementación ocular desconocida")
    result=deepcopy(profile)
    modes=result.setdefault("gesture_modes",{})
    if "eyes" not in modes:
        legacy=modes.get(engine)
        approved=result.get("gesture_mode_origin",{}).get(engine)=="measured"
        modes["eyes"]=deepcopy(legacy) if legacy is not None else dict(status="draft",validation={"passed":False})
        if not approved:
            modes["eyes"]["validation"]={"passed":False}
        else:
            result.setdefault("gesture_mode_origin",{})["eyes"]="measured"
        result["ocular_migration"]=dict(version=1,engine=engine,gesture_source=engine if legacy else None,
                                        approvals_preserved=approved,legacy_models_preserved=True)
    return result
