from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

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
    report = {
        "schema_version": 1,
        "dataset_jsonl": str(dataset),
        "input_records": len(records),
        "converted_alerts": len(alerts),
        "incident_windows": len(windows),
        "high_value_windows": high_value_windows,
        "window_labels": dict(label_counts.most_common()),
        "validation_scope": "admission-layer transfer only; does not claim RCA accuracy",
    }
    if args.output_json:
        path = Path(args.output_json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
    return report


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
            "path_up": str(record.get("path_up") or "1"),
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
