"""Decisión temporal unilateral/bilateral sin afectar otros gestos."""


class BrowArbiter:
    def __init__(self, window_ms=200):
        if not 0 <= window_ms <= 1000:
            raise ValueError("Ventana de arbitraje inválida")
        self.window_s = window_ms / 1000
        self.reset()

    def reset(self):
        self.started = None
        self.first = None
        self.choice = None

    def update(self, left, right, both, now):
        if not (left or right or both):
            self.reset()
            return None
        if self.started is None:
            self.started = now
            self.first = "left" if left else "right" if right else "both"
        if self.choice is not None:
            # Decisión por episodio: un segundo lado tardío no convierte scroll en pausa.
            if self.choice == "both":
                return "both" if both else None
            return self.choice if (left if self.choice == "left" else right) else None
        if both and now - self.started <= self.window_s + 1e-9:
            self.choice = "both"
        elif now - self.started >= self.window_s - 1e-9:
            if self.first == "left" and left:
                self.choice = "left"
            elif self.first == "right" and right:
                self.choice = "right"
        if self.choice is None and not both and not (left if self.first == "left" else right):
            # Un intento que se soltó antes de resolver no crea un gesto fantasma.
            self.reset()
        return self.choice
