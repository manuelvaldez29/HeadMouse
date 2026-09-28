"""Wizard genérico de repeticiones; sin Qt, webcam ni salida al sistema."""
import math
import time
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime, timezone
from adaptive_calibration import GestureCalibration, statistics
from calibration_logic import Samples
from calibration_validation import CalibrationValidation
from config import DEFAULT_THRESHOLDS
from gesture_engine import GestureEngine
from gesture_signals import GESTURE_SIGNALS

PHASES = (("neutral", "Relajá la cara y mirá al centro"),) + tuple(
    (s.phase_id,s.instruction) for s in GESTURE_SIGNALS.values())


class CalibrationSession:
    def __init__(self, profile, config, clock=time.monotonic, enabled=None, source=None):
        self.profile, self.config, self.clock = deepcopy(profile), deepcopy(config), clock
        self.source = source or config.calibration.brow_signal_source
        if self.source not in ("GEOMETRIC","BLENDSHAPE","HYBRID"):
            raise ValueError("Fuente de calibración inválida")
        previous=profile.get("gesture_calibrations",{})
        availability={key:previous.get(key,{}).get("enabled",True) for key in GESTURE_SIGNALS}
        if enabled is not None:
            if not isinstance(enabled,dict) or set(enabled)-set(GESTURE_SIGNALS) or any(type(v) is not bool for v in enabled.values()):
                raise ValueError("Disponibilidad de gestos inválida")
            availability.update(enabled)
        self.models={key:GestureCalibration(key,s.channels,s.directions,
                                           self.source if s.brow else "GEOMETRIC",availability[key])
                     for key,s in GESTURE_SIGNALS.items()}
        for model in self.models.values():
            if not model.enabled: model.disable()
        self.phase=0
        self.gesture_id=None
        self.samples=Samples()
        self.baseline=None
        self.baseline_signals={key:[] for key in GESTURE_SIGNALS}
        self.candidate=self.validator=None
        self.state="ready"
        self.stage="baseline"
        self.error=self.feedback=self.capture_message=""
        self.started=clock()
        self._window_started=None
        self._last_timestamp=0
        self._rows=[]
        self._neutral_rows=[]
        self.current_values=None
        self.telemetry=[]
        self.face=None

    def _enter(self,stage):
        self.stage=stage
        self.state="countdown" if stage=="baseline" else "settling"
        self.started=self.clock()
        self._window_started=None
        self._rows=[]
        self.error=""

    def start(self):
        self._enter("baseline" if self.baseline is None else "neutral")

    def restart(self):
        self.__init__(self.profile,self.config,self.clock,
                      {key:m.enabled for key,m in self.models.items()},self.source)
        self.start()

    def repeat(self,gesture_id=None):
        if gesture_id is None and self.validator is not None:
            self.validator.retry_current()
            self.state="validation"
            return
        key=gesture_id or self.gesture_id
        if key is not None and self.baseline is None and self.validator is not None:
            raise ValueError("Para volver a medir un perfil anterior, iniciá una nueva calibración")
        if key is None:
            self.samples=Samples()
            self.baseline_signals={key:[] for key in GESTURE_SIGNALS}
            self.start()
            return
        if key not in self.models: raise ValueError("Gesto desconocido")
        old=self.models[key]
        if not old.enabled: raise ValueError("Habilitá el gesto antes de repetirlo")
        self.models[key]=GestureCalibration(key,old.channels,old.directions,old.source,retries=old.retries+1)
        self.candidate=self.validator=None
        self._select(key)

    def set_enabled(self,gesture_id,enabled):
        if gesture_id not in self.models or type(enabled) is not bool:
            raise ValueError("Disponibilidad inválida")
        if self.baseline is None and self.validator is not None:
            raise ValueError("Para cambiar gestos de una calibración anterior, iniciá una nueva calibración")
        model=self.models[gesture_id]
        if enabled==model.enabled: return
        previous_state=self.state
        self.candidate=self.validator=None
        if enabled:
            self.models[gesture_id]=GestureCalibration(gesture_id,model.channels,model.directions,model.source)
            if self.baseline is not None: self._select(gesture_id)
        else:
            model.disable()
            if self.baseline is not None and (self.gesture_id==gesture_id or previous_state in ("measured","validated","validation")):
                self._advance()

    def _select(self,key):
        self.gesture_id=key
        self.phase=list(GESTURE_SIGNALS).index(key)+1
        self._neutral_rows=[]
        self.current_values=None
        self._enter("neutral")

    def _advance(self):
        for key,model in self.models.items():
            if model.enabled and (not model.usable or len(model.active_samples)<self.config.calibration.repetitions):
                self._select(key)
                return
        self.candidate=self._build_profile()
        self.state="measured"
        self.feedback="Mediciones completas. Iniciá la validación."

    def _build_profile(self):
        settings=asdict(self.config)
        settings["calibration"]["brow_signal_source"]=self.source
        thresholds=DEFAULT_THRESHOLDS.copy()
        for key,model in self.models.items():
            spec=GESTURE_SIGNALS[key]
            if not model.enabled:
                settings["actions"]["bindings"][key]="NONE"
                # Neutral observado también permite suprimir parpadeos bilaterales
                # cuando solo uno de los guiños puede calibrarse.
                rows=self.baseline_signals[key]
                if rows:
                    model.neutral_statistics={channel:statistics([row[i] for row in rows])
                                              for i,channel in enumerate(model.channels)}
            elif model.source=="GEOMETRIC" and len(spec.channels)==1:
                thresholds[spec.legacy_keys[0]]=model.activation_threshold[spec.channels[0]]
        return dict(user_id=self.profile["user_id"],display_name=self.profile.get("display_name",self.profile["user_id"]),
                    calibrated_at=datetime.now(timezone.utc).isoformat(),calibration_version="0.3.1",
                    status="calibrated",settings=settings,thresholds=thresholds,
                    neutral_nose_x=self.baseline.median("nose_x"),neutral_nose_y=self.baseline.median("nose_y"),
                    gesture_calibrations={key:model.to_record() for key,model in self.models.items()},
                    validation={"passed":False},calibration_telemetry=deepcopy(self.telemetry))

    def validate(self):
        if self.candidate is None: raise ValueError("Primero completá las mediciones")
        gesture=GestureEngine(None,config=self.config.gesture,calibration=self.candidate,clock=self.clock)
        cc=self.config.calibration
        self.validator=CalibrationValidation(gesture,cc.validation_timeout_s,self.clock,cc.validation_neutral_s,
                                              cc.validation_noise_s,cc.validation_wrong_s)
        self.state="validation"
        self.error=""

    def _neutral_ok(self,values):
        reference=self.baseline_signals[self.gesture_id]
        if not reference: return False
        model=self.models[self.gesture_id]
        for index,direction in enumerate(model.directions):
            stats=statistics([row[index] for row in reference])
            tolerance=max(3*self.config.calibration.min_separation,
                          self.config.calibration.noise_multiplier*1.4826*stats["mad"],.1*abs(stats["median"]))
            if direction*(values[index]-stats["median"])>tolerance: return False
        return True

    def update(self,face):
        self.face=face
        now,cc=self.clock(),self.config.calibration
        if self.state=="validation":
            self.validator.update(face)
            if self.validator.passed: self.state="validated"
            return
        if self.state not in ("countdown","settling","measuring"): return
        fresh=face.fresh(self.config.gesture.stale_after_s,now)
        spec=GESTURE_SIGNALS.get(self.gesture_id)
        values=spec.extract(face,self.models[self.gesture_id].source) if fresh and spec else None
        self.current_values=values
        delay=cc.countdown_s if self.stage=="baseline" else cc.transition_s
        if self.state in ("countdown","settling"):
            if now-self.started>=delay:
                self.state="measuring"
                self.started=now
            return
        if now-self.started>cc.validation_timeout_s:
            self.state,self.error="error","No pudimos capturar una ventana estable. Repetí este gesto."
            return
        usable=fresh and (self.stage=="baseline" or values is not None)
        if usable and self.stage=="neutral": usable=self._neutral_ok(values)
        if not usable:
            self._reset_window()
            self.feedback="Volvé a posición neutral" if fresh and values is not None else "Esperando rostro y señal válidos"
            return
        if face.timestamp_ms<=self._last_timestamp: return
        if self._last_timestamp and face.timestamp_ms-self._last_timestamp>self.config.gesture.stale_after_s*1000:
            self._reset_window()
        self._last_timestamp=face.timestamp_ms
        if self._window_started is None: self._window_started=now
        if self.stage=="baseline":
            self.samples.add(face,self.config.gesture.stale_after_s,now)
            for key,adapter in GESTURE_SIGNALS.items():
                row=adapter.extract(face,self.models[key].source)
                if row is not None: self.baseline_signals[key].append(row)
            count=len(self.samples.nose_x)
        else:
            self._rows.append(values)
            count=len(self._rows)
        self.feedback="Capturando posición neutral" if self.stage!="active" else "Capturando gesto cómodo"
        duration=cc.measuring_s if self.stage=="baseline" else cc.neutral_window_s if self.stage=="neutral" else cc.active_window_s
        minimum=cc.min_samples if self.stage=="baseline" else cc.min_window_samples
        if now-self._window_started<duration: return
        if count<minimum:
            self.state,self.error="error","Muestras insuficientes. Repetí este gesto."
            return
        if self.stage=="baseline":
            self.baseline=self.samples
            self._advance()
        elif self.stage=="neutral":
            self._neutral_rows=self._rows.copy()
            self._enter("active")
        else:
            model=self.models[self.gesture_id]
            model.add_repetition(self._neutral_rows,self._rows)
            attempt=len(model.active_samples)
            # Estimación provisional para el medidor; no habilita guardar ni omite repeticiones.
            model.fit(replace(cc,repetitions=attempt))
            self.capture_message=f"{GESTURE_SIGNALS[self.gesture_id].label}: intento {attempt}/{cc.repetitions} capturado ✓"
            if attempt<cc.repetitions:
                self._enter("neutral")
            else:
                model.fit(cc)
                self.telemetry.append(model.to_record())
                if not model.usable:
                    self.state="error"
                    self.error="Señal demasiado inestable o débil. Repetí solamente este gesto, o marcalo no disponible."
                else:
                    self.feedback="Buena separación" if model.quality_label=="BUENA" else "Separación aceptable"
                    self._advance()

    def _reset_window(self):
        self._rows=[]
        self._window_started=None
        if self.stage=="baseline":
            self.samples=Samples()
            self.baseline_signals={key:[] for key in GESTURE_SIGNALS}

    def result(self):
        if self.state!="validated" or not self.validator or not self.validator.passed:
            raise ValueError("Completá la validación antes de guardar")
        result=deepcopy(self.candidate)
        result["validation"]=dict(passed=True,recognized=self.validator.recognized.copy(),
                                  validated_at=datetime.now(timezone.utc).isoformat())
        for record in result.get("gesture_calibrations",{}).values():
            record["validation_state"]="passed" if record["enabled"] else "disabled"
        return result

    def snapshot(self):
        cc=self.config.calibration
        model=self.models.get(self.gesture_id)
        if self.validator:
            instruction="Validación completa. Guardá tu perfil." if self.validator.passed else self.validator.instruction
        elif self.state=="measured": instruction="Mediciones completas. Validá los gestos disponibles."
        elif self.stage in ("baseline","neutral"): instruction="Relajá la cara y volvé a posición neutral"
        else: instruction=GESTURE_SIGNALS[self.gesture_id].instruction
        duration=cc.measuring_s if self.stage=="baseline" else cc.neutral_window_s if self.stage=="neutral" else cc.active_window_s
        elapsed=0 if self._window_started is None else self.clock()-self._window_started
        return dict(state=self.state,stage=self.stage,phase=self.phase+1,total_phases=len(PHASES),
                    gesture_id=self._meter_key(),instruction=instruction,
                    countdown=max(0,math.ceil((cc.countdown_s if self.stage=="baseline" else cc.transition_s)-(self.clock()-self.started))),
                    progress=min(1,elapsed/duration) if self.state=="measuring" else 0,
                    samples=len(self.samples.nose_x) if self.stage=="baseline" else len(self._rows),
                    attempt=min(cc.repetitions,(len(model.active_samples)+1)) if model else 0,repetitions=cc.repetitions,
                    feedback=self._live_feedback(),capture_message=self.capture_message,
                    recognized=self.validator.recognized.copy() if self.validator else [],
                    enabled={key:m.enabled for key,m in self.models.items()},
                    quality={key:dict(label=(self.candidate["gesture_calibrations"][key]["quality_label"]
                                            if self.validator and self.candidate.get("gesture_calibrations") else
                                            "NO DISPONIBLE" if not m.enabled else "PENDIENTE" if not m.active_samples else
                                            m.quality_label+(" (provisional)" if len(m.active_samples)<cc.repetitions else "")),
                                      score=m.quality_score,retries=m.retries) for key,m in self.models.items()},
                    meter=self._meter(),error=self.error or (self.validator.error if self.validator else "") or "",
                    can_save=self.state=="validated")

    def _live_feedback(self):
        if self.state=="error": return self.error
        if self.state=="validated": return "Validación completa"
        if self.validator and self.validator.neutral: return "Volvé a posición neutral"
        if (self.stage=="active" and self.state=="measuring") or self.state=="validation":
            meter=self._meter()
            if meter and all(row["value"] is not None and row["activation"] is not None for row in meter):
                if all(row["direction"]*(row["value"]-row["activation"])>=0 for row in meter):
                    return "Gesto detectado: sostenelo cómodamente"
                return "Todavía falta un poco de gesto; sin forzar"
        return self.feedback

    def _meter_key(self):
        key=self.gesture_id
        if self.validator and self.validator.index<len(self.validator.gestures):
            event=self.validator.gestures[self.validator.index][0]
            key=next(k for k,s in GESTURE_SIGNALS.items() if s.event_type==event)
        return key

    def _meter(self):
        key=self._meter_key()
        if not key: return []
        model=self.models[key]
        record=self.candidate.get("gesture_calibrations",{}).get(key,{}) if self.validator and self.candidate else model.to_record()
        rows=self.baseline_signals[key]
        source=record.get("source",model.source)
        values=GESTURE_SIGNALS[key].extract(self.face,source) if self.face and self.face.fresh(self.config.gesture.stale_after_s,self.clock()) else None
        result=[]
        for index,channel in enumerate(model.channels):
            neutral=record.get("neutral_statistics",{}).get(channel,{}).get("median")
            if neutral is None and rows: neutral=statistics([row[index] for row in rows])["median"]
            active=record.get("active_statistics",{}).get(channel,{}).get("p90" if model.directions[index]>0 else "p10")
            result.append(dict(channel=channel,value=values[index] if values else None,
                               neutral=neutral,comfortable=active,activation=record.get("activation_threshold",{}).get(channel),
                               release=record.get("release_threshold",{}).get(channel),direction=model.directions[index]))
        return result
