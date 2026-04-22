from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from core.aiops_agent.alert_reasoning_runtime.incident_window import build_incident_window_index
from core.benchmark.external_validation_adapter import _to_alert
from core.benchmark.rcaeval_re1_converter import _convert_case


DEFAULT_TOP_SYMPTOMS = 5


def run(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.rcaeval_root)
    if not root.exists():
        raise FileNotFoundError(f"{root} does not exist")

    cases = _find_cases(root)
    records: list[dict[str, Any]] = []
    case_summaries: list[dict[str, Any]] = []
    for case_dir in cases:
        converted = _convert_case(
            case_dir=case_dir,
            top_symptoms=args.top_symptoms,
            min_symptom_score=args.min_symptom_score,
        )
        dataset_family, dataset_name = _dataset_names(case_dir)
        for record in converted["records"]:
            record["dataset_family"] = dataset_family
            record["dataset"] = dataset_name
            records.append(record)
        summary = {
            **converted["summary"],
            "dataset_family": dataset_family,
            "dataset": dataset_name,
            "case_dir": str(case_dir),
        }
        case_summaries.append(summary)

    windows, _ = build_incident_window_index(
        [_to_alert(record, idx) for idx, record in enumerate(records)],
        window_sec=args.window_sec,
        window_mode=str(getattr(args, "window_mode", "session") or "session"),
        max_window_sec=getattr(args, "max_window_sec", None),
    )

    _write_jsonl(Path(args.output_jsonl), records)
    if args.output_cases_jsonl:
        _write_jsonl(Path(args.output_cases_jsonl), case_summaries)
    if args.output_windows_jsonl:
        _write_jsonl(Path(args.output_windows_jsonl), windows)

    summary = {
        "schema_version": 1,
        "source": "RCAEval",
        "source_root": str(root),
        "cases": len(cases),
        "records": len(records),
        "incident_windows": len(windows),
        "window_sec": args.window_sec,
        "window_mode": str(getattr(args, "window_mode", "session") or "session"),
        "max_window_sec": getattr(args, "max_window_sec", None) or args.window_sec,
        "root_cause_records": sum(1 for item in records if item.get("is_root_cause")),
        "symptom_records": sum(1 for item in records if not item.get("is_root_cause")),
        "top_symptoms": args.top_symptoms,
        "min_symptom_score": args.min_symptom_score,
        "per_dataset": _per_dataset_summary(case_summaries, records, windows),
        "output_jsonl": str(Path(args.output_jsonl)),
        "output_windows_jsonl": str(Path(args.output_windows_jsonl)) if args.output_windows_jsonl else "",
        "conversion_scope": (
            "RCAEval metric cases converted to admission-layer records; ground-truth "
            "service, fault type, dataset, and run identity are preserved."
        ),
    }
    if args.output_summary_json:
        path = Path(args.output_summary_json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(summary, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=True, indent=2, sort_keys=True))
    return summary


def _find_cases(root: Path) -> list[Path]:
    search_roots = [root]
    if (root / "data").exists():
        search_roots.append(root / "data")

    cases: dict[str, Path] = {}
    for base in search_roots:
        for path in base.glob("RE*/*/*"):
            if (path / "data.csv").exists() and (path / "inject_time.txt").exists():
                cases[str(path.resolve())] = path
        for path in base.glob("*/RE*/*/*"):
            if (path / "data.csv").exists() and (path / "inject_time.txt").exists():
                cases[str(path.resolve())] = path
    return sorted(cases.values(), key=lambda item: str(item))


def _dataset_names(case_dir: Path) -> tuple[str, str]:
    dataset_name = "unknown"
    dataset_family = "unknown"
    for parent in case_dir.parents:
        if parent.name.startswith("RE") and "-" in parent.name:
            dataset_name = parent.name
        elif parent.name.startswith("RE") and "-" not in parent.name:
            dataset_family = parent.name
            break
    if dataset_family == "unknown" and dataset_name != "unknown":
        dataset_family = dataset_name.split("-", 1)[0]
    return dataset_family, dataset_name


def _per_dataset_summary(
    case_summaries: list[dict[str, Any]],
    records: list[dict[str, Any]],
    windows: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    per_dataset: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "dataset_family": "unknown",
            "cases": 0,
            "records": 0,
            "root_cause_records": 0,
            "symptom_records": 0,
            "incident_windows": 0,
            "root_services": {},
            "fault_types": {},
        }
    )
    for item in case_summaries:
        dataset = str(item.get("dataset") or "unknown")
        entry = per_dataset[dataset]
        entry["dataset_family"] = str(item.get("dataset_family") or "unknown")
        entry["cases"] += 1
        _increment(entry["root_services"], str(item.get("root_service") or "unknown"))
        _increment(entry["fault_types"], str(item.get("fault_type") or "unknown"))
    for item in records:
        dataset = str(item.get("dataset") or item.get("benchmark") or "unknown")
        entry = per_dataset[dataset]
        entry["records"] += 1
        if item.get("is_root_cause"):
            entry["root_cause_records"] += 1
        else:
            entry["symptom_records"] += 1
    record_dataset_by_id = {
        str(item.get("id") or ""): str(item.get("dataset") or item.get("benchmark") or "unknown")
        for item in records
    }
    for window in windows:
        datasets = {
            record_dataset_by_id.get(str(alert_id), "unknown")
            for alert_id in window.get("alert_ids") or []
            if str(alert_id)
        }
        if not datasets:
            datasets = {"unknown"}
        for dataset in datasets:
            per_dataset[dataset]["incident_windows"] += 1
    return dict(sorted(per_dataset.items(), key=lambda item: item[0]))


def _increment(values: dict[str, int], key: str) -> None:
    values[key] = int(values.get(key, 0)) + 1


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fp:
        for record in records:
            fp.write(json.dumps(record, ensure_ascii=True, sort_keys=True) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert all available RCAEval cases into AiCS admission records.")
    parser.add_argument("--rcaeval-root", required=True)
    parser.add_argument("--output-jsonl", required=True)
    parser.add_argument("--output-cases-jsonl", default="")
    parser.add_argument("--output-windows-jsonl", default="")
    parser.add_argument("--output-summary-json", default="")
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
    parser.add_argument("--top-symptoms", type=int, default=DEFAULT_TOP_SYMPTOMS)
    parser.add_argument("--min-symptom-score", type=float, default=1.0)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
