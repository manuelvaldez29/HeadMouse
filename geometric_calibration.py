"""Five-target geometric calibration with held-out validation and bounded posture correction."""
from dataclasses import asdict
import math
from statistics import median

from direction_diagnostic import (DIRECTIONS, DirectionClassifier, DirectionDiagnostic,
                                  _head_shift, HEAD_POSITION_DELTA, HEAD_ANGLE_DELTA)
from posture_adjustment import fit_adjustment, PoseAdjustment, pose_features

AXES = (("left", "right"), ("up", "down"))
LABELS = dict(center="centro", left="izquierda", right="derecha", up="arriba", down="abajo")
MINIMUM = 8
CHANNELS = {
    "left": ("local_left", "hybrid_left"),
    "right": ("local_right", "hybrid_right"),
    "both": ("canthi_both", "eyelids_both", "local_both", "hybrid_both", "weighted"),
}


def midpoint(values):
    return tuple(map(median, zip(*values)))


def local_point(eye):
    g = eye.get("geometry")
    if (not g or any(g[key] is None for key in ("width_px", "iris_x_px", "iris_y_px", "corner_1_x_px",
            "corner_1_y_px", "corner_2_x_px", "corner_2_y_px")) or g["width_px"] < 2
            or eye.get("blink") or not eye.get("available") or not eye.get("eye_ratio")):
        return None
    hx = g["corner_2_x_px"] - g["corner_1_x_px"]
    hy = g["corner_2_y_px"] - g["corner_1_y_px"]
    dx = g["iris_x_px"] - g["corner_1_x_px"]
    dy = g["iris_y_px"] - g["corner_1_y_px"]
    return ((dx*hx + dy*hy)/g["width_px"]**2, g["canthi_y_raw"])


def signals(row, mirrored=True):
    base = row["signals"]
    points, weights = {}, {}
    for side, eye in row["eyes"].items():
        point = local_point(eye)
        if point is None or any(v is None or not 0 <= v <= 1 for v in point):
            continue
        points[side] = (point[0] if mirrored else 1-point[0], point[1])
        weights[side] = eye["eye_ratio"] * eye["geometry"]["width_px"]
    out = {name: base[name] for name in ("canthi_both", "eyelids_both") if name in base}
    out.update({f"local_{side}": point for side,point in points.items()})
    for side, point in points.items():
        eyelids = base.get(f"eyelids_{side}")
        if eyelids is not None:
            out[f"hybrid_{side}"] = (point[0], eyelids[1])
    if len(points) == 2 and sum(weights.values()) > 0:
        pair = list(points.values())
        out["local_both"] = tuple((a+b)/2 for a,b in zip(*pair))
        if "eyelids_both" in out:
            out["hybrid_both"] = (out["local_both"][0], out["eyelids_both"][1])
        # Limit dominance of a single eye. Inter-eye agreement is gated separately.
        factor = max(.25, min(.75, weights["left"]/sum(weights.values())))
        out["weighted"] = tuple(factor*a+(1-factor)*b for a,b in zip(points["left"],points["right"]))
    return out


def agreement_limit(rows):
    return tuple(sorted(abs(left[i]-right[i]) for left,right in rows)[int(.95*(len(rows)-1))]
                 for i in range(2)) if rows else None


def gate_weighted(values, limit):
    if limit is not None and "weighted" in values:
        if any(abs(a-b)>bound for a,b,bound in zip(values["local_left"], values["local_right"], limit)):
            values.pop("weighted")
    return values


def axis_ranges(model, noise):
    signs, ranges = [], []
    for axis, (low, high) in enumerate(AXES):
        center = model.centers["center"][axis]
        a, b = model.centers[low][axis], model.centers[high][axis]
        sign = math.copysign(1., b-a)
        pair = ((center-a)*sign, (b-center)*sign)
        signs.append(sign)
        ranges.append(pair if min(pair) > max(2.5*noise[axis], 1e-8) else None)
    return tuple(signs), tuple(ranges)


def score(rows, model, channel, adjustment=None):
    matrix = {label: dict.fromkeys((*DIRECTIONS,"unavailable"),0) for label in DIRECTIONS}
    changes = 0
    corrected = 0
    for label, samples in rows:
        points = [(values[channel], pose) for values,pose in samples if channel in values]
        if adjustment:
            corrected_points = [adjustment.correct(point, pose) for point,pose in points]
            valid = [point for point in corrected_points if point is not None]
            corrected += len(valid)
            values = valid
        else:
            values = [point for point,_ in points]
        labels = [model.estimate(point)[0] for point in values]
        changes += sum(a!=b for a,b in zip(labels,labels[1:]))
        predicted = model.estimate(midpoint(values))[0] if len(values)>=MINIMUM else None
        matrix[label][predicted or "unavailable"] += 1
    return dict(correct=sum(matrix[k][k] for k in DIRECTIONS), expected=len(rows), confusion=matrix,
                switches=changes, corrected_frames=corrected)


def fit(rows, source, multipose, *, reserve=True):
    candidates = {}
    train = rows[:-5] if reserve else rows
    holdout = rows[-5:] if reserve else []
    limit = agreement_limit([(v["local_left"],v["local_right"]) for _, samples in train for v,_ in samples
                             if "local_left" in v and "local_right" in v])
    train = [(d,[(gate_weighted(dict(v),limit),p) for v,p in samples]) for d,samples in train]
    holdout = [(d,[(gate_weighted(dict(v),limit),p) for v,p in samples]) for d,samples in holdout]
    for channel in (channel for group in CHANNELS.values() for channel in group):
        samples = {(i,d): [(v[channel],None,None,p) for v,p in points if channel in v]
                   for i,(d,points) in enumerate(train)}
        groups = {d:[midpoint([p[0] for p in points]) for (_,label),points in samples.items()
                      if label==d and len(points)>=MINIMUM] for d in DIRECTIONS}
        if not all(groups.values()):
            continue
        model = DirectionClassifier.fit(groups)
        center = [p[0] for (_,label),points in samples.items() if label=="center" for p in points]
        noise = [median(abs(p[i]-model.centers["center"][i]) for p in center)*1.4826 for i in range(2)]
        center_extent = [max(abs(p[i]-model.centers["center"][i]) for p in center) for i in range(2)]
        poses = [p[3] for points in samples.values() for p in points if p[3] is not None]
        if not poses:
            continue
        lower,upper = [list(map(fn,zip(*poses))) for fn in (min,max)]
        stats = score(holdout, model, channel)
        ranges = axis_ranges(model,noise)[1]
        candidate = dict(centers=model.centers, noise=noise, center_extent=center_extent,
                         lower=lower, upper=upper, reference=midpoint(poses),
                         stats=stats, axes=[r is not None for r in ranges])
        if multipose and all(len(points) >= MINIMUM for points in samples.values()):
            adjustment = fit_adjustment(samples,0,model,MINIMUM)
            if adjustment and min(adjustment.classifier().scales)>1e-8:
                adjusted = score(holdout,adjustment.classifier(),channel,adjustment)
                candidate["ridge_validation"] = adjusted
                if (adjusted["correct"] > stats["correct"] and adjusted["switches"] <= stats["switches"]
                        and not adjusted["confusion"]["center"]["unavailable"]
                        and adjusted["confusion"]["center"]["center"] >= stats["confusion"]["center"]["center"]
                        and all(axis_ranges(adjustment.classifier(),noise)[1])):
                    candidate["adjustment"] = asdict(adjustment)
                    adjusted_center = [adjustment.correct(p[0],p[3]) for (_,label),points in samples.items()
                                       if label=="center" for p in points if p[3] is not None]
                    neutral = adjustment.centers["center"]
                    candidate["adjusted_center_extent"] = [
                        max(abs(p[i]-neutral[i]) for p in adjusted_center) for i in range(2)]
        candidates[channel] = candidate
    viable = [channel for channel in CHANNELS[source] if channel in candidates]
    if not viable:
        raise ValueError("Faltan muestras válidas en uno o más objetivos del ojo seleccionado.")
    selected = max(viable,key=lambda c:(sum(candidates[c]["axes"]),candidates[c]["stats"]["confusion"]["center"]["center"],
                                         candidates[c]["stats"]["correct"],-candidates[c]["stats"]["switches"]))
    return dict(version=1, selected=selected, candidates=candidates, agreement=limit,
                training_counts={str(i):len(points) for i,(_,points) in enumerate(train)})


def repair_axis(saved, rows, axis):
    """Keep the other axis frozen and refit only the three measured targets."""
    channel = saved["selected"]
    old = saved["candidates"][channel]
    measured = {}
    for label, points in rows[:3]:
        values = [gate_weighted(dict(v), saved.get("agreement")) for v, _ in points]
        measured[label] = [v[channel] for v in values if channel in v]
    if any(len(measured.get(label, ())) < MINIMUM for label in ("center", *AXES[axis])):
        raise ValueError("Faltaron muestras del eje. Se conserva la calibración anterior.")
    centers = {label: list(value) for label,value in old["centers"].items()}
    shift = midpoint(measured["center"])[axis] - centers["center"][axis]
    for label, center in centers.items():
        center[axis] = midpoint(measured[label])[axis] if label in measured else center[axis] + shift
    noise = list(old["noise"])
    noise[axis] = 1.4826 * median(abs(p[axis]-centers["center"][axis]) for p in measured["center"])
    model = DirectionClassifier(centers)
    candidate = {k:v for k,v in old.items() if k not in ("adjustment", "ridge_validation", "adjusted_center_extent")}
    extent = list(old.get("center_extent", (0.,0.)))
    extent[axis] = max(abs(p[axis]-centers["center"][axis]) for p in measured["center"])
    candidate.update(centers=centers, noise=noise, center_extent=extent,
                     axes=[pair is not None for pair in axis_ranges(model, noise)[1]],
                     stats=score((), model, channel))
    return {k:v for k,v in saved.items() if k not in ("validation", "previous")} | {
        "candidates": saved["candidates"] | {channel: candidate}}


def read_record(record):
    if record["version"] != 1 or record["selected"] not in record["candidates"] or not isinstance(record["context"],dict):
        raise ValueError("Calibración geométrica incompatible.")
    for c in record["candidates"].values():
        if set(c["centers"]) != set(DIRECTIONS) or any(len(p)!=2 or any(not math.isfinite(v) for v in p)
                                                      for p in c["centers"].values()):
            raise ValueError("Centros inválidos.")
        if len(c["noise"])!=2 or any(not 0<=v<=1 for v in c["noise"]) or any(
                len(c[k])!=6 or any(not math.isfinite(v) for v in c[k]) for k in ("lower","upper","reference")) or any(
                not a<=v<=b for a,v,b in zip(c["lower"],c["reference"],c["upper"])):
            raise ValueError("Contexto de postura inválido.")
        if c.get("adjustment"):
            PoseAdjustment.read(c["adjustment"])
        for field in ("center_extent", "adjusted_center_extent"):
            if field in c and (len(c[field]) != 2 or any(not 0 <= value <= 1 for value in c[field])):
                raise ValueError("Variación del centro inválida.")
    return record


class GeometricSession(DirectionDiagnostic):
    def __init__(self, clock, context, mode, saved=None, axis=None):
        super().__init__(clock, rounds=1, limits=context["blink_limits"])
        self.context,self.mode,self.saved = context,mode,saved
        self.checkpoint = None
        self.summary = None
        self.axis = axis
        if mode == "recenter":
            self.schedule=["center"]
        if mode=="repair":
            self.schedule=["center",*AXES[axis]]
        if mode=="fit":
            self.schedule[:5] = ["center", "left", "right", "up", "down"]

    def _report_channels(self):
        return ()

    def _usable_sample(self, row):
        if not super()._usable_sample(row) or pose_features(row["head"]) is None:
            return False
        values = signals(row, mirrored=self.context["mirrored"])
        if self.mode == "fit":
            return any(channel in values for channel in CHANNELS[self.context["source"]])
        return self.saved["selected"] in gate_weighted(values, self.saved.get("agreement"))

    def update(self, face, fps):
        super().update(face,fps)
        if self.state!="ready" or self.summary is not None:
            return
        rows = []
        for trial in self.trials:
            if not trial["used"]:
                continue
            collected = []
            previous = None
            for row in trial["samples"]:
                if row["phase"]!="fixation" or row["rejected"]:
                    continue
                current = row["head"]
                delta = _head_shift(current, previous) if current is not None and previous is not None else None
                previous = current
                if delta and (delta[0] > HEAD_POSITION_DELTA or (delta[1] is not None and delta[1] > HEAD_ANGLE_DELTA)):
                    continue
                collected.append((signals(row,mirrored=self.context.get("mirrored",True)),pose_features(current)))
            rows.append((trial["target"],collected))
        try:
            if len(rows)!=len(self.schedule):
                raise ValueError("Faltan objetivos completos. Volvé a medir los objetivos omitidos.")
            if self.mode in ("fit","repair"):
                if self.mode=="repair":
                    self.checkpoint = repair_axis(self.saved, rows, self.axis)
                else:
                    self.checkpoint = fit(rows,self.context["source"],False,reserve=False)
                self.checkpoint.update(context=self.context,session_id=self.session_id)
                self.summary = []
                selected = self.checkpoint["selected"]
                axes = self.checkpoint["candidates"][selected]["axes"]
                self.summary.append("Calibración lista." if all(axes) else
                    "Podés activar con velocidad reducida en el eje disponible." if any(axes) else
                    "La mirada central no se distingue de las direcciones. Repetí la calibración.")
                for axis,good in enumerate(axes):
                    if not good:
                        self.summary.append(f"Eje {'horizontal' if axis==0 else 'vertical'} sin separación suficiente. Podés repetir ese eje.")
            else:
                self._recenter(rows[0][1])
        except (ValueError,KeyError) as exc:
            self.summary=[str(exc)]

    def _recenter(self, rows):
        channel=self.saved["selected"]
        c=self.saved["candidates"][channel]
        adjustment = PoseAdjustment.read(c["adjustment"]) if c.get("adjustment") else None
        points = [(gate_weighted(dict(v),self.saved.get("agreement")), pose) for v,pose in rows]
        values = [adjustment.correct(v[channel], pose) if adjustment else v[channel]
                  for v,pose in points if channel in v]
        values = [value for value in values if value is not None]
        if len(values)<MINIMUM:
            raise ValueError("Faltaron muestras estables del centro en la postura calibrada.")
        new=midpoint(values)
        model=adjustment.classifier() if adjustment else DirectionClassifier(c["centers"])
        _,ranges=axis_ranges(model,c["noise"])
        if any(pair is None or abs(new[i]-model.centers["center"][i])>min(pair)/2 or
               median(abs(p[i]-new[i]) for p in values)*1.4826 > max(c["noise"][i],1e-6)
               for i,pair in enumerate(ranges)):
            raise ValueError("El centro cambió demasiado o la señal es inestable. Recalibrá el eje afectado.")
        shift=[b-a for a,b in zip(model.centers["center"],new)]
        centers = {d:tuple(x+y for x,y in zip(point,shift)) for d,point in model.centers.items()}
        updated = {"adjustment": c["adjustment"] | {"centers": centers}} if adjustment else {"centers": centers}
        candidates = self.saved["candidates"] | {channel: c | updated}
        self.checkpoint={k:v for k,v in self.saved.items() if k not in ("validation","previous")} | {
            "candidates":candidates,"previous":{k:v for k,v in self.saved.items() if k != "previous"}}
        self.summary=["Centro actualizado. Podés revertir el ajuste."]

    def snapshot(self):
        s=super().snapshot()
        if self.mode in ("fit", "repair") and self.checkpoint:
            selected = self.checkpoint["selected"]
            s["repair_axes"] = [i for i, good in enumerate(self.checkpoint["candidates"][selected]["axes"]) if not good]
        s["geometric_summary"] = self.summary
        return s

    def record(self):
        return super().record() | {"experiment":"geometric_joystick","mode":self.mode,"context":self.context,
                                   "geometric_summary":self.summary,"checkpoint":self.checkpoint}
