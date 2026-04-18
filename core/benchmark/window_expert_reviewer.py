from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from core.aiops_agent.alert_reasoning_runtime.window_labeling import build_weak_window_label


REVIEWER_ID = "codex_structural_window_review_v1"


def run(args: argparse.Namespace) -> dict[str, Any]:
    windows = _read_jsonl(Path(args.windows_jsonl))
    records = [_review_record(window) for window in windows]
    if args.output_jsonl:
        output = Path(args.output_jsonl)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", encoding="utf-8") as fp:
            for record in records:
                fp.write(json.dumps(record, ensure_ascii=True, sort_keys=True) + "\n")

    summary = _summary(records)
    summary.update(
        {
            "schema_version": 1,
            "windows_jsonl": args.windows_jsonl,
            "output_jsonl": args.output_jsonl,
            "reviewer": REVIEWER_ID,
            "review_scope": (
                "expert-style structural review from deterministic window fields; "
                "not a substitute for independent human operator labels"
            ),
        }
    )
    if args.output_json:
        output_json = Path(args.output_json)
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(
            json.dumps(summary, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(summary, ensure_ascii=True, indent=2, sort_keys=True))
    return summary


def _review_record(window: dict[str, Any]) -> dict[str, Any]:
    return {
        "window": window,
        "weak_label": build_weak_window_label(window),
        "expert_label": review_window(window),
    }


def review_window(window: dict[str, Any]) -> dict[str, Any]:
    label = str(window.get("window_label") or "")
    high_value = int(window.get("high_value_count") or 0) > 0
    alert_count = int(window.get("alert_count") or 0)
    device_count = int(window.get("device_count") or 0)
    path_count = int(window.get("path_count") or 0)
    pressure_score = int(window.get("pressure_score") or 0)
    recurrence = bool(window.get("recurrence_pressure"))
    topology = bool(window.get("topology_pressure"))
    spread = bool(window.get("multi_device_spread"))
    downstream = int(window.get("max_downstream_dependents") or 0)
    representatives = _representative_ids(window)
    selected_devices = (window.get("selected_evidence_targets") or {}).get("devices") or []
    selected_paths = (window.get("selected_evidence_targets") or {}).get("path_signatures") or []
    coverage = _representative_coverage(window)

    should_invoke = _should_invoke(
        label=label,
        high_value=high_value,
        alert_count=alert_count,
        pressure_score=pressure_score,
        recurrence=recurrence,
        topology=topology,
        spread=spread,
        downstream=downstream,
    )
    timeline_required = alert_count > 1 or recurrence or spread
    timeline_sufficient = (not timeline_required) or len(window.get("timeline") or []) >= 2
    representative_sufficient = bool(representatives) and coverage >= (0.67 if should_invoke else 0.34)
    selected_device_covered = bool(selected_devices) and (not should_invoke or len(selected_devices) >= min(device_count, 1))
    selected_path_covered = bool(selected_paths) and (not should_invoke or len(selected_paths) >= min(path_count, 1))
    false_skip = bool(should_invoke)

    return {
        "schema_version": 1,
        "reviewer": REVIEWER_ID,
        "label_source": "expert_style_structural_review",
        "should_invoke_external": bool(should_invoke),
        "representative_alert_sufficient": bool(representative_sufficient),
        "selected_device_covered": bool(selected_device_covered),
        "selected_path_covered": bool(selected_path_covered),
        "timeline_sufficient": bool(timeline_sufficient),
        "false_skip_if_local": bool(false_skip),
        "risk_level": _risk_level(
            should_invoke=should_invoke,
            high_value=high_value,
            pressure_score=pressure_score,
            spread=spread,
        ),
        "review_notes": _review_notes(
            label=label,
            should_invoke=should_invoke,
            high_value=high_value,
            pressure_score=pressure_score,
            recurrence=recurrence,
            topology=topology,
            spread=spread,
            representative_sufficient=representative_sufficient,
        ),
    }


def _should_invoke(
    *,
    label: str,
    high_value: bool,
    alert_count: int,
    pressure_score: int,
    recurrence: bool,
    topology: bool,
    spread: bool,
    downstream: int,
) -> bool:
    if high_value or label in {"external_induced_fault", "mixed_fault_and_transient"}:
        return True
    if spread and alert_count >= 2:
        return True
    if recurrence and (topology or downstream >= 10 or alert_count >= 4):
        return True
    if label == "external_unknown_with_pressure" and pressure_score >= 2:
        return True
    return False


def _risk_level(*, should_invoke: bool, high_value: bool, pressure_score: int, spread: bool) -> str:
    if high_value or (should_invoke and spread):
        return "high"
    if should_invoke or pressure_score >= 2:
        return "medium"
    return "low"


def _review_notes(
    *,
    label: str,
    should_invoke: bool,
    high_value: bool,
    pressure_score: int,
    recurrence: bool,
    topology: bool,
    spread: bool,
    representative_sufficient: bool,
) -> str:
    reasons: list[str] = [f"window_label={label}"]
    if high_value:
        reasons.append("high-value evidence present")
    if spread:
        reasons.append("multi-device spread present")
    if recurrence:
        reasons.append("recurrence pressure present")
    if topology:
        reasons.append("topology pressure present")
    if pressure_score:
        reasons.append(f"pressure_score={pressure_score}")
    if not representative_sufficient:
        reasons.append("representative set requires follow-up review")
    reasons.append("external path recommended" if should_invoke else "bounded local path acceptable")
    return "; ".join(reasons)


def _representative_coverage(window: dict[str, Any]) -> float:
    selection = ((window.get("selected_evidence_targets") or {}).get("representative_selection") or {})
    coverage = selection.get("coverage") or {}
    try:
        return float(coverage.get("coverage_rate") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _representative_ids(window: dict[str, Any]) -> list[str]:
    selected = window.get("selected_evidence_targets") or {}
    values = selected.get("representative_alert_ids") or selected.get("alert_ids") or []
    return [str(value) for value in values if str(value)]


def _summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    labels = [record.get("expert_label") or {} for record in records]
    return {
        "windows_reviewed": len(records),
        "should_invoke_external": sum(1 for label in labels if label.get("should_invoke_external")),
        "local_windows": sum(1 for label in labels if not label.get("should_invoke_external")),
        "false_skip_if_local": sum(1 for label in labels if label.get("false_skip_if_local")),
        "representative_sufficient": sum(1 for label in labels if label.get("representative_alert_sufficient")),
        "selected_device_covered": sum(1 for label in labels if label.get("selected_device_covered")),
        "selected_path_covered": sum(1 for label in labels if label.get("selected_path_covered")),
        "timeline_sufficient": sum(1 for label in labels if label.get("timeline_sufficient")),
        "risk_levels": dict(Counter(str(label.get("risk_level") or "unknown") for label in labels).most_common()),
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
    parser = argparse.ArgumentParser(description="Create expert-style structural reviews for incident windows.")
    parser.add_argument("--windows-jsonl", required=True)
    parser.add_argument("--output-jsonl", default="")
    parser.add_argument("--output-json", default="")
    run(parser.parse_args())


if __name__ == "__main__":
    main()
