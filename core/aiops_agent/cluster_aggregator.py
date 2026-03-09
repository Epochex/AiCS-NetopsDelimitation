from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


@dataclass(frozen=True)
class ClusterKey:
    rule_id: str
    severity: str
    service: str
    src_device_key: str


@dataclass(frozen=True)
class ClusterTrigger:
    key: ClusterKey
    cluster_size: int
    first_alert_ts: str
    last_alert_ts: str
    window_sec: int
    sample_alert_ids: list[str]


class AlertClusterAggregator:
    def __init__(self, window_sec: int, min_alerts: int, cooldown_sec: int) -> None:
        self.window_sec = max(10, int(window_sec))
        self.min_alerts = max(2, int(min_alerts))
        self.cooldown_sec = max(10, int(cooldown_sec))
        self._timeline: dict[ClusterKey, deque[tuple[datetime, str]]] = defaultdict(deque)
        self._last_emit_ts: dict[ClusterKey, datetime] = {}

    def observe(self, alert: dict[str, Any]) -> ClusterTrigger | None:
        key = _build_cluster_key(alert)
        now = _parse_alert_ts(alert)
        events = self._timeline[key]
        events.append((now, str(alert.get("alert_id") or "")))

        cutoff = now - timedelta(seconds=self.window_sec)
        while events and events[0][0] < cutoff:
            events.popleft()

        cluster_size = len(events)
        if cluster_size < self.min_alerts:
            return None

        last_emit = self._last_emit_ts.get(key)
        if last_emit is not None and (now - last_emit).total_seconds() < self.cooldown_sec:
            return None

        self._last_emit_ts[key] = now
        first_ts = events[0][0].isoformat()
        last_ts = events[-1][0].isoformat()
        sample_ids = [x[1] for x in list(events)[-5:]]
        return ClusterTrigger(
            key=key,
            cluster_size=cluster_size,
            first_alert_ts=first_ts,
            last_alert_ts=last_ts,
            window_sec=self.window_sec,
            sample_alert_ids=sample_ids,
        )


def _build_cluster_key(alert: dict[str, Any]) -> ClusterKey:
    excerpt = alert.get("event_excerpt") or {}
    return ClusterKey(
        rule_id=str(alert.get("rule_id") or "unknown"),
        severity=str(alert.get("severity") or "unknown").lower(),
        service=str(excerpt.get("service") or "unknown"),
        src_device_key=str(excerpt.get("src_device_key") or "unknown"),
    )


def _parse_alert_ts(alert: dict[str, Any]) -> datetime:
    raw = alert.get("alert_ts")
    if isinstance(raw, str) and raw:
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)
