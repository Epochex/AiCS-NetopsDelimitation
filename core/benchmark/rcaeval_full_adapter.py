from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

from core.aiops_agent.alert_reasoning_runtime.incident_window import build_incident_window_index
from core.benchmark.external_validation_adapter import _to_alert
from core.benchmark.rcaeval_re1_converter import _convert_case, _iso, _safe_float


DEFAULT_TOP_SYMPTOMS = 5
DEFAULT_TOP_LOGS = 4
DEFAULT_TOP_TRACES = 4
PRE_WINDOW_SEC = 600
POST_WINDOW_SEC = 600


def run(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.rcaeval_root)
    if not root.exists():
        raise FileNotFoundError(f"{root} does not exist")

    cases = _find_cases(root)
    include_families = {
        str(item).upper()
        for item in list(getattr(args, "include_families", []) or [])
        if str(item)
    }
    if include_families:
        cases = [
            case_dir
            for case_dir in cases
            if _dataset_names(case_dir)[0].upper() in include_families
        ]
    records: list[dict[str, Any]] = []
    case_summaries: list[dict[str, Any]] = []
    for case_dir in cases:
        if (case_dir / "data.csv").exists():
            converted = _convert_case(
                case_dir=case_dir,
                top_symptoms=args.top_symptoms,
                min_symptom_score=args.min_symptom_score,
            )
        else:
            converted = _convert_multisource_case(
                case_dir=case_dir,
                top_symptoms=args.top_symptoms,
                min_symptom_score=args.min_symptom_score,
                top_logs=args.top_logs,
                top_traces=args.top_traces,
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
        "included_families": sorted(include_families),
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
            "RCAEval cases converted to admission-layer records across metrics, logs, and traces when available; "
            "ground-truth service, fault type, dataset, run identity, and derived indicator metadata are preserved."
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
            if _is_case_dir(path):
                cases[str(path.resolve())] = path
        for path in base.glob("*/RE*/*/*"):
            if _is_case_dir(path):
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


def _is_case_dir(path: Path) -> bool:
    return bool((path / "inject_time.txt").exists() and ((path / "data.csv").exists() or (path / "simple_metrics.csv").exists()))


def _convert_multisource_case(
    *,
    case_dir: Path,
    top_symptoms: int,
    min_symptom_score: float,
    top_logs: int,
    top_traces: int,
) -> dict[str, Any]:
    dataset_name = case_dir.parents[1].name
    run_id = case_dir.name
    service_fault = case_dir.parent.name
    root_service, fault_type = _parse_service_fault(service_fault)
    inject_ts = int((case_dir / "inject_time.txt").read_text(encoding="utf-8").strip())
    case_id = f"{dataset_name}:{service_fault}:{run_id}"

    metric_rows = _read_csv(case_dir / "simple_metrics.csv")
    metric_records = _rank_metric_symptoms(
        rows=metric_rows,
        case_id=case_id,
        dataset_name=dataset_name,
        run_id=run_id,
        root_service=root_service,
        fault_type=fault_type,
        inject_ts=inject_ts,
        top_symptoms=top_symptoms,
        min_score=min_symptom_score,
    )
    log_records = _rank_log_symptoms(
        rows=_read_csv(case_dir / "logts.csv"),
        cluster_info=_read_json(case_dir / "cluster_info.json"),
        case_id=case_id,
        dataset_name=dataset_name,
        run_id=run_id,
        root_service=root_service,
        fault_type=fault_type,
        inject_ts=inject_ts,
        top_logs=top_logs,
        min_score=min_symptom_score,
    )
    trace_records = _rank_trace_symptoms(
        rows=_read_csv(case_dir / "tracets_err.csv"),
        modality="trace_err",
        case_id=case_id,
        dataset_name=dataset_name,
        run_id=run_id,
        root_service=root_service,
        fault_type=fault_type,
        inject_ts=inject_ts,
        top_traces=top_traces,
        min_score=min_symptom_score,
    )
    trace_records.extend(
        _rank_trace_symptoms(
            rows=_read_csv(case_dir / "tracets_lat.csv"),
            modality="trace_lat",
            case_id=case_id,
            dataset_name=dataset_name,
            run_id=run_id,
            root_service=root_service,
            fault_type=fault_type,
            inject_ts=inject_ts,
            top_traces=top_traces,
            min_score=min_symptom_score,
        )
    )
    ranked_records = _dedupe_records(metric_records + log_records + trace_records)
    root_indicator = _root_indicator_for_case(
        dataset_name=dataset_name,
        root_service=root_service,
        fault_type=fault_type,
        ranked_records=ranked_records,
    )
    root_record = _root_multisource_record(
        case_id=case_id,
        dataset_name=dataset_name,
        run_id=run_id,
        root_service=root_service,
        fault_type=fault_type,
        inject_ts=inject_ts,
        downstream=max(len(ranked_records), 1),
        root_indicator=root_indicator,
    )
    records = [root_record, *ranked_records]
    summary = {
        "case_id": case_id,
        "benchmark": dataset_name,
        "root_service": root_service,
        "fault_type": fault_type,
        "run_id": run_id,
        "root_indicator": root_indicator["indicator"],
        "root_indicator_modality": root_indicator["modality"],
        "metric_records": sum(1 for item in ranked_records if str(item.get("indicator_modality") or "") == "metric"),
        "log_records": sum(1 for item in ranked_records if str(item.get("indicator_modality") or "") == "log"),
        "trace_records": sum(1 for item in ranked_records if str(item.get("indicator_modality") or "").startswith("trace")),
        "symptoms": len(ranked_records),
    }
    return {"records": records, "summary": summary}


def _rank_metric_symptoms(
    *,
    rows: list[dict[str, str]],
    case_id: str,
    dataset_name: str,
    run_id: str,
    root_service: str,
    fault_type: str,
    inject_ts: int,
    top_symptoms: int,
    min_score: float,
) -> list[dict[str, Any]]:
    ranking = _rank_series_rows(
        rows=rows,
        inject_ts=inject_ts,
        min_score=min_score,
        parser=_parse_metric_column,
    )
    records: list[dict[str, Any]] = []
    for rank, item in enumerate(ranking[:top_symptoms], start=1):
        records.append(
            _symptom_record_from_rank(
                case_id=case_id,
                dataset_name=dataset_name,
                run_id=run_id,
                root_service=root_service,
                fault_type=fault_type,
                inject_ts=inject_ts + rank,
                rank=rank,
                item=item,
                modality="metric",
            )
        )
    return records


def _rank_log_symptoms(
    *,
    rows: list[dict[str, str]],
    cluster_info: dict[str, Any],
    case_id: str,
    dataset_name: str,
    run_id: str,
    root_service: str,
    fault_type: str,
    inject_ts: int,
    top_logs: int,
    min_score: float,
) -> list[dict[str, Any]]:
    ranking = _rank_series_rows(
        rows=rows,
        inject_ts=inject_ts,
        min_score=min_score,
        parser=lambda column: _parse_log_column(column, cluster_info=cluster_info),
    )
    records: list[dict[str, Any]] = []
    for rank, item in enumerate(ranking[:top_logs], start=1):
        records.append(
            _symptom_record_from_rank(
                case_id=case_id,
                dataset_name=dataset_name,
                run_id=run_id,
                root_service=root_service,
                fault_type=fault_type,
                inject_ts=inject_ts + 100 + rank,
                rank=rank,
                item=item,
                modality="log",
            )
        )
    return records


def _rank_trace_symptoms(
    *,
    rows: list[dict[str, str]],
    modality: str,
    case_id: str,
    dataset_name: str,
    run_id: str,
    root_service: str,
    fault_type: str,
    inject_ts: int,
    top_traces: int,
    min_score: float,
) -> list[dict[str, Any]]:
    if not rows:
        return []
    ranking = _rank_series_rows(
        rows=rows,
        inject_ts=inject_ts,
        min_score=min_score,
        parser=lambda column: _parse_trace_column(column, modality=modality),
    )
    records: list[dict[str, Any]] = []
    for rank, item in enumerate(ranking[:top_traces], start=1):
        records.append(
            _symptom_record_from_rank(
                case_id=case_id,
                dataset_name=dataset_name,
                run_id=run_id,
                root_service=root_service,
                fault_type=fault_type,
                inject_ts=inject_ts + 200 + rank,
                rank=rank,
                item=item,
                modality=modality,
            )
        )
    return records


def _rank_series_rows(
    *,
    rows: list[dict[str, str]],
    inject_ts: int,
    min_score: float,
    parser: Any,
) -> list[dict[str, Any]]:
    if not rows:
        return []
    columns = [
        column
        for column in rows[0].keys()
        if column != "time" and parser(column) is not None
    ]
    pre = [row for row in rows if inject_ts - PRE_WINDOW_SEC <= _safe_int(row.get("time")) < inject_ts]
    post = [row for row in rows if inject_ts <= _safe_int(row.get("time")) < inject_ts + POST_WINDOW_SEC]
    if not pre or not post:
        return []

    per_indicator: dict[str, dict[str, Any]] = {}
    for column in columns:
        parsed = parser(column)
        if parsed is None:
            continue
        service, indicator_name, indicator_tokens = parsed
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
        if score < min_score:
            continue
        key = f"{service}|{indicator_name}"
        current = per_indicator.get(key)
        if current is None or score > float(current["score"]):
            per_indicator[key] = {
                "service": service,
                "indicator_name": indicator_name,
                "indicator_tokens": indicator_tokens,
                "score": score,
                "pre_mean": pre_mean,
                "post_mean": post_mean,
            }
    return sorted(per_indicator.values(), key=lambda item: float(item["score"]), reverse=True)


def _parse_metric_column(column: str) -> tuple[str, str, list[str]] | None:
    if "_" not in column:
        return None
    service, metric = column.rsplit("_", 1)
    return service, column, [service, metric, column]


def _parse_log_column(column: str, *, cluster_info: dict[str, Any]) -> tuple[str, str, list[str]] | None:
    if "_" not in column:
        return None
    service, cluster_id = column.rsplit("_", 1)
    cluster = cluster_info.get(str(cluster_id)) or {}
    template = str(cluster.get("template") or f"log_cluster_{cluster_id}")
    return service, f"{service}_log_{cluster_id}", [service, "log", template]


def _parse_trace_column(column: str, *, modality: str) -> tuple[str, str, list[str]] | None:
    if "_" not in column:
        return None
    service, operation = column.split("_", 1)
    return service, f"{service}_{modality}_{operation}", [service, modality, operation]


def _symptom_record_from_rank(
    *,
    case_id: str,
    dataset_name: str,
    run_id: str,
    root_service: str,
    fault_type: str,
    inject_ts: int,
    rank: int,
    item: dict[str, Any],
    modality: str,
) -> dict[str, Any]:
    service = str(item["service"])
    indicator_name = str(item["indicator_name"])
    indicator_tokens = [str(token) for token in list(item.get("indicator_tokens") or []) if str(token)]
    return {
        "id": f"{case_id}:{modality}:{rank}:{service}",
        "timestamp": _iso(inject_ts),
        "benchmark": dataset_name,
        "case_id": case_id,
        "run_id": run_id,
        "service": service,
        "root_cause": root_service,
        "root_service": root_service,
        "fault_type": "transient_fault",
        "ground_truth_fault_type": fault_type,
        "is_root_cause": False,
        "path_signature": _path_signature(case_id=case_id, service=service),
        "downstream_dependents": 1,
        "metric_name": indicator_name,
        "indicator_name": indicator_name,
        "indicator_modality": modality,
        "indicator_tokens": indicator_tokens,
        "root_indicator": indicator_name if service == root_service else "",
        "anomaly_score": round(float(item["score"]), 6),
        "pre_mean": round(float(item["pre_mean"]), 6),
        "post_mean": round(float(item["post_mean"]), 6),
    }


def _root_multisource_record(
    *,
    case_id: str,
    dataset_name: str,
    run_id: str,
    root_service: str,
    fault_type: str,
    inject_ts: int,
    downstream: int,
    root_indicator: dict[str, Any],
) -> dict[str, Any]:
    indicator_tokens = [str(token) for token in list(root_indicator.get("tokens") or []) if str(token)]
    indicator_name = str(root_indicator.get("indicator") or f"{root_service}_{fault_type}")
    return {
        "id": f"{case_id}:root",
        "timestamp": _iso(inject_ts),
        "benchmark": dataset_name,
        "case_id": case_id,
        "run_id": run_id,
        "service": root_service,
        "root_cause": root_service,
        "root_service": root_service,
        "fault_type": _scenario_name(dataset_name=dataset_name, fault_type=fault_type),
        "ground_truth_fault_type": fault_type,
        "is_root_cause": True,
        "path_signature": _path_signature(case_id=case_id, service=root_service),
        "downstream_dependents": downstream,
        "metric_name": indicator_name,
        "indicator_name": indicator_name,
        "indicator_modality": str(root_indicator.get("modality") or "metric"),
        "indicator_tokens": indicator_tokens,
        "root_indicator": indicator_name,
        "anomaly_score": None,
    }


def _root_indicator_for_case(
    *,
    dataset_name: str,
    root_service: str,
    fault_type: str,
    ranked_records: list[dict[str, Any]],
) -> dict[str, Any]:
    if dataset_name.startswith("RE2"):
        indicator = f"{root_service}_{fault_type}"
        return {
            "indicator": indicator,
            "modality": "metric",
            "tokens": [root_service, fault_type, indicator],
        }
    root_service_records = [record for record in ranked_records if str(record.get("service") or "") == root_service]
    if root_service_records:
        best = max(root_service_records, key=lambda item: float(item.get("anomaly_score") or 0.0))
        return {
            "indicator": str(best.get("indicator_name") or f"{root_service}_{fault_type}"),
            "modality": str(best.get("indicator_modality") or "log"),
            "tokens": list(best.get("indicator_tokens") or []),
        }
    return {
        "indicator": f"{root_service}_{fault_type}",
        "modality": "metric",
        "tokens": [root_service, fault_type, f"{root_service}_{fault_type}"],
    }


def _dedupe_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    for record in records:
        key = f"{record.get('service')}|{record.get('indicator_modality')}|{record.get('indicator_name')}"
        current = by_key.get(key)
        if current is None or float(record.get("anomaly_score") or 0.0) > float(current.get("anomaly_score") or 0.0):
            by_key[key] = record
    return sorted(by_key.values(), key=lambda item: float(item.get("anomaly_score") or 0.0), reverse=True)


def _scenario_name(*, dataset_name: str, fault_type: str) -> str:
    if dataset_name.startswith("RE3"):
        return f"rcaeval_code_{fault_type}"
    return f"rcaeval_{fault_type}_fault"


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as fp:
        return list(csv.DictReader(fp))


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_service_fault(value: str) -> tuple[str, str]:
    if "_" not in value:
        return value, "unknown"
    service, fault = value.rsplit("_", 1)
    return service, fault


def _path_signature(*, case_id: str, service: str) -> str:
    return f"{service}|case={case_id}"


def _safe_int(value: Any) -> int:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return 0


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
    parser.add_argument("--top-logs", type=int, default=DEFAULT_TOP_LOGS)
    parser.add_argument("--top-traces", type=int, default=DEFAULT_TOP_TRACES)
    parser.add_argument("--min-symptom-score", type=float, default=1.0)
    parser.add_argument("--include-families", nargs="*", default=[])
    run(parser.parse_args())


if __name__ == "__main__":
    main()
