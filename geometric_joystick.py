from collections import Counter, deque
import math
from statistics import median
import time

from gaze_source import selected_eyes_open
from gesture_engine import EV_CURSOR_MOVE, GestureEvent
from geometric_calibration import AXES, CHANNELS, axis_ranges, gate_weighted, signals
from direction_diagnostic import observe_direction, DirectionClassifier
from posture_adjustment import PoseAdjustment
from posture_adjustment import pose_features

ENTER = (.55, .65)  # piso por eje de la fracción del recorrido centro→borde que hace falta para mover
# Por dirección, medido en sesiones reales: abajo se infla solo (pide más) y arriba recorre poco (pide menos).
ENTER_BY_ZONE = dict(left=.55, right=.55, up=.65, down=.8)
EXIT = (.7, .8)     # histéresis por eje: la zona activa se conserva hasta caer por debajo de ENTER·EXIT
OUTSIDE = 3.      # recorridos más allá del punto calibrado: la mirada salió de la pantalla
ARM_MS = 200      # mirar la zona central este tiempo habilita los bordes; salir de la pantalla los deshabilita
HOLD_MS = 110     # la zona debe repetirse en fotogramas consecutivos antes de mover
RESUME_MS = 500   # un parpadeo breve no reinicia la rampa de velocidad
USABLE = .65      # umbral máximo aceptable: por encima, el ruido se come el recorrido
MOVING = dict(left="Moviendo a la izquierda", right="Moviendo a la derecha",
              up="Moviendo hacia arriba", down="Moviendo hacia abajo")
POSE_NAMES = ("nariz_x", "nariz_y", "distancia", "inclinación", "giro", "ladeo")
# nariz: fracción del cuadro · distancia: log de la escala del rostro · ángulos: grados
POSE_MARGINS = (.10, .10, .20, 12., 12., 12.)
# El puntero va hacia donde se mira y frena al llegar: así se lo puede mirar sin que se mueva.
REACH = .37 * 1.15  # del centro al punto calibrado (13 % del borde), estirado para llegar a los bordes
GAP_START = .08     # fracción de pantalla entre el puntero y la mirada para que arranque
GAP_SLOW = 3.       # px/s por cada px que falta: llega frenando en vez de pasarse
TRACE_LIMIT = 9000  # muestras guardadas por sesión (~10 min a 15 fps, ~2 MB): alcanza para diagnosticar
VECTORS = dict(left=(-1, 0), right=(1, 0), up=(0, -1), down=(0, 1))


def whiten(model, noise):
    """Cada zona como vector desde el centro, medido en unidades del ruido de fijación.

    Los ejes de la señal no coinciden con los de la pantalla: al mirar arriba el iris también
    se corre de costado. Por eso cada zona se reconoce por su punto calibrado completo (x, y)
    y no por un eje aislado.
    """
    sigma = tuple(max(value, .02*extent, 1e-9) for value, extent in zip(noise, model.scales))
    center = model.centers["center"]
    return sigma, {name: tuple((model.centers[name][i]-center[i])/sigma[i] for i in (0, 1)) for name in VECTORS}


def calibration_quality(record, config):
    """Qué ejes sirven y con qué umbral, como fracción del recorrido centro→objetivo.

    Una zona sirve si su punto calibrado queda lejos del centro y de las otras zonas respecto
    del ruido robusto (MAD) de la fijación central. El máximo observado en el centro no
    interviene: una sola microsacada lo inflaba hasta bloquear el eje.
    """
    candidate = record["candidates"][record["selected"]]
    adjustment = PoseAdjustment.read(candidate["adjustment"]) if candidate.get("adjustment") else None
    model = adjustment.classifier() if adjustment else DirectionClassifier(candidate["centers"])
    signs = axis_ranges(model, candidate["noise"])[0]
    vectors = whiten(model, candidate["noise"])[1]
    need = 2.5 / USABLE
    def clear(name):
        return math.hypot(*vectors[name]) >= need and all(
            math.dist(vectors[name], vectors[other]) >= need for other in VECTORS if other != name)
    ranges = tuple(tuple(math.hypot(*vectors[name]) for name in pair) if all(map(clear, pair)) else None
                   for pair in AXES)
    minimum = tuple(config.dead_zone if zone is None else zone for zone in (config.dead_zone_x, config.dead_zone_y))
    zones = tuple(max(enter, zone, 2.5/min(pair)) if pair else 1.
                  for enter, zone, pair in zip(ENTER, minimum, ranges))
    return model, adjustment, signs, ranges, zones


def calibration_message(ranges):
    if all(ranges):
        return "Calibración lista. Ya podés activar el control."
    if any(ranges):
        works, fails = (("izquierda y derecha", "arriba y abajo") if ranges[0]
                        else ("arriba y abajo", "izquierda y derecha"))
        return (f"Calibración parcial: mirar los bordes mueve el puntero hacia {works}. La cámara todavía no "
                f"distingue {fails}; podés repetir ese eje. Los clics quedan deshabilitados.")
    return ("La cámara todavía no distingue tu mirada al centro de la mirada a los bordes. "
            "Repetí los cinco puntos moviendo solo los ojos, con la cabeza quieta.")


def select_usable_candidate(record, config):
    """Más ejes utilizables primero; después las señales de los dos ojos; después el recorrido.

    Con un solo ojo, mirar de costado corre la lectura vertical (en sentidos opuestos en cada
    ojo). El promedio de ambos lo cancela, así que se prefiere mientras sirva en los mismos ejes.
    """
    def rank(candidate):
        ranges = calibration_quality(candidate, config)[3]
        margins = [min(pair) for pair in ranges if pair]
        return (len(margins), candidate["selected"] in CHANNELS[source], min(margins, default=0.),
                candidate["selected"] == record["selected"])
    # Con ambos ojos abiertos también valen las señales de un solo ojo: si un ojo se ve
    # mejor que el promedio de los dos, conviene usar ese en lugar de bloquear un eje.
    source = record["context"]["source"]
    channels = CHANNELS[source] + (CHANNELS["left"] + CHANNELS["right"] if source == "both" else ())
    eligible = [record | {"selected": channel} for channel in channels if channel in record["candidates"]]
    return max(eligible, key=rank, default=record)


class GeometricJoystick:
    """Joystick por bordes: mirar hacia un borde de la pantalla mueve el puntero hacia ese lado.

    Se mueve desde donde esté y con una velocidad que crece mientras se sostiene la mirada.
    Toda la zona central, y mirar fuera de la pantalla, lo dejan quieto.
    """
    name = "eye_joystick"
    eye_source = "both"

    def __init__(self, vision, record, config, max_age, clock):
        self.vision, self.config, self.clock = vision, config, clock
        self.record = record
        self.channel = record["selected"]
        self.eye_source = record["context"]["source"]
        self.params = record["candidates"][self.channel]
        self.model, self.adjustment, self.orientation, self.ranges, self.zones = calibration_quality(record, config)
        self.reduced = not all(self.ranges)
        self.sigma, vectors = whiten(self.model, self.params["noise"])
        self.vectors = {name: vector for name, vector in vectors.items() if self.ranges[name in AXES[1]]}
        self.sums = {}
        self.recent = deque(maxlen=3)
        self.cursor = None        # puntero en la pantalla calibrada (0–1 por eje); lo informa el control
        self.arrived = False
        self.gap = None
        self.extent = tuple(record["context"].get("pad", (0, 0, 1920, 1080))[2:])
        self.frozen = False       # «quieto» por voz: se sigue leyendo la mirada, pero ningún borde mueve
        self.ready = False        # las zonas solo mandan después de pasar por el centro del recuadro
        self.center_since = None
        self.trace = []           # (ms, x, y, zona vista, zona que mueve): números, nunca imágenes
        self.max_age = min(max_age,.25)
        self.blink_limits = record["context"]["blink_limits"]
        self.limits = tuple(self.blink_limits[k] for k in ("left","right"))
        self.reason = "Esperando mirada"
        self.direction = None
        self.signal = None
        self.pose = None
        self.position = None
        self.started = clock()
        self.last_stamp = self.valid_stamp = 0
        self.zone = self.candidate = None
        self.candidate_since = self.zone_since = 0
        self.resume = (None, 0, 0)
        self.last_emit = 0.
        self.armed = False
        self.movement = (0., 0.)
        self.counts = Counter()
        self.samples = Counter()
        self.posture_counts = Counter()
        self.posture_failed = []
        self.seconds = Counter()
        self.accounted = None
        self.pixels = 0.
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

    def reset(self, reason, *, disarm=True, stamp=None):
        self.reason = reason
        self._halt(stamp)
        self.candidate = None
        if disarm:
            self.recent.clear()
            self.direction = None
            self.armed = False
            self.ready = False
            self.center_since = None

    def _posture_ok(self, face):
        pose = pose_features((face.nose_x, face.nose_y, face.face_scale, face.head_pitch, face.head_yaw, face.head_roll))
        if pose is None:
            return False
        if self.adjustment:
            return all(lo <= val <= hi for lo, val, hi in zip(self.adjustment.lower, pose, self.adjustment.upper))
        # Cinco fijaciones seguidas capturan apenas milímetros de postura: usar esos extremos
        # como límite rechazaba casi todas las muestras en cuanto la persona se acomodaba.
        # El margen cubre el uso sentado normal y sigue frenando un cambio grande de postura.
        failed = [name for name, lo, val, hi, margin in zip(POSE_NAMES, self.params["lower"], pose,
                                                            self.params["upper"], POSE_MARGINS)
                  if not lo - margin <= val <= hi + margin]
        self.posture_failed = failed
        return not failed

    def _account(self, now):
        if self.accounted is not None:
            self.seconds[self.reason] += min(max(0., now - self.accounted), .5)
        self.accounted = now

    def _classify(self, position):
        """Cuánto avanzó la mirada hacia cada borde, eje por eje; el horizontal decide primero.

        Medido en sesiones reales por bordes: el horizontal es limpio, pero el vertical se infla
        hacia «abajo» al mirar de costado o entrecerrar los ojos, y el descanso queda algo corrido
        hacia «arriba». Por eso el vertical pide más recorrido y solo cuenta si no hay orden horizontal.
        """
        outside = False
        self.arrived = False
        for axis in (0, 1):
            for name in AXES[axis]:
                limit = max(self.zones[axis], ENTER_BY_ZONE[name])
                vector = self.vectors.get(name)
                if vector is None or not vector[axis]:
                    continue
                progress = position[axis] / vector[axis]  # 0 en el centro, 1 en el punto calibrado del borde
                if progress > 1 + OUTSIDE:
                    outside = True
                elif progress > limit or (self.zone == name and progress > EXIT[axis] * limit):
                    if self.cursor is None:
                        return name
                    # Dónde cae la mirada en la pantalla (0–1) y cuánto le falta al puntero para llegar.
                    side = 1 if name == AXES[axis][1] else -1
                    gap = side * (.5 + side * REACH * progress - self.cursor[axis])
                    if gap > (0. if self.zone == name else GAP_START):
                        self.gap = gap * self.extent[axis]
                        return name
                    self.arrived = True  # el puntero ya está donde se mira: probar el otro eje
        return "outside" if outside else "center"

    def _steady(self, raw):
        """El vertical salta de a un fotograma: se usa la mediana de los últimos tres."""
        self.recent.append(raw[1])
        return raw[0], median(self.recent)

    def _halt(self, stamp=None):
        if self.zone in VECTORS and stamp is not None:
            self.resume = (self.zone, self.zone_since, stamp)
        self.zone = None
        self.movement = (0., 0.)

    def _speed(self, stamp):
        """px/s: arranca despacio para ajustar fino y acelera al sostener la mirada."""
        held = (stamp - self.zone_since) / 1000
        start = 10 * self.config.sensitivity
        top = max(start, 40 * self.config.max_delta)
        ramp = 16 / max(self.config.acceleration, .5)
        progress = min(1., max(0., held - .25) / ramp)
        return start + (top - start) * progress * progress

    def _emit(self, now):
        if self.zone not in VECTORS:
            return None
        elapsed, self.last_emit = min(max(0., now - self.last_emit), .1), now
        speed = self._speed(self.last_stamp)
        if self.cursor is not None and self.gap is not None:
            speed = min(speed, max(10 * self.config.sensitivity, GAP_SLOW * self.gap))
        step = speed * elapsed
        self.movement = tuple(axis * step for axis in VECTORS[self.zone])
        if not step:
            return None
        self.counts["moves"] += 1
        self.pixels += step
        return GestureEvent(EV_CURSOR_MOVE, dx=self.movement[0], dy=self.movement[1],
                            source_timestamp_ms=self.last_stamp)

    def update(self, face, now, *, paused=False, gesture=False):
        self._account(now)
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
        stamp = face.timestamp_ms
        if gesture or not selected_eyes_open(face,self.eye_source,self.limits):
            self.reset("Guiño o gesto · puntero detenido", disarm=False, stamp=stamp)
            return None
        if stamp == self.last_stamp:
            return self._emit(now)  # entre fotogramas sigue el movimiento ya decidido
        self.last_stamp = stamp
        self.counts["results"] += 1
        row = observe_direction(face,fresh=True,fps=0,observed_at=now,phase="fixation",limits=self.blink_limits,models={})
        values = gate_weighted(signals(row,mirrored=face.gaze_mirrored),self.record.get("agreement"))
        point = values.get(self.channel)
        self.pose = row["head"]
        self.signal = point
        if point is None:
            self.counts["rejected"] += 1
            self.reset("Iris oculto o desacuerdo binocular", disarm=False, stamp=stamp)
            return None
        if self.adjustment:
            point = self.adjustment.correct(point,pose_features(self.pose))
        if point is None or not self._posture_ok(face):
            self.counts["posture"] += 1
            self.posture_counts.update(getattr(self, "posture_failed", ()))
            self.reset("Postura fuera del rango observado")
            return None
        self.direction = self.model.estimate(point)[0]
        if not any(self.ranges):
            self.reason = "Señal insuficiente en los dos ejes"
            self.movement = (0.,0.)
            return None
        center = self.model.centers["center"]
        raw = tuple((value - ref) / sigma for value, ref, sigma in zip(point, center, self.sigma))
        self.position = self._steady(raw)
        self.counts["valid"] += 1
        self.valid_stamp = stamp
        seen = self._classify(self.position)
        if self.frozen and seen in VECTORS:
            seen = "center"
        self.samples[seen] += 1
        total = self.sums.setdefault(seen, [0., 0.])
        total[0] += self.position[0]
        total[1] += self.position[1]
        self.armed = True
        if len(self.trace) < TRACE_LIMIT:
            self.trace.append((stamp, round(self.position[0], 2), round(self.position[1], 2), seen, self.zone,
                               {name: [round(value, 4) for value in pair] for name, pair in values.items()}))
        if seen not in VECTORS:
            self._halt(stamp)
            self.zone = seen
            self.candidate = None
            if seen == "center":
                self.center_since = self.center_since or stamp
                self.ready = self.ready or stamp - self.center_since >= ARM_MS
                self.reason = ("Centro · quieto por voz, decí «mover»" if self.frozen else
                               "Centro · el puntero ya está donde mirás" if self.arrived else "Centro · puntero quieto")
            else:
                self.center_since = None
                self.reason = "Mirada fuera de la pantalla · puntero quieto"
            return None
        self.center_since = None
        if not self.ready:
            self._halt(stamp)
            self.candidate = None
            self.reason = "Mirá el centro de la pantalla para empezar"
            return None
        if seen == self.zone:
            return self._emit(now)
        if seen != self.candidate:
            self.candidate, self.candidate_since = seen, stamp
        self._halt(stamp)
        if stamp - self.candidate_since < HOLD_MS:
            self.reason = "Estabilizando mirada"
            return None
        previous, since, stopped = self.resume
        self.zone_since = since + stamp - stopped if previous == seen and stamp - stopped <= RESUME_MS else stamp
        self.zone, self.candidate, self.last_emit = seen, None, now
        self.reason = MOVING[seen]
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
        return dict(reason=self.reason, zone=self.zone, position=self.position, direction=self.direction,
                    signal=self.signal, pose=self.pose, movement=self.movement, center=self.model.centers["center"],
                    armed=self.armed, valid_fps=self.counts["valid"] / elapsed,
                    rejected=self.counts["rejected"], results=self.counts["results"],
                    detection_losses=self.counts["losses"],
                    cpu_one_core_percent=100 * (time.process_time() - self.cpu_start) / elapsed,
                    peak_process_rss_bytes=self.peak_rss or None,
                    movement_latency_ms=median(self.latency) if self.latency else None)

    def summary(self):
        """Resumen local, sin imágenes, de en qué estado pasó el tiempo la sesión."""
        return dict(channel=self.channel, usable_axes=[pair is not None for pair in self.ranges],
                    thresholds=[round(zone, 3) for zone in self.zones],
                    seconds_by_state={reason: round(value, 2) for reason, value in self.seconds.most_common()},
                    samples_by_zone=dict(self.samples), results=self.counts["results"], valid=self.counts["valid"],
                    rejected_signal=self.counts["rejected"], rejected_posture=self.counts["posture"],
                    posture_out_of_range=dict(self.posture_counts),
                    # en unidades de ruido: dónde quedó calibrada cada zona y dónde cayó la mirada
                    calibrated_zones={name: [round(value, 1) for value in vector] for name, vector in self.vectors.items()},
                    mean_signal_by_zone={name: [round(value / self.samples[name], 1) for value in total]
                                         for name, total in self.sums.items()},
                    face_losses=self.counts["losses"], movement_events=self.counts["moves"],
                    pixels_moved=round(self.pixels))
