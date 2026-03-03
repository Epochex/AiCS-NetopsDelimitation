from __future__ import annotations

import hashlib
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


@dataclass
class RuleConfig:
    deny_window_sec: int = 60
    deny_threshold: int = 30
    bytes_window_sec: int = 300
    bytes_threshold: int = 20_000_000
    cooldown_sec: int = 60


class RuleEngine:
    def __init__(self, config: RuleConfig):
        self.config = config
        self._deny_windows: dict[str, deque[datetime]] = defaultdict(deque)
        self._bytes_windows: dict[str, deque[tuple[datetime, int]]] = defaultdict(deque)
        self._last_alert_at: dict[str, datetime] = {}

    def process(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        event_ts = _parse_event_ts(event)
        if event_ts is None:
            return []

        alerts = []

        deny_alert = self._rule_deny_burst(event, event_ts)
        if deny_alert:
            alerts.append(deny_alert)

        bytes_alert = self._rule_bytes_spike(event, event_ts)
        if bytes_alert:
            alerts.append(bytes_alert)

        return alerts

    def _rule_deny_burst(self, event: dict[str, Any], now: datetime) -> dict[str, Any] | None:
        action = str(event.get("action") or "").lower()
        if action != "deny":
            return None

        key = str(event.get("src_device_key") or event.get("srcip") or "unknown")
        bucket = self._deny_windows[key]
        cutoff = now - timedelta(seconds=self.config.deny_window_sec)

        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        bucket.append(now)

        if len(bucket) < self.config.deny_threshold:
            return None

        alert_key = f"deny_burst::{key}"
        if not self._cooldown_ok(alert_key, now):
            return None

        return _make_alert(
            rule_id="deny_burst_v1",
            severity="warning",
            event=event,
            event_ts=now,
            dimensions={"src_device_key": key},
            metrics={
                "deny_count": len(bucket),
                "window_sec": self.config.deny_window_sec,
                "threshold": self.config.deny_threshold,
            },
        )

    def _rule_bytes_spike(self, event: dict[str, Any], now: datetime) -> dict[str, Any] | None:
        srcip = str(event.get("srcip") or "unknown")
        try:
            bytes_total = int(event.get("bytes_total") or 0)
        except (TypeError, ValueError):
            bytes_total = 0

        if bytes_total <= 0:
            return None

        bucket = self._bytes_windows[srcip]
        cutoff = now - timedelta(seconds=self.config.bytes_window_sec)

        while bucket and bucket[0][0] < cutoff:
            bucket.popleft()
        bucket.append((now, bytes_total))

        aggregate = sum(x[1] for x in bucket)
        if aggregate < self.config.bytes_threshold:
            return None

        alert_key = f"bytes_spike::{srcip}"
        if not self._cooldown_ok(alert_key, now):
            return None

        return _make_alert(
            rule_id="bytes_spike_v1",
            severity="critical",
            event=event,
            event_ts=now,
            dimensions={"srcip": srcip},
            metrics={
                "bytes_sum": aggregate,
                "window_sec": self.config.bytes_window_sec,
                "threshold": self.config.bytes_threshold,
            },
        )

    def _cooldown_ok(self, alert_key: str, now: datetime) -> bool:
        last = self._last_alert_at.get(alert_key)
        if last is not None and (now - last).total_seconds() < self.config.cooldown_sec:
            return False
        self._last_alert_at[alert_key] = now
        return True


def _parse_event_ts(event: dict[str, Any]) -> datetime | None:
    raw_ts = event.get("event_ts")
    if not isinstance(raw_ts, str) or not raw_ts:
        return None

    text = raw_ts.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _make_alert(
    rule_id: str,
    severity: str,
    event: dict[str, Any],
    event_ts: datetime,
    dimensions: dict[str, Any],
    metrics: dict[str, Any],
) -> dict[str, Any]:
    source_event_id = str(event.get("event_id") or "")
    seed = f"{rule_id}|{source_event_id}|{int(event_ts.timestamp())}"
    alert_id = hashlib.sha1(seed.encode("utf-8"), usedforsecurity=False).hexdigest()

    return {
        "schema_version": 1,
        "alert_id": alert_id,
        "alert_ts": event_ts.isoformat(),
        "rule_id": rule_id,
        "severity": severity,
        "source_event_id": source_event_id,
        "dimensions": dimensions,
        "metrics": metrics,
        "event_excerpt": {
            "event_ts": event.get("event_ts"),
            "type": event.get("type"),
            "subtype": event.get("subtype"),
            "action": event.get("action"),
            "srcip": event.get("srcip"),
            "dstip": event.get("dstip"),
            "service": event.get("service"),
            "src_device_key": event.get("src_device_key"),
        },
    }
