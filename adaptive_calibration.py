"""Calibración robusta genérica de señales binarias y compuestas.

Las muestras solo viven en memoria. to_record exporta agregados explicables.
No conoce cejas, ojos, boca, MediaPipe, Qt ni acciones del sistema.
"""
import math
from copy import deepcopy
from dataclasses import dataclass, field
from statistics import median, mean


def percentile(values, p):
    values = sorted(values)
    if not values:
        raise ValueError("Sin muestras")
    pos = (len(values) - 1) * p / 100
    lo, hi = math.floor(pos), math.ceil(pos)
    return values[lo] + (values[hi] - values[lo]) * (pos - lo)


def statistics(values):
    if not values or any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
        raise ValueError("Muestras vacías o inválidas")
    center = float(median(values))
    return dict(count=len(values), median=center,
                mad=float(median(abs(v-center) for v in values)),
                p10=percentile(values, 10), p90=percentile(values, 90))


@dataclass
class GestureCalibration:
    gesture_id: str
    channels: tuple
    directions: tuple
    source: str = "GEOMETRIC"
    enabled: bool = True
    neutral_samples: list = field(default_factory=list, repr=False)
    active_samples: list = field(default_factory=list, repr=False)
    repetitions: list = field(default_factory=list)
    neutral_statistics: dict = field(default_factory=dict)
    active_statistics: dict = field(default_factory=dict)
    activation_threshold: dict = field(default_factory=dict)
    release_threshold: dict = field(default_factory=dict)
    quality_score: float = 0.
    quality_label: str = "REPETIR"
    validation_state: str = "pending"
    reasons: list = field(default_factory=list)
    retries: int = 0
    separation: dict = field(default_factory=dict)
    neutral_noise: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.channels or len(self.channels) != len(self.directions) or len(set(self.channels)) != len(self.channels):
            raise ValueError("Canales de calibración inválidos")
        if any(d not in (-1, 1) for d in self.directions):
            raise ValueError("Dirección de activación inválida")

    def add_repetition(self, neutral, active):
        """Ventanas ya filtradas por frescura/transición en la sesión de captura."""
        for rows in (neutral, active):
            if not rows or any(len(row) != len(self.channels) or any(
                    type(v) not in (int, float) or not math.isfinite(v) for v in row) for row in rows):
                raise ValueError("Repetición vacía o inválida")
        n, a = [tuple(row) for row in neutral], [tuple(row) for row in active]
        self.neutral_samples.append(n)
        self.active_samples.append(a)
        self.validation_state = "pending"

    def disable(self):
        self.enabled = False
        self.activation_threshold.clear()
        self.release_threshold.clear()
        self.quality_score, self.quality_label = 0., "NO DISPONIBLE"
        self.validation_state = "disabled"

    def fit(self, config):
        """Mismo ajuste para cualquier número de canales y dirección de señal.

        Intersección de los intervalos p90(neutral)..p10(activo) de TODAS las
        repeticiones, con margen MAD neutral. Se maximiza la exactitud balanceada
        de la peor repetición; los empates favorecen el mayor margen a las clases.
        La calidad publicada es esa exactitud mínima dentro de la muestra, NO
        una estimación de precisión futura o clínica.
        """
        self.reasons = []
        self.activation_threshold.clear()
        self.release_threshold.clear()
        self.neutral_statistics.clear()
        self.active_statistics.clear()
        self.separation.clear()
        self.neutral_noise.clear()
        self.repetitions = []
        self.quality_score, self.quality_label = 0., "REPETIR"
        self.validation_state = "repeat"
        if not self.enabled:
            self.disable()
            return self
        if len(self.active_samples) != len(self.neutral_samples) or len(self.active_samples) < config.repetitions:
            self.reasons.append("Faltan repeticiones cómodas")
            return self
        if any(len(rows) < config.min_window_samples for rows in self.neutral_samples + self.active_samples):
            self.reasons.append("Muestras insuficientes en una repetición")
            return self
        self.repetitions = [dict(attempt=index+1, neutral_count=len(n), active_count=len(a),
                                 neutral_statistics={key:statistics([row[i] for row in n]) for i,key in enumerate(self.channels)},
                                 active_statistics={key:statistics([row[i] for row in a]) for i,key in enumerate(self.channels)})
                            for index,(n,a) in enumerate(zip(self.neutral_samples,self.active_samples))]
        channel_scores = []
        for i, (channel, direction) in enumerate(zip(self.channels, self.directions)):
            neutral = [[row[i] * direction for row in rows] for rows in self.neutral_samples]
            active = [[row[i] * direction for row in rows] for rows in self.active_samples]
            ns, ac = [statistics(v) for v in neutral], [statistics(v) for v in active]
            # Exportar unidades originales, incluso para gestos de señal decreciente.
            self.neutral_statistics[channel] = statistics([row[i] for rows in self.neutral_samples for row in rows])
            self.active_statistics[channel] = statistics([row[i] for rows in self.active_samples for row in rows])
            noise = max(1.4826 * s["mad"] for s in ns)
            low = max(max(s["p90"], s["median"] + max(config.min_separation, config.noise_multiplier * 1.4826*s["mad"])) for s in ns)
            high = min(s["p10"] for s in ac)
            self.separation[channel] = high - low
            self.neutral_noise[channel] = noise
            if high - low <= config.min_separation:
                self.reasons.append(f"{channel}: señal débil o neutral inestable")
                continue
            # Candidates de distribuciones, acotados al hueco robusto.
            points = sorted(set([low, high] + [v for groups in (neutral, active) for rows in groups for v in rows if low < v < high]))
            candidates = [(a+b)/2 for a,b in zip(points, points[1:])]
            def scores(t):
                return [((sum(v <= t for v in n)/len(n)) + (sum(v > t for v in a)/len(a)))/2
                        for n,a in zip(neutral, active)]
            threshold = max(candidates, key=lambda t: (min(scores(t)), mean(scores(t)), min(t-low, high-t)))
            # Liberación entre banda neutral robusta y activación: hueco positivo.
            release = (low + threshold)/2
            self.activation_threshold[channel] = direction * threshold
            self.release_threshold[channel] = direction * release
            channel_scores.append(min(scores(threshold)))
        if not self.reasons:
            # Calidad conjunta AND: exactitud balanceada mínima por repetición.
            def active_row(row):
                return all(d * (value - self.activation_threshold[key]) > 0
                           for key,d,value in zip(self.channels,self.directions,row))
            scores = []
            for index,(neutral,active) in enumerate(zip(self.neutral_samples,self.active_samples)):
                specificity = sum(not active_row(v) for v in neutral)/len(neutral)
                sensitivity = sum(active_row(v) for v in active)/len(active)
                score = (specificity+sensitivity)/2
                scores.append(score)
                self.repetitions[index].update(specificity=specificity, sensitivity=sensitivity, balanced_accuracy=score)
            self.quality_score = min(scores + channel_scores)
            self.quality_label = "BUENA" if self.quality_score >= .95 else "ACEPTABLE" if self.quality_score >= .85 else "DÉBIL"
            if self.quality_score < .85:
                self.reasons.append("Las repeticiones no se distinguen de forma consistente")
        else:
            self.quality_label = "DÉBIL"
        self.validation_state = "pending" if self.usable else "repeat"
        return self

    @property
    def usable(self):
        return (not self.enabled or (not self.reasons and self.quality_score >= .85
                and set(self.activation_threshold) == set(self.channels)))

    def to_record(self):
        """Nunca serializar las muestras individuales ni imágenes."""
        names = ("gesture_id", "source", "enabled", "repetitions", "neutral_statistics",
                 "active_statistics", "activation_threshold", "release_threshold", "quality_score",
                 "quality_label", "validation_state", "reasons", "retries", "separation", "neutral_noise")
        result = {name: deepcopy(getattr(self, name)) for name in names}
        result.update(channels=list(self.channels), directions=list(self.directions),
                      repetitions_valid=sum(r.get("balanced_accuracy", 0) >= .85 for r in self.repetitions),
                      repetitions_captured=len(self.neutral_samples), method="robust_distribution_gap_v1")
        return result


class HysteresisGate:
    """Compuerta genérica por canal; AND para señales compuestas."""
    def __init__(self, channels, directions, activation, release):
        self.channels, self.directions = tuple(channels), tuple(directions)
        self.activation, self.release = dict(activation), dict(release)
        if len(self.channels) != len(self.directions) or not self.channels:
            raise ValueError("Canales inválidos")
        for key,d in zip(self.channels,self.directions):
            if d not in (-1,1) or key not in self.activation or key not in self.release:
                raise ValueError("Umbrales incompletos")
            a,r = self.activation[key], self.release[key]
            if any(type(v) not in (int,float) or not math.isfinite(v) for v in (a,r)) or d*(a-r) < 0:
                raise ValueError("Histéresis inválida")
        self.reset()

    def reset(self):
        self.states = [False] * len(self.channels)

    def update(self, values):
        if values is None or len(values) != len(self.channels) or any(
                type(v) not in (int,float) or not math.isfinite(v) for v in values):
            self.reset()
            return False
        for i,(key,d,v) in enumerate(zip(self.channels,self.directions,values)):
            threshold = self.release[key] if self.states[i] else self.activation[key]
            self.states[i] = d*(v-threshold) > 0
        return all(self.states)
