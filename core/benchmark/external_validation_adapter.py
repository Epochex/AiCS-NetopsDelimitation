from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from core.aiops_agent.alert_reasoning_runtime.budget_controller import select_windows_under_budget
from core.aiops_agent.alert_reasoning_runtime.incident_window import build_incident_window_index
from core.aiops_agent.alert_reasoning_runtime.window_labeling import build_weak_window_label


BUDGET_FRACTIONS = (1, 2, 5, 10, 20, 40, 60)


def run(args: argparse.Namespace) -> dict[str, Any]:
    dataset = Path(args.dataset_jsonl)
    if not dataset.exists():
        raise FileNotFoundError(
            f"{dataset} does not exist. Export RCAEval incidents to JSONL before running external validation."
        )
    records = _read_jsonl(dataset)
    alerts = [_to_alert(record, idx) for idx, record in enumerate(records)]
    windows, _ = build_incident_window_index(alerts, window_sec=args.window_sec)
    label_counts = Counter(str(window.get("window_label") or "unknown") for window in windows)
    high_value_windows = sum(1 for window in windows if int(window.get("high_value_count") or 0) > 0)
    policies = _policy_metrics(windows)
    report = {
        "schema_version": 1,
        "dataset_jsonl": str(dataset),
        "input_records": len(records),
        "converted_alerts": len(alerts),
        "incident_windows": len(windows),
        "high_value_windows": high_value_windows,
        "window_labels": dict(label_counts.most_common()),
        "policies": policies,
        "validation_scope": "admission-layer transfer only; does not claim RCA accuracy",
    }
    if getattr(args, "output_windows_jsonl", ""):
        _write_windows_jsonl(Path(args.output_windows_jsonl), windows)
    if getattr(args, "output_labels_jsonl", ""):
        _write_labels_jsonl(Path(args.output_labels_jsonl), windows)
    if args.output_json:
        path = Path(args.output_json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
    return report


def _policy_metrics(windows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    all_windows = {str(window.get("window_id") or "") for window in windows}
    high_value_windows = {
        str(window.get("window_id") or "")
        for window in windows
        if int(window.get("high_value_count") or 0) > 0
    }
    risk_windows = {
        str(window.get("window_id") or "")
        for window in windows
        if str(window.get("recommended_action") or "") == "external"
        or str(window.get("risk_tier") or "") == "high"
    }
    policies = {
        "invoke-all": _metrics(windows, all_windows, call_mode="all-alerts"),
        "scenario-only": _metrics(windows, high_value_windows, call_mode="high-value-alerts"),
        "window-risk-tier": _metrics(windows, risk_windows, call_mode="representative-alerts"),
        "oracle": _metrics(windows, high_value_windows, call_mode="high-value-alerts"),
    }
    for value in BUDGET_FRACTIONS:
        fraction = value / 100.0
        risk_admission = select_windows_under_budget(windows, budget_fraction=fraction)
        coverage_admission = select_windows_under_budget(
            windows,
            budget_fraction=fraction,
            min_high_value=False,
        )
        policies[f"budget-risk-{value}"] = _metrics(
            windows,
            set(risk_admission.get("selected_window_ids") or set()),
            call_mode="representative-alerts",
            admission=risk_admission,
        )
        policies[f"budget-coverage-{value}"] = _metrics(
            windows,
            set(coverage_admission.get("selected_window_ids") or set()),
            call_mode="representative-alerts",
            admission=coverage_admission,
        )
    return policies


def _metrics(
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
    external_calls = _external_call_count(selected, call_mode=call_mode)
    pressure_total = sum(1 for window in windows if _has_pressure(window))
    pressure_skipped = sum(1 for window in windows if _has_pressure(window) and str(window.get("window_id") or "") not in selected_window_ids)
    evidence_covered = sum(1 for window in selected if _evidence_target_covered(window))
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
        "budget_summary": _budget_summary(admission),
    }


def _external_call_count(windows: list[dict[str, Any]], *, call_mode: str) -> int:
    if call_mode == "all-alerts":
        return sum(int(window.get("alert_count") or 0) for window in windows)
    if call_mode == "high-value-alerts":
        return sum(max(1, int(window.get("high_value_count") or 0)) for window in windows)
    if call_mode == "representative-alerts":
        return sum(_representative_cost(window) for window in windows)
    raise ValueError(f"unknown call mode: {call_mode}")


def _representative_cost(window: dict[str, Any]) -> int:
    targets = window.get("selected_evidence_targets") or {}
    values = targets.get("representative_alert_ids") or targets.get("alert_ids") or []
    return max(1, len([value for value in values if str(value)]))


def _has_pressure(window: dict[str, Any]) -> bool:
    return bool(
        window.get("topology_pressure")
        or window.get("recurrence_pressure")
        or window.get("multi_device_spread")
    )


def _evidence_target_covered(window: dict[str, Any]) -> bool:
    targets = window.get("selected_evidence_targets") or {}
    return bool(targets.get("devices") and targets.get("path_signatures") and targets.get("representative_alert_ids"))


def _budget_summary(admission: dict[str, Any] | None) -> dict[str, Any]:
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


def _to_alert(record: dict[str, Any], idx: int) -> dict[str, Any]:
    device = str(record.get("service") or record.get("root_service") or record.get("root_cause") or "unknown")
    root = str(record.get("root_cause") or record.get("root_service") or device)
    scenario = str(record.get("fault_type") or record.get("scenario") or record.get("label") or "unknown").lower()
    severity = "warning"
    if str(record.get("severity") or "").lower() == "critical":
        severity = "critical"
    return {
        "alert_id": str(record.get("alert_id") or record.get("id") or f"external-{idx}"),
        "rule_id": "external_validation_fault_v1",
        "severity": severity,
        "alert_ts": str(record.get("timestamp") or record.get("time") or record.get("start_time") or ""),
        "dimensions": {
            "src_device_key": device,
            "fault_scenario": scenario,
            "ground_truth_root_service": root,
        },
        "metrics": {
            "label_value": scenario,
            "metric_name": str(record.get("metric_name") or ""),
            "anomaly_score": record.get("anomaly_score"),
        },
        "event_excerpt": {
            "src_device_key": device,
            "service": device,
            "ground_truth_root_service": root,
            "is_root_cause": bool(record.get("is_root_cause")),
            "case_id": str(record.get("case_id") or ""),
        },
        "topology_context": {
            "src_device_key": device,
            "path_signature": str(record.get("path_signature") or record.get("trace_id") or device),
            "downstream_dependents": str(record.get("downstream_dependents") or "0"),
            "path_up": str(record.get("path_up") or ""),
        },
        "device_profile": {
            "src_device_key": device,
            "device_name": device,
        },
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _write_windows_jsonl(path: Path, windows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fp:
        for window in windows:
            fp.write(json.dumps(window, ensure_ascii=True, sort_keys=True) + "\n")


def _write_labels_jsonl(path: Path, windows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fp:
        for window in windows:
            fp.write(json.dumps(build_weak_window_label(window), ensure_ascii=True, sort_keys=True) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run admission-layer external validation on RCAEval-style JSONL.")
    parser.add_argument("--dataset-jsonl", required=True)
    parser.add_argument("--window-sec", type=int, default=600)
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-windows-jsonl", default="")
    parser.add_argument("--output-labels-jsonl", default="")
    run(parser.parse_args())


if __name__ == "__main__":
    main()
