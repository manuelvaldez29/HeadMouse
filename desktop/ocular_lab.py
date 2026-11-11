"""Qt laboratory for simulated diagnosis and virtual-only joystick practice."""
from dataclasses import asdict, replace
import json
from pathlib import Path
import uuid

from PySide6.QtCore import QEvent, QObject, QPointF, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (QApplication, QBoxLayout, QCheckBox, QComboBox, QDialog, QDoubleSpinBox,
                               QFileDialog, QFormLayout, QFrame, QGridLayout, QLabel, QProgressBar, QPushButton, QScrollArea,
                               QSpinBox, QVBoxLayout, QWidget)

from desktop.direction_diagnostic import LABELS
from direction_diagnostic import DIRECTIONS, RAW_CHANNELS, TARGETS
from gaze_source import gaze_position
from ocular_comparison import CourseComparison
from ocular_joystick import HEIGHT, STEPS, WIDTH, JoystickOptions
from ocular_lab import JoystickCourse
from ocular_replay import ReplayComparison
from ocular_simulation import SCENARIOS, SyntheticDiagnostic, write_report
from ocular_temporal import WINDOWS

ARROWS = dict(up="↑", down="↓", left="←", right="→", center="■")
KEYS = {Qt.Key.Key_Up: "up", Qt.Key.Key_Down: "down", Qt.Key.Key_Left: "left", Qt.Key.Key_Right: "right"}
POSITIONS = dict(center="Centro", top_left="Arriba a la izquierda", top_right="Arriba a la derecha",
                 bottom_left="Abajo a la izquierda", bottom_right="Abajo a la derecha")
METHODS = dict(previous="Anterior", median="Ventana con mediana", weighted="Ventana con voto ponderado")
EYES = dict(left="ojo izquierdo", right="ojo derecho", both="ambos ojos")


class LabWorker(QObject):
    snapshot = Signal(object)
    finished = Signal()

    def __init__(self, export_dir):
        super().__init__()
        self.export_dir = export_dir
        self.timer = None
        self.run = None
        self.state = "idle"
        self.message = ""

    @Slot()
    def prepare(self):
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self.tick)
        self.publish()

    @Slot(str, object)
    def command(self, action, data):
        try:
            if action == "close":
                self.timer.stop()
                self.run = None
                self.finished.emit()
                return
            if action == "start":
                kind, scenario, seed, config, options, automatic = data
                if kind == "diagnostic":
                    self.run = SyntheticDiagnostic(config, seed, scenario)
                elif kind == "comparison":
                    self.run = CourseComparison(config, seed, scenario, options)
                elif kind == "replay":
                    self.run = ReplayComparison(config, options)
                else:
                    self.run = JoystickCourse(config, seed, scenario, options, automatic=automatic)
                self.state, self.message = "running", ""
                try:
                    write_report(self.export_dir / "options.json", asdict(options))
                except OSError:
                    self.message = "La sesión sigue activa. No se pudieron guardar las opciones."
                self.timer.start()
            elif action == "pause":
                if self.state == "paused":
                    self.state = "running"
                    self.timer.start()
                elif self.state == "running":
                    self._stop("paused")
            elif action == "stop":
                self._stop("stopped")
            elif action == "export":
                self.export()
            elif isinstance(self.run, JoystickCourse) and self.state == "running":
                self.run.command(action, data)
            self.publish()
        except Exception as exc:
            self.fail(exc)

    def _stop(self, state):
        self.timer.stop()
        if isinstance(self.run, JoystickCourse):
            self.run.stop_motion()
        self.state = state

    def fail(self, exc):
        self._stop("error")
        self.message = f"Simulación detenida. {exc}"
        self.publish()

    @Slot()
    def tick(self):
        try:
            self.run.step()
            complete = (self.run.session.state == "ready" if isinstance(self.run, SyntheticDiagnostic) else self.run.done)
            if complete:
                self._stop("complete")
            self.publish()
        except Exception as exc:
            self.fail(exc)

    def export(self):
        if self.state not in ("stopped", "complete") or self.run is None:
            return
        if (isinstance(self.run, SyntheticDiagnostic) and self.run.session.state != "ready"
                or isinstance(self.run, (CourseComparison, ReplayComparison)) and not self.run.done):
            return
        path = self.export_dir / f"{uuid.uuid4().hex}.json"
        try:
            write_report(path, self.run.record())
        except OSError as exc:
            self.message = f"No se pudo exportar el JSON. {exc}"
        else:
            self.message = f"Informe sintético guardado en {path}"

    def publish(self):
        payload = dict(state=self.state, message=self.message, diagnostic=None, joystick=None, eyes=None,
                       comparison=None, replay=None)
        if isinstance(self.run, SyntheticDiagnostic):
            payload["diagnostic"] = self.run.session.snapshot()
            face = self.run.face
            if face is not None:
                payload["eyes"] = tuple(gaze_position(face, side) for side in ("left", "right"))
        elif isinstance(self.run, JoystickCourse):
            payload["joystick"] = self.run.snapshot()
        elif isinstance(self.run, CourseComparison):
            run = self.run
            payload["comparison"] = dict(progress=run.progress(), result=run.record() if run.done else None)
        elif isinstance(self.run, ReplayComparison):
            payload["replay"] = self.run.snapshot()
        self.snapshot.emit(payload)


class LabCanvas(QWidget):
    def __init__(self):
        super().__init__()
        self.data = {}
        self.setMinimumSize(290, 200)
        self.setAccessibleName("Área de simulación ocular y cursor virtual")

    def paintEvent(self, event):
        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.fillRect(self.rect(), QColor("#091220"))
            joystick = self.data.get("joystick")
            if joystick:
                self._arena(painter, joystick)
                return
            midpoint = QPointF(self.width() / 2, self.height() / 2)
            painter.setPen(QPen(QColor("#34506a"), 1))
            painter.drawLine(QPointF(midpoint.x(), 10), QPointF(midpoint.x(), self.height() - 10))
            painter.drawLine(QPointF(10, midpoint.y()), QPointF(self.width() - 10, midpoint.y()))
            trial = self.data.get("diagnostic") or {}
            target = TARGETS.get(trial.get("target"))
            if target is not None:
                painter.setPen(QPen(QColor("#ffd477"), 2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(QPointF(target[0] * self.width(), target[1] * self.height()), 10, 10)
            for point, color in zip(self.data.get("eyes") or (), ("#6df4e0", "#dcadff")):
                if point is not None:
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor(color))
                    painter.drawEllipse(QPointF(point[0] * self.width(), point[1] * self.height()), 7, 7)

    def _arena(self, painter, data):
        point = lambda pair: QPointF(8 + pair[0] * (self.width() - 16) / WIDTH,
                                     8 + pair[1] * (self.height() - 16) / HEIGHT)
        painter.setPen(QPen(QColor("#3a637e"), 1))
        painter.drawPolyline(QPolygonF([point(pair) for pair in data["path"]]))
        if data["target"]:
            x, y, radius = data["target"]
            painter.setBrush(QColor("#3c3420"))
            painter.setPen(QPen(QColor("#ffd477"), 2))
            painter.drawEllipse(point((x, y)), radius * (self.width() - 16) / WIDTH,
                                radius * (self.height() - 16) / HEIGHT)
        painter.setPen(QPen(QColor("#091220"), 1))
        painter.setBrush(QColor("#6df4e0"))
        painter.drawEllipse(point(data["joystick"]["position"]), 7, 7)


class OcularLabDialog(QDialog):
    command = Signal(str, object)
    closed = Signal()

    def __init__(self, parent, export_dir):
        super().__init__(parent)
        try:
            raw = json.loads((Path(export_dir) / "options.json").read_text(encoding="utf-8"))
            options = JoystickOptions(**raw)
        except (OSError, TypeError, ValueError):
            options = JoystickOptions()
        self._last_start = None
        self._closing = False
        self._key_direction = None
        self._input_mode = options.selection
        self._busy = False
        self._last_state = "idle"
        self.setWindowTitle("Laboratorio ocular")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        bounds = self.screen().availableGeometry()
        self.resize(min(980, bounds.width() - 24), min(750, bounds.height() - 56))
        self.thread = QThread(self)
        self.worker = LabWorker(Path(export_dir))
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.prepare)
        self.command.connect(self.worker.command, Qt.ConnectionType.QueuedConnection)
        self.worker.snapshot.connect(self.present)
        self.worker.finished.connect(self.thread.quit, Qt.ConnectionType.DirectConnection)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self._closed)

        layout = QVBoxLayout(self)
        title = QLabel("Modo simulación — sin webcam")
        title.setObjectName("BigInstruction")
        title.setWordWrap(True)
        layout.addWidget(title)
        self.scroll = scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        self.body = body = QBoxLayout(QBoxLayout.Direction.LeftToRight, content)
        body.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(content)
        self.live_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self.live_layout.addWidget(scroll, 1)
        layout.addLayout(self.live_layout, 1)
        self.settings_panel = QWidget()
        config = QFormLayout(self.settings_panel)
        config.setContentsMargins(0, 0, 0, 0)
        body.addWidget(self.settings_panel)
        self.scenario = QComboBox()
        for name, (label, _) in SCENARIOS.items():
            self.scenario.addItem(label, name)
        config.addRow("Escenario", self.scenario)
        self.seed = QSpinBox()
        self.seed.setRange(0, 2_147_483_647)
        self.seed.setValue(42)
        config.addRow("Semilla", self.seed)
        self.noise = self._number(0., .35, .005, 3)
        self.horizontal = self._number(0., .45, .01, 3)
        self.vertical = self._number(0., .45, .01, 3)
        for name, widget in (("Ruido", self.noise), ("Amplitud horizontal", self.horizontal),
                             ("Amplitud vertical", self.vertical)):
            config.addRow(name, widget)
        self.scenario.currentIndexChanged.connect(self._scenario)
        self._scenario()
        self.mode = QComboBox()
        self.mode.addItem("Por pasos", "step")
        self.mode.addItem("Continuo", "continuous")
        self.mode.setCurrentIndex(self.mode.findData(options.mode))
        config.addRow("Movimiento", self.mode)
        self.selection = QComboBox()
        self.selection.addItem("Dirección ocular", "ocular")
        self.selection.addItem("Flechas manuales", "manual")
        self.selection.setCurrentIndex(self.selection.findData(options.selection))
        config.addRow("Método de selección", self.selection)
        self.task_set = QComboBox()
        self.task_set.addItem("Recorrido clásico", "classic")
        self.task_set.addItem("Tareas de precisión", "precision")
        self.task_set.setCurrentIndex(self.task_set.findData(options.task_set))
        config.addRow("Área virtual", self.task_set)
        self.fine_mode = QCheckBox("Ajuste fino cerca del objetivo")
        self.fine_mode.setChecked(options.fine)
        config.addRow(self.fine_mode)
        self.step_repeat = QCheckBox("Repetir pasos al mantener")
        self.step_repeat.setChecked(options.step_repeat)
        config.addRow(self.step_repeat)
        self.policy = QComboBox()
        self.policy.addItem("Mantener con límite", "hold")
        self.policy.addItem("Pulso breve", "pulse")
        self.policy.setCurrentIndex(self.policy.findData(options.continuous_policy))
        config.addRow("Continuo", self.policy)
        self.pulse = self._number(.18, 1., .05, 2)
        self.pulse.setValue(options.pulse_seconds)
        self.pulse.setSuffix(" s")
        config.addRow("Duración del pulso", self.pulse)
        self.max_duration = self._number(.25, 5., .25, 2)
        self.max_duration.setValue(options.max_duration)
        self.max_duration.setSuffix(" s")
        config.addRow("Límite de movimiento", self.max_duration)
        self.algorithm = QComboBox()
        for name, caption in METHODS.items():
            self.algorithm.addItem(caption, name)
        self.algorithm.setCurrentIndex(self.algorithm.findData(options.algorithm))
        config.addRow("Algoritmo", self.algorithm)
        self.channel = QComboBox()
        for name in RAW_CHANNELS:
            reference, eyes = name.split("_")
            self.channel.addItem(("Párpados" if reference == "eyelids" else "Comisuras") + " · " + EYES[eyes], name)
        self.channel.setCurrentIndex(self.channel.findData(options.channel))
        config.addRow("Señal ocular", self.channel)
        self.window_seconds = QComboBox()
        for seconds in WINDOWS:
            self.window_seconds.addItem(f"{seconds*1000:.0f} ms", seconds)
        self.window_seconds.setCurrentIndex(self.window_seconds.findData(options.window))
        config.addRow("Ventana causal", self.window_seconds)
        self.confidence = self._number(.20, .95, .03, 2)
        self.confidence.setValue(options.confidence)
        config.addRow("Confianza mínima", self.confidence)
        self.pixels = QComboBox()
        for distance in STEPS:
            self.pixels.addItem(f"{distance} px", distance)
        self.pixels.setCurrentIndex(self.pixels.findData(options.pixels))
        config.addRow("Distancia por paso", self.pixels)
        self.dwell = self._number(.12, 1.5, .05, 2)
        self.dwell.setValue(options.dwell)
        self.dwell.setSuffix(" s")
        config.addRow("Permanencia", self.dwell)
        self.speed = self._number(40., 300., 5., 0)
        self.speed.setValue(options.max_speed)
        self.speed.setSuffix(" px/s")
        config.addRow("Velocidad máxima", self.speed)
        self.initial_speed = self._number(5., 100., 5., 0)
        self.initial_speed.setValue(options.initial_speed)
        self.initial_speed.setSuffix(" px/s")
        config.addRow("Velocidad inicial", self.initial_speed)
        self.acceleration = self._number(5., 400., 5., 0)
        self.acceleration.setValue(options.acceleration)
        self.acceleration.setSuffix(" px/s²")
        config.addRow("Aceleración", self.acceleration)
        self.initial_speed.valueChanged.connect(lambda value: self.speed.setMinimum(max(40., value)))
        self.speed.valueChanged.connect(lambda value: self.initial_speed.setMaximum(min(100., value)))
        self.initial_speed.setMaximum(min(100., self.speed.value()))
        self.anchor = QComboBox()
        for key, label in POSITIONS.items():
            self.anchor.addItem(label, key)
        self.anchor.setCurrentIndex(self.anchor.findData(options.position))
        self.anchor.currentIndexChanged.connect(self._place)
        config.addRow("Ubicar panel", self.anchor)
        self.automatic = QCheckBox("Recorrido automático")
        self.automatic.setChecked(True)
        self.automatic.toggled.connect(lambda checked: self.command.emit(
            "auto" if checked else "intent", None if checked else "center"))
        self.inputs = (self.scenario, self.seed, self.noise, self.horizontal, self.vertical, self.mode,
                       self.pixels, self.dwell, self.speed, self.anchor, self.algorithm, self.channel,
                       self.window_seconds, self.confidence, self.selection, self.task_set, self.fine_mode,
                       self.step_repeat, self.policy, self.pulse, self.max_duration, self.initial_speed,
                       self.acceleration)

        center = QVBoxLayout()
        body.addLayout(center, 1)
        self.canvas = LabCanvas()
        self.canvas.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        center.addWidget(self.canvas, 1)
        self.status = QLabel("Iniciá el diagnóstico o el recorrido del joystick.")
        self.status.setWordWrap(True)
        self.progress = QProgressBar()
        self.progress.setAccessibleName("Progreso de la sesión sintética")
        center.addWidget(self.progress)
        center.addWidget(self.automatic)
        self.confirm = QPushButton("Confirmar objetivo virtual")
        self.confirm.clicked.connect(lambda: self.command.emit("confirm", None))
        self.confirm.hide()
        center.addWidget(self.confirm)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.summary.hide()
        center.addWidget(self.summary)
        self.cross = QWidget()
        grid = QGridLayout(self.cross)
        grid.setSpacing(8)
        self.directions = {}
        for name, row, column in (("up", 0, 1), ("left", 1, 0), ("center", 1, 1),
                                   ("right", 1, 2), ("down", 2, 1)):
            label = "Detener" if name == "center" else LABELS[name]
            arrow = QPushButton(f"{ARROWS[name]}\n{label}")
            arrow.setAccessibleName(label)
            arrow.setMinimumSize(83, 62)
            arrow.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            arrow.pressed.connect(lambda name=name: self._press(name))
            arrow.released.connect(lambda: self.command.emit("release", None))
            grid.addWidget(arrow, row, column)
            self.directions[name] = arrow
        self.live_layout.addWidget(self.cross, 0, Qt.AlignmentFlag.AlignVCenter)
        self.cross.hide()
        layout.addWidget(self.status)

        actions = QGridLayout()
        layout.addLayout(actions)
        self.diagnose = QPushButton("Iniciar diagnóstico")
        self.practice = QPushButton("Probar joystick")
        self.pause = QPushButton("Pausar")
        self.stop = QPushButton("Detener sesión")
        self.restart = QPushButton("Reiniciar")
        self.export = QPushButton("Exportar JSON")
        self.compare = QPushButton("Comparar algoritmos")
        self.replay = QPushButton("Reproducir registro")
        buttons = ((self.diagnose, lambda: self.start("diagnostic")),
                   (self.practice, lambda: self.start("joystick")),
                   (self.pause, lambda: self.command.emit("pause", None)),
                   (self.stop, lambda: self.command.emit("stop", None)),
                   (self.restart, self._restart),
                   (self.export, lambda: self.command.emit("export", None)),
                   (self.compare, lambda: self.start("comparison")),
                   (self.replay, self.open_replay))
        for widget, callback in buttons:
            widget.clicked.connect(callback)
        for index, widget in enumerate((self.diagnose, self.practice, self.compare, self.replay, self.export)):
            actions.addWidget(widget, index // 3, index % 3)
        for index, widget in enumerate((self.pause, self.stop, self.restart)):
            actions.addWidget(widget, 2, index)
        self.note = QLabel()
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        for button in (self.pause, self.stop, self.restart, self.export):
            button.setEnabled(False)
        application = QApplication.instance()
        application.aboutToQuit.connect(self.finish_shutdown)
        application.installEventFilter(self)
        self.thread.start()
        QTimer.singleShot(0, self._place)

    def resizeEvent(self, event):
        if hasattr(self, "settings_panel") and hasattr(self, "live_layout"):
            direction = QBoxLayout.Direction.LeftToRight if event.size().width() >= 800 else QBoxLayout.Direction.TopToBottom
            if self.body.direction() != direction:
                self.body.setDirection(direction)
            self.settings_panel.setVisible(not self._busy)
            direction = QBoxLayout.Direction.LeftToRight if event.size().width() >= 590 else QBoxLayout.Direction.TopToBottom
            if self.live_layout.direction() != direction:
                self.live_layout.setDirection(direction)
        super().resizeEvent(event)

    def _number(self, low, high, step, decimals):
        widget = QDoubleSpinBox()
        widget.setDecimals(decimals)
        widget.setRange(low, high)
        widget.setSingleStep(step)
        return widget

    def _scenario(self):
        config = SCENARIOS[self.scenario.currentData()][1]
        self.noise.setValue(config.noise)
        self.horizontal.setValue(config.horizontal)
        self.vertical.setValue(config.vertical)

    def _place(self):
        bounds = self.screen().availableGeometry()
        anchor = self.anchor.currentData()
        x = bounds.left() if anchor.endswith("left") else bounds.right() - self.width() + 1
        y = bounds.top() if anchor.startswith("top") else bounds.bottom() - self.height() + 1
        if anchor == "center":
            x = bounds.center().x() - self.width() // 2
            y = bounds.center().y() - self.height() // 2
        self.move(max(bounds.left(), x), max(bounds.top(), y))

    def _options(self):
        return JoystickOptions(mode=self.mode.currentData(), pixels=self.pixels.currentData(),
                                  dwell=self.dwell.value(), max_speed=self.speed.value(),
                                  position=self.anchor.currentData(), algorithm=self.algorithm.currentData(),
                                  window=self.window_seconds.currentData(), channel=self.channel.currentData(),
                                  confidence=self.confidence.value(), selection=self.selection.currentData(),
                                  task_set=self.task_set.currentData(), fine=self.fine_mode.isChecked(),
                                  step_repeat=self.step_repeat.isChecked(), continuous_policy=self.policy.currentData(),
                                  pulse_seconds=self.pulse.value(), max_duration=self.max_duration.value(),
                                  initial_speed=self.initial_speed.value(), acceleration=self.acceleration.value())

    def start(self, kind):
        scenario = self.scenario.currentData()
        config = replace(SCENARIOS[scenario][1], noise=self.noise.value(), horizontal=self.horizontal.value(),
                         vertical=self.vertical.value())
        options = self._options()
        self._input_mode = options.selection
        self.canvas.setFocus()
        self._last_start = (kind, scenario, self.seed.value(), config, options, self.automatic.isChecked())
        self._restart()

    def open_replay(self):
        path, _ = QFileDialog.getOpenFileName(self, "Abrir diagnóstico ocular", "", "Registros JSON (*.json)")
        if path:
            self._last_start = ("replay", "", 0, Path(path), self._options(), False)
            self._restart()

    def _press(self, name):
        self.automatic.setChecked(False)
        self._input_mode = "manual"
        self.command.emit("press", name)

    def _restart(self):
        if self._last_start:
            self.command.emit("start", self._last_start)

    @Slot(object)
    def present(self, data):
        state = data["state"]
        completed = state == "complete" and self._last_state != state
        self._last_state = state
        joystick, diagnostic, comparison = data["joystick"], data["diagnostic"], data.get("comparison")
        replay = data.get("replay")
        busy = state in ("running", "paused")
        if self._busy != busy:
            self._busy = busy
            self.settings_panel.setVisible(not busy)
        for control in self.inputs:
            control.setEnabled(not busy)
        self.diagnose.setEnabled(not busy)
        self.practice.setEnabled(not busy)
        self.compare.setEnabled(not busy)
        self.replay.setEnabled(not busy)
        for button in (self.diagnose, self.practice, self.compare, self.replay, self.export):
            button.setVisible(not busy)
        self.pause.setVisible(busy)
        self.stop.setVisible(busy)
        self.pause.setEnabled(busy)
        self.pause.setText("Reanudar" if state == "paused" else "Pausar")
        self.stop.setEnabled(busy)
        self.restart.setEnabled(self._last_start is not None)
        self.export.setEnabled(state == "complete" or (state == "stopped" and joystick is not None))
        self.automatic.setVisible(diagnostic is None and comparison is None and replay is None)
        self.automatic.setEnabled(not joystick or joystick["selection"] == "ocular" or joystick["can_auto"])
        self.confirm.setVisible(bool(joystick and joystick["task_set"] == "precision"))
        self.confirm.setEnabled(bool(joystick and state == "running" and joystick["ready_to_confirm"]))
        self.cross.setVisible(joystick is not None)
        self.cross.setEnabled(state == "running" and (not joystick or joystick["training"] is None))
        self.canvas.data = data
        self.canvas.update()
        self.note.setText(data["message"])
        self.summary.hide()
        if joystick:
            self._input_mode = joystick["selection"]
            self._present_joystick(joystick)
        elif diagnostic:
            self._present_diagnostic(diagnostic, data["eyes"])
        elif comparison:
            self._present_comparison(comparison)
        elif replay:
            self._present_replay(replay)
        if state == "paused":
            self.status.setText("En pausa · cursor virtual detenido")
        elif state == "stopped":
            self.status.setText("Sesión detenida")
        if completed and self.summary.isVisible():
            QTimer.singleShot(0, self._reveal_summary)

    def _reveal_summary(self):
        self.scroll.ensureWidgetVisible(self.summary)

    def _present_comparison(self, comparison):
        self.progress.setRange(0, 100)
        self.progress.setValue(round(comparison["progress"] * 100))
        self.progress.setFormat("%p %")
        self.status.setText("Comparación sintética con la misma semilla y los mismos objetivos.")
        result = comparison["result"]
        if result is None:
            return
        rows = []
        for method, record in result["runs"].items():
            metrics = record["metrics"]
            rows.append(f"{METHODS[method]} · {metrics['targets_reached']}/{len(record['course'])} regiones · "
                        f"{metrics['elapsed_s']:.1f} s · {metrics['distance_px']:.0f} px · "
                        f"{metrics['accidental_activations']} falsas · {metrics['incorrect_activations']} incorrectas")
        delta = result["delta"]
        rows.append(f"Diferencia temporal vs. anterior · {delta['targets_reached']:+d} regiones · "
                    f"{delta['elapsed_s']:+.1f} s · {delta['stationary_percent']:+.1f} pp detenido")
        self.summary.setText("\n".join(rows))
        self.summary.show()

    def _present_replay(self, session):
        self.progress.setRange(0, 100)
        self.progress.setValue(round(session["progress"]*100))
        self.progress.setFormat("%p %")
        origin = {"synthetic": "sintético", "webcam": "webcam", "unmarked": "origen sin marca"}[session["origin"]]
        predictions = " · ".join(f"{METHODS[key]} {LABELS.get(value, 'Sin decisión')}" for key, value in session["labels"].items())
        self.status.setText(f"Reproducción offline · {origin}\nSolicitada {LABELS.get(session['requested'], '—')} · {predictions}")
        report = session["result"]
        if report:
            lines = [f"Ronda de entrenamiento {report['training_round']+1} · evaluación "
                     + ", ".join(str(index+1) for index in report["evaluation_rounds"])]
            for method, stats in report["methods"].items():
                score = stats["correct_percent"]
                accuracy = f"{score:.1f} % de aciertos" if score is not None else "Sin fijaciones evaluables"
                lines.append(f"{METHODS[method]} · {accuracy} · {stats['operations']} operaciones virtuales")
            self.summary.setText("\n".join(lines))
            self.summary.show()

    def _present_diagnostic(self, session, eyes):
        self.progress.setRange(0, session["total"])
        self.progress.setValue(session["done"])
        self.progress.setFormat("%v / %m objetivos")
        if session["report"]:
            report = session["report"]
            channel = report["channels"]["eyelids_both"]
            score = channel["accuracy_percent"]
            valid = report["valid_percent"]
            parts = [f"{valid:.0f} % de muestras válidas" if valid is not None else "Sin muestras de fijación"]
            parts.append(f"{score:.0f} % de exactitud sintética en rondas separadas"
                         if score is not None else "Rondas insuficientes para estimar exactitud")
            self.status.setText(" · ".join(parts))
            confusion = channel["confusion"]
            rows = [" / ".join(str(confusion[target][predicted]) for predicted in DIRECTIONS) for target in DIRECTIONS]
            self.summary.setText("Matriz binocular por párpados · columnas Centro, Arriba, Abajo, Izquierda, Derecha\n"
                                 + "\n".join(f"{LABELS[target]} → {row}" for target, row in zip(DIRECTIONS, rows)))
            self.summary.show()
            return
        target = LABELS.get(session["target"], "—")
        phase = "Fijación" if session["state"] == "fixation" else "Transición"
        valid = sum(point is not None for point in (eyes or ()))
        self.status.setText(f"Objetivo {target} · {phase} · {valid}/2 iris válidos\n"
                            "Izquierdo en verde y derecho en violeta.")

    def _present_joystick(self, session):
        control = session["joystick"]
        self.progress.setRange(0, session["targets"])
        self.progress.setValue(session["target_index"])
        self.progress.setFormat("%v / %m regiones")
        for name, button in self.directions.items():
            active = name == control["active"]
            selected = name == control["candidate"]
            color = "#6df4e0" if active else "#ffd477" if selected else ""
            style = f"border: 3px solid {color}; color: {color};" if color else ""
            if button.styleSheet() != style:
                button.setStyleSheet(style)
        if session["training"] is not None:
            self.status.setText(f"Preparando clasificador con otra semilla · {session['training']}/20")
            return
        if session["training_error"]:
            self.status.setText(session["training_error"] + " Podés usar los botones del panel.")
            return
        estimate = LABELS.get(session["estimate"], "Sin decisión")
        instant = LABELS.get(session["instantaneous"], "Sin señal")
        candidate = LABELS.get(control["candidate"], "—") if not control["locked"] else "—"
        confirmed = LABELS.get(control["confirmed"], "—")
        active = LABELS.get(control["active"], "Detenido") if control["state"] != "boundary" else "Límite"
        x, y = control["position"]
        dwell = "Activación manual" if session["selection"] == "manual" else f"Permanencia {control['dwell_progress']:.0%}"
        state = ("Manual" if session["selection"] == "manual" else "Pérdida de señal" if session["invalid"]
                 else "Ocular · neutral" if session["estimate"] == "center" else "Ocular")
        detail = " · Ajuste fino" if session["fine"] else ""
        if session["task_set"] == "precision" and session["target"]:
            radius = session["target"][2]
            size = "grande" if radius >= 30 else "mediano" if radius >= 15 else "pequeño"
            detail += f" · Objetivo {size}"
        if control["locked"]:
            detail += (" · Pulsá una flecha para rearmar" if session["selection"] == "manual"
                       else " · Volvé a neutral para rearmar")
        self.status.setText(f"{state}{detail}\nInstantánea {instant} · Estabilizada {estimate} · Confianza {session['confidence']:.0%}\n"
                            f"Candidata {candidate} · Confirmada {confirmed} · Activo {active}\n"
                            f"{dwell} · X {x:.0f} / Y {y:.0f} · "
                            f"{control['speed']:.0f} px/s · {control['active_seconds']:.2f} s activo\n"
                            f"{control['distance']:.0f} px recorridos · {control['stops']} detenciones · "
                            f"{control['changes']} cambios · {session['operations']} operaciones · "
                            f"{session['elapsed_s']:.1f} s simulados")
        if session["done"]:
            outcome = "Recorrido completado" if session["target_index"] == session["targets"] else "Tiempo agotado"
            self.summary.setText(f"{outcome} · {session['accidental']} activaciones en neutral · "
                                 f"{session['incorrect']} direcciones incorrectas · {session['corrections']} correcciones")
            self.summary.show()

    def changeEvent(self, event):
        if event.type() == QEvent.Type.ActivationChange and not self.isActiveWindow():
            self._key_direction = None
            self.command.emit("neutral", None)
        super().changeEvent(event)

    def eventFilter(self, watched, event):
        if (self.isVisible() and event.type() in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress)
                and event.key() in (Qt.Key.Key_F8, Qt.Key.Key_Escape)):
            event.accept()
            if event.type() == QEvent.Type.KeyPress:
                parent = self.parentWidget()
                if parent is None:
                    self.close()
                else:
                    parent.stop_immediately()
            return True
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event):
        if event.key() in KEYS and not event.isAutoRepeat():
            self._key_direction = event.key()
            self.automatic.setChecked(False)
            self.command.emit("press" if self._input_mode == "manual" else "intent", KEYS[event.key()])
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not event.isAutoRepeat():
            self.command.emit("confirm", None)
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == self._key_direction and not event.isAutoRepeat():
            self._key_direction = None
            self.command.emit("release" if self._input_mode == "manual" else "neutral", None)
        else:
            super().keyReleaseEvent(event)

    def reject(self):
        self.close()

    def _request_close(self):
        if not self._closing:
            self._closing = True
            self.command.emit("close", None)

    @Slot()
    def finish_shutdown(self):
        if self.thread.isRunning():
            self._request_close()
            self.thread.wait()

    def closeEvent(self, event):
        if self.thread.isRunning():
            event.ignore()
            self._request_close()
            return
        event.accept()

    @Slot()
    def _closed(self):
        QApplication.instance().removeEventFilter(self)
        self.close()
        self.closed.emit()
