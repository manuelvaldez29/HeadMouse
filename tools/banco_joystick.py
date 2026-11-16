"""Banco de pruebas del joystick ocular con grabaciones reales, sin cámara.

En cada calibración guardada se sabe qué punto miraba la persona (centro, izquierda,
derecha, arriba o abajo). El banco toma la calibración de una sesión y reconoce los puntos
mirados en las OTRAS sesiones de la misma persona, como pasaría al usarlo otro día. Así,
antes de cambiar un umbral, se ve si mejora o empeora para cada persona y no solo para una.

    python tools/banco_joystick.py                         # las grabaciones de esta PC
    python tools/banco_joystick.py carpeta1 carpeta2 ...   # una carpeta por persona
    python tools/banco_joystick.py diagnostico.zip          # un diagnóstico exportado

Cada carpeta puede ser la de datos de CONFA (o HeadMouse), su subcarpeta logs o un .zip exportado
con «Exportar diagnóstico». Solo se usan números de la señal: no hay imágenes.
"""
from collections import Counter
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import Mock
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app_paths import data_root  # noqa: E402
from config import EyeTrackingConfig  # noqa: E402
from direction_diagnostic import DIRECTIONS  # noqa: E402
from geometric_calibration import gate_weighted, signals  # noqa: E402
from geometric_joystick import GeometricJoystick, select_usable_candidate  # noqa: E402

WITH_SPREAD = "--fijos" not in sys.argv  # comparar contra los umbrales fijos viejos
NAMES = dict(center="centro", left="izquierda", right="derecha", up="arriba", down="abajo")


def calibration_files(source):
    source = Path(source)
    if source.suffix == ".zip":
        folder = Path(tempfile.mkdtemp(prefix="confa-banco-"))
        with zipfile.ZipFile(source) as archive:
            for name in archive.namelist():
                if Path(name).name.startswith("joystick-calibration-") and name.endswith(".json"):
                    (folder / Path(name).name).write_bytes(archive.read(name))
        source = folder
    if (source / "logs").is_dir():
        source = source / "logs"
    return sorted(source.glob("joystick-calibration-*.json"))


def load(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    record = data.get("checkpoint")
    if not record or not data.get("trials"):
        return None
    labeled = {}
    for trial in data["trials"]:
        if not trial.get("used"):
            continue
        rows = [row for row in trial["samples"] if row["phase"] == "fixation" and row["rejected"] is None]
        labeled.setdefault(trial["target"], []).extend(
            gate_weighted(signals(row, mirrored=data["context"].get("mirrored", True)), record.get("agreement"))
            for row in rows)
    return dict(name=Path(path).stem.replace("joystick-calibration-", ""), mode=data.get("mode"),
                record=record, labeled=labeled)


def with_spread(record, labeled):
    """Calibraciones viejas no guardaban el temblor por dirección: se calcula de sus puntos."""
    from geometric_calibration import direction_spread
    candidates = {}
    for channel, candidate in record["candidates"].items():
        if not candidate.get("spread"):
            points = {label: [v[channel] for v in rows if channel in v] for label, rows in labeled.items()}
            candidate = dict(candidate, spread=direction_spread(points))
        candidates[channel] = candidate
    return dict(record, candidates=candidates)


def recognizer(record):
    record = select_usable_candidate(record, EyeTrackingConfig())
    joystick = GeometricJoystick(Mock(_frame_size=None), record, EyeTrackingConfig(), .25, lambda: 0.)
    center = joystick.model.centers["center"]

    def classify(values):
        point = values.get(joystick.channel)
        if point is None:
            return "sin señal"
        joystick.zone = None
        joystick.cursor = None
        position = tuple((value - ref) / sigma for value, ref, sigma in zip(point, center, joystick.sigma))
        zone = joystick._classify(position)
        return "fuera" if zone == "outside" else NAMES.get(zone, zone)
    return joystick, classify


def evaluate(train, test):
    record = with_spread(train["record"], train["labeled"]) if WITH_SPREAD else train["record"]
    joystick, classify = recognizer(record)
    confusion = {target: Counter(classify(values) for values in rows) for target, rows in test["labeled"].items()}
    hits = {target: confusion[target][NAMES[target]] / max(1, sum(confusion[target].values()))
            for target in confusion}
    return joystick, confusion, hits


def report(sessions, out=print):
    fits = [s for s in sessions if s and s["mode"] == "fit"]
    if len(fits) < 1:
        out("No hay calibraciones completas grabadas.")
        return {}
    totals = {target: [] for target in DIRECTIONS}
    for train in fits:
        tests = [s for s in sessions if s and s is not train and set(s["labeled"]) >= {"center"}] or [train]
        for test in tests:
            joystick, confusion, hits = evaluate(train, test)
            tag = "misma sesión" if test is train else f"otra sesión ({test['name']})"
            out(f"Calibración {train['name']} · señal {joystick.channel} · probada en {tag}")
            for target in DIRECTIONS:
                if target not in confusion:
                    continue
                total = sum(confusion[target].values())
                worst = ", ".join(f"{name} {count}" for name, count in confusion[target].most_common(3)
                                  if name != NAMES[target])
                out(f"  {NAMES[target]:<10} {100 * hits[target]:5.0f} % de {total:3d} muestras"
                    + (f"  (confundida con: {worst})" if worst else ""))
                totals[target].append(hits[target])
    summary = {NAMES[t]: sum(v) / len(v) for t, v in totals.items() if v}
    out("Promedio por dirección: " + " · ".join(f"{name} {100 * value:.0f} %" for name, value in summary.items()))
    return summary


def main(argv=None):
    argv = [arg for arg in (sys.argv[1:] if argv is None else argv) if arg != "--fijos"]
    sources = argv or [data_root()]
    for source in sources:
        print(f"\n=== {source} ===")
        report([load(path) for path in calibration_files(source)])


if __name__ == "__main__":
    main()
