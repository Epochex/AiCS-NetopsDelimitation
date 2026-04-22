from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from core.aiops_agent.alert_reasoning_runtime.budget_controller import select_windows_under_budget
from core.aiops_agent.alert_reasoning_runtime.incident_window import build_incident_window_index
from core.aiops_agent.alert_reasoning_runtime.window_labeling import build_weak_window_label
from core.benchmark.admission_metrics import (
    read_jsonl,
    selected_window_metrics,
    write_jsonl,
)


BUDGET_FRACTIONS = (1, 2, 5, 10, 20, 40, 60)


def run(args: argparse.Namespace) -> dict[str, Any]:
    dataset = Path(args.dataset_jsonl)
    if not dataset.exists():
        raise FileNotFoundError(
            f"{dataset} does not exist. Export RCAEval incidents to JSONL before running external validation."
        )
    records = read_jsonl(dataset)
    alerts = [_to_alert(record, idx) for idx, record in enumerate(records)]
    windows, _ = build_incident_window_index(
        alerts,
        window_sec=args.window_sec,
        window_mode=str(getattr(args, "window_mode", "session") or "session"),
        max_window_sec=getattr(args, "max_window_sec", None),
    )
    label_counts = Counter(str(window.get("window_label") or "unknown") for window in windows)
    high_value_windows = sum(1 for window in windows if int(window.get("high_value_count") or 0) > 0)
    policies = _policy_metrics(windows)
    report = {
        "schema_version": 1,
        "dataset_jsonl": str(dataset),
        "input_records": len(records),
        "converted_alerts": len(alerts),
        "incident_windows": len(windows),
        "window_sec": args.window_sec,
        "window_mode": str(getattr(args, "window_mode", "session") or "session"),
        "max_window_sec": getattr(args, "max_window_sec", None) or args.window_sec,
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
        "invoke-all": selected_window_metrics(windows, all_windows, call_mode="all-alerts"),
        "scenario-only": selected_window_metrics(windows, high_value_windows, call_mode="high-value-alerts"),
        "window-risk-tier": selected_window_metrics(windows, risk_windows, call_mode="representative-alerts"),
        "oracle": selected_window_metrics(windows, high_value_windows, call_mode="high-value-alerts"),
    }
    for value in BUDGET_FRACTIONS:
        fraction = value / 100.0
        risk_admission = select_windows_under_budget(windows, budget_fraction=fraction)
        coverage_admission = select_windows_under_budget(
            windows,
            budget_fraction=fraction,
            min_high_value=False,
        )
        policies[f"budget-risk-{value}"] = selected_window_metrics(
            windows,
            set(risk_admission.get("selected_window_ids") or set()),
            call_mode="representative-alerts",
            admission=risk_admission,
        )
        policies[f"budget-coverage-{value}"] = selected_window_metrics(
            windows,
            set(coverage_admission.get("selected_window_ids") or set()),
            call_mode="representative-alerts",
            admission=coverage_admission,
        )
    return policies


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


def _write_windows_jsonl(path: Path, windows: list[dict[str, Any]]) -> None:
    write_jsonl(path, windows)


def _write_labels_jsonl(path: Path, windows: list[dict[str, Any]]) -> None:
    write_jsonl(path, [build_weak_window_label(window) for window in windows])


def main() -> None:
    parser = argparse.ArgumentParser(description="Run admission-layer external validation on RCAEval-style JSONL.")
    parser.add_argument("--dataset-jsonl", required=True)
    parser.add_argument("--window-sec", type=int, default=600)
    parser.add_argument(
        "--window-mode",
        choices=[
            "session",
            "fixed",
            "adaptive",
            "aics-topology",
            "aics-evidence",
            "aics",
        ],
        default="session",
    )
    parser.add_argument("--max-window-sec", type=int, default=0)
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-windows-jsonl", default="")
    parser.add_argument("--output-labels-jsonl", default="")
    run(parser.parse_args())


if __name__ == "__main__":
    main()
