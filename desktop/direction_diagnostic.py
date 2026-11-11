"""Qt presentation for the ocular direction diagnostic."""
from PySide6.QtCore import QPointF, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QLabel, QHBoxLayout, QProgressBar, QPushButton, QVBoxLayout, QWidget

from direction_diagnostic import TARGETS

LABELS = dict(center="Centro", up="Arriba", down="Abajo", left="Izquierda", right="Derecha")
SOURCES = dict(left="izquierdo", right="derecho", both="ambos ojos")
REFERENCES = dict(eyelids="Párpados", canthi="Comisuras")
MODELS = dict(relative_model="Modelo relativo guardado", absolute_model="Modelo absoluto guardado")


def _channel_label(name):
    if name in MODELS:
        return MODELS[name]
    reference, source = name.split("_")
    return f"{REFERENCES[reference]} · {SOURCES[source]}"


class DirectionTarget(QWidget):
    displayed = Signal(str, int, int, int, int)

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(240)
        self.target = self.token = self.painted = None
        self.setAccessibleName("Objetivo de mirada")

    def present(self, target, token):
        if (target, token) == (self.target, self.token):
            return
        self.target, self.token = target, token
        self.setAccessibleName(f"Objetivo de mirada: {LABELS[target]}" if target else "Evaluación terminada")
        self.update()

    def paintEvent(self, event):
        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.fillRect(self.rect(), QColor("#091220"))
            if self.target is None:
                return
            x, y = TARGETS[self.target]
            point = QPointF(x * self.width(), y * self.height())
            painter.setPen(QColor("#091220"))
            painter.setBrush(QColor("#ffd477"))
            painter.drawEllipse(point, 13, 13)
        if self.token != self.painted:
            self.painted = self.token
            self.displayed.emit(*self.token, self.width(), self.height())


class DirectionDiagnosticPanel(QWidget):
    def __init__(self, request):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.instruction = QLabel("Mirá el punto amarillo. Mantené la cabeza cómoda y quieta.")
        self.instruction.setWordWrap(True)
        layout.addWidget(self.instruction)
        self.target = DirectionTarget()
        self.target.displayed.connect(lambda session, index, attempt, width, height: request(
            "ack_direction_target", session_id=session, index=index, attempt=attempt,
            viewport=(width, height)))
        layout.addWidget(self.target)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setAccessibleName("Progreso del diagnóstico ocular")
        self.progress.setFormat("%v / %m objetivos")
        layout.addWidget(self.progress)
        row = QHBoxLayout()
        self.retry = QPushButton("Repetir captura")
        self.retry.clicked.connect(lambda: request("repeat_direction_target"))
        self.skip = QPushButton("Omitir")
        self.skip.clicked.connect(lambda: request("repeat_direction_target", skip=True))
        self.save = QPushButton("Reintentar guardado")
        self.save.clicked.connect(lambda: request("save_direction_report"))
        cancel = QPushButton("Cerrar diagnóstico")
        cancel.clicked.connect(lambda: request("cancel_direction_diagnostic"))
        for button in (self.retry, self.skip, self.save, cancel):
            row.addWidget(button)
        layout.addLayout(row)
        self.result = QLabel()
        self.result.setWordWrap(True)
        layout.addWidget(self.result)
        self.hide()

    def present(self, session):
        self.setVisible(session is not None)
        if session is None:
            self.target.present(None, None)
            return
        state = session["state"]
        target = session["target"]
        self.target.setVisible(target is not None)
        self.target.present(target, session["token"])
        self.instruction.setVisible(target is not None)
        self.progress.setRange(0, session["total"])
        self.progress.setValue(session["done"])
        self.retry.setVisible(state == "retry")
        self.skip.setVisible(state == "retry")
        self.save.setVisible(bool(session["save_error"]))
        status = dict(await_target="Preparando objetivo", transition="Acomodá la mirada",
                      fixation="Mantené la mirada", retry="Faltaron muestras válidas",
                      ready="Evaluación terminada")[state]
        if target is not None:
            status = f"{LABELS[target]} · {status}"
            if session["valid"] is not None:
                status += " · " + ("Señal válida" if session["valid"] else "Señal ausente o inválida")
        self.status.setText(status)
        self.result.setVisible(state == "ready")
        if state == "ready":
            lines = _summary(session["report"])
            if session["path"]:
                lines.append(f"Informe local en {session['path']}")
            elif session["save_error"]:
                lines.append("No se pudo guardar el informe. Podés reintentar antes de cerrar.")
            self.result.setText("\n".join(lines))


def _summary(report):
    valid = report["valid_percent"]
    lines = [f"Muestras válidas durante fijación: {valid:.0f} %" if valid is not None
             else "Sin muestras de fijación."]
    channels = report["channels"]
    eligible = {name: data for name, data in channels.items() if data["accuracy_percent"] is not None}
    for name, data in channels.items():
        trials = data["evaluated_trials"] + data["unclassified_trials"]
        score = data["accuracy_percent"]
        coverage = data["valid_fixation_percent"]
        details = f" · {coverage:.0f} % de muestras válidas" if coverage is not None else ""
        evaluation = f"{score:.0f} % en {trials} capturas de validación" if score is not None else "Datos insuficientes"
        lines.append(f"{_channel_label(name)} · {evaluation}{details}")
    if not eligible:
        return lines + ["Faltan repeticiones completas para comparar direcciones."]
    best = max(eligible, key=lambda name: (len(eligible[name]["folds"]), eligible[name]["accuracy_percent"]))
    matrix = channels[best]["confusion"]
    ranked = sorted((target for target in LABELS if sum(matrix[target].values())),
                    key=lambda target: matrix[target][target] / sum(matrix[target].values()), reverse=True)
    if ranked:
        lines.append(f"{_channel_label(best)} · Dirección con más aciertos: {LABELS[ranked[0]]}")
    pairs = (("up", "center"), ("down", "center"), ("up", "down"), ("left", "right"))
    for a, b in pairs:
        lines.append(f"{LABELS[a]} ↔ {LABELS[b]} · {matrix[a][b] + matrix[b][a]} confusiones")
    separation = channels[best]["separation"]
    for title, key in (("Horizontal", "left:right"), ("Vertical", "up:down")):
        ratio = separation.get(key, {}).get("gap_over_fixation_sd")
        if ratio is not None:
            lines.append(f"{title} · separación entre extremos de {ratio:.1f} veces la variación en fijación")
    return lines
