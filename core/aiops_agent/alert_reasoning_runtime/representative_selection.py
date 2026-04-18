from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def select_representative_alerts(
    alerts: list[dict[str, Any]],
    *,
    max_items: int = 3,
    prefer_high_value: bool = True,
) -> dict[str, Any]:
    """Select a small alert set that covers devices, paths, scenarios, and time."""

    if max_items <= 0 or not alerts:
        return _empty()

    candidates = sorted(alerts, key=_alert_sort_key)
    if prefer_high_value:
        high_value = [alert for alert in candidates if _is_high_value(alert)]
        if high_value:
            candidates = high_value + [alert for alert in candidates if alert not in high_value]

    universe = _coverage_universe(alerts)
    selected: list[dict[str, Any]] = []
    covered: set[str] = set()
    remaining = list(candidates)

    while remaining and len(selected) < max_items:
        best = max(
            remaining,
            key=lambda alert: (
                len(_coverage_features(alert) - covered),
                int(_is_high_value(alert)),
                _downstream_dependents(alert),
                -len(selected),
            ),
        )
        selected.append(best)
        covered |= _coverage_features(best)
        remaining = [alert for alert in remaining if _alert_id(alert) != _alert_id(best)]
        if universe and universe.issubset(covered):
            break

    selected_ids = [_alert_id(alert) for alert in selected if _alert_id(alert)]
    return {
        "schema_version": 1,
        "representative_alert_ids": selected_ids,
        "representative_count": len(selected_ids),
        "coverage": _coverage_report(universe=universe, covered=covered),
        "selection_reason": "greedy coverage over device, path, scenario, time, and pressure features",
    }


def _empty() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "representative_alert_ids": [],
        "representative_count": 0,
        "coverage": {
            "covered_features": 0,
            "total_features": 0,
            "coverage_rate": 0.0,
            "missing_features": [],
        },
        "selection_reason": "no alerts available",
    }


def _coverage_report(*, universe: set[str], covered: set[str]) -> dict[str, Any]:
    total = len(universe)
    present = len(universe & covered)
    return {
        "covered_features": present,
        "total_features": total,
        "coverage_rate": round((present / max(total, 1)), 6),
        "missing_features": sorted(universe - covered)[:20],
    }


def _coverage_universe(alerts: list[dict[str, Any]]) -> set[str]:
    features: set[str] = set()
    for alert in alerts:
        features |= _coverage_features(alert)
    return features


def _coverage_features(alert: dict[str, Any]) -> set[str]:
    features = {
        f"device:{_device(alert) or 'unknown'}",
        f"path:{_path_signature(alert) or 'unknown'}",
        f"scenario:{_scenario(alert)}",
        f"time:{_time_bucket(alert)}",
    }
    if _is_high_value(alert):
        features.add("value:high")
    if _downstream_dependents(alert) >= 10:
        features.add("pressure:downstream")
    if str((alert.get("severity") or "")).lower() == "critical":
        features.add("severity:critical")
    return features


def _alert_sort_key(alert: dict[str, Any]) -> tuple[datetime, str]:
    return (
        _parse_ts(alert.get("alert_ts")) or datetime.min.replace(tzinfo=timezone.utc),
        _alert_id(alert),
    )


def _parse_ts(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _time_bucket(alert: dict[str, Any]) -> str:
    ts = _parse_ts(alert.get("alert_ts"))
    if ts is None:
        return "unknown"
    minute = (ts.minute // 5) * 5
    return ts.replace(minute=minute, second=0, microsecond=0).isoformat()


def _alert_id(alert: dict[str, Any]) -> str:
    return str(alert.get("alert_id") or "")


def _scenario(alert: dict[str, Any]) -> str:
    dimensions = alert.get("dimensions") or {}
    metrics = alert.get("metrics") or {}
    return str(
        dimensions.get("fault_scenario")
        or metrics.get("label_value")
        or metrics.get("scenario")
        or "unknown"
    ).strip().lower()


def _device(alert: dict[str, Any]) -> str:
    topology = alert.get("topology_context") or {}
    excerpt = alert.get("event_excerpt") or {}
    dimensions = alert.get("dimensions") or {}
    device_profile = alert.get("device_profile") or {}
    return str(
        topology.get("src_device_key")
        or excerpt.get("src_device_key")
        or dimensions.get("src_device_key")
        or device_profile.get("src_device_key")
        or ""
    ).strip()


def _path_signature(alert: dict[str, Any]) -> str:
    topology = alert.get("topology_context") or {}
    return str(topology.get("path_signature") or "").strip()


def _downstream_dependents(alert: dict[str, Any]) -> int:
    topology = alert.get("topology_context") or {}
    try:
        return int(str(topology.get("downstream_dependents") or "0"))
    except ValueError:
        return 0


def _is_high_value(alert: dict[str, Any]) -> bool:
    scenario = _scenario(alert)
    severity = str(alert.get("severity") or "").lower()
    if severity == "critical":
        return True
    return scenario not in {"", "unknown", "healthy", "normal", "transient_fault", "transient_healthy"}
