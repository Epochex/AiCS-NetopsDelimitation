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
from core.benchmark.window_risk_ablation import ABLATIONS, _ablated_window


DEFAULT_RECORDS_JSONL = "/data/Netops-causality-remediation/outputs/rcaeval/rcaeval_re23_admission_records.jsonl"
DEFAULT_OUTPUT_JSON = "/data/Netops-causality-remediation/documentation/results/rcaeval_re23_negative_benchmark.json"
DEFAULT_OUTPUT_PNG = "/data/Netops-causality-remediation/documentation/images/rcaeval_re23_negative_benchmark.png"
WINDOW_CONFIGS = (
    ("session-600x600", "session", 600, 600, "Sessionized"),
    ("adaptive-600x1800", "adaptive", 600, 1800, "Gap-Adaptive"),
    ("aics-topology-500x1200", "aics-topology", 500, 1200, "Topology-Coupled AiCS"),
    ("aics-evidence-600x1800", "aics-evidence", 600, 1800, "Evidence-Coupled AiCS"),
    ("aics-hybrid-600x1800", "aics", 600, 1800, "Hybrid AiCS"),
)
ABLATION_ORDER = (
    "full",
    "no-mixed-fault",
    "no-recurrence",
    "no-topology",
    "no-missing-evidence",
    "no-self-healing-offset",
)


def run(args: argparse.Namespace) -> dict[str, Any]:
    records_path = Path(args.records_jsonl)
    if not records_path.exists():
        _materialize_records(args, output_jsonl=records_path)
    records = [
        record
        for record in read_jsonl(records_path)
        if str(record.get("dataset_family") or "").upper() in {"RE2", "RE3"}
    ]
    if not records:
        raise ValueError("no RE2/RE3 records available for negative benchmark")

    results = [_config_summary(records=records, config=config) for config in WINDOW_CONFIGS]
    best = max(
        results,
        key=lambda item: (
            float(((item.get("strict_budget_20") or {}).get("high_value_window_recall") or 0.0)),
            -float(((item.get("risk_budget_20") or {}).get("external_calls") or 0.0)),
        ),
    )
    best_windows = _build_windows(
        records=records,
        mode=str(best["window_mode"]),
        window_sec=int(best["window_sec"]),
        max_window_sec=int(best["max_window_sec"]),
    )
    ablations = [_ablation_summary(name=name, windows=best_windows) for name in ABLATION_ORDER]

    report = {
        "schema_version": 1,
        "records_jsonl": str(records_path),
        "records": len(records),
        "window_configs": results,
        "recommended_config": {
            "config_id": best["config_id"],
            "display_name": best["display_name"],
            "reason": "highest strict-budget-20 recall under comparable external-call cost on RE2/RE3",
        },
        "risk_atom_ablations": ablations,
        "negative_benchmark_scope": (
            "RCAEval RE2/RE3 reduce the pure fault-state shortcut by mixing metrics, logs, traces, "
            "and code-level fault cases; the benchmark compares boundary families and risk-atom sensitivity "
            "under a shared 20% budget slice"
        ),
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
            window_sec=600,
            window_mode="session",
            max_window_sec=600,
            top_symptoms=args.top_symptoms,
            top_logs=args.top_logs,
            top_traces=args.top_traces,
            min_symptom_score=args.min_symptom_score,
            include_families=["RE2", "RE3"],
        )
    )


def _config_summary(records: list[dict[str, Any]], config: tuple[str, str, int, int, str]) -> dict[str, Any]:
    config_id, mode, window_sec, max_window_sec, display_name = config
    windows = _build_windows(records=records, mode=mode, window_sec=window_sec, max_window_sec=max_window_sec)
    strict_budget = select_windows_under_budget(windows, budget_fraction=0.2, min_high_value=False)
    risk_budget = select_windows_under_budget(windows, budget_fraction=0.2, min_high_value=True)
    high_value_window_ids = {
        str(window.get("window_id") or "")
        for window in windows
        if int(window.get("high_value_count") or 0) > 0
    }
    fault_state_only = selected_window_metrics(windows, high_value_window_ids, call_mode="high-value-alerts")
    return {
        "config_id": config_id,
        "display_name": display_name,
        "window_mode": mode,
        "window_sec": window_sec,
        "max_window_sec": max_window_sec,
        "incident_windows": len(windows),
        "case_mix": dict(Counter(_case_mix(window) for window in windows).most_common()),
        "fault_state_only": fault_state_only,
        "strict_budget_20": selected_window_metrics(
            windows,
            set(strict_budget.get("selected_window_ids") or set()),
            call_mode="representative-alerts",
            admission=strict_budget,
        ),
        "risk_budget_20": selected_window_metrics(
            windows,
            set(risk_budget.get("selected_window_ids") or set()),
            call_mode="representative-alerts",
            admission=risk_budget,
        ),
    }


def _build_windows(*, records: list[dict[str, Any]], mode: str, window_sec: int, max_window_sec: int) -> list[dict[str, Any]]:
    windows, _ = build_incident_window_index(
        [_to_alert(record, idx) for idx, record in enumerate(records)],
        window_sec=window_sec,
        window_mode=mode,
        max_window_sec=max_window_sec,
    )
    return windows


def _case_mix(window: dict[str, Any]) -> str:
    high_value = int(window.get("high_value_count") or 0)
    alert_count = max(1, int(window.get("alert_count") or 0))
    ratio = high_value / alert_count
    if high_value <= 0:
        return "symptom_only"
    if ratio >= 0.5:
        return "fault_dense"
    return "symptom_heavy_mixed"


def _ablation_summary(name: str, windows: list[dict[str, Any]]) -> dict[str, Any]:
    config = ABLATIONS[name]
    ablated = [_ablated_window(window, config=config) for window in windows]
    strict_budget = select_windows_under_budget(ablated, budget_fraction=0.2, min_high_value=False)
    risk_budget = select_windows_under_budget(ablated, budget_fraction=0.2, min_high_value=True)
    return {
        "ablation": name,
        "description": config["description"],
        "strict_budget_20": selected_window_metrics(
            ablated,
            set(strict_budget.get("selected_window_ids") or set()),
            call_mode="representative-alerts",
            admission=strict_budget,
        ),
        "risk_budget_20": selected_window_metrics(
            ablated,
            set(risk_budget.get("selected_window_ids") or set()),
            call_mode="representative-alerts",
            admission=risk_budget,
        ),
    }


def _render_plot(report: dict[str, Any], *, output_png: Path) -> None:
    configs = list(report.get("window_configs") or [])
    fig, axes = plt.subplots(1, 2, figsize=(12.5, 4.8))

    family_colors = {
        "Sessionized": "#1f77b4",
        "Gap-Adaptive": "#ff7f0e",
        "Topology-Coupled AiCS": "#2ca02c",
        "Evidence-Coupled AiCS": "#d62728",
        "Hybrid AiCS": "#9467bd",
    }
    for row in configs:
        strict = row.get("strict_budget_20") or {}
        name = str(row.get("display_name") or "")
        x_value = float(strict.get("external_calls") or 0.0)
        y_value = float(strict.get("high_value_window_recall") or 0.0)
        axes[0].scatter(x_value, y_value, s=90, color=family_colors.get(name, "#333333"))
        axes[0].annotate(
            f"{name}\nwindows={int(row.get('incident_windows') or 0)}",
            (x_value, y_value),
            textcoords="offset points",
            xytext=(5, 5),
            fontsize=8,
        )
    axes[0].set_title("RCAEval RE2/RE3 Hard-Budget Stress")
    axes[0].set_xlabel("Strict-budget 20% external calls")
    axes[0].set_ylabel("Strict-budget 20% high-value recall")
    axes[0].set_ylim(0.0, 0.40)
    axes[0].grid(alpha=0.25)
    axes[0].annotate(
        "better",
        xy=(0.92, 0.90),
        xytext=(0.72, 0.72),
        xycoords="axes fraction",
        textcoords="axes fraction",
        arrowprops={"arrowstyle": "->", "lw": 1.2, "color": "#444444"},
        fontsize=9,
        color="#444444",
    )

    ablations = list(report.get("risk_atom_ablations") or [])
    labels = [str(item.get("ablation") or "") for item in ablations]
    recalls = [float(((item.get("strict_budget_20") or {}).get("high_value_window_recall") or 0.0)) for item in ablations]
    y = list(range(len(labels)))
    axes[1].plot(recalls, y, marker="o", color="#2ca02c", lw=1.5)
    baseline = recalls[0] if recalls else 0.0
    axes[1].axvline(baseline, color="#999999", linestyle="--", lw=1.0)
    axes[1].set_yticks(y, labels)
    axes[1].set_xlim(max(0.0, baseline - 0.05), min(1.0, baseline + 0.05))
    axes[1].set_xlabel("Strict-budget 20% high-value recall")
    axes[1].set_title("Risk-Atom Ablation on Topology-Coupled AiCS")
    axes[1].grid(axis="x", alpha=0.25)
    axes[1].text(
        0.98,
        0.06,
        "All ablations coincide on RE2/RE3.\nThis benchmark separates boundary families,\nnot fine-grained atom importance.",
        transform=axes[1].transAxes,
        ha="right",
        va="bottom",
        fontsize=8,
        bbox={"boxstyle": "round,pad=0.25", "facecolor": "#f7f7f7", "edgecolor": "#cccccc"},
    )

    fig.tight_layout()
    output_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_png, dpi=180, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run stronger RE2/RE3 negative benchmarks for AiCS.")
    parser.add_argument("--records-jsonl", default=DEFAULT_RECORDS_JSONL)
    parser.add_argument("--rcaeval-root", default="/data/external_benchmarks/RCAEval")
    parser.add_argument("--top-symptoms", type=int, default=5)
    parser.add_argument("--top-logs", type=int, default=4)
    parser.add_argument("--top-traces", type=int, default=4)
    parser.add_argument("--min-symptom-score", type=float, default=1.0)
    parser.add_argument("--output-json", default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-png", default=DEFAULT_OUTPUT_PNG)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
