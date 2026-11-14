"""Qt presentation for the ocular direction diagnostic."""
from PySide6.QtWidgets import QLabel, QHBoxLayout, QProgressBar, QPushButton, QVBoxLayout, QWidget

LABELS = dict(center="Centro", up="Arriba", down="Abajo", left="Izquierda", right="Derecha")
SOURCES = dict(left="izquierdo", right="derecho", both="ambos ojos")
REFERENCES = dict(eyelids="Párpados", canthi="Comisuras")
MODELS = dict(relative_model="Modelo relativo guardado", absolute_model="Modelo absoluto guardado")


def _channel_label(name):
    if name in MODELS:
        return MODELS[name]
    reference, source = name.split("_")
    return f"{REFERENCES[reference]} · {SOURCES[source]}"


class DirectionDiagnosticPanel(QWidget):
    def __init__(self, request, activate):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 12)
        layout.setSpacing(10)
        self.title = QLabel("Calibración del joystick")
        self.title.setObjectName("Title")
        layout.addWidget(self.title)
        self.instruction = QLabel()
        self.instruction.setWordWrap(True)
        layout.addWidget(self.instruction)
        layout.addStretch(1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setAccessibleName("Progreso del diagnóstico ocular")
        self.progress.setFormat("%v / %m objetivos")
        layout.addWidget(self.progress)
        row = QHBoxLayout()
        row.addStretch()
        self.retry = QPushButton("Repetir captura")
        self.retry.clicked.connect(lambda: request("repeat_direction_target"))
        self.save = QPushButton("Reintentar guardado")
        self.save.clicked.connect(lambda: request("save_direction_report"))
        self.activate = QPushButton("Activar control")
        self.activate.setObjectName("Primary")
        self.activate.clicked.connect(activate)
        cancel = self.cancel = QPushButton("Cerrar diagnóstico")
        cancel.clicked.connect(lambda: request("cancel_direction_diagnostic"))
        for button in (self.retry, self.save, self.activate, cancel):
            row.addWidget(button)
        layout.addLayout(row)
        self.axis_buttons = [QPushButton("Repetir eje horizontal"), QPushButton("Repetir eje vertical")]
        axis_row = QHBoxLayout()
        axis_row.addStretch()
        for axis, widget in enumerate(self.axis_buttons):
            widget.clicked.connect(lambda checked=False, value=axis: request("retry_geometric_axis", axis=value))
            axis_row.addWidget(widget)
        layout.addLayout(axis_row)
        self.result = QLabel()
        self.result.setWordWrap(True)
        layout.addWidget(self.result)
        self.hide()

    def present(self, session, *, can_activate=False):
        self.setVisible(session is not None)
        if session is None:
            return
        state = session["state"]
        self.cancel.setText("Volver a Ojos" if state == "ready" else "Cancelar calibración")
        self.instruction.setText(
            "Seguí el círculo amarillo: aparece en el centro de la pantalla y cerca de cada borde. "
            "Son cinco puntos, una sola vez. Mové sobre todo los ojos y dejá la cabeza lo más quieta "
            "que puedas: así la cámara ve más diferencia entre un punto y otro.")
        target = session["target"]
        self.instruction.setVisible(target is not None)
        self.progress.setRange(0, session["total"])
        self.progress.setValue(session["done"])
        self.retry.setVisible(state == "retry")
        self.save.setVisible(bool(session["save_error"]))
        self.activate.setVisible(state == "ready" and can_activate)
        status = dict(await_target="Preparando objetivo", transition="Acomodá la mirada",
                      fixation="Mantené la mirada", retry="Faltaron muestras válidas",
                      ready="Calibración terminada")[state]
        for axis, widget in enumerate(self.axis_buttons):
            widget.setVisible(axis in session.get("repair_axes", ()))
        if target is not None:
            status = f"{LABELS[target]} · {status}"
            if session["valid"] is not None:
                status += " · " + ("Señal válida" if session["valid"] else "Señal ausente o inválida")
        if state == "retry":
            status += " · Acomodate frente a la cámara y tocá Repetir captura."
        self.status.setText(status)
        self.result.setVisible(state == "ready")
        if state == "ready":
            lines = list(session.get("geometric_summary") or _summary(session["report"]))
            if session["path"] and not any(line.startswith("Calibración guardada") for line in lines):
                lines.append("Calibración guardada.")
            elif session["save_error"]:
                lines.append("No se pudo guardar la calibración. Podés reintentar antes de cerrar.")
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
