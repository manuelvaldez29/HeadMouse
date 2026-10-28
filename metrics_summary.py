"""Resumen de sesiones para la pantalla Métricas; puro, sin Qt ni archivos.

Una sesión cuenta como "con control" si ejecutó alguna acción (incluido mover el
cursor o pausar). Las sesiones de vista previa, diagnóstico o calibración no
ejecutan acciones y no entran en las tasas por minuto, que es lo que permite
comparar sesiones de distinta duración.
"""
from datetime import datetime

MIN_DURATION_S = 30  # sesiones más cortas dan tasas por minuto inestables


def _started(row):
    try:
        moment = datetime.fromisoformat(str(row.get("started_at")))
    except (TypeError, ValueError):
        return None
    return moment.astimezone() if moment.tzinfo else moment


def control_sessions(history, profile_id=None, min_duration_s=MIN_DURATION_S):
    """Sesiones con control, en orden cronológico, con sus tasas por minuto."""
    result = []
    for row in history:
        if profile_id and row.get("profile_id") != profile_id:
            continue
        actions = row.get("actions_executed") or {}
        duration = row.get("duration_s") or 0
        started = _started(row)
        if not actions or duration < min_duration_s or started is None:
            continue
        minutes = duration / 60
        dictations = row.get("dictations") or {}
        result.append(dict(
            started=started, minutes=minutes,
            clicks=row.get("clicks", 0) or 0, scrolls=row.get("scrolls", 0) or 0,
            pauses=actions.get("PAUSE", 0), losses=row.get("tracking_losses", 0) or 0,
            dictations=dictations.get("typed", 0) + dictations.get("command", 0),
            fps=row.get("fps_mean") or 0, latency_ms=row.get("processing_ms_mean") or 0))
    for session in result:
        for key in ("clicks", "scrolls", "pauses", "losses"):
            session[key + "_per_min"] = session[key] / session["minutes"]
    return sorted(result, key=lambda s: s["started"])


def totals(sessions):
    """Tasas agregadas ponderadas por duración (total de eventos / total de minutos)."""
    minutes = sum(s["minutes"] for s in sessions)
    rate = lambda key: sum(s[key] for s in sessions) / minutes if minutes else None
    return dict(sessions=len(sessions), minutes=minutes, clicks_per_min=rate("clicks"),
                scrolls_per_min=rate("scrolls"), pauses_per_min=rate("pauses"),
                losses_per_min=rate("losses"))


def duration_text(minutes):
    seconds = round(minutes * 60)
    if seconds < 60:
        return f"{seconds} s"
    hours, rest = divmod(seconds // 60, 60)
    return f"{hours} h {rest:02d} min" if hours else f"{rest} min {seconds % 60:02d} s"
