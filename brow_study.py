"""
brow_study.py
HeadMouse — Estudio de señales de cejas frente a la pose de la cabeza

Guía al usuario por posturas (mirar arriba/abajo/costados sin mover las cejas)
y elevaciones de cejas, y registra por frame las cuatro fuentes de señal:
GEOMETRIC, BLENDSHAPE, HYBRID y GEOMETRIC_3D. No guarda imágenes ni mueve el
mouse. Al terminar compara qué tan bien separa cada fuente "cejas levantadas"
de "solo mover la cabeza".

Uso:
    python brow_study.py                     # captura (unos 2 minutos) y análisis
    python brow_study.py --analyze ARCHIVO   # solo análisis de una captura previa

Controles: SPACE comienza, Q cancela (lo capturado hasta ahí se conserva).
"""
import argparse
import json
import logging
import math
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from types import SimpleNamespace

from config import ROOT, load_config, configure_logging
from gesture_signals import SOURCES, brow_signal

# Texto ASCII: cv2.putText no dibuja tildes.
SEGMENTS = (
    ("NEUTRAL", "Mira al centro con la cara relajada", 5),
    ("LOOK_UP", "Mira hacia ARRIBA (como para subir el cursor) SIN levantar las cejas", 5),
    ("LOOK_DOWN", "Mira hacia ABAJO sin mover las cejas", 5),
    ("LOOK_LEFT", "Gira la cabeza a la IZQUIERDA sin mover las cejas", 4),
    ("LOOK_RIGHT", "Gira la cabeza a la DERECHA sin mover las cejas", 4),
    ("BOTH_RAISE", "Mira al centro y levanta AMBAS cejas, comodo", 4),
    ("LEFT_RAISE", "Mira al centro y levanta solo la ceja IZQUIERDA", 4),
    ("RIGHT_RAISE", "Mira al centro y levanta solo la ceja DERECHA", 4),
    ("UP_AND_RAISE", "Mira hacia ARRIBA y levanta AMBAS cejas", 4),
)
TRANSITION_S = 2.0
ROUNDS = 2
POSE_ONLY = ("NEUTRAL", "LOOK_UP", "LOOK_DOWN", "LOOK_LEFT", "LOOK_RIGHT")
RAISE = {"left": ("BOTH_RAISE", "LEFT_RAISE"), "right": ("BOTH_RAISE", "RIGHT_RAISE")}
FIELDS = ("nose_x", "nose_y", "head_pitch", "head_yaw", "head_roll",
          "brow_left_lift", "brow_right_lift", "brow_left_3d", "brow_right_3d")


def schedule(rounds=ROUNDS, transition_s=TRANSITION_S):
    """Lista (inicio, fin, ronda, etiqueta, instrucción, fase) en segundos."""
    rows, t = [], 0.
    for round_index in range(1, rounds + 1):
        for label, text, hold in SEGMENTS:
            rows.append((t, t + transition_s, round_index, label, text, "transition"))
            t += transition_s
            rows.append((t, t + hold, round_index, label, text, "hold"))
            t += hold
    return rows


def segment_at(timeline, elapsed):
    for row in timeline:
        if row[0] <= elapsed < row[1]:
            return row
    return None


def frame_record(face, elapsed, segment):
    _, _, round_index, label, _, phase = segment
    record = dict(t=round(elapsed, 4), round=round_index, label=label, phase=phase)
    record.update({name: getattr(face, name, None) for name in FIELDS})
    record["blendshapes"] = dict(face.blendshapes)
    return record


# ── Análisis ──────────────────────────────────────────────────────────────────

def _face(record):
    return SimpleNamespace(**{name: record.get(name) for name in FIELDS},
                           blendshapes=tuple(sorted(record.get("blendshapes", {}).items())))


def _values(records, source, side, labels):
    out = []
    for r in records:
        if r["phase"] == "hold" and r["label"] in labels:
            v = brow_signal(_face(r), side, source)
            if v is not None and math.isfinite(v):
                out.append((v, r.get("head_pitch")))
    return out


def auc(positive, negative):
    """Probabilidad de que un frame con cejas levantadas supere a uno sin."""
    if not positive or not negative:
        return None
    negative = sorted(negative)
    import bisect
    total = 0.
    for p in positive:
        below = bisect.bisect_left(negative, p)
        ties = bisect.bisect_right(negative, p) - below
        total += below + ties / 2
    return total / (len(positive) * len(negative))


def _percentile(values, p):
    values = sorted(values)
    pos = (len(values) - 1) * p / 100
    lo, hi = math.floor(pos), math.ceil(pos)
    return values[lo] + (values[hi] - values[lo]) * (pos - lo)


def _slope(pairs):
    pairs = [(p, v) for v, p in pairs if p is not None]
    if len(pairs) < 3:
        return None
    mx = sum(p for p, _ in pairs) / len(pairs)
    my = sum(v for _, v in pairs) / len(pairs)
    var = sum((p - mx) ** 2 for p, _ in pairs)
    return None if var <= 1e-12 else sum((p - mx) * (v - my) for p, v in pairs) / var


def analyze(records):
    """Métricas por fuente y lado. Escala-libre: todo relativo a la amplitud."""
    results = []
    for source in SOURCES:
        for side in ("left", "right"):
            raised = _values(records, source, side, RAISE[side])
            neutral = _values(records, source, side, ("NEUTRAL",))
            pose = _values(records, source, side, POSE_ONLY)
            up = _values(records, source, side, ("LOOK_UP",))
            up_raise = _values(records, source, side, ("UP_AND_RAISE",))
            row = dict(source=source, side=side, frames=len(raised) + len(pose))
            if len(raised) < 5 or len(neutral) < 5 or len(up) < 5:
                row["missing"] = True
                results.append(row)
                continue
            r, n, p, u = ([v for v, _ in rows] for rows in (raised, neutral, pose, up))
            amplitude = median(r) - median(n)
            threshold = _percentile(r, 5)  # detecta el 95 % de los frames levantados
            slope = _slope(pose)
            row.update(
                amplitude=amplitude,
                auc_pose=auc(r, p), auc_look_up=auc(r, u),
                false_up=sum(v >= threshold for v in u) / len(u),
                false_pose=sum(v >= threshold for v in p) / len(p),
                look_up_shift=(median(u) - median(n)) / amplitude if amplitude > 0 else None,
                pitch_per_10deg=slope * 10 / amplitude if slope is not None and amplitude > 0 else None,
                up_raise_detected=(sum(v >= threshold for v, _ in up_raise) / len(up_raise)) if up_raise else None)
            results.append(row)
    return results


def ranking(results):
    """Ordena fuentes por su peor ceja: una señal sirve si separa en ambas."""
    worst = {}
    for row in results:
        source = row["source"]
        score = None if row.get("missing") or row["amplitude"] <= 0 else (row["auc_look_up"], -row["false_up"])
        if source in worst and worst[source] is None:
            continue
        worst[source] = None if score is None else min(worst.get(source, score), score)
    valid = [(score, source) for source, score in worst.items() if score is not None]
    return [source for _, source in sorted(valid, reverse=True)]


def posture_table(records):
    """Mediana de cada postura respecto del neutral, en % de la amplitud de
    ambas cejas, por fuente y lado; más pitch/yaw relativos al neutral."""
    holds = [r for r in records if r["phase"] == "hold"]
    def med(rows, key):
        values = [r[key] for r in rows if r.get(key) is not None]
        return median(values) if values else None
    neutral = [r for r in holds if r["label"] == "NEUTRAL"]
    pitch0, yaw0 = med(neutral, "head_pitch"), med(neutral, "head_yaw")
    base = {}
    for source in SOURCES:
        for side in ("left", "right"):
            n = [v for v, _ in _values(records, source, side, ("NEUTRAL",))]
            b = [v for v, _ in _values(records, source, side, ("BOTH_RAISE",))]
            base[source, side] = (median(n), median(b) - median(n)) if n and b and median(b) > median(n) else None
    rows = []
    for label, _, _ in SEGMENTS:
        group = [r for r in holds if r["label"] == label]
        if not group:
            continue
        pitch, yaw = med(group, "head_pitch"), med(group, "head_yaw")
        row = dict(label=label, pitch=None if pitch is None or pitch0 is None else pitch - pitch0,
                   yaw=None if yaw is None or yaw0 is None else yaw - yaw0)
        for (source, side), reference in base.items():
            values = [v for v, _ in _values(records, source, side, (label,))]
            row[source, side] = (median(values) - reference[0]) / reference[1] if reference and values else None
        rows.append(row)
    return rows


def laterality(records):
    """Fuentes cuya ceja 'left' responde más a levantar la derecha (y viceversa)."""
    swapped = []
    for source in SOURCES:
        response = {}
        for label in ("LEFT_RAISE", "RIGHT_RAISE"):
            for side in ("left", "right"):
                values = [v for v, _ in _values(records, source, side, (label,))]
                neutral = [v for v, _ in _values(records, source, side, ("NEUTRAL",))]
                response[label, side] = median(values) - median(neutral) if values and neutral else None
        if None in response.values():
            continue
        own = response["LEFT_RAISE", "left"] + response["RIGHT_RAISE", "right"]
        crossed = response["LEFT_RAISE", "right"] + response["RIGHT_RAISE", "left"]
        if crossed > own:
            swapped.append(source)
    return swapped


def report(results, path=None, meta=None, records=None):
    def fmt(v, pct=False):
        if v is None:
            return "—"
        return f"{100 * v:.0f} %" if pct else f"{v:.2f}"
    lines = ["# Estudio de señales de cejas", ""]
    if meta:
        lines += [f"- {key}: {value}" for key, value in meta.items()] + [""]
    lines += ["| Fuente | Ceja | AUC vs. mirar arriba | AUC vs. toda pose | Falsos al mirar arriba | "
              "Falsos en pose | Desplazamiento al mirar arriba | Por cada 10° de pitch | "
              "Detecta arriba + cejas |",
              "|---|---|---|---|---|---|---|---|---|"]
    for row in results:
        if row.get("missing"):
            lines.append(f"| {row['source']} | {row['side']} | sin datos | | | | | | |")
            continue
        lines.append(f"| {row['source']} | {row['side']} | {fmt(row['auc_look_up'])} | {fmt(row['auc_pose'])} | "
                     f"{fmt(row['false_up'], True)} | {fmt(row['false_pose'], True)} | "
                     f"{fmt(row['look_up_shift'], True)} | {fmt(row['pitch_per_10deg'], True)} | "
                     f"{fmt(row['up_raise_detected'], True)} |")
    if records:
        postures = posture_table(records)
        lines += ["", "## Respuesta por postura (% de la amplitud de ambas cejas; izq. / der.)", "",
                  "| Postura | Δ pitch | Δ yaw | " + " | ".join(SOURCES) + " |",
                  "|---|---|---|" + "---|" * len(SOURCES)]
        for row in postures:
            cells = ["/".join(fmt(row[source, side], True) for side in ("left", "right")) for source in SOURCES]
            angles = ["—" if row[k] is None else f"{row[k]:+.0f}°" for k in ("pitch", "yaw")]
            lines.append(f"| {row['label']} | {angles[0]} | {angles[1]} | " + " | ".join(cells) + " |")
        swapped = laterality(records)
        if swapped:
            lines += ["", "**Lateralidad invertida** (la ceja izquierda responde a la derecha): " + ", ".join(swapped)]
    order = ranking(results)
    lines += ["", "AUC: 1 separa perfecto, 0.5 es azar. Falsos: frames sin cejas levantadas que superan el "
              "umbral que detecta el 95 % de los frames levantados. Desplazamiento y pitch: en proporción "
              "a la amplitud del gesto (100 % = mirar arriba equivale a levantar las cejas).", "",
              "Orden por la peor ceja (AUC vs. mirar arriba): " + (" > ".join(order) if order else "sin datos")]
    text = "\n".join(lines) + "\n"
    if path:
        Path(path).write_text(text, encoding="utf-8")
    return text


def load(path):
    with open(path, encoding="utf-8") as stream:
        rows = [json.loads(line) for line in stream if line.strip()]
    meta = rows[0] if rows and rows[0].get("experiment") == "brow_study" else {}
    return meta, [r for r in rows if "label" in r]


# ── Captura ──────────────────────────────────────────────────────────────────

def capture(args):
    import cv2
    from vision_engine import VisionEngine
    config = load_config(args.config)
    if args.camera is not None:
        config.vision.camera_index = args.camera
        config.vision.__post_init__()
    directory = ROOT / "data" / "experiments"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"brow_study_{uuid.uuid4().hex}.jsonl"
    timeline = schedule()
    vision = VisionEngine(config=config.vision)
    frames = 0
    try:
        vision.start()
        vision.wait_ready()
        started, last_ts = None, 0
        with path.open("w", encoding="utf-8") as stream:
            stream.write(json.dumps(dict(experiment="brow_study", schema_version=1,
                                         created_at=datetime.now(timezone.utc).isoformat(),
                                         camera=config.vision.camera_index), ensure_ascii=False) + "\n")
            while True:
                if vision.error or not vision.is_alive():
                    raise RuntimeError("Captura detenida") from vision.error
                frame = vision.get_frame()
                if frame is None:
                    time.sleep(.01)
                    continue
                face = vision.get_face_data()
                now = time.monotonic()
                elapsed = None if started is None else now - started
                segment = None if elapsed is None else segment_at(timeline, elapsed)
                if started is not None and segment is None:
                    break
                if segment and face.timestamp_ms > last_ts and face.fresh(.25, now):
                    last_ts = face.timestamp_ms
                    stream.write(json.dumps(frame_record(face, elapsed, segment), allow_nan=False) + "\n")
                    frames += 1
                _draw(cv2, frame, segment, elapsed, timeline, face.fresh(.25, now))
                cv2.imshow("HeadMouse - estudio de cejas", frame)
                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), ord("Q"), 27):
                    logging.warning("Estudio cancelado; se conservan %s frames", frames)
                    break
                if key == ord(" ") and started is None:
                    started = time.monotonic()
    finally:
        vision.stop()
        cv2.destroyAllWindows()
    logging.info("Captura guardada: %s (%s frames, sin imágenes)", path, frames)
    return path


def _draw(cv2, frame, segment, elapsed, timeline, tracked):
    h, w = frame.shape[:2]
    cv2.rectangle(frame, (0, 0), (w, 70), (20, 20, 20), -1)
    if segment is None:
        text, color, sub = "SPACE para comenzar (unos 2 minutos). Q cancela.", (255, 255, 255), ""
    else:
        start, end, round_index, _, text, phase = segment
        color = (30, 160, 255) if phase == "transition" else (40, 210, 80)
        sub = f"Ronda {round_index}/{ROUNDS} - {'preparate' if phase == 'transition' else 'mantene'} " \
              f"{math.ceil(end - elapsed)} s"
        cv2.rectangle(frame, (0, h - 8), (int(w * elapsed / timeline[-1][1]), h), (40, 210, 80), -1)
    cv2.putText(frame, text, (10, 28), cv2.FONT_HERSHEY_SIMPLEX, .55, color, 1, cv2.LINE_AA)
    cv2.putText(frame, sub if tracked else "Rostro no detectado", (10, 56), cv2.FONT_HERSHEY_SIMPLEX, .55,
                (200, 200, 200) if tracked else (50, 50, 220), 1, cv2.LINE_AA)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Compara señales de cejas frente a la pose; sin imágenes ni mouse")
    parser.add_argument("--analyze", help="Analizar una captura JSONL existente")
    parser.add_argument("--config")
    parser.add_argument("--camera", type=int)
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], default="INFO")
    args = parser.parse_args(argv)
    configure_logging(args.log_level)
    path = Path(args.analyze) if args.analyze else capture(args)
    meta, records = load(path)
    holds = [r for r in records if r["phase"] == "hold"]
    duration = max((r["t"] for r in records), default=0)
    info = dict(archivo=path.name, frames=len(records), frames_analizados=len(holds),
                fps=f"{len(records) / duration:.1f}" if duration else "—")
    print(report(analyze(records), path.with_name(path.stem + "_report.md"), info, records))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
