from collections import Counter, deque
import math
from statistics import median
import time

from direction_diagnostic import DIRECTIONS
from gaze_source import selected_eyes_open
from gesture_engine import EV_CURSOR_MOVE, GestureEvent
from geometric_calibration import axis_ranges, gate_weighted, signals
from direction_diagnostic import observe_direction, DirectionClassifier
from posture_adjustment import PoseAdjustment
from posture_adjustment import pose_features
from tracking import ocular_delta


def calibration_quality(record, config):
    candidate = record["candidates"][record["selected"]]
    adjustment = PoseAdjustment.read(candidate["adjustment"]) if candidate.get("adjustment") else None
    model = adjustment.classifier() if adjustment else DirectionClassifier(candidate["centers"])
    signs, ranges = axis_ranges(model, candidate["noise"])
    minimum = tuple(config.dead_zone if zone is None else zone for zone in (config.dead_zone_x, config.dead_zone_y))
    extent = candidate.get("adjusted_center_extent" if adjustment else "center_extent", (0.,0.))
    zones = tuple(max(zone, max(2.5*sigma, jitter)/min(pair)) if pair else 1.
                  for zone,sigma,jitter,pair in zip(minimum,candidate["noise"],extent,ranges))
    ranges = tuple(pair if 1.15*zone < 1 else None for pair,zone in zip(ranges,zones))
    return model, adjustment, signs, ranges, zones


def calibration_message(ranges):
    if all(ranges):
        return "Calibración lista. Mirá al centro para iniciar."
    if any(ranges):
        axis = "vertical" if ranges[0] else "horizontal"
        return f"Calibración limitada: repetí el eje {axis} o usá movimiento reducido, sin clics."
    return "Calibración insegura: el centro no se distingue de las direcciones. Calibrá de nuevo."


class GeometricJoystick:
    name = "eye_joystick"
    eye_source = "both"
    MAX_BURST = 3.

    def __init__(self, vision, record, config, max_age, clock):
        self.vision, self.config, self.clock = vision, config, clock
        self.record = record
        self.channel = record["selected"]
        self.eye_source = record["context"]["source"]
        self.params = record["candidates"][self.channel]
        self.model, self.adjustment, self.orientation, self.ranges, self.zones = calibration_quality(record, config)
        self.reduced = not all(self.ranges)
        self.max_age = min(max_age,.25)
        self.blink_limits = record["context"]["blink_limits"]
        self.limits = tuple(self.blink_limits[k] for k in ("left","right"))
        self.reason = "Esperando mirada"
        self.intent = (0,0)
        self.intent_since = [None,None]
        self.direction = None
        self.signal = None
        self.pose = None
        self.started = clock()
        self.last_stamp = self.valid_stamp = 0
        self.active_since = None
        self.neutral_since = None
        self.armed = False
        self.movement = (0., 0.)
        self.filtered = (0., 0.)
        self.counts = Counter()
        self.latency = deque(maxlen=240)
        self.closed = False
        self.frame_size = (record["context"]["camera"]["frame_width"], record["context"]["camera"]["frame_height"])
        try:
            import psutil
            self.process = psutil.Process()
        except ImportError:
            self.process = None
        self.cpu_start, self.next_usage, self.peak_rss = time.process_time(), self.started, 0

    def close(self):
        self.closed = True
        self.reset("Prueba detenida")

    def reset(self, reason, *, disarm=True):
        self.reason = reason
        self.movement = self.filtered = (0., 0.)
        self.neutral_since = None
        self.intent = (0,0)
        self.intent_since = [None,None]
        if disarm:
            self.direction = None
            self.armed = False
            self.active_since = None

    def _posture_ok(self, face):
        pose = pose_features((face.nose_x, face.nose_y, face.face_scale, face.head_pitch, face.head_yaw, face.head_roll))
        return pose is not None and all(lo <= val <= hi for lo, val, hi in zip(self.params["lower"], pose, self.params["upper"]))

    def update(self, face, now, *, paused=False, gesture=False):
        if self.process is not None and now >= self.next_usage:
            self.next_usage = now + .5
            self.peak_rss = max(self.peak_rss, self.process.memory_info().rss)
        if paused or self.closed:
            self.reset("Rostro ausente · cursor detenido" if not face.fresh(self.max_age, now) else "Control en pausa")
            return None
        if not face.fresh(self.max_age, now):
            if self.armed:
                self.counts["losses"] += 1
            self.reset("Rostro ausente o vencido")
            return None
        if getattr(self.vision, "_frame_size", self.frame_size) != self.frame_size:
            self.reset("Cambió la resolución de cámara")
            return None
        if gesture or not selected_eyes_open(face,self.eye_source,self.limits):
            self.reset("Guiño o gesto · puntero detenido", disarm=False)
            return None
        stamp = face.timestamp_ms
        if stamp == self.last_stamp:
            return None
        if self.last_stamp and stamp-self.last_stamp>self.max_age*1000:
            self.reset("Se interrumpió la captura · volvé al centro")
        self.last_stamp = stamp
        self.counts["results"] += 1
        row = observe_direction(face,fresh=True,fps=0,observed_at=now,phase="fixation",limits=self.blink_limits,models={})
        values = gate_weighted(signals(row,mirrored=face.gaze_mirrored),self.record.get("agreement"))
        point = values.get(self.channel)
        self.pose = row["head"]
        self.signal = point
        if point is None:
            self.counts["rejected"] += 1
            self.reset("Iris oculto o desacuerdo binocular")
            return None
        if self.adjustment:
            point = self.adjustment.correct(point,pose_features(self.pose))
        if point is None or not self._posture_ok(face):
            self.reset("Postura fuera del rango observado")
            return None
        self.direction = self.model.estimate(point)[0]
        if not all(self.ranges):
            self.reason = "Señal insuficiente en un eje"
            if not any(self.ranges):
                self.movement = (0.,0.)
                return None
        center = self.model.centers["center"]
        shift = tuple((value - ref) * sign for value, ref, sign in zip(point, center, self.orientation))
        position = tuple(delta / pair[int(delta >= 0)] if pair else 0. for delta, pair in zip(shift, self.ranges))
        if any(self.ranges[axis] and abs(value) > 1 + (self.params["noise"][axis] * 2.5 / min(self.ranges[axis]))
               for axis, value in enumerate(position)):
            self.counts["rejected"] += 1
            self.reset("Mirada fuera del rango calibrado")
            return None
        self.counts["valid"] += 1
        self.valid_stamp = stamp
        if all(abs(value) <= zone for value, zone in zip(position, self.zones)):
            self.reason = "Centro · cursor quieto"
            self.filtered = self.movement = (0., 0.)
            self.active_since = None
            self.intent = (0,0)
            self.intent_since = [None,None]
            if self.neutral_since is None:
                self.neutral_since = stamp
            if stamp - self.neutral_since >= 120:
                self.armed = True
            return None
        self.neutral_since = None
        if not self.armed:
            self.reason = "Mirá al centro para rearmar el movimiento"
            return None
        if self.active_since is None:
            self.active_since = now
        if now - self.active_since > self.MAX_BURST:
            self.reset("Volvé al centro para continuar")
            return None
        intent = tuple(int(math.copysign(1,value)) if abs(value)>zone*(1.15 if old==0 else 1.) else 0
                       for value,zone,old in zip(position,self.zones,self.intent))
        for axis,sign in enumerate(intent):
            if sign != self.intent[axis]:
                self.intent_since[axis] = stamp if sign else None
        self.intent = intent
        alpha = self.config.smoothing_alpha
        self.filtered = tuple((alpha if abs(value)<abs(prev) else alpha*.5)*prev +
                              (1-(alpha if abs(value)<abs(prev) else alpha*.5))*max(-1.,min(1.,value))
                              if sign and self.intent_since[i] is not None and stamp-self.intent_since[i]>=60
                              and value*sign>0 else 0.
                              for i,(prev,value,sign) in enumerate(zip(self.filtered,position,intent)))
        self.movement = ocular_delta(self.filtered, self.config, self.zones)
        speed = math.hypot(*self.movement)
        limit = min(self.config.max_delta, 3.) if self.reduced else self.config.max_delta
        if speed > limit:
            self.movement = tuple(value * limit / speed for value in self.movement)
        self.reason = "Señal válida" if any(self.movement) else "Estabilizando mirada"
        if any(self.movement):
            return GestureEvent(EV_CURSOR_MOVE, dx=self.movement[0], dy=self.movement[1], source_timestamp_ms=stamp)
        return None

    def actions_allowed(self, face, now):
        return (not self.reduced and not self.closed and self.armed and self.valid_stamp > 0
                and getattr(self.vision, "_frame_size", self.frame_size) == self.frame_size
                and 0 <= now - self.valid_stamp / 1000 <= self.max_age
                and face.fresh(self.max_age, now) and self._posture_ok(face))

    def dwell_allowed(self, now):
        return (self.actions_allowed(self.vision.get_face_data(), now) and self.reason.startswith("Centro")
                and self.movement == (0., 0.))

    def status(self):
        elapsed = max(.001, self.clock() - self.started)
        return dict(reason=self.reason, direction=self.direction, signal=self.signal, pose=self.pose, movement=self.movement, center=self.model.centers["center"], armed=self.armed, valid_fps=self.counts["valid"] / elapsed,
                    rejected=self.counts["rejected"], results=self.counts["results"],
                    detection_losses=self.counts["losses"],
                    cpu_one_core_percent=100 * (time.process_time() - self.cpu_start) / elapsed,
                    peak_process_rss_bytes=self.peak_rss or None,
                    movement_latency_ms=median(self.latency) if self.latency else None)
