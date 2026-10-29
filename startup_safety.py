"""Puerta de estabilidad para autoarranque; no cámara ni acciones del SO."""
from collections import deque
from gaze_source import gaze_position


class StableStartup:
    def __init__(self):self.reset()
    def reset(self):self.rows=deque(maxlen=30);self.last_timestamp=0
    def update(self,snapshot,now):
        face=snapshot.get("face")
        if (not face or not face.fresh(snapshot["settings"]["gesture"]["stale_after_s"],now) or
            not snapshot.get("camera_status",{}).get("ready") or snapshot.get("activation_blockers")):
            self.reset();return False
        if face.timestamp_ms<=self.last_timestamp:return False
        self.last_timestamp=face.timestamp_ms
        values=(face.nose_x,face.nose_y)
        if snapshot.get("public_method")=="eyes":
            d=snapshot.get("diagnostic",{}).get("tracking",{})
            gaze=gaze_position(face,snapshot["eye_source"],d.get("vertical_reference","eyelids"))
            if gaze is None:self.reset();return False
            values+=tuple(gaze)
        self.rows.append((face.timestamp_ms,*values))
        if len(self.rows)<10 or self.rows[-1][0]-self.rows[0][0]<700:return False
        return all(max(r[i] for r in self.rows)-min(r[i] for r in self.rows)<=(.025 if i<=2 else .04)
                   for i in range(1,len(self.rows[0])))
