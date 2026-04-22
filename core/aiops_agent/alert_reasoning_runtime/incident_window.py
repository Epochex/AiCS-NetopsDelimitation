from __future__ import annotations

import hashlib
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from core.aiops_agent.alert_reasoning_runtime.representative_selection import select_representative_alerts
from core.aiops_agent.alert_reasoning_runtime.window_risk import score_window_risk


SELF_HEALING_SCENARIOS = {"transient_fault", "transient_healthy"}
NON_FAULT_SCENARIOS = {"", "unknown", "healthy", "normal"}
EXTERNAL_WINDOW_LABELS = {
    "external_induced_fault",
    "mixed_fault_and_transient",
    "external_multi_device_spread",
    "external_repeated_transient",
    "external_unknown_with_pressure",
}


def build_incident_windows(
    alerts: list[dict[str, Any]],
    window_sec: int = 600,
    *,
    group_by_scenario: bool = False,
    window_mode: str = "session",
    max_window_sec: int | None = None,
    representative_max_items: int = 3,
) -> list[dict[str, Any]]:
    """Group deterministic alerts into bounded incident windows.

    The grouping is intentionally deterministic and model-free. The default
    mode is sessionized: alerts with the same normalized path shape stay in
    one incident window while their inter-arrival gap remains within
    ``window_sec`` and the total session duration remains bounded. This avoids
    splitting related alerts at arbitrary wall-clock bucket boundaries while
    still preventing long-running transient streams from becoming one large
    incident. ``window_mode="fixed"`` retains the older fixed-bucket behavior
    for sensitivity checks. The path shape removes the seed device prefix when
    LCORE-style hop metadata is available, allowing a window to capture
    multiple devices that share the same topological shape.
    """

    mode = str(window_mode or "session").strip().lower()
    if mode in {"fixed", "bucket", "fixed_bucket"}:
        return _build_fixed_bucket_windows(
            alerts,
            window_sec=window_sec,
            group_by_scenario=group_by_scenario,
            representative_max_items=representative_max_items,
        )
    if mode in {"adaptive", "adaptive_session", "adaptive-session"}:
        return _build_adaptive_session_windows(
            alerts,
            default_idle_gap_sec=window_sec,
            max_window_sec=max_window_sec or window_sec,
            group_by_scenario=group_by_scenario,
            representative_max_items=representative_max_items,
        )
    if mode in {"aics-topology", "aics_topology", "topology-coupled"}:
        return _build_admission_coupled_windows(
            alerts,
            default_idle_gap_sec=window_sec,
            max_window_sec=max_window_sec or window_sec,
            group_by_scenario=group_by_scenario,
            representative_max_items=representative_max_items,
            strategy="topology",
        )
    if mode in {"aics-evidence", "aics_evidence", "evidence-coupled"}:
        return _build_admission_coupled_windows(
            alerts,
            default_idle_gap_sec=window_sec,
            max_window_sec=max_window_sec or window_sec,
            group_by_scenario=group_by_scenario,
            representative_max_items=representative_max_items,
            strategy="evidence",
        )
    if mode in {"aics", "aics-hybrid", "aics_hybrid", "admission", "admission-coupled"}:
        return _build_admission_coupled_windows(
            alerts,
            default_idle_gap_sec=window_sec,
            max_window_sec=max_window_sec or window_sec,
            group_by_scenario=group_by_scenario,
            representative_max_items=representative_max_items,
            strategy="hybrid",
        )
    if mode not in {"session", "sessionized", "idle_gap"}:
        raise ValueError(f"unsupported incident window mode: {window_mode}")
    return _build_sessionized_windows(
        alerts,
        idle_gap_sec=window_sec,
        max_window_sec=max_window_sec or window_sec,
        group_by_scenario=group_by_scenario,
        representative_max_items=representative_max_items,
    )


def _build_fixed_bucket_windows(
    alerts: list[dict[str, Any]],
    *,
    window_sec: int,
    group_by_scenario: bool,
    representative_max_items: int,
) -> list[dict[str, Any]]:
    buckets: dict[tuple[int, str, str], list[dict[str, Any]]] = {}
    for alert in sorted(alerts, key=_alert_sort_key):
        ts = _parse_ts(alert.get("alert_ts"))
        bucket = int(ts.timestamp()) // max(1, window_sec) if ts else 0
        scenario = _scenario(alert) if group_by_scenario else "*"
        key = (bucket, scenario, _path_shape(alert))
        buckets.setdefault(key, []).append(alert)

    windows = [
        _build_window(
            bucket_key=key,
            window_alerts=value,
            window_sec=window_sec,
            representative_max_items=representative_max_items,
        )
        for key, value in sorted(buckets.items(), key=lambda item: item[0])
    ]
    return windows


def _build_sessionized_windows(
    alerts: list[dict[str, Any]],
    *,
    idle_gap_sec: int,
    max_window_sec: int,
    group_by_scenario: bool,
    representative_max_items: int,
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for alert in sorted(alerts, key=_alert_sort_key):
        scenario = _scenario(alert) if group_by_scenario else "*"
        groups.setdefault((scenario, _path_shape(alert)), []).append(alert)

    windows: list[dict[str, Any]] = []
    session_idx = 0
    idle_gap = max(1, idle_gap_sec)
    max_duration = max(idle_gap, max_window_sec)
    for (scenario_key, path_shape), grouped_alerts in sorted(groups.items(), key=lambda item: item[0]):
        current: list[dict[str, Any]] = []
        start_ts: datetime | None = None
        last_ts: datetime | None = None
        for alert in grouped_alerts:
            ts = _parse_ts(alert.get("alert_ts")) or last_ts or start_ts
            if current and ts is not None and last_ts is not None:
                gap = (ts - last_ts).total_seconds()
                duration = (ts - start_ts).total_seconds() if start_ts is not None else 0
                if gap > idle_gap or duration > max_duration:
                    windows.append(
                        _build_window(
                            bucket_key=(session_idx, scenario_key, path_shape),
                            window_alerts=current,
                            window_sec=idle_gap,
                            window_mode="session",
                            max_window_sec=max_duration,
                            representative_max_items=representative_max_items,
                        )
                    )
                    session_idx += 1
                    current = []
                    start_ts = None
            if not current:
                start_ts = ts
            current.append(alert)
            last_ts = ts
        if current:
            windows.append(
                _build_window(
                    bucket_key=(session_idx, scenario_key, path_shape),
                    window_alerts=current,
                    window_sec=idle_gap,
                    window_mode="session",
                    max_window_sec=max_duration,
                    representative_max_items=representative_max_items,
                )
            )
            session_idx += 1
    return sorted(windows, key=lambda window: (str(window.get("window_start") or ""), str(window.get("window_id") or "")))


def _build_adaptive_session_windows(
    alerts: list[dict[str, Any]],
    *,
    default_idle_gap_sec: int,
    max_window_sec: int,
    group_by_scenario: bool,
    representative_max_items: int,
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for alert in sorted(alerts, key=_alert_sort_key):
        scenario = _scenario(alert) if group_by_scenario else "*"
        groups.setdefault((scenario, _path_shape(alert)), []).append(alert)

    windows: list[dict[str, Any]] = []
    session_idx = 0
    default_idle_gap = max(1, default_idle_gap_sec)
    max_duration_cap = max(default_idle_gap, max_window_sec)
    for (scenario_key, path_shape), grouped_alerts in sorted(groups.items(), key=lambda item: item[0]):
        parsed_ts = [_parse_ts(alert.get("alert_ts")) for alert in grouped_alerts]
        gaps = _observed_gaps_sec(parsed_ts)
        group_idle_gap = _estimate_group_idle_gap_sec(
            gaps,
            default_idle_gap_sec=default_idle_gap,
            max_window_sec=max_duration_cap,
        )
        current: list[dict[str, Any]] = []
        current_gaps: list[float] = []
        start_ts: datetime | None = None
        last_ts: datetime | None = None
        max_duration = max(group_idle_gap, max_duration_cap)
        for alert, ts in zip(grouped_alerts, parsed_ts):
            ts = ts or last_ts or start_ts
            if current and ts is not None and last_ts is not None:
                gap = (ts - last_ts).total_seconds()
                duration = (ts - start_ts).total_seconds() if start_ts is not None else 0.0
                dynamic_gap = _dynamic_idle_gap_sec(
                    current_gaps,
                    group_idle_gap_sec=group_idle_gap,
                    default_idle_gap_sec=default_idle_gap,
                    max_window_sec=max_duration_cap,
                )
                if gap > dynamic_gap or duration > max_duration:
                    windows.append(
                        _build_window(
                            bucket_key=(session_idx, scenario_key, path_shape),
                            window_alerts=current,
                            window_sec=group_idle_gap,
                            window_mode="adaptive_session",
                            max_window_sec=max_duration,
                            group_idle_gap_sec=group_idle_gap,
                            representative_max_items=representative_max_items,
                        )
                    )
                    session_idx += 1
                    current = []
                    current_gaps = []
                    start_ts = None
            if not current:
                start_ts = ts
            elif ts is not None and last_ts is not None:
                current_gaps.append((ts - last_ts).total_seconds())
            current.append(alert)
            last_ts = ts
        if current:
            windows.append(
                _build_window(
                    bucket_key=(session_idx, scenario_key, path_shape),
                    window_alerts=current,
                    window_sec=group_idle_gap,
                    window_mode="adaptive_session",
                    max_window_sec=max_duration,
                    group_idle_gap_sec=group_idle_gap,
                    representative_max_items=representative_max_items,
                )
            )
            session_idx += 1
    return sorted(windows, key=lambda window: (str(window.get("window_start") or ""), str(window.get("window_id") or "")))


def _build_admission_coupled_windows(
    alerts: list[dict[str, Any]],
    *,
    default_idle_gap_sec: int,
    max_window_sec: int,
    group_by_scenario: bool,
    representative_max_items: int,
    strategy: str,
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for alert in sorted(alerts, key=_alert_sort_key):
        scenario = _scenario(alert) if group_by_scenario else "*"
        groups.setdefault((scenario, _path_shape(alert)), []).append(alert)

    windows: list[dict[str, Any]] = []
    session_idx = 0
    default_idle_gap = max(1, default_idle_gap_sec)
    max_duration_cap = max(default_idle_gap, max_window_sec)
    window_mode = f"aics_{strategy}"
    for (scenario_key, path_shape), grouped_alerts in sorted(groups.items(), key=lambda item: item[0]):
        parsed_ts = [_parse_ts(alert.get("alert_ts")) for alert in grouped_alerts]
        gaps = _observed_gaps_sec(parsed_ts)
        group_idle_gap = _estimate_group_idle_gap_sec(
            gaps,
            default_idle_gap_sec=default_idle_gap,
            max_window_sec=max_duration_cap,
        )
        current: list[dict[str, Any]] = []
        current_gaps: list[float] = []
        start_ts: datetime | None = None
        last_ts: datetime | None = None
        max_duration = max(group_idle_gap, max_duration_cap)
        for alert, ts in zip(grouped_alerts, parsed_ts):
            ts = ts or last_ts or start_ts
            if current and ts is not None and last_ts is not None:
                gap = max(0.0, (ts - last_ts).total_seconds())
                duration = (ts - start_ts).total_seconds() if start_ts is not None else 0.0
                dynamic_gap = _dynamic_idle_gap_sec(
                    current_gaps,
                    group_idle_gap_sec=group_idle_gap,
                    default_idle_gap_sec=default_idle_gap,
                    max_window_sec=max_duration_cap,
                )
                hard_split = gap > dynamic_gap or duration > max_duration
                soft_score, soft_reasons = _admission_boundary_score(
                    current,
                    next_alert=alert,
                    gap_sec=gap,
                    group_idle_gap_sec=group_idle_gap,
                    dynamic_gap_sec=dynamic_gap,
                    default_idle_gap_sec=default_idle_gap,
                    strategy=strategy,
                )
                if hard_split or _should_soft_split(
                    current,
                    gap_sec=gap,
                    duration_sec=duration,
                    group_idle_gap_sec=group_idle_gap,
                    dynamic_gap_sec=dynamic_gap,
                    score=soft_score,
                    reasons=soft_reasons,
                    strategy=strategy,
                ):
                    windows.append(
                        _build_window(
                            bucket_key=(session_idx, scenario_key, path_shape),
                            window_alerts=current,
                            window_sec=group_idle_gap,
                            window_mode=window_mode,
                            max_window_sec=max_duration,
                            group_idle_gap_sec=group_idle_gap,
                            representative_max_items=representative_max_items,
                            boundary_strategy=strategy,
                        )
                    )
                    session_idx += 1
                    current = []
                    current_gaps = []
                    start_ts = None
            if not current:
                start_ts = ts
            elif ts is not None and last_ts is not None:
                current_gaps.append(max(0.0, (ts - last_ts).total_seconds()))
            current.append(alert)
            last_ts = ts
        if current:
            windows.append(
                _build_window(
                    bucket_key=(session_idx, scenario_key, path_shape),
                    window_alerts=current,
                    window_sec=group_idle_gap,
                    window_mode=window_mode,
                    max_window_sec=max_duration,
                    group_idle_gap_sec=group_idle_gap,
                    representative_max_items=representative_max_items,
                    boundary_strategy=strategy,
                )
            )
            session_idx += 1
    return sorted(windows, key=lambda window: (str(window.get("window_start") or ""), str(window.get("window_id") or "")))


def index_windows_by_alert_id(windows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for window in windows:
        for alert_id in window.get("alert_ids") or []:
            if alert_id:
                index[str(alert_id)] = window
    return index


def build_incident_window_index(
    alerts: list[dict[str, Any]],
    window_sec: int = 600,
    *,
    group_by_scenario: bool = False,
    window_mode: str = "session",
    max_window_sec: int | None = None,
    representative_max_items: int = 3,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    windows = build_incident_windows(
        alerts,
        window_sec=window_sec,
        group_by_scenario=group_by_scenario,
        window_mode=window_mode,
        max_window_sec=max_window_sec,
        representative_max_items=representative_max_items,
    )
    return windows, index_windows_by_alert_id(windows)


def summarize_incident_window(window: dict[str, Any] | None) -> dict[str, Any]:
    if not window:
        return {
            "window_id": "",
            "alert_count": 0,
            "device_count": 0,
            "path_count": 0,
            "path_shape_count": 0,
            "scenario_counts": {},
            "recurrence_pressure": False,
            "topology_pressure": False,
            "multi_device_spread": False,
            "window_label": "",
            "recommended_action": "local",
            "quality_proxy_label": "",
            "risk_score": 0,
            "risk_tier": "low",
            "risk_atoms": [],
            "timeline": [],
        }
    return {
        "window_id": str(window.get("window_id") or ""),
        "window_start": str(window.get("window_start") or ""),
        "window_end": str(window.get("window_end") or ""),
        "alert_count": int(window.get("alert_count") or 0),
        "device_count": int(window.get("device_count") or 0),
        "path_count": int(window.get("path_count") or 0),
        "path_shape_count": int(window.get("path_shape_count") or 0),
        "scenario_counts": window.get("scenario_counts") or {},
        "devices": list(window.get("devices") or [])[:8],
        "path_signatures": list(window.get("path_signatures") or [])[:8],
        "path_shapes": list(window.get("path_shapes") or [])[:8],
        "recurrence_pressure": bool(window.get("recurrence_pressure")),
        "topology_pressure": bool(window.get("topology_pressure")),
        "multi_device_spread": bool(window.get("multi_device_spread")),
        "max_downstream_dependents": int(window.get("max_downstream_dependents") or 0),
        "pressure_score": int(window.get("pressure_score") or 0),
        "window_label": str(window.get("window_label") or ""),
        "recommended_action": str(window.get("recommended_action") or "local"),
        "quality_proxy_label": str(window.get("quality_proxy_label") or ""),
        "risk_score": int(window.get("risk_score") or 0),
        "risk_tier": str(window.get("risk_tier") or "low"),
        "risk_atoms": list(window.get("risk_atoms") or [])[:12],
        "risk_reasons": list(window.get("risk_reasons") or [])[:8],
        "decision_reason": str(window.get("decision_reason") or ""),
        "selected_evidence_targets": window.get("selected_evidence_targets") or {},
        "excluded_evidence_targets": window.get("excluded_evidence_targets") or [],
        "timeline": list(window.get("timeline") or [])[:12],
    }


def build_window_evidence_boundary(window: dict[str, Any] | None) -> dict[str, Any]:
    """Return the window-level selected, excluded, and missing evidence surfaces."""

    if not window:
        return {
            "schema_version": 1,
            "window_id": "",
            "window_label": "",
            "recommended_action": "local",
            "selected_surface": {},
            "excluded_surface": [],
            "missing_surface": [{"field": "incident_window", "reason": "no incident window available"}],
        }
    selected = window.get("selected_evidence_targets") or {}
    excluded = window.get("excluded_evidence_targets") or []
    missing = []
    if not selected.get("devices"):
        missing.append({"field": "devices", "reason": "no device evidence in incident window"})
    if not selected.get("path_signatures"):
        missing.append({"field": "path_signatures", "reason": "no path evidence in incident window"})
    if int(window.get("alert_count") or 0) <= 1:
        missing.append({"field": "timeline", "reason": "single-alert window has no temporal ordering"})
    return {
        "schema_version": 1,
        "window_id": str(window.get("window_id") or ""),
        "window_label": str(window.get("window_label") or ""),
        "recommended_action": str(window.get("recommended_action") or "local"),
        "decision_reason": str(window.get("decision_reason") or ""),
        "pressure_score": int(window.get("pressure_score") or 0),
        "quality_proxy_label": str(window.get("quality_proxy_label") or ""),
        "risk_score": int(window.get("risk_score") or 0),
        "risk_tier": str(window.get("risk_tier") or "low"),
        "risk_atoms": list(window.get("risk_atoms") or [])[:12],
        "risk_weights": window.get("risk_weights") or {},
        "risk_reasons": list(window.get("risk_reasons") or [])[:8],
        "selected_surface": selected,
        "excluded_surface": excluded,
        "missing_surface": missing,
    }


def _build_window(
    *,
    bucket_key: tuple[int, str, str],
    window_alerts: list[dict[str, Any]],
    window_sec: int,
    window_mode: str = "fixed",
    max_window_sec: int | None = None,
    group_idle_gap_sec: int | None = None,
    representative_max_items: int = 3,
    boundary_strategy: str = "",
) -> dict[str, Any]:
    bucket, scenario_key, path_shape = bucket_key
    timestamps = [_parse_ts(alert.get("alert_ts")) for alert in window_alerts]
    parsed = [ts for ts in timestamps if ts is not None]
    start = min(parsed) if parsed else datetime.fromtimestamp(bucket * window_sec, timezone.utc)
    end = max(parsed) if parsed else start
    devices = sorted({_device(alert) for alert in window_alerts if _device(alert)})
    path_signatures = sorted({_path_signature(alert) for alert in window_alerts if _path_signature(alert)})
    path_shapes = sorted({_path_shape(alert) for alert in window_alerts if _path_shape(alert)})
    scenario_counts = Counter(_scenario(alert) for alert in window_alerts)
    max_downstream = max((_downstream_dependents(alert) for alert in window_alerts), default=0)
    high_value_alerts = [alert for alert in window_alerts if _is_high_value(alert)]
    self_healing_alerts = [alert for alert in window_alerts if _scenario(alert) in SELF_HEALING_SCENARIOS]
    timeline = [
        {
            "alert_id": str(alert.get("alert_id") or ""),
            "alert_ts": str(alert.get("alert_ts") or ""),
            "device": _device(alert),
            "scenario": _scenario(alert),
            "path_signature": _path_signature(alert),
            "severity": str(alert.get("severity") or "unknown").lower(),
        }
        for alert in sorted(window_alerts, key=_alert_sort_key)
    ]
    high_value_count = len(high_value_alerts)
    self_healing_count = len(self_healing_alerts)
    recurrence_pressure = len(window_alerts) >= 3
    multi_device_spread = len(devices) >= 2
    topology_pressure = multi_device_spread or len(path_signatures) >= 2 or max_downstream >= 10
    alert_ids = [str(alert.get("alert_id") or "") for alert in window_alerts if str(alert.get("alert_id") or "")]
    window_label = _window_label(
        high_value_count=high_value_count,
        self_healing_count=self_healing_count,
        total_count=len(window_alerts),
        recurrence_pressure=recurrence_pressure,
        topology_pressure=topology_pressure,
        multi_device_spread=multi_device_spread,
    )
    recommended_action = "external" if window_label in EXTERNAL_WINDOW_LABELS else "local"
    pressure_score = int(recurrence_pressure) + int(topology_pressure) + int(multi_device_spread) + int(max_downstream >= 10)
    quality_proxy_label = _quality_proxy_label(
        high_value_count=high_value_count,
        self_healing_count=self_healing_count,
        total_count=len(window_alerts),
        pressure_score=pressure_score,
    )
    selected_targets, excluded_targets = _window_evidence_targets(
        window_alerts=window_alerts,
        high_value_alerts=high_value_alerts,
        self_healing_alerts=self_healing_alerts,
        devices=devices,
        path_signatures=path_signatures,
        recommended_action=recommended_action,
        window_label=window_label,
        representative_max_items=representative_max_items,
    )
    window_id = _hash_id(
        "incident-window|"
        f"{bucket}|{scenario_key}|{path_shape}|{','.join(alert_ids[:8])}|{len(alert_ids)}"
    )
    window = {
        "schema_version": 1,
        "window_id": window_id,
        "window_mode": window_mode,
        "boundary_strategy": boundary_strategy or window_mode,
        "window_sec": window_sec,
        "max_window_sec": max_window_sec or window_sec,
        "group_idle_gap_sec": group_idle_gap_sec or window_sec,
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "group_key": {
            "time_bucket": bucket,
            "session_index": bucket if window_mode in {"session", "adaptive_session"} else None,
            "scenario": scenario_key,
            "path_shape": path_shape,
        },
        "alert_count": len(window_alerts),
        "alert_ids": alert_ids,
        "sample_alert_ids": alert_ids[:12],
        "scenario_counts": dict(scenario_counts),
        "devices": devices,
        "device_count": len(devices),
        "path_signatures": path_signatures,
        "path_count": len(path_signatures),
        "path_shapes": path_shapes,
        "path_shape_count": len(path_shapes),
        "first_alert_ts": start.isoformat(),
        "last_alert_ts": end.isoformat(),
        "timeline": timeline,
        "recurrence_pressure": recurrence_pressure,
        "topology_pressure": topology_pressure,
        "multi_device_spread": multi_device_spread,
        "max_downstream_dependents": max_downstream,
        "pressure_score": pressure_score,
        "high_value_count": high_value_count,
        "self_healing_count": self_healing_count,
        "self_healing_dominant": self_healing_count > 0 and high_value_count == 0,
        "window_label": window_label,
        "recommended_action": recommended_action,
        "quality_proxy_label": quality_proxy_label,
        "decision_reason": _window_decision_reason(
            window_label=window_label,
            alert_count=len(window_alerts),
            device_count=len(devices),
            high_value_count=high_value_count,
            pressure_score=pressure_score,
        ),
        "selected_evidence_targets": selected_targets,
        "excluded_evidence_targets": excluded_targets,
    }
    window.update(score_window_risk(window))
    return window


def _window_label(
    *,
    high_value_count: int,
    self_healing_count: int,
    total_count: int,
    recurrence_pressure: bool,
    topology_pressure: bool,
    multi_device_spread: bool,
) -> str:
    if high_value_count > 0 and self_healing_count > 0:
        return "mixed_fault_and_transient"
    if high_value_count > 0:
        return "external_induced_fault"
    if self_healing_count > 0 and multi_device_spread:
        return "external_multi_device_spread"
    if self_healing_count > 0 and recurrence_pressure:
        return "external_repeated_transient"
    if self_healing_count > 0 and topology_pressure:
        return "local_transient_with_pressure"
    if self_healing_count == total_count and total_count > 0:
        return "local_single_transient"
    if recurrence_pressure or topology_pressure:
        return "external_unknown_with_pressure"
    return "local_low_evidence"


def _quality_proxy_label(
    *,
    high_value_count: int,
    self_healing_count: int,
    total_count: int,
    pressure_score: int,
) -> str:
    if high_value_count > 0 and self_healing_count > 0:
        return "mixed_high_value_window"
    if high_value_count > 0:
        return "high_value_window"
    if self_healing_count == total_count and pressure_score > 0:
        return "pressure_self_healing_window"
    if self_healing_count == total_count:
        return "low_value_self_healing_window"
    if pressure_score > 0:
        return "unknown_pressure_window"
    return "low_evidence_window"


def _window_evidence_targets(
    *,
    window_alerts: list[dict[str, Any]],
    high_value_alerts: list[dict[str, Any]],
    self_healing_alerts: list[dict[str, Any]],
    devices: list[str],
    path_signatures: list[str],
    recommended_action: str,
    window_label: str,
    representative_max_items: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    target_alerts = high_value_alerts or window_alerts
    representative_selection = select_representative_alerts(
        target_alerts,
        max_items=max(1, representative_max_items),
    )
    target_ids = _alert_ids(target_alerts)
    representative_ids = representative_selection.get("representative_alert_ids") or []
    selected = {
        "alert_ids": target_ids[:12],
        "representative_alert_ids": representative_ids[:6],
        "representative_selection": representative_selection,
        "devices": sorted({_device(alert) for alert in target_alerts if _device(alert)})[:8] or devices[:8],
        "path_signatures": sorted({_path_signature(alert) for alert in target_alerts if _path_signature(alert)})[:8]
        or path_signatures[:8],
        "timeline_required": len(window_alerts) > 1,
        "selection_basis": window_label,
    }
    excluded: list[dict[str, Any]] = []
    if recommended_action == "local":
        excluded.append(
            {
                "kind": "local_window",
                "alert_ids": _alert_ids(window_alerts)[:12],
                "reason": "window label remains on bounded local path",
            }
        )
    elif high_value_alerts and self_healing_alerts:
        excluded.append(
            {
                "kind": "transient_context_not_primary",
                "alert_ids": _alert_ids(self_healing_alerts)[:12],
                "reason": "transient alerts are retained as context but not primary targets",
            }
        )
    return selected, excluded


def _representatives_by_device(alerts: list[dict[str, Any]], max_items: int) -> list[dict[str, Any]]:
    reps: list[dict[str, Any]] = []
    seen: set[str] = set()
    for alert in sorted(alerts, key=_alert_sort_key):
        device = _device(alert) or str(alert.get("alert_id") or "")
        if device in seen:
            continue
        reps.append(alert)
        seen.add(device)
        if len(reps) >= max_items:
            break
    if not reps and alerts:
        reps.append(sorted(alerts, key=_alert_sort_key)[0])
    return reps


def _alert_ids(alerts: list[dict[str, Any]]) -> list[str]:
    return [str(alert.get("alert_id") or "") for alert in alerts if str(alert.get("alert_id") or "")]


def _window_decision_reason(
    *,
    window_label: str,
    alert_count: int,
    device_count: int,
    high_value_count: int,
    pressure_score: int,
) -> str:
    if window_label == "mixed_fault_and_transient":
        return f"window contains {high_value_count} high-value alerts and transient context."
    if window_label == "external_induced_fault":
        return f"window contains {high_value_count} high-value fault alerts."
    if window_label == "external_multi_device_spread":
        return f"transient-looking alerts span {device_count} devices."
    if window_label == "external_repeated_transient":
        return f"transient-looking alerts repeat {alert_count} times in the window."
    if window_label == "local_transient_with_pressure":
        return f"transient-looking window has topology pressure score {pressure_score} but no recurrence or spread trigger."
    if window_label == "local_single_transient":
        return "single transient-looking window remains local."
    if window_label == "external_unknown_with_pressure":
        return f"unknown window has pressure score {pressure_score}."
    return "low-evidence window remains local."


def _alert_sort_key(alert: dict[str, Any]) -> tuple[datetime, str]:
    return (
        _parse_ts(alert.get("alert_ts")) or datetime.min.replace(tzinfo=timezone.utc),
        str(alert.get("alert_id") or ""),
    )


def _observed_gaps_sec(timestamps: list[datetime | None]) -> list[float]:
    values: list[float] = []
    previous: datetime | None = None
    for ts in timestamps:
        if ts is None:
            continue
        if previous is not None:
            values.append(max(0.0, (ts - previous).total_seconds()))
        previous = ts
    return values


def _estimate_group_idle_gap_sec(
    gaps: list[float],
    *,
    default_idle_gap_sec: int,
    max_window_sec: int,
) -> int:
    minimum = max(60, default_idle_gap_sec // 4)
    positive = sorted(gap for gap in gaps if gap > 0)
    if len(positive) < 3:
        return max(minimum, default_idle_gap_sec)
    median = _percentile(positive, 0.50)
    q25 = _percentile(positive, 0.25)
    q75 = _percentile(positive, 0.75)
    q90 = _percentile(positive, 0.90)
    mad = _percentile([abs(gap - median) for gap in positive], 0.50)
    iqr = max(q75 - q25, 1.0)
    robust_tail = max(q75 + iqr, median + 3.0 * max(mad, 1.0))
    candidate = min(max(q90, robust_tail), float(max_window_sec))
    return int(round(max(minimum, candidate)))


def _dynamic_idle_gap_sec(
    recent_gaps: list[float],
    *,
    group_idle_gap_sec: int,
    default_idle_gap_sec: int,
    max_window_sec: int,
) -> int:
    minimum = max(60, default_idle_gap_sec // 4)
    if not recent_gaps:
        return group_idle_gap_sec
    tail = recent_gaps[-3:]
    median = _percentile(tail, 0.50)
    mad = _percentile([abs(gap - median) for gap in tail], 0.50)
    local_scale = max(median * 3.0, median + 3.0 * max(mad, 1.0))
    candidate = min(float(group_idle_gap_sec), local_scale, float(max_window_sec))
    return int(round(max(minimum, candidate)))


def _admission_boundary_score(
    current_alerts: list[dict[str, Any]],
    *,
    next_alert: dict[str, Any],
    gap_sec: float,
    group_idle_gap_sec: int,
    dynamic_gap_sec: int,
    default_idle_gap_sec: int,
    strategy: str,
) -> tuple[int, list[str]]:
    if not current_alerts:
        return 0, []

    weights_by_strategy = {
        "topology": {
            "gap_soft": 1,
            "new_device": 2,
            "new_path_signature": 1,
            "fanout_tier_shift": 1,
            "family_shift": 1,
            "coverage_novelty": 0,
            "representative_churn": 0,
            "sudden_fault_entry": 1,
        },
        "evidence": {
            "gap_soft": 1,
            "new_device": 0,
            "new_path_signature": 1,
            "fanout_tier_shift": 0,
            "family_shift": 2,
            "coverage_novelty": 2,
            "representative_churn": 1,
            "sudden_fault_entry": 2,
        },
        "hybrid": {
            "gap_soft": 1,
            "new_device": 1,
            "new_path_signature": 1,
            "fanout_tier_shift": 1,
            "family_shift": 2,
            "coverage_novelty": 1,
            "representative_churn": 1,
            "sudden_fault_entry": 2,
        },
    }
    weights = weights_by_strategy.get(strategy, weights_by_strategy["hybrid"])
    score = 0
    reasons: list[str] = []

    current_devices = {_device(alert) for alert in current_alerts if _device(alert)}
    current_paths = {_path_signature(alert) for alert in current_alerts if _path_signature(alert)}
    current_families = {
        family
        for family in (_scenario_family(alert) for alert in current_alerts)
        if family not in {"unknown", "normal"}
    }
    next_family = _scenario_family(next_alert)
    next_device = _device(next_alert)
    next_path = _path_signature(next_alert)

    soft_gap_sec = max(60, int(round(min(group_idle_gap_sec, dynamic_gap_sec, max(default_idle_gap_sec, 60)) * 0.35)))
    if gap_sec >= soft_gap_sec:
        score += weights["gap_soft"]
        reasons.append("soft temporal discontinuity")
    if next_device and next_device not in current_devices:
        score += weights["new_device"]
        reasons.append("device frontier shift")
    if next_path and next_path not in current_paths:
        score += weights["new_path_signature"]
        reasons.append("path signature shift")
    if _downstream_tier(next_alert) not in {_downstream_tier(alert) for alert in current_alerts}:
        score += weights["fanout_tier_shift"]
        reasons.append("downstream fanout tier shift")
    if current_families and next_family not in current_families and next_family not in {"unknown", "normal"}:
        score += weights["family_shift"]
        reasons.append("fault-state family transition")

    novelty = len(_boundary_features(next_alert) - _boundary_feature_universe(current_alerts))
    if novelty >= 2:
        score += weights["coverage_novelty"]
        reasons.append("evidence boundary novelty")

    if _representative_churn(current_alerts, next_alert) >= 2:
        score += weights["representative_churn"]
        reasons.append("representative set churn")

    if next_family == "fault" and all(_scenario_family(alert) == "transient" for alert in current_alerts) and len(current_alerts) >= 2:
        score += weights["sudden_fault_entry"]
        reasons.append("fault entry after transient burst")

    return score, _dedupe(reasons)


def _should_soft_split(
    current_alerts: list[dict[str, Any]],
    *,
    gap_sec: float,
    duration_sec: float,
    group_idle_gap_sec: int,
    dynamic_gap_sec: int,
    score: int,
    reasons: list[str],
    strategy: str,
) -> bool:
    if len(current_alerts) < 2 or not reasons:
        return False
    thresholds = {"topology": 4, "evidence": 5, "hybrid": 5}
    threshold = thresholds.get(strategy, 5)
    soft_gap_sec = max(60, int(round(min(group_idle_gap_sec, dynamic_gap_sec) * 0.35)))
    if gap_sec >= soft_gap_sec and score >= threshold:
        return True
    if "fault entry after transient burst" in reasons and gap_sec >= 60 and score >= threshold:
        return True
    if duration_sec >= max(group_idle_gap_sec, dynamic_gap_sec) and score >= (threshold + 1):
        return True
    return False


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    q = min(max(q, 0.0), 1.0)
    index = q * (len(ordered) - 1)
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    weight = index - lower
    return float(ordered[lower] * (1.0 - weight) + ordered[upper] * weight)


def _scenario_family(alert: dict[str, Any]) -> str:
    scenario = _scenario(alert)
    if scenario == "induced_fault":
        return "fault"
    if scenario in SELF_HEALING_SCENARIOS:
        return "transient"
    if scenario in NON_FAULT_SCENARIOS:
        return "normal"
    return "unknown"


def _downstream_tier(alert: dict[str, Any]) -> str:
    downstream = _downstream_dependents(alert)
    if downstream >= 10:
        return "high"
    if downstream >= 3:
        return "medium"
    return "low"


def _boundary_features(alert: dict[str, Any]) -> set[str]:
    features = {
        f"device:{_device(alert) or 'unknown'}",
        f"path:{_path_signature(alert) or 'unknown'}",
        f"family:{_scenario_family(alert)}",
        f"fanout:{_downstream_tier(alert)}",
    }
    if _is_high_value(alert):
        features.add("value:high")
    return features


def _boundary_feature_universe(alerts: list[dict[str, Any]]) -> set[str]:
    features: set[str] = set()
    for alert in alerts:
        features |= _boundary_features(alert)
    return features


def _representative_churn(current_alerts: list[dict[str, Any]], next_alert: dict[str, Any]) -> int:
    before = set(
        (select_representative_alerts(current_alerts, max_items=2).get("representative_alert_ids") or [])
    )
    after = set(
        (select_representative_alerts([*current_alerts, next_alert], max_items=2).get("representative_alert_ids") or [])
    )
    return len(before ^ after)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


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
    excerpt = alert.get("event_excerpt") or {}
    path = str(topology.get("path_signature") or "").strip()
    if path:
        return path
    srcintf = str(excerpt.get("srcintf") or topology.get("srcintf") or "unknown").strip()
    dstintf = str(excerpt.get("dstintf") or topology.get("dstintf") or "unknown").strip()
    return f"{srcintf or 'unknown'}->{dstintf or 'unknown'}"


def _path_shape(alert: dict[str, Any]) -> str:
    signature = _path_signature(alert)
    if "|" in signature:
        return "|".join(signature.split("|")[1:]) or signature
    topology = alert.get("topology_context") or {}
    hop_core = str(topology.get("hop_to_core") or "").strip()
    hop_server = str(topology.get("hop_to_server") or "").strip()
    path_up = str(topology.get("path_up") or "").strip()
    parts = []
    if hop_core:
        parts.append(f"hop_core={hop_core}")
    if hop_server:
        parts.append(f"hop_server={hop_server}")
    if path_up:
        parts.append(f"path_up={path_up}")
    return "|".join(parts) if parts else signature


def _downstream_dependents(alert: dict[str, Any]) -> int:
    topology = alert.get("topology_context") or {}
    try:
        return int(str(topology.get("downstream_dependents") or "0"))
    except ValueError:
        return 0


def _is_high_value(alert: dict[str, Any]) -> bool:
    severity = str(alert.get("severity") or "").lower()
    scenario = _scenario(alert)
    if severity == "critical":
        return True
    return scenario not in SELF_HEALING_SCENARIOS and scenario not in NON_FAULT_SCENARIOS


def _hash_id(seed: str) -> str:
    return hashlib.sha1(seed.encode("utf-8"), usedforsecurity=False).hexdigest()
