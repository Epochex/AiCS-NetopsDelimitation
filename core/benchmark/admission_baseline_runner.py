from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from core.aiops_agent.alert_reasoning_runtime.budget_controller import select_windows_under_budget
from core.aiops_agent.alert_reasoning_runtime.incident_window import build_incident_window_index
from core.benchmark.external_validation_adapter import _to_alert
from core.benchmark.topology_subgraph_ablation import _iter_alerts


BUDGET_FRACTIONS = (1, 2, 5, 10, 20, 40, 60)
STATIC_POLICIES = (
    "invoke-all",
    "analyze-all-windows",
    "representative-only",
    "scenario-only",
    "topology+timeline",
    "risk-score",
    "risk-coverage",
    "oracle",
)


def run(args: argparse.Namespace) -> dict[str, Any]:
    alerts = _load_alerts(args)
    if args.max_alerts > 0:
        alerts = alerts[: args.max_alerts]
    budget_fractions = _parse_budgets(args.budgets)
    windows, _ = build_incident_window_index(
        alerts,
        window_sec=args.window_sec,
        group_by_scenario=bool(getattr(args, "group_by_scenario", False)),
    )
    policies = _evaluate_policies(windows, budget_fractions=budget_fractions)
    report = {
        "schema_version": 1,
        "source": args.source,
        "alerts": len(alerts),
        "incident_windows": len(windows),
        "high_value_windows": sum(1 for window in windows if _is_high_value_window(window)),
        "pressure_windows": sum(1 for window in windows if _has_pressure(window)),
        "window_sec": args.window_sec,
        "policies": policies,
        "per_dataset": _per_dataset_reports(args, budget_fractions=budget_fractions),
        "metric_scope": (
            "admission-layer quality-cost metrics; does not claim model diagnosis accuracy"
        ),
    }
    if args.output_json:
        path = Path(args.output_json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.output_windows_jsonl:
        _write_jsonl(Path(args.output_windows_jsonl), windows)
    print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
    return report


def _load_alerts(args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.source == "lcore":
        alerts = _iter_alerts(Path(args.alert_dir), args.limit_files)
        return alerts
    if args.source == "rcaeval":
        records = _read_jsonl(Path(args.dataset_jsonl))
        return [_to_alert(record, idx) for idx, record in enumerate(records)]
    raise ValueError(f"unsupported source: {args.source}")


def _per_dataset_reports(args: argparse.Namespace, *, budget_fractions: tuple[int, ...]) -> dict[str, Any]:
    if args.source != "rcaeval" or not args.dataset_jsonl:
        return {}
    records = _read_jsonl(Path(args.dataset_jsonl))
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        dataset = str(record.get("dataset") or record.get("benchmark") or "unknown")
        grouped.setdefault(dataset, []).append(record)
    reports: dict[str, Any] = {}
    for dataset, items in sorted(grouped.items()):
        alerts = [_to_alert(record, idx) for idx, record in enumerate(items)]
        windows, _ = build_incident_window_index(
            alerts,
            window_sec=args.window_sec,
            group_by_scenario=bool(getattr(args, "group_by_scenario", False)),
        )
        reports[dataset] = {
            "alerts": len(alerts),
            "incident_windows": len(windows),
            "high_value_windows": sum(1 for window in windows if _is_high_value_window(window)),
            "pressure_windows": sum(1 for window in windows if _has_pressure(window)),
            "policies": _evaluate_policies(windows, budget_fractions=budget_fractions),
        }
    return reports


def _evaluate_policies(windows: list[dict[str, Any]], *, budget_fractions: tuple[int, ...]) -> dict[str, Any]:
    policies: dict[str, Any] = {
        "invoke-all": _metrics(windows, _all_window_ids(windows), call_mode="all-alerts"),
        "analyze-all-windows": _metrics(windows, _all_window_ids(windows), call_mode="full-windows"),
        "representative-only": _metrics(windows, _all_window_ids(windows), call_mode="representative-alerts"),
        "scenario-only": _metrics(windows, _scenario_selected(windows), call_mode="representative-alerts"),
        "topology+timeline": _metrics(windows, _topology_timeline_selected(windows), call_mode="representative-alerts"),
        "risk-score": _metrics(windows, _risk_score_selected(windows, fraction=0.2), call_mode="representative-alerts"),
        "risk-coverage": _metrics(
            windows,
            set(select_windows_under_budget(windows, budget_fraction=0.2).get("selected_window_ids") or set()),
            call_mode="representative-alerts",
        ),
        "oracle": _metrics(windows, _oracle_selected(windows), call_mode="representative-alerts"),
    }
    for value in budget_fractions:
        fraction = value / 100.0
        risk_score_ids = _risk_score_selected(windows, fraction=fraction)
        risk_coverage = select_windows_under_budget(windows, budget_fraction=fraction)
        coverage = select_windows_under_budget(windows, budget_fraction=fraction, min_high_value=False)
        policies[f"risk-score-{value}"] = _metrics(
            windows,
            risk_score_ids,
            call_mode="representative-alerts",
            budget_fraction=fraction,
        )
        policies[f"risk-coverage-{value}"] = _metrics(
            windows,
            set(risk_coverage.get("selected_window_ids") or set()),
            call_mode="representative-alerts",
            admission=risk_coverage,
            budget_fraction=fraction,
        )
        policies[f"coverage-only-{value}"] = _metrics(
            windows,
            set(coverage.get("selected_window_ids") or set()),
            call_mode="representative-alerts",
            admission=coverage,
            budget_fraction=fraction,
        )
    return policies


def _metrics(
    windows: list[dict[str, Any]],
    selected_window_ids: set[str],
    *,
    call_mode: str,
    admission: dict[str, Any] | None = None,
    budget_fraction: float | None = None,
) -> dict[str, Any]:
    selected = [window for window in windows if _window_id(window) in selected_window_ids]
    total_alerts = sum(int(window.get("alert_count") or 0) for window in windows)
    total_windows = len(windows)
    high_value_total = sum(1 for window in windows if _is_high_value_window(window))
    high_value_retained = sum(1 for window in selected if _is_high_value_window(window))
    pressure_total = sum(1 for window in windows if _has_pressure(window))
    pressure_skipped = sum(1 for window in windows if _has_pressure(window) and _window_id(window) not in selected_window_ids)
    external_calls = _external_calls(selected, call_mode=call_mode)
    context_units = _context_units(selected, call_mode=call_mode)
    covered = sum(1 for window in selected if _evidence_target_covered(window))
    selected_risk = sum(int(window.get("risk_score") or 0) for window in selected)
    total_risk = sum(int(window.get("risk_score") or 0) for window in windows)
    return {
        "call_mode": call_mode,
        "budget_fraction": budget_fraction,
        "selected_windows": len(selected),
        "external_calls": external_calls,
        "call_reduction_percent": round((1 - external_calls / max(total_alerts, 1)) * 100, 2),
        "context_units": context_units,
        "context_reduction_percent": round((1 - context_units / max(total_alerts, 1)) * 100, 2),
        "window_reduction_percent": round((1 - len(selected) / max(total_windows, 1)) * 100, 2),
        "high_value_window_recall": round(high_value_retained / max(high_value_total, 1), 6),
        "false_skip_windows": high_value_total - high_value_retained,
        "false_skip_rate": round((high_value_total - high_value_retained) / max(high_value_total, 1), 6),
        "pressure_window_skip_rate": round(pressure_skipped / max(pressure_total, 1), 6),
        "evidence_target_coverage_rate": round(covered / max(len(selected), 1), 6),
        "risk_weight_coverage_rate": round(selected_risk / max(total_risk, 1), 6),
        "admission_summary": _admission_summary(admission),
    }


def _external_calls(windows: list[dict[str, Any]], *, call_mode: str) -> int:
    if call_mode == "all-alerts":
        return sum(int(window.get("alert_count") or 0) for window in windows)
    if call_mode in {"full-windows", "representative-alerts"}:
        return len(windows)
    raise ValueError(f"unknown call mode: {call_mode}")


def _context_units(windows: list[dict[str, Any]], *, call_mode: str) -> int:
    if call_mode in {"all-alerts", "full-windows"}:
        return sum(int(window.get("alert_count") or 0) for window in windows)
    if call_mode == "representative-alerts":
        return sum(_representative_cost(window) for window in windows)
    raise ValueError(f"unknown call mode: {call_mode}")


def _representative_cost(window: dict[str, Any]) -> int:
    targets = window.get("selected_evidence_targets") or {}
    values = targets.get("representative_alert_ids") or targets.get("alert_ids") or []
    return max(1, len([item for item in values if str(item)]))


def _all_window_ids(windows: list[dict[str, Any]]) -> set[str]:
    return {_window_id(window) for window in windows}


def _scenario_selected(windows: list[dict[str, Any]]) -> set[str]:
    return {_window_id(window) for window in windows if _is_high_value_window(window)}


def _oracle_selected(windows: list[dict[str, Any]]) -> set[str]:
    return _scenario_selected(windows)


def _topology_timeline_selected(windows: list[dict[str, Any]]) -> set[str]:
    return {
        _window_id(window)
        for window in windows
        if _is_high_value_window(window)
        or str(window.get("window_label") or "") in {"mixed_fault_and_transient", "external_multi_device_spread"}
        or (
            bool(window.get("recurrence_pressure"))
            and bool(window.get("topology_pressure"))
            and int(window.get("alert_count") or 0) >= 3
        )
    }


def _risk_score_selected(windows: list[dict[str, Any]], *, fraction: float) -> set[str]:
    budget_calls = max(1, int(round(sum(int(window.get("alert_count") or 0) for window in windows) * fraction)))
    selected: set[str] = set()
    used = 0
    for window in sorted(
        windows,
        key=lambda item: (int(item.get("risk_score") or 0), int(item.get("high_value_count") or 0), int(item.get("alert_count") or 0)),
        reverse=True,
    ):
        cost = _representative_cost(window)
        if used + cost > budget_calls and selected:
            continue
        selected.add(_window_id(window))
        used += cost
        if used >= budget_calls:
            break
    return selected


def _is_high_value_window(window: dict[str, Any]) -> bool:
    return int(window.get("high_value_count") or 0) > 0


def _has_pressure(window: dict[str, Any]) -> bool:
    return bool(window.get("topology_pressure") or window.get("recurrence_pressure") or window.get("multi_device_spread"))


def _evidence_target_covered(window: dict[str, Any]) -> bool:
    targets = window.get("selected_evidence_targets") or {}
    return bool(targets.get("devices") and targets.get("path_signatures") and targets.get("representative_alert_ids"))


def _window_id(window: dict[str, Any]) -> str:
    return str(window.get("window_id") or "")


def _admission_summary(admission: dict[str, Any] | None) -> dict[str, Any]:
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


def _parse_budgets(raw: str) -> tuple[int, ...]:
    if not raw.strip():
        return BUDGET_FRACTIONS
    values = []
    for item in raw.split(","):
        item = item.strip()
        if item:
            values.append(int(item))
    return tuple(values)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fp:
        for record in records:
            fp.write(json.dumps(record, ensure_ascii=True, sort_keys=True) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run unified AiCS admission baselines.")
    parser.add_argument("--source", choices=["lcore", "rcaeval"], required=True)
    parser.add_argument("--alert-dir", default="/data/netops-runtime/LCORE-D/work/alerts-lcore-corepatched-full-20260412T152119Z")
    parser.add_argument("--dataset-jsonl", default="")
    parser.add_argument("--limit-files", type=int, default=0)
    parser.add_argument("--max-alerts", type=int, default=0)
    parser.add_argument("--window-sec", type=int, default=600)
    parser.add_argument("--group-by-scenario", action="store_true")
    parser.add_argument("--budgets", default="1,2,5,10,20,40,60")
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-windows-jsonl", default="")
    run(parser.parse_args())


if __name__ == "__main__":
    main()
