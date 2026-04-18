from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from core.aiops_agent.alert_reasoning_runtime.budget_controller import select_windows_under_budget
from core.aiops_agent.alert_reasoning_runtime.incident_window import build_incident_window_index


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
    if args.output_json:
        path = Path(args.output_json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
    return report


def _policy_metrics(windows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        "invoke-all": _metrics(windows, {str(window.get("window_id") or "") for window in windows}),
        "scenario-only": _metrics(
            windows,
            {
                str(window.get("window_id") or "")
                for window in windows
                if int(window.get("high_value_count") or 0) > 0
            },
        ),
        "window-risk-tier": _metrics(
            windows,
            {
                str(window.get("window_id") or "")
                for window in windows
                if str(window.get("recommended_action") or "") == "external"
                or str(window.get("risk_tier") or "") == "high"
            },
        ),
        "budget-risk-20": _metrics(
            windows,
            set(select_windows_under_budget(windows, budget_fraction=0.20).get("selected_window_ids") or set()),
        ),
        "budget-coverage-20": _metrics(
            windows,
            set(
                select_windows_under_budget(
                    windows,
                    budget_fraction=0.20,
                    min_high_value=False,
                ).get("selected_window_ids")
                or set()
            ),
        ),
    }


def _metrics(windows: list[dict[str, Any]], selected_window_ids: set[str]) -> dict[str, Any]:
    total = len(windows)
    high_value_total = sum(1 for window in windows if int(window.get("high_value_count") or 0) > 0)
    selected = [
        window for window in windows
        if str(window.get("window_id") or "") in selected_window_ids
    ]
    high_value_retained = sum(1 for window in selected if int(window.get("high_value_count") or 0) > 0)
    representative_calls = sum(_representative_cost(window) for window in selected)
    return {
        "selected_windows": len(selected),
        "representative_calls": representative_calls,
        "window_reduction_percent": round((1 - len(selected) / max(total, 1)) * 100, 2),
        "high_value_window_recall": round(high_value_retained / max(high_value_total, 1), 6),
        "high_value_windows_retained": high_value_retained,
        "high_value_windows_total": high_value_total,
    }


def _representative_cost(window: dict[str, Any]) -> int:
    targets = window.get("selected_evidence_targets") or {}
    values = targets.get("representative_alert_ids") or targets.get("alert_ids") or []
    return max(1, len([value for value in values if str(value)]))


def _to_alert(record: dict[str, Any], idx: int) -> dict[str, Any]:
    root = str(record.get("root_cause") or record.get("root_service") or record.get("service") or "unknown")
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
            "src_device_key": root,
            "fault_scenario": scenario,
        },
        "metrics": {
            "label_value": scenario,
        },
        "event_excerpt": {
            "src_device_key": root,
            "service": str(record.get("service") or root),
        },
        "topology_context": {
            "src_device_key": root,
            "path_signature": str(record.get("path_signature") or record.get("trace_id") or root),
            "downstream_dependents": str(record.get("downstream_dependents") or "0"),
            "path_up": str(record.get("path_up") or ""),
        },
        "device_profile": {
            "src_device_key": root,
            "device_name": root,
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Run admission-layer external validation on RCAEval-style JSONL.")
    parser.add_argument("--dataset-jsonl", required=True)
    parser.add_argument("--window-sec", type=int, default=600)
    parser.add_argument("--output-json", default="")
    run(parser.parse_args())


if __name__ == "__main__":
    main()
