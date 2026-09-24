"""Agregados acotados por sesión. Nunca recibe ni guarda imágenes/landmarks."""
import json
import threading
import time
import uuid
from datetime import datetime, timezone
from config import ROOT


class SessionMetrics:
    def __init__(self, profile_id, directory=None, enabled=True, clock=time.monotonic):
        self.profile_id = profile_id
        self.directory = ROOT / "data" / "metrics" if directory is None else directory
        self.enabled = enabled
        self.clock = clock
        self.started = clock()
        self.started_at = datetime.now(timezone.utc).isoformat()
        self._lock = threading.Lock()
        self.frames = 0
        self.processing_sum = 0.0
        self.processing_max = 0.0
        self.latency_sum = 0.0
        self.latency_max = 0.0
        self.latency_count = 0
        self.events = {}
        self.actions = {}
        self.tracking_losses = 0
        self._tracking = False
        self._path = None

    def frame(self, face):
        if not self.enabled:
            return
        with self._lock:
            self.frames += 1
            self.processing_sum += face.processing_ms
            self.processing_max = max(self.processing_max, face.processing_ms)

    def tracking(self, detected):
        if not self.enabled:
            return
        with self._lock:
            if self._tracking and not detected:
                self.tracking_losses += 1
            self._tracking = detected

    def generated(self, events):
        if not self.enabled:
            return
        with self._lock:
            for event in events:
                self.events[event.type] = self.events.get(event.type, 0) + 1

    def action(self, event):
        if not self.enabled:
            return
        with self._lock:
            self.actions[event.type] = self.actions.get(event.type, 0) + 1
            if event.detected_at > 0:
                latency = max(0, (self.clock() - event.detected_at) * 1000)
                self.latency_sum += latency
                self.latency_max = max(self.latency_max, latency)
                self.latency_count += 1

    def snapshot(self):
        with self._lock:
            duration = max(0, self.clock() - self.started)
            return dict(schema_version=1, profile_id=self.profile_id, started_at=self.started_at,
                        duration_s=duration, frames_processed=self.frames,
                        fps_mean=self.frames / duration if duration else 0,
                        processing_ms_mean=self.processing_sum / self.frames if self.frames else 0,
                        processing_ms_max=self.processing_max,
                        detection_to_action_ms_mean=self.latency_sum / self.latency_count if self.latency_count else None,
                        detection_to_action_ms_max=self.latency_max if self.latency_count else None,
                        latency_samples=self.latency_count, events_generated=dict(self.events),
                        actions_executed=dict(self.actions), events_total=sum(self.events.values()),
                        clicks=sum(self.actions.get(k, 0) for k in ("LEFT_CLICK", "RIGHT_CLICK", "DOUBLE_CLICK")),
                        scrolls=sum(self.actions.get(k, 0) for k in ("SCROLL_UP", "SCROLL_DOWN")),
                        tracking_losses=self.tracking_losses)

    def close(self):
        if not self.enabled or self._path is not None:
            return self._path
        from pathlib import Path
        directory = Path(self.directory)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"session-{uuid.uuid4().hex}.json"
        with path.open("x", encoding="utf-8") as stream:
            json.dump(self.snapshot(), stream, indent=2, allow_nan=False)
        self._path = path
        return path
