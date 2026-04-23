from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

DEFAULT_SELECTION_STRATEGY = "branch-preserving"


def select_representative_alerts(
    alerts: list[dict[str, Any]],
    *,
    max_items: int = 3,
    prefer_high_value: bool = True,
    reference_alerts: list[dict[str, Any]] | None = None,
    strategy: str = DEFAULT_SELECTION_STRATEGY,
    timeline_required: bool | None = None,
) -> dict[str, Any]:
    """Select a small alert set that covers the current evidence surface or full window branches."""

    if max_items <= 0 or not alerts:
        return _empty()

    normalized = str(strategy or DEFAULT_SELECTION_STRATEGY).strip().lower()
    if normalized in {"default", "branch_preserving"}:
        normalized = DEFAULT_SELECTION_STRATEGY
    if normalized not in {"legacy", DEFAULT_SELECTION_STRATEGY}:
        raise ValueError(f"unsupported representative selection strategy: {strategy}")

    candidates = _ordered_candidates(alerts, prefer_high_value=prefer_high_value)
    reference = sorted(reference_alerts or alerts, key=_alert_sort_key)
    universe = _coverage_universe(alerts)
    branch_spec = _branch_spec(reference, timeline_required=timeline_required)
    branch_universe = _branch_universe(reference, spec=branch_spec)

    if normalized == "legacy":
        selected = _select_legacy(candidates, max_items=max_items)
    else:
        selected = _select_branch_preserving(
            candidates,
            max_items=max_items,
            branch_spec=branch_spec,
            branch_universe=branch_universe,
            prefer_high_value=prefer_high_value,
        )

    covered = _selection_coverage(selected)
    branch_covered = _selection_branch_coverage(selected, spec=branch_spec)
    selected_ids = [_alert_id(alert) for alert in selected if _alert_id(alert)]
    return {
        "schema_version": 2,
        "selection_strategy": normalized,
        "representative_alert_ids": selected_ids,
        "representative_count": len(selected_ids),
        "coverage": _coverage_report(universe=universe, covered=covered),
        "branch_coverage": _coverage_report(universe=branch_universe, covered=branch_covered),
        "selection_reason": _selection_reason(normalized),
    }


def _empty() -> dict[str, Any]:
    return {
        "schema_version": 2,
        "selection_strategy": DEFAULT_SELECTION_STRATEGY,
        "representative_alert_ids": [],
        "representative_count": 0,
        "coverage": {
            "covered_features": 0,
            "total_features": 0,
            "coverage_rate": 0.0,
            "missing_features": [],
        },
        "branch_coverage": {
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


def _ordered_candidates(
    alerts: list[dict[str, Any]],
    *,
    prefer_high_value: bool,
) -> list[dict[str, Any]]:
    candidates = sorted(alerts, key=_alert_sort_key)
    if not prefer_high_value:
        return candidates
    high_value = [alert for alert in candidates if _is_high_value(alert)]
    if not high_value:
        return candidates
    return high_value + [alert for alert in candidates if alert not in high_value]


def _select_legacy(
    alerts: list[dict[str, Any]],
    *,
    max_items: int,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    covered: set[str] = set()
    universe = _coverage_universe(alerts)
    remaining = list(alerts)

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
    return selected


def _select_branch_preserving(
    alerts: list[dict[str, Any]],
    *,
    max_items: int,
    branch_spec: dict[str, Any],
    branch_universe: set[str],
    prefer_high_value: bool,
) -> list[dict[str, Any]]:
    if not branch_universe:
        return _select_legacy(alerts, max_items=max_items)

    selected: list[dict[str, Any]] = []
    covered: set[str] = set()
    remaining = list(alerts)
    full_features = _coverage_universe(alerts)
    feature_covered: set[str] = set()

    while remaining and len(selected) < max_items:
        best = max(
            remaining,
            key=lambda alert: (
                _weighted_gain(_branch_features(alert, spec=branch_spec) - covered),
                _weighted_gain(_coverage_features(alert) - feature_covered),
                int(prefer_high_value and _is_high_value(alert)),
                _downstream_dependents(alert),
                int(_scenario_family(alert) == "fault"),
            ),
        )
        selected.append(best)
        covered |= _branch_features(best, spec=branch_spec)
        feature_covered |= _coverage_features(best)
        remaining = [alert for alert in remaining if _alert_id(alert) != _alert_id(best)]
        if branch_universe.issubset(covered):
            break

    if remaining and len(selected) < max_items and not full_features.issubset(feature_covered):
        tail = _select_legacy(remaining, max_items=max_items - len(selected))
        seen = {_alert_id(alert) for alert in selected}
        for alert in tail:
            alert_id = _alert_id(alert)
            if alert_id and alert_id not in seen:
                selected.append(alert)
                seen.add(alert_id)
                if len(selected) >= max_items:
                    break
    return selected


def _weighted_gain(features: set[str]) -> int:
    score = 0
    for feature in features:
        if feature.startswith("branch:"):
            score += 5
        elif feature.startswith("family:"):
            score += 4
        elif feature.startswith("time:"):
            score += 3
        elif feature == "value:high":
            score += 4
        elif feature.startswith("pressure:"):
            score += 2
        else:
            score += 1
    return score


def _coverage_universe(alerts: list[dict[str, Any]]) -> set[str]:
    features: set[str] = set()
    for alert in alerts:
        features |= _coverage_features(alert)
    return features


def _selection_coverage(alerts: list[dict[str, Any]]) -> set[str]:
    covered: set[str] = set()
    for alert in alerts:
        covered |= _coverage_features(alert)
    return covered


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


def _selection_branch_coverage(alerts: list[dict[str, Any]], *, spec: dict[str, Any]) -> set[str]:
    covered: set[str] = set()
    for alert in alerts:
        covered |= _branch_features(alert, spec=spec)
    return covered


def _branch_spec(reference_alerts: list[dict[str, Any]], *, timeline_required: bool | None) -> dict[str, Any]:
    branches = sorted(
        {
            f"{_device(alert) or 'unknown'}|{_path_signature(alert) or 'unknown'}"
            for alert in reference_alerts
        }
    )
    families = {
        family
        for family in (_scenario_family(alert) for alert in reference_alerts)
        if family in {"fault", "transient"}
    }
    unique_ts = sorted(
        {
            (_parse_ts(alert.get("alert_ts")) or datetime.min.replace(tzinfo=timezone.utc)).isoformat()
            for alert in reference_alerts
        }
    )
    needs_time = bool(timeline_required) or len(unique_ts) >= 3 or len(reference_alerts) >= 3
    return {
        "branch_ids": branches,
        "families": families,
        "include_branch_ids": len(branches) >= 2,
        "include_timeline": needs_time,
        "include_middle_time": len(unique_ts) >= 5,
        "first_ts": unique_ts[0] if unique_ts else "",
        "last_ts": unique_ts[-1] if unique_ts else "",
        "include_high_value": any(_is_high_value(alert) for alert in reference_alerts),
        "include_downstream": any(_downstream_dependents(alert) >= 10 for alert in reference_alerts),
    }


def _branch_universe(reference_alerts: list[dict[str, Any]], *, spec: dict[str, Any]) -> set[str]:
    features: set[str] = set()
    if spec.get("include_branch_ids"):
        for branch_id in spec.get("branch_ids") or []:
            features.add(f"branch:{branch_id}")
    for family in sorted(spec.get("families") or []):
        features.add(f"family:{family}")
    if spec.get("include_timeline"):
        first_ts = str(spec.get("first_ts") or "")
        last_ts = str(spec.get("last_ts") or "")
        if first_ts:
            features.add("time:start")
        if last_ts and last_ts != first_ts:
            features.add("time:end")
        if spec.get("include_middle_time") and first_ts and last_ts and first_ts != last_ts:
            features.add("time:middle")
    if spec.get("include_high_value"):
        features.add("value:high")
    if spec.get("include_downstream"):
        features.add("pressure:downstream")
    return features


def _branch_features(alert: dict[str, Any], *, spec: dict[str, Any]) -> set[str]:
    features: set[str] = set()
    if spec.get("include_branch_ids"):
        branch_id = f"{_device(alert) or 'unknown'}|{_path_signature(alert) or 'unknown'}"
        features.add(f"branch:{branch_id}")
    family = _scenario_family(alert)
    if family in set(spec.get("families") or set()):
        features.add(f"family:{family}")
    if spec.get("include_timeline"):
        ts = (_parse_ts(alert.get("alert_ts")) or datetime.min.replace(tzinfo=timezone.utc)).isoformat()
        if ts and ts == str(spec.get("first_ts") or ""):
            features.add("time:start")
        if ts and ts == str(spec.get("last_ts") or ""):
            features.add("time:end")
        if (
            spec.get("include_middle_time")
            and ts
            and ts not in {str(spec.get("first_ts") or ""), str(spec.get("last_ts") or "")}
        ):
            features.add("time:middle")
    if spec.get("include_high_value") and _is_high_value(alert):
        features.add("value:high")
    if spec.get("include_downstream") and _downstream_dependents(alert) >= 10:
        features.add("pressure:downstream")
    return features


def _selection_reason(strategy: str) -> str:
    if strategy == "legacy":
        return "greedy coverage over device, path, scenario, time, and pressure features"
    return "branch-preserving coverage over incident-window device, path, fault-family, and timeline anchors"


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


def _scenario_family(alert: dict[str, Any]) -> str:
    scenario = _scenario(alert)
    if scenario == "induced_fault":
        return "fault"
    if scenario in {"transient_fault", "transient_healthy"}:
        return "transient"
    if scenario in {"", "unknown", "healthy", "normal"}:
        return "normal"
    return "unknown"


def _is_high_value(alert: dict[str, Any]) -> bool:
    scenario = _scenario(alert)
    severity = str(alert.get("severity") or "").lower()
    if severity == "critical":
        return True
    return scenario not in {"", "unknown", "healthy", "normal", "transient_fault", "transient_healthy"}
