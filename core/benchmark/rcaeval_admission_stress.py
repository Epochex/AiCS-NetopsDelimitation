from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt

from core.aiops_agent.alert_reasoning_runtime.budget_controller import select_windows_under_budget
from core.aiops_agent.alert_reasoning_runtime.incident_window import build_incident_window_index
from core.benchmark.admission_metrics import read_jsonl, selected_window_metrics
from core.benchmark.external_validation_adapter import _to_alert
from core.benchmark.rcaeval_full_adapter import run as run_rcaeval_full_adapter


DEFAULT_RECORDS_JSONL = "/data/Netops-causality-remediation/outputs/rcaeval/rcaeval_admission_records.jsonl"
DEFAULT_OUTPUT_JSON = "/data/Netops-causality-remediation/documentation/results/rcaeval_admission_stress_summary.json"
DEFAULT_OUTPUT_PNG = "/data/Netops-causality-remediation/documentation/images/rcaeval_admission_stress_summary.png"


def run(args: argparse.Namespace) -> dict[str, Any]:
    records_path = Path(args.records_jsonl)
    if not records_path.exists():
        if not args.rcaeval_root:
            raise FileNotFoundError(f"{records_path} does not exist and --rcaeval-root was not provided")
        _materialize_records(args, output_jsonl=records_path)
    records = read_jsonl(records_path)
    if not records:
        raise ValueError("no RCAEval admission records available")

    by_dataset: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        dataset = str(record.get("dataset") or record.get("benchmark") or "unknown")
        by_dataset[dataset].append(record)

    dataset_windows: dict[str, list[dict[str, Any]]] = {}
    all_windows: list[dict[str, Any]] = []
    for dataset, items in sorted(by_dataset.items()):
        windows = _dataset_windows(
            items,
            window_sec=args.window_sec,
            window_mode=str(getattr(args, "window_mode", "session") or "session"),
            max_window_sec=getattr(args, "max_window_sec", None),
        )
        dataset_windows[dataset] = windows
        all_windows.extend(windows)

    report = {
        "schema_version": 1,
        "records_jsonl": str(records_path),
        "records": len(records),
        "datasets": len(dataset_windows),
        "window_sec": args.window_sec,
        "window_mode": str(getattr(args, "window_mode", "session") or "session"),
        "max_window_sec": getattr(args, "max_window_sec", None) or args.window_sec,
        "combined": _slice_summary("combined", all_windows),
        "per_dataset": {
            dataset: _slice_summary(dataset, windows)
            for dataset, windows in sorted(dataset_windows.items())
        },
        "per_case_mix": {
            label: _slice_summary(label, windows)
            for label, windows in sorted(_group_case_mix(all_windows).items())
        },
        "shortcut_risk_summary": _shortcut_risk_summary(all_windows),
    }
    output_json = Path(args.output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.output_png:
        _render_plot(report, output_png=Path(args.output_png))
    print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
    return report


def _materialize_records(args: argparse.Namespace, *, output_jsonl: Path) -> None:
    output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    run_rcaeval_full_adapter(
        argparse.Namespace(
            rcaeval_root=str(args.rcaeval_root),
            output_jsonl=str(output_jsonl),
            output_cases_jsonl="",
            output_windows_jsonl="",
            output_summary_json="",
            window_sec=args.window_sec,
            window_mode=str(getattr(args, "window_mode", "session") or "session"),
            max_window_sec=getattr(args, "max_window_sec", None),
            top_symptoms=args.top_symptoms,
            min_symptom_score=args.min_symptom_score,
        )
    )


def _dataset_windows(
    records: list[dict[str, Any]],
    *,
    window_sec: int,
    window_mode: str,
    max_window_sec: int | None,
) -> list[dict[str, Any]]:
    dataset = str(records[0].get("dataset") or records[0].get("benchmark") or "unknown") if records else "unknown"
    alerts = [_to_alert(record, idx) for idx, record in enumerate(records)]
    windows, _ = build_incident_window_index(
        alerts,
        window_sec=window_sec,
        window_mode=window_mode,
        max_window_sec=max_window_sec,
    )
    for window in windows:
        window["_dataset"] = dataset
        window["_case_mix"] = _case_mix(window)
    return windows


def _slice_summary(label: str, windows: list[dict[str, Any]]) -> dict[str, Any]:
    all_window_ids = {str(window.get("window_id") or "") for window in windows}
    high_value_window_ids = {
        str(window.get("window_id") or "")
        for window in windows
        if int(window.get("high_value_count") or 0) > 0
    }
    risk_window_ids = {
        str(window.get("window_id") or "")
        for window in windows
        if str(window.get("recommended_action") or "") == "external"
        or str(window.get("risk_tier") or "") == "high"
    }
    strict_budget = select_windows_under_budget(windows, budget_fraction=0.2, min_high_value=False)
    risk_budget = select_windows_under_budget(windows, budget_fraction=0.2, min_high_value=True)
    policies = {
        "invoke-all": selected_window_metrics(windows, all_window_ids, call_mode="all-alerts"),
        "fault-state-only": selected_window_metrics(windows, high_value_window_ids, call_mode="high-value-alerts"),
        "window-risk-tier": selected_window_metrics(windows, risk_window_ids, call_mode="representative-alerts"),
        "strict-budget-20": selected_window_metrics(
            windows,
            set(strict_budget.get("selected_window_ids") or set()),
            call_mode="representative-alerts",
            admission=strict_budget,
        ),
        "risk-budget-20": selected_window_metrics(
            windows,
            set(risk_budget.get("selected_window_ids") or set()),
            call_mode="representative-alerts",
            admission=risk_budget,
        ),
    }
    return {
        "label": label,
        "incident_windows": len(windows),
        "high_value_windows": sum(1 for window in windows if int(window.get("high_value_count") or 0) > 0),
        "window_labels": dict(Counter(str(window.get("window_label") or "unknown") for window in windows).most_common()),
        "risk_tiers": dict(Counter(str(window.get("risk_tier") or "unknown") for window in windows).most_common()),
        "case_mix": dict(Counter(_case_mix(window) for window in windows).most_common()),
        "policies": policies,
    }


def _group_case_mix(windows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for window in windows:
        grouped[_case_mix(window)].append(window)
    return grouped


def _case_mix(window: dict[str, Any]) -> str:
    high_value = int(window.get("high_value_count") or 0)
    alert_count = max(1, int(window.get("alert_count") or 0))
    ratio = high_value / alert_count
    if high_value <= 0:
        return "transient_only"
    if ratio >= 0.5:
        return "fault_dense"
    return "symptom_heavy_mixed"


def _shortcut_risk_summary(windows: list[dict[str, Any]]) -> dict[str, Any]:
    total = max(len(windows), 1)
    counts = Counter(_case_mix(window) for window in windows)
    return {
        "fault_dense_rate": round(counts.get("fault_dense", 0) / total, 6),
        "symptom_heavy_mixed_rate": round(counts.get("symptom_heavy_mixed", 0) / total, 6),
        "transient_only_rate": round(counts.get("transient_only", 0) / total, 6),
        "note": "A low fault-dense rate means the fault-state shortcut must survive symptom-heavy windows to remain effective.",
    }


def _render_plot(report: dict[str, Any], *, output_png: Path) -> None:
    dataset_rows = [report.get("combined") or {}]
    dataset_rows.extend(
        row
        for _, row in sorted((report.get("per_dataset") or {}).items())
        if isinstance(row, dict)
    )
    labels = [str(row.get("label") or "") for row in dataset_rows]
    x = list(range(len(labels)))
    width = 0.22
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))

    def _policy_metric(row: dict[str, Any], policy: str, key: str) -> float:
        policies = row.get("policies") or {}
        metrics = policies.get(policy) or {}
        try:
            return float(metrics.get(key) or 0.0)
        except (TypeError, ValueError):
            return 0.0

    for offset, policy, color in (
        (-width, "fault-state-only", "#1f77b4"),
        (0.0, "strict-budget-20", "#d62728"),
        (width, "risk-budget-20", "#2ca02c"),
    ):
        axes[0].bar(
            [value + offset for value in x],
            [_policy_metric(row, policy, "high_value_window_recall") for row in dataset_rows],
            width=width,
            label=policy,
            color=color,
        )
        axes[1].bar(
            [value + offset for value in x],
            [_policy_metric(row, policy, "external_calls") for row in dataset_rows],
            width=width,
            label=policy,
            color=color,
        )

    axes[0].set_title("RCAEval Recall Stress")
    axes[0].set_xticks(x, labels)
    axes[0].set_ylim(0.0, 1.05)
    axes[0].grid(axis="y", alpha=0.25)
    axes[0].legend(frameon=False)

    axes[1].set_title("RCAEval Call Cost")
    axes[1].set_xticks(x, labels)
    axes[1].grid(axis="y", alpha=0.25)
    axes[1].legend(frameon=False)

    fig.tight_layout()
    output_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_png, dpi=180, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Stress admission policies across RCAEval splits and case mixes.")
    parser.add_argument("--records-jsonl", default=DEFAULT_RECORDS_JSONL)
    parser.add_argument("--rcaeval-root", default="/data/external_benchmarks/RCAEval")
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
    parser.add_argument("--top-symptoms", type=int, default=5)
    parser.add_argument("--min-symptom-score", type=float, default=1.0)
    parser.add_argument("--output-json", default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-png", default=DEFAULT_OUTPUT_PNG)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
