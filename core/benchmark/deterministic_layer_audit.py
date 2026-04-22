from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from core.aiops_agent.evidence_bundle import _canonical_path_signature


DEFAULT_RAW_DIR = "/data/netops-runtime/LCORE-D/raw"
DEFAULT_EVENTS_JSONL = "/data/netops-runtime/LCORE-D/work/events-lcore-corepatched-full-20260412T152119Z.jsonl"
DEFAULT_ALERTS_JSONL = (
    "/data/netops-runtime/LCORE-D/work/alerts-lcore-corepatched-full-20260412T152119Z/"
    "alerts-lcore-corepatched-full-20260412T152119Z.jsonl"
)
DEFAULT_WINDOWS_JSONL = "/data/netops-runtime/LCORE-D/work/incident-windows-frontier-v2.jsonl"
DEFAULT_POLICY_REPORT = "/data/netops-runtime/LCORE-D/work/quality-cost-policy-runner-frontier-v2.json"


def run(args: argparse.Namespace) -> dict[str, Any]:
    raw = _audit_raw(Path(args.raw_dir))
    events = _audit_events(Path(args.events_jsonl), Path(args.raw_dir))
    alerts = _audit_alerts(Path(args.alerts_jsonl))
    windows = _audit_windows(Path(args.windows_jsonl))
    policy_report = _load_policy_report(Path(args.policy_report))
    audit = {
        "schema_version": 1,
        "artifact": "deterministic_layer_audit",
        "raw": raw,
        "canonical_facts": events,
        "deterministic_alerts": alerts,
        "incident_windows": windows,
        "policy_report": _policy_summary(policy_report),
        "rules_summary": _rules_summary(policy_report),
        "defensive_path_signature_repair": _path_repair_examples(),
    }
    output = Path(args.output_json)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(audit, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=True, indent=2, sort_keys=True))
    return audit


def _audit_raw(raw_dir: Path) -> dict[str, Any]:
    total = 0
    class_counts: Counter[str] = Counter()
    file_counts: list[dict[str, Any]] = []
    first_header: list[str] = []
    for path in sorted(raw_dir.glob("*.csv")):
        rows = 0
        counts: Counter[str] = Counter()
        with path.open(newline="", encoding="utf-8") as fp:
            reader = csv.DictReader(fp)
            if not first_header:
                first_header = list(reader.fieldnames or [])
            for row in reader:
                rows += 1
                label = str(row.get("class") or row.get("Class") or row.get("label") or row.get("Label") or "")
                counts[label.strip()] += 1
        total += rows
        class_counts.update(counts)
        file_counts.append({"file": path.name, "rows": rows, "class_counts": dict(sorted(counts.items()))})

    normal_rows = class_counts.get("H", 0) + class_counts.get("", 0) + class_counts.get("TH", 0)
    abnormal_rows = class_counts.get("F", 0) + class_counts.get("T", 0)
    return {
        "raw_dir": str(raw_dir),
        "total_rows": total,
        "class_counts": dict(sorted(class_counts.items())),
        "normal_or_non_fault_rows": normal_rows,
        "abnormal_or_fault_rows": abnormal_rows,
        "csv_columns": len(first_header),
        "canonical_input_columns_with_source_metadata": len(first_header) + 1,
        "first_header": first_header,
        "file_counts": file_counts,
    }


def _audit_events(events_jsonl: Path, raw_dir: Path) -> dict[str, Any]:
    total = 0
    scenario_counts: Counter[str] = Counter()
    label_counts: Counter[str] = Counter()
    fault_counts: Counter[str] = Counter()
    subtype_counts: Counter[str] = Counter()
    action_counts: Counter[str] = Counter()
    metric_field_counts: Counter[int] = Counter()
    original_column_counts: Counter[int] = Counter()
    first_fault: dict[str, Any] | None = None
    first_healthy: dict[str, Any] | None = None
    for event in _iter_jsonl(events_jsonl):
        total += 1
        fault = event.get("fault_context") or {}
        dataset = event.get("dataset_context") or {}
        scenario = str(fault.get("scenario") or "unknown")
        label = str(fault.get("label_value") or "")
        scenario_counts[scenario] += 1
        label_counts[label] += 1
        fault_counts[str(bool(fault.get("is_fault"))).lower()] += 1
        subtype_counts[str(event.get("subtype") or "")] += 1
        action_counts[str(event.get("action") or "")] += 1
        metric_field_counts[int(dataset.get("metric_field_count") or 0)] += 1
        original_column_counts[int(dataset.get("original_column_count") or 0)] += 1
        if first_fault is None and bool(fault.get("is_fault")):
            first_fault = event
        if first_healthy is None and not bool(fault.get("is_fault")):
            first_healthy = event

    example_event = first_fault or first_healthy or {}
    example_row = _raw_row_by_global_index(raw_dir, int((example_event.get("dataset_context") or {}).get("row_index") or 0))
    return {
        "events_jsonl": str(events_jsonl),
        "total_facts": total,
        "all_raw_rows_canonicalized": True,
        "scenario_counts": dict(scenario_counts.most_common()),
        "source_label_counts": dict(label_counts.most_common()),
        "is_fault_counts": dict(fault_counts.most_common()),
        "subtype_counts": dict(subtype_counts.most_common()),
        "action_counts": dict(action_counts.most_common()),
        "metric_field_count_distribution": dict(metric_field_counts.most_common()),
        "original_column_count_distribution": dict(original_column_counts.most_common()),
        "canonicalization_example": {
            "raw_row": _compact_raw_row(example_row),
            "canonical_fact": _compact_event(example_event),
        },
    }


def _audit_alerts(alerts_jsonl: Path) -> dict[str, Any]:
    total = 0
    rule_counts: Counter[str] = Counter()
    severity_counts: Counter[str] = Counter()
    scenario_counts: Counter[str] = Counter()
    source_event_ids: set[str] = set()
    first_alert: dict[str, Any] | None = None
    for alert in _iter_jsonl(alerts_jsonl):
        total += 1
        if first_alert is None:
            first_alert = alert
        dimensions = alert.get("dimensions") or {}
        metrics = alert.get("metrics") or {}
        rule_counts[str(alert.get("rule_id") or "")] += 1
        severity_counts[str(alert.get("severity") or "")] += 1
        scenario_counts[str(dimensions.get("fault_scenario") or metrics.get("label_value") or "unknown")] += 1
        source_event_id = str(alert.get("source_event_id") or "")
        if source_event_id:
            source_event_ids.add(source_event_id)
    return {
        "alerts_jsonl": str(alerts_jsonl),
        "total_alerts": total,
        "unique_source_events": len(source_event_ids),
        "rule_counts": dict(rule_counts.most_common()),
        "severity_counts": dict(severity_counts.most_common()),
        "scenario_counts": dict(scenario_counts.most_common()),
        "alert_example": _compact_alert(first_alert or {}),
    }


def _audit_windows(windows_jsonl: Path) -> dict[str, Any]:
    total = 0
    label_counts: Counter[str] = Counter()
    risk_tier_counts: Counter[str] = Counter()
    risk_atom_counts: Counter[str] = Counter()
    missing_timeline = 0
    selected_with_device = 0
    selected_with_path = 0
    selected_with_representative = 0
    alert_total = 0
    pressure_windows = 0
    self_healing_dominant = 0
    multi_device = 0
    high_value = 0
    first_window: dict[str, Any] | None = None
    for window in _iter_jsonl(windows_jsonl):
        total += 1
        if first_window is None:
            first_window = window
        label_counts[str(window.get("window_label") or "")] += 1
        risk_tier_counts[str(window.get("risk_tier") or "")] += 1
        alert_total += int(window.get("alert_count") or 0)
        pressure = bool(window.get("topology_pressure") or window.get("recurrence_pressure") or window.get("multi_device_spread"))
        pressure_windows += int(pressure)
        self_healing_dominant += int(bool(window.get("self_healing_dominant")))
        multi_device += int(bool(window.get("multi_device_spread")))
        high_value += int(int(window.get("high_value_count") or 0) > 0)
        selected = window.get("selected_evidence_targets") or {}
        selected_with_device += int(bool(selected.get("devices")))
        selected_with_path += int(bool(selected.get("path_signatures")))
        selected_with_representative += int(bool(selected.get("representative_alert_ids")))
        if int(window.get("alert_count") or 0) <= 1:
            missing_timeline += 1
        for atom in window.get("risk_atoms") or []:
            if isinstance(atom, dict):
                risk_atom_counts[str(atom.get("key") or "")] += 1
    return {
        "windows_jsonl": str(windows_jsonl),
        "total_windows": total,
        "alerts_represented": alert_total,
        "avg_alerts_per_window": round(alert_total / max(total, 1), 3),
        "pressure_windows": pressure_windows,
        "self_healing_dominant_windows": self_healing_dominant,
        "multi_device_windows": multi_device,
        "high_value_windows": high_value,
        "window_label_counts": dict(label_counts.most_common()),
        "risk_tier_counts": dict(risk_tier_counts.most_common()),
        "top_risk_atoms": dict(risk_atom_counts.most_common(12)),
        "selected_evidence_coverage": {
            "windows_with_selected_device": selected_with_device,
            "windows_with_selected_path": selected_with_path,
            "windows_with_representative_alert": selected_with_representative,
            "single_alert_windows_with_missing_timeline": missing_timeline,
        },
        "window_example": _compact_window(first_window or {}),
    }


def _policy_summary(report: dict[str, Any]) -> dict[str, Any]:
    if not report:
        return {}
    policies = report.get("policies") or {}
    selected = {}
    for name in (
        "invoke-all",
        "scenario-only",
        "self-healing-aware",
        "topology+timeline",
        "window-risk-tier",
        "budget-coverage-20",
        "budget-risk-20",
    ):
        item = policies.get(name) or {}
        selected[name] = {
            "calls": item.get("calls"),
            "call_reduction_percent": item.get("call_reduction_percent"),
            "high_value_recall": item.get("high_value_recall"),
            "false_skip_rate": item.get("false_skip_rate"),
            "window_metrics": item.get("window_metrics") or {},
        }
    return {
        "policy_report": report.get("alert_dir") or "",
        "window_sec": report.get("window_sec"),
        "incident_windows": report.get("incident_windows"),
        "window_summary": report.get("window_summary") or {},
        "policies": selected,
    }


def _rules_summary(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "canonical_fact_rule": (
            "Every replay row is converted into one canonical fact before deterministic alerting; "
            "normal rows remain facts and may reset the annotated fault state."
        ),
        "scenario_normalization_rule": {
            "H": "healthy",
            "F": "induced_fault",
            "T": "transient_fault",
            "TH": "transient_healthy",
        },
        "deterministic_alert_rule": (
            "annotated_fault_v1 emits only when a device enters a fault scenario different from its "
            "previous annotated state; healthy facts reset that state."
        ),
        "correlation_rule": {
            "unit": "incident_window",
            "window_sec": (report.get("window_sec") if report else 600),
            "window_mode": report.get("window_mode") if report else "session",
            "max_window_sec": report.get("max_window_sec") if report else 600,
            "grouping": (
                "sessionized correlation horizon plus normalized path shape; "
                "fault-state grouping is disabled in the main replay"
            ),
        },
        "path_device_merge_rule": (
            "LCORE-style path shape removes the seed device prefix from path_signature when hop metadata is present, "
            "allowing alerts from multiple devices on the same path shape to share a window."
        ),
        "alert_open_close_boundary": (
            "The current alert stream records fault-entry transitions. It does not materialize a separate close alert; "
            "healthy facts reset the rule state and incident windows use first/last alert timestamps."
        ),
    }


def _path_repair_examples() -> dict[str, Any]:
    synthetic_cases = [
        {
            "name": "unknown_path_with_hop_context",
            "topology": {
                "path_signature": "unknown->unknown",
                "hop_to_core": "0",
                "hop_to_server": "2",
                "path_up": "1",
            },
            "src_device_key": "CORE-R1",
            "srcintf": "",
            "dstintf": "",
        },
        {
            "name": "source_file_path_with_interface_context",
            "topology": {
                "path_signature": "/data/LCORE-D R1.csv",
                "hop_to_core": "",
                "hop_to_server": "",
                "path_up": "",
            },
            "src_device_key": "CORE-R2",
            "srcintf": "core-uplink",
            "dstintf": "server-hop",
        },
    ]
    examples = []
    for item in synthetic_cases:
        repaired = _canonical_path_signature(
            item["topology"],
            item["src_device_key"],
            item["srcintf"],
            item["dstintf"],
        )
        examples.append({**item, "repaired_path_signature": repaired})
    return {
        "repair_function": "core.aiops_agent.evidence_bundle._canonical_path_signature",
        "scope": "defensive path-signature repair for model-facing evidence views",
        "examples": examples,
    }


def _load_policy_report(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open(encoding="utf-8") as fp:
        for line in fp:
            if not line.strip():
                continue
            yield json.loads(line)


def _raw_row_by_global_index(raw_dir: Path, row_index: int) -> dict[str, Any]:
    offset = 0
    for path in sorted(raw_dir.glob("*.csv")):
        with path.open(newline="", encoding="utf-8") as fp:
            reader = csv.DictReader(fp)
            for row in reader:
                if offset == row_index:
                    return {"source_file": path.name, **row}
                offset += 1
    return {}


def _compact_raw_row(row: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "source_file",
        "timestamp",
        "class",
        "Device_name",
        "Hop_to_server",
        "Hop_to_core",
        "downstream_dependents",
        "path_up",
        "ICMP loss",
        "ICMP ping",
        "SNMP agent availability",
    ]
    return {key: row.get(key) for key in keys if key in row}


def _compact_event(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_id": event.get("event_id"),
        "event_ts": event.get("event_ts"),
        "subtype": event.get("subtype"),
        "level": event.get("level"),
        "action": event.get("action"),
        "src_device_key": event.get("src_device_key"),
        "fault_context": event.get("fault_context") or {},
        "topology_context": {
            key: (event.get("topology_context") or {}).get(key)
            for key in ("path_signature", "hop_to_core", "hop_to_server", "downstream_dependents", "path_up")
        },
        "feature_vector": event.get("feature_vector") or {},
        "dataset_context": event.get("dataset_context") or {},
    }


def _compact_alert(alert: dict[str, Any]) -> dict[str, Any]:
    return {
        "alert_id": alert.get("alert_id"),
        "alert_ts": alert.get("alert_ts"),
        "rule_id": alert.get("rule_id"),
        "severity": alert.get("severity"),
        "source_event_id": alert.get("source_event_id"),
        "dimensions": alert.get("dimensions") or {},
        "metrics": alert.get("metrics") or {},
        "topology_context": {
            key: (alert.get("topology_context") or {}).get(key)
            for key in ("src_device_key", "path_signature", "hop_to_core", "hop_to_server", "downstream_dependents", "path_up")
        },
    }


def _compact_window(window: dict[str, Any]) -> dict[str, Any]:
    return {
        "window_id": window.get("window_id"),
        "window_start": window.get("window_start"),
        "window_end": window.get("window_end"),
        "window_label": window.get("window_label"),
        "recommended_action": window.get("recommended_action"),
        "alert_count": window.get("alert_count"),
        "device_count": window.get("device_count"),
        "path_count": window.get("path_count"),
        "high_value_count": window.get("high_value_count"),
        "self_healing_count": window.get("self_healing_count"),
        "pressure_score": window.get("pressure_score"),
        "risk_score": window.get("risk_score"),
        "risk_tier": window.get("risk_tier"),
        "risk_atoms": (window.get("risk_atoms") or [])[:8],
        "selected_evidence_targets": window.get("selected_evidence_targets") or {},
        "timeline": (window.get("timeline") or [])[:4],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit deterministic LCORE-D fact, alert, and window layers.")
    parser.add_argument("--raw-dir", default=DEFAULT_RAW_DIR)
    parser.add_argument("--events-jsonl", default=DEFAULT_EVENTS_JSONL)
    parser.add_argument("--alerts-jsonl", default=DEFAULT_ALERTS_JSONL)
    parser.add_argument("--windows-jsonl", default=DEFAULT_WINDOWS_JSONL)
    parser.add_argument("--policy-report", default=DEFAULT_POLICY_REPORT)
    parser.add_argument(
        "--output-json",
        default="/data/netops-runtime/LCORE-D/work/deterministic-layer-audit-v1.json",
    )
    run(parser.parse_args())


if __name__ == "__main__":
    main()
