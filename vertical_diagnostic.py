"""Centro/arriba/abajo: medir referencias reales, sin backend del sistema."""
import math
import time
from copy import deepcopy
import numpy as np
from gaze_source import gaze_position,selected_eyes_open


class MemoryMouse:
    """Únicamente registra deltas; no dispone de ninguna API del sistema."""
    PAUSE=0
    FAILSAFE=True
    last_move=(0,0)
    def __init__(self,width=1920,height=1080):
        self.dimensions=(width,height);self.cursor=(width//2,height//2)
    def size(self):return self.dimensions
    def position(self):return self.cursor
    def moveRel(self,x,y,**kw):
        self.last_move=(x,y);self.cursor=(self.cursor[0]+x,self.cursor[1]+y)
    def moveTo(self,x,y,**kw):
        self.last_move=(x-self.cursor[0],y-self.cursor[1]);self.cursor=(x,y)
    def __getattr__(self,name):raise AssertionError("Acción prohibida en diagnóstico: "+name)


class DiagnosticMovementTrace:
    def __init__(self,profile,cfg,clock=time.monotonic):
        from types import SimpleNamespace
        from ocular_profiles import calibration_for
        from profiles import gesture_profile
        from gesture_engine import GestureEngine
        from tracking import create_strategy
        from control_engine import ControlEngine
        from config import DEFAULT_THRESHOLDS,method_bank
        self.method='eye_absolute' if cfg.ui.tracking_method=='eye_absolute' else 'eye'
        record=calibration_for(profile,self.method,cfg.ui.eye_source)
        context=(record or {}).get('context',{})
        self.saved_context=deepcopy(context or (record or {}).get('camera_context'))
        self.mouse=MemoryMouse(context.get('width',1920),context.get('height',1080))
        self.face=None;self.control=None;self.last={}
        if record:
            runtime=gesture_profile(profile,method_bank(cfg))
            if runtime.get('status')=='draft':runtime=dict(thresholds=DEFAULT_THRESHOLDS.copy())
            self.gesture=GestureEngine(None,calibration=runtime,config=cfg.gesture,movement_only=True,clock=clock,
                strategy=create_strategy(self.method,record,cfg.absolute if self.method=='eye_absolute' else cfg.eye,cfg.ui.eye_source))
            view=SimpleNamespace(get_face_data=lambda:self.face,get_fps=lambda:0)
            self.control=ControlEngine(view,self.gesture,cfg.control,backend=self.mouse,movement_only=True)
            self.control.toggle_pause()

    def feed(self,face):
        self.face=face;self.mouse.last_move=(0,0)
        if not self.control:
            self.last=dict(method=self.method,block_reason="No hay modelo de movimiento compatible; no se cambia de respuesta automáticamente")
            return self.last
        before=self.mouse.position()
        self.control._tick()
        d=self.gesture.tracking_diagnostic()
        position=self.gesture.strategy.position(face)
        self.last=dict(method=self.method,filtered_y=d.get('delta_y'),normalized_y=position[1] if position else None,
            computed_dy=d.get('cursor_delta',(0,0))[1],would_send_dy=self.mouse.last_move[1],
            computed_dx=d.get('cursor_delta',(0,0))[0],would_send_dx=self.mouse.last_move[0],
            head_pitch=face.head_pitch,head_yaw=face.head_yaw,block_reason=d.get('block_reason'))
        if self.method=='eye_absolute':
            prediction=d.get('prediction')
            self.last.update(filtered_y=prediction[1] if prediction else None,
                computed_dy=prediction[1]*(self.mouse.size()[1]-1)-before[1] if prediction else 0,
                computed_dx=prediction[0]*(self.mouse.size()[0]-1)-before[0] if prediction else 0)
        return self.last


class VerticalDiagnosticSession:
    targets=((.5,.5),(.5,.1),(.5,.9))
    names=("centro","arriba","abajo")
    def __init__(self,source="both",clock=time.monotonic,limits=(.045,.045),settle_s=2.5,duration_s=2.,min_samples=20):
        self.source,self.clock,self.limits=source,clock,limits
        self.settle_s,self.duration_s,self.min_samples=settle_s,duration_s,min_samples
        self.index,self.state,self.points=0,"settling",{}
        self.rows=[]
        self.last_timestamp=0
        self.started=clock()
        self.message="Mirá al centro. Diagnóstico sin movimiento real del mouse."
        self.head_stable=None
        self.trace_method=None
        self.trace_context={}

    def repeat(self,index):
        if type(index) is not int or not 0<=index<3:raise ValueError("Objetivo inválido")
        self.index,self.state=index,"settling"
        self.points.pop(index,None)
        self.rows=[]
        self.last_timestamp=0
        self.started=self.clock()

    def update(self,face,tracking=None):
        if self.state in ("ready","error"):return
        elapsed=self.clock()-self.started
        if elapsed>25:
            self.state="error"
            self.message="Tiempo agotado: "+self.message+". Repetí este objetivo."
            return
        if elapsed<self.settle_s:return
        self.state="capturing"
        if not face.fresh(.25,self.clock()):
            self.rows.clear();self.message="Esperando rostro y frames recientes";return
        if face.timestamp_ms<=self.last_timestamp:return
        self.last_timestamp=face.timestamp_ms
        if gaze_position(face,self.source) is None or not selected_eyes_open(face,self.source,self.limits):
            self.rows.clear();self.message="Esperando iris seleccionado y ojos abiertos";return
        values={}
        for source in ("left","right","both"):
            for reference in ("eyelids","canthi"):
                p=gaze_position(face,source,reference)
                if p is not None:values[source+"_"+reference]=p[1]
        for row in face.ocular_geometry:
            for key,value in zip(("iris_x_px","iris_y_px","top_x_px","top_y_px","bottom_x_px","bottom_y_px",
                                  "canthus1_x_px","canthus1_y_px","canthus2_x_px","canthus2_y_px","eye_width_px","det","eyelids_y","canthi_y"),row[1:]):
                if value is not None:values[row[0]+"_"+key]=float(value)
        values.update(nose_x=face.nose_x,nose_y=face.nose_y,face_scale=face.face_scale,
                      processing_ms=face.processing_ms,frame_age_ms=(self.clock()-face.timestamp_ms/1000)*1000)
        for key,value in (tracking or {}).items():
            if isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value):values["tracking_"+key]=float(value)
        self.rows.append((face.timestamp_ms,values))
        while len(self.rows)>self.min_samples and self.rows[1][0]<face.timestamp_ms-self.duration_s*1000:self.rows.pop(0)
        self.message=f"Midiendo mirada al {self.names[self.index]}. Mantené la cabeza quieta."
        if len(self.rows)<self.min_samples or self.rows[-1][0]-self.rows[0][0]<self.duration_s*1000-1:return
        common=set.intersection(*(set(row[1]) for row in self.rows))
        median={k:float(np.median([r[1][k] for r in self.rows])) for k in common}
        spread={k:float(np.percentile([r[1][k] for r in self.rows],90)-np.percentile([r[1][k] for r in self.rows],10)) for k in common}
        if spread["nose_x"]>.03 or spread["nose_y"]>.03:
            self.head_stable=False
            self.message="La cabeza se mueve durante la medición; mantenela estable.";return
        self.head_stable=True
        signal_spread=spread.get(self.source+"_eyelids",.1)
        self.points[self.index]=dict(target=self.names[self.index],samples=len(self.rows),median=median,
            spread_p10_p90=spread,quality=max(0.,1-signal_spread/.1),unstable_signal=bool(signal_spread>.1),
            sample_duration_s=(self.rows[-1][0]-self.rows[0][0])/1000)
        missing=[i for i in range(3) if i not in self.points]
        if not missing:
            self.state="ready";self.message="Medición completa. No se guardó ninguna calibración ni se movió el mouse.";return
        self.index=missing[0];self.rows=[];self.started=self.clock();self.state="settling"
        self.message=f"Ahora mirá al objetivo de {self.names[self.index]}."

    def report(self):
        comparisons={}
        if len(self.points)==3:
            for source in ("left","right","both"):
                for reference in ("eyelids","canthi"):
                    key=source+"_"+reference
                    if all(key in p["median"] for p in self.points.values()):
                        center=self.points[0]["median"][key]
                        up=self.points[1]["median"][key]-center;down=self.points[2]["median"][key]-center
                        nc=self.points[0]["spread_p10_p90"][key]
                        nu=max(nc,self.points[1]["spread_p10_p90"][key])
                        nd=max(nc,self.points[2]["spread_p10_p90"][key])
                        comparisons[key]=dict(delta_up=up,delta_down=down,signs_match=bool(up<0<down),
                                              noise_up=nu,noise_down=nd,
                                              amplitude_over_noise_up=abs(up)/nu if nu else None,
                                              amplitude_over_noise_down=abs(down)/nd if nd else None,
                                              exceeds_three_spreads=bool(-up>3*nu and down>3*nd),
                                              relative_ranges_at_least_002=bool(-up>=.02 and down>=.02))
        return dict(state=self.state,message=self.message,source=self.source,points=deepcopy(self.points),comparison=comparisons,
                    mouse_backend="memory_only",calibration_saved=False,trace_method=self.trace_method,
                    trace_context=deepcopy(self.trace_context))

    def snapshot(self):
        return dict(state=self.state,phase="training",index=self.index,total=3,target=self.targets[self.index],
            method="vertical_diagnostic",kind="Diagnóstico vertical · sin mover el mouse",source_label=self.source,
            countdown=max(0,self.settle_s-(self.clock()-self.started)),message=self.message,samples=len(self.rows),
            rejected=0,can_save=False,points=deepcopy(self.points),head_stable=self.head_stable)


def main():
    import argparse,json
    from pathlib import Path
    from datetime import datetime,timezone
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-camera-free",action="store_true")
    args=parser.parse_args()
    if not args.confirm_camera_free:parser.error("Cerrá las otras aplicaciones de cámara y usá --confirm-camera-free")
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer
    from desktop.gaze_overlay import GazeOverlay
    from desktop.style import apply_style
    from profiles import ProfileStore,gesture_profile
    from config import load_config
    from vision_engine import VisionEngine
    app=QApplication([]);apply_style(app)
    profile={}
    last=Path('data/last_profile.json')
    if last.exists():profile=ProfileStore().load(json.loads(last.read_text(encoding='utf-8'))['user_id'])
    cfg=load_config(overrides=profile.get('settings',{}))
    thresholds=gesture_profile(profile,'eye').get('thresholds',{})
    session=VerticalDiagnosticSession(cfg.ui.eye_source,limits=(thresholds.get('blink_left',.045),thresholds.get('blink_right',.045)))
    engine=VisionEngine(config=cfg.vision)
    # Ejecutar el motor de movimiento sobre un backend exclusivamente en RAM.
    # No se importa ni se instancia PyAutoGUI en esta herramienta.
    trace=DiagnosticMovementTrace(profile,cfg)
    from dataclasses import asdict
    session.trace_method=trace.method
    session.trace_context=dict(selected_method=cfg.ui.tracking_method,eye=asdict(cfg.eye),absolute=asdict(cfg.absolute),
                               saved_context=trace.saved_context,profile_id=profile.get('user_id'))
    widget=GazeOverlay();widget.setGeometry(app.primaryScreen().geometry());widget.winId();widget.windowHandle().setScreen(app.primaryScreen())
    widget.repeat.connect(session.repeat);widget.cancel.connect(app.quit)
    widget.showFullScreen()
    report_path=Path('data/logs')/('vertical-physical-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.json')
    completed=[False];started=[False]
    def tick():
        try:
            if engine.error:raise RuntimeError(str(engine.error))
            if not engine.ready.is_set():return
            if not started[0]:engine.wait_ready(0);session.started=time.monotonic();started[0]=True
            face=engine.get_face_data()
            session.update(face,trace.feed(face))
            widget.present(session.snapshot(),None)
            from dataclasses import asdict
            from gaze_source import eye_coordinates,SOURCE_LABELS
            widget.present_camera(dict(frame=engine.get_frame(),face=face,detected=face.fresh(.25),settings=asdict(cfg),
                eye_source_label=SOURCE_LABELS[cfg.ui.eye_source],used_gaze=gaze_position(face,cfg.ui.eye_source),
                eye_availability={s:eye_coordinates(face,s) is not None for s in ("left","right")}))
            widget.save_button.hide()
            if session.state=='ready' and not completed[0]:
                completed[0]=True
                report_path.write_text(json.dumps(session.report(),indent=2),encoding='utf-8')
                print(str(report_path.resolve()),flush=True)
                print(json.dumps(session.report()['comparison']),flush=True)
                QTimer.singleShot(2000,app.quit)
        except Exception as exc:
            print('DIAGNOSTIC_ERROR',str(exc),flush=True);app.quit()
    timer=QTimer();timer.timeout.connect(tick);timer.start(33)
    engine.start()
    try:app.exec()
    finally:
        timer.stop();engine.stop()
        if not completed[0]:report_path.write_text(json.dumps(session.report(),indent=2),encoding='utf-8')
        widget.blockSignals(True);widget.close();widget.deleteLater()
    return 0 if completed[0] else 1


if __name__=='__main__':raise SystemExit(main())
