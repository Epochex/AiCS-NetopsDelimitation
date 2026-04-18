from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, pstdev
from typing import Any


DEFAULT_TOP_SYMPTOMS = 5
PRE_WINDOW_SEC = 600
POST_WINDOW_SEC = 600


def run(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.re1_root)
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
        records.extend(converted["records"])
        case_summaries.append(converted["summary"])

    output = Path(args.output_jsonl)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as fp:
        for record in records:
            fp.write(json.dumps(record, ensure_ascii=True, sort_keys=True) + "\n")

    summary = {
        "schema_version": 1,
        "source": "RCAEval RE1",
        "source_root": str(root),
        "cases": len(cases),
        "records": len(records),
        "root_cause_records": sum(1 for item in records if item.get("is_root_cause")),
        "symptom_records": sum(1 for item in records if not item.get("is_root_cause")),
        "top_symptoms": args.top_symptoms,
        "min_symptom_score": args.min_symptom_score,
        "benchmarks": _counts(case_summaries, "benchmark"),
        "fault_types": _counts(case_summaries, "fault_type"),
        "services": _counts(case_summaries, "root_service"),
        "output_jsonl": str(output),
        "conversion_scope": (
            "metric-derived admission records; RCAEval ground-truth service and fault labels are preserved"
        ),
    }
    if args.output_summary_json:
        summary_path = Path(args.output_summary_json)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(
            json.dumps(summary, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(summary, ensure_ascii=True, indent=2, sort_keys=True))
    return summary


def _find_cases(root: Path) -> list[Path]:
    cases = [
        path
        for path in root.glob("RE1-*/*/*")
        if (path / "data.csv").exists() and (path / "inject_time.txt").exists()
    ]
    return sorted(cases, key=lambda path: str(path))


def _convert_case(*, case_dir: Path, top_symptoms: int, min_symptom_score: float) -> dict[str, Any]:
    benchmark = case_dir.parents[1].name
    service_fault = case_dir.parent.name
    run_id = case_dir.name
    root_service, fault_type = _parse_service_fault(service_fault)
    inject_ts = int((case_dir / "inject_time.txt").read_text(encoding="utf-8").strip())
    rows = _read_csv(case_dir / "data.csv")
    symptoms = _rank_symptoms(
        rows=rows,
        inject_ts=inject_ts,
        root_service=root_service,
        top_symptoms=top_symptoms,
        min_symptom_score=min_symptom_score,
    )
    case_id = f"{benchmark}:{service_fault}:{run_id}"
    downstream = max(len(symptoms), 1)
    records = [
        _root_record(
            case_id=case_id,
            benchmark=benchmark,
            run_id=run_id,
            root_service=root_service,
            fault_type=fault_type,
            inject_ts=inject_ts,
            downstream=downstream,
        )
    ]
    for idx, symptom in enumerate(symptoms, start=1):
        records.append(
            _symptom_record(
                case_id=case_id,
                benchmark=benchmark,
                run_id=run_id,
                root_service=root_service,
                fault_type=fault_type,
                inject_ts=inject_ts + idx,
                downstream=downstream,
                rank=idx,
                symptom=symptom,
            )
        )
    return {
        "records": records,
        "summary": {
            "case_id": case_id,
            "benchmark": benchmark,
            "root_service": root_service,
            "fault_type": fault_type,
            "run_id": run_id,
            "symptoms": len(symptoms),
        },
    }


def _root_record(
    *,
    case_id: str,
    benchmark: str,
    run_id: str,
    root_service: str,
    fault_type: str,
    inject_ts: int,
    downstream: int,
) -> dict[str, Any]:
    scenario = f"rcaeval_{fault_type}_fault"
    return {
        "id": f"{case_id}:root",
        "timestamp": _iso(inject_ts),
        "benchmark": benchmark,
        "case_id": case_id,
        "run_id": run_id,
        "service": root_service,
        "root_cause": root_service,
        "fault_type": scenario,
        "ground_truth_fault_type": fault_type,
        "is_root_cause": True,
        "path_signature": _path_signature(case_id=case_id, service=root_service),
        "downstream_dependents": downstream,
        "metric_name": f"{root_service}_{fault_type}",
        "anomaly_score": None,
    }


def _symptom_record(
    *,
    case_id: str,
    benchmark: str,
    run_id: str,
    root_service: str,
    fault_type: str,
    inject_ts: int,
    downstream: int,
    rank: int,
    symptom: dict[str, Any],
) -> dict[str, Any]:
    service = str(symptom["service"])
    return {
        "id": f"{case_id}:symptom:{rank}",
        "timestamp": _iso(inject_ts),
        "benchmark": benchmark,
        "case_id": case_id,
        "run_id": run_id,
        "service": service,
        "root_cause": root_service,
        "fault_type": "transient_fault",
        "ground_truth_fault_type": fault_type,
        "is_root_cause": False,
        "path_signature": _path_signature(case_id=case_id, service=service),
        "downstream_dependents": downstream,
        "metric_name": symptom["metric"],
        "metric_kind": symptom["metric_kind"],
        "anomaly_score": round(float(symptom["score"]), 6),
        "pre_mean": round(float(symptom["pre_mean"]), 6),
        "post_mean": round(float(symptom["post_mean"]), 6),
    }


def _path_signature(*, case_id: str, service: str) -> str:
    return f"{service}|case={case_id}"


def _rank_symptoms(
    *,
    rows: list[dict[str, str]],
    inject_ts: int,
    root_service: str,
    top_symptoms: int,
    min_symptom_score: float,
) -> list[dict[str, Any]]:
    if not rows:
        return []
    columns = [
        column
        for column in rows[0].keys()
        if column != "time" and not column.startswith("time.") and _metric_service(column)
    ]
    pre = [row for row in rows if inject_ts - PRE_WINDOW_SEC <= _safe_int(row.get("time")) < inject_ts]
    post = [row for row in rows if inject_ts <= _safe_int(row.get("time")) < inject_ts + POST_WINDOW_SEC]
    if not pre or not post:
        return []

    per_service: dict[str, dict[str, Any]] = {}
    for column in columns:
        service = _metric_service(column)
        if not service or service == root_service:
            continue
        pre_values = [_safe_float(row.get(column)) for row in pre]
        post_values = [_safe_float(row.get(column)) for row in post]
        pre_values = [value for value in pre_values if math.isfinite(value)]
        post_values = [value for value in post_values if math.isfinite(value)]
        if not pre_values or not post_values:
            continue
        pre_mean = mean(pre_values)
        post_mean = mean(post_values)
        scale = max(abs(pre_mean) * 0.05, pstdev(pre_values) if len(pre_values) > 1 else 0.0, 1e-6)
        score = abs(post_mean - pre_mean) / scale
        if score < min_symptom_score:
            continue
        current = per_service.get(service)
        if current is None or score > float(current["score"]):
            per_service[service] = {
                "service": service,
                "metric": column,
                "metric_kind": _metric_kind(column),
                "score": score,
                "pre_mean": pre_mean,
                "post_mean": post_mean,
            }
    return sorted(per_service.values(), key=lambda item: float(item["score"]), reverse=True)[:top_symptoms]


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as fp:
        return list(csv.DictReader(fp))


def _parse_service_fault(value: str) -> tuple[str, str]:
    if "_" not in value:
        return value, "unknown"
    service, fault = value.rsplit("_", 1)
    return service, fault


def _metric_service(column: str) -> str:
    if "_" not in column:
        return ""
    service, _ = column.rsplit("_", 1)
    return service


def _metric_kind(column: str) -> str:
    if "_" not in column:
        return "unknown"
    return column.rsplit("_", 1)[-1]


def _safe_int(value: Any) -> int:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return float("nan")


def _iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


def _counts(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for item in items:
        counts[str(item.get(key) or "unknown")] += 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert RCAEval RE1 metric cases into admission records.")
    parser.add_argument("--re1-root", required=True)
    parser.add_argument("--output-jsonl", required=True)
    parser.add_argument("--output-summary-json", default="")
    parser.add_argument("--top-symptoms", type=int, default=DEFAULT_TOP_SYMPTOMS)
    parser.add_argument("--min-symptom-score", type=float, default=1.0)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
