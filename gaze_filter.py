"""Filtro de fijaciones para el cursor por posición de mirada. Sin Qt, cámara ni NumPy.

La mirada alterna fijaciones (el ojo quieto sobre algo) con saltos rápidos
(sacadas). Un promedio exponencial trata todo igual: con el ruido de la webcam
el cursor "nada" alrededor del punto mirado y además llega tarde a los saltos.
Este filtro mantiene un ancla fija mientras la mirada siga dentro de un radio y
salta de una vez cuando sale de él de forma sostenida.

- El radio es elíptico: el eje vertical es más ruidoso (el iris se mueve unas
  cuatro veces menos en vertical que en horizontal), así que se tolera más.
- Un salto requiere que la mediana de las últimas lecturas quede fuera del radio
  en cuadros consecutivos: una lectura suelta (p. ej. el párpado abriéndose
  después de parpadear) no mueve el cursor.
- Dentro de la fijación, el ancla sólo se acomoda si la mediana larga se aleja
  de forma sostenida (mirar algo un poco al lado) y para cerca de ella: el
  ruido no la mueve.
- Un parpadeo o una pérdida breve de iris no borra el ancla: la mirada casi
  nunca cambia durante un parpadeo.
"""
from collections import deque
import math
from statistics import median


class FixationFilter:
    def __init__(self, width, height, radius_px=70., vertical_factor=1.6, smoothing=.65,
                 short_frames=3, saccade_frames=2, long_ms=500, keep_ms=1500):
        self.size = (max(width-1, 1), max(height-1, 1))
        self.radius = (radius_px, radius_px*vertical_factor)
        self.follow = 1-smoothing  # cuánto se acerca el ancla por cuadro al acomodarse
        self.short_frames, self.saccade_frames = short_frames, saccade_frames
        self.long_ms, self.keep_ms = long_ms, keep_ms
        self.samples = deque()
        self.anchor = None
        self.last_ms = None
        self.state = "sin datos"
        self._outside = 0
        self._settling = False

    def reset(self):
        self.samples.clear()
        self.anchor = self.last_ms = None
        self._outside, self._settling = 0, False
        self.state = "sin datos"

    def interrupt(self):
        """Parpadeo o iris perdido: se descartan las lecturas, se conserva el ancla."""
        self.samples.clear()
        self._outside, self._settling = 0, False

    def _distance(self, point):
        return math.hypot((point[0]-self.anchor[0])/self.radius[0], (point[1]-self.anchor[1])/self.radius[1])

    def update(self, timestamp_ms, position):
        """Predicción normalizada (0-1) → posición filtrada normalizada."""
        point = (position[0]*self.size[0], position[1]*self.size[1])
        if self.anchor is None or self.last_ms is None or timestamp_ms-self.last_ms > self.keep_ms:
            self.reset()
            self.anchor = point
        self.last_ms = timestamp_ms
        self.samples.append((timestamp_ms, point))
        while self.samples[0][0] < timestamp_ms-self.long_ms:
            self.samples.popleft()
        recent = [p for _, p in list(self.samples)[-self.short_frames:]]
        short = (median(p[0] for p in recent), median(p[1] for p in recent))
        if len(recent) == self.short_frames and self._distance(short) > 1:
            self._outside += 1
            if self._outside >= self.saccade_frames:
                # Salto: la fijación anterior ya no sirve para la mediana larga.
                self.anchor = short
                for _ in range(len(self.samples)-self.short_frames):
                    self.samples.popleft()
                self._outside, self._settling = 0, False
                self.state = "salto"
            else:
                self.state = "posible salto"
        else:
            self._outside = 0
            long = (median(p[0] for _, p in self.samples), median(p[1] for _, p in self.samples))
            distance = self._distance(long)
            # Acomodarse sólo con medio tramo largo de lecturas (no con la primera
            # después de un parpadeo). Histéresis: empezar a .35 del radio y parar a .1.
            enough = self.samples[-1][0]-self.samples[0][0] >= self.long_ms/2
            self._settling = enough and distance > (.1 if self._settling else .35)
            if self._settling:
                self.anchor = tuple(a+self.follow*(m-a) for a, m in zip(self.anchor, long))
            self.state = "acomodando" if self._settling else "fijación"
        return self.anchor[0]/self.size[0], self.anchor[1]/self.size[1]

    def diagnostic(self):
        return dict(state=self.state, radius_px=list(self.radius),
                    anchor_px=list(self.anchor) if self.anchor else None)
