from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fp:
        for record in records:
            fp.write(json.dumps(record, ensure_ascii=True, sort_keys=True) + "\n")


def representative_ids(window: dict[str, Any]) -> set[str]:
    targets = window.get("selected_evidence_targets") or {}
    values = targets.get("representative_alert_ids") or targets.get("alert_ids") or []
    return {str(value) for value in values if str(value)}


def representative_cost(window: dict[str, Any]) -> int:
    return max(1, len(representative_ids(window)))


def has_pressure(window: dict[str, Any]) -> bool:
    return bool(
        window.get("topology_pressure")
        or window.get("recurrence_pressure")
        or window.get("multi_device_spread")
    )


def evidence_target_covered(window: dict[str, Any]) -> bool:
    targets = window.get("selected_evidence_targets") or {}
    return bool(
        targets.get("devices")
        and targets.get("path_signatures")
        and targets.get("representative_alert_ids")
    )


def external_call_count(windows: list[dict[str, Any]], *, call_mode: str) -> int:
    if call_mode == "all-alerts":
        return sum(int(window.get("alert_count") or 0) for window in windows)
    if call_mode == "high-value-alerts":
        return sum(max(1, int(window.get("high_value_count") or 0)) for window in windows)
    if call_mode == "representative-alerts":
        return sum(representative_cost(window) for window in windows)
    raise ValueError(f"unknown call mode: {call_mode}")


def budget_summary(admission: dict[str, Any] | None) -> dict[str, Any]:
    if not admission:
        return {}
    return {
        "admission_strategy": admission.get("admission_strategy"),
        "budget_fraction": admission.get("budget_fraction"),
        "budget_external_calls": admission.get("budget_external_calls"),
        "used_external_calls": admission.get("used_external_calls"),
        "safety_floor_extra_calls": admission.get("safety_floor_extra_calls"),
        "selected_windows": admission.get("selected_windows"),
        "covered_risk_atom_count": admission.get("covered_risk_atom_count"),
    }


def selected_window_metrics(
    windows: list[dict[str, Any]],
    selected_window_ids: set[str],
    *,
    call_mode: str,
    admission: dict[str, Any] | None = None,
) -> dict[str, Any]:
    total = len(windows)
    total_alerts = sum(int(window.get("alert_count") or 0) for window in windows)
    high_value_total = sum(1 for window in windows if int(window.get("high_value_count") or 0) > 0)
    selected = [
        window for window in windows
        if str(window.get("window_id") or "") in selected_window_ids
    ]
    high_value_retained = sum(1 for window in selected if int(window.get("high_value_count") or 0) > 0)
    external_calls = external_call_count(selected, call_mode=call_mode)
    pressure_total = sum(1 for window in windows if has_pressure(window))
    pressure_skipped = sum(
        1
        for window in windows
        if has_pressure(window) and str(window.get("window_id") or "") not in selected_window_ids
    )
    evidence_covered = sum(1 for window in selected if evidence_target_covered(window))
    return {
        "selected_windows": len(selected),
        "external_calls": external_calls,
        "call_mode": call_mode,
        "call_reduction_percent": round((1 - external_calls / max(total_alerts, 1)) * 100, 2),
        "window_reduction_percent": round((1 - len(selected) / max(total, 1)) * 100, 2),
        "high_value_window_recall": round(high_value_retained / max(high_value_total, 1), 6),
        "high_value_windows_retained": high_value_retained,
        "high_value_windows_total": high_value_total,
        "false_skip_windows": high_value_total - high_value_retained,
        "false_skip_rate": round((high_value_total - high_value_retained) / max(high_value_total, 1), 6),
        "pressure_windows_total": pressure_total,
        "pressure_windows_skipped": pressure_skipped,
        "pressure_window_skip_rate": round(pressure_skipped / max(pressure_total, 1), 6),
        "evidence_target_coverage_rate": round(evidence_covered / max(len(selected), 1), 6),
        "budget_summary": budget_summary(admission),
    }
