from __future__ import annotations

import argparse
import contextlib
import io
import json
from argparse import Namespace
from collections import defaultdict
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

import matplotlib.pyplot as plt

from core.aiops_agent.alert_reasoning_runtime.budget_controller import select_windows_under_budget
from core.aiops_agent.alert_reasoning_runtime.incident_window import build_incident_window_index
from core.benchmark.admission_metrics import read_jsonl, selected_window_metrics
from core.benchmark.external_validation_adapter import _to_alert
from core.benchmark.quality_cost_policy_runner import run as run_quality_cost


DEFAULT_LCORE_ALERT_DIR = "/data/netops-runtime/LCORE-D/work/alerts-lcore-corepatched-full-20260412T152119Z"
DEFAULT_RCAEVAL_RECORDS = "/data/Netops-causality-remediation/outputs/rcaeval/rcaeval_admission_records.jsonl"
DEFAULT_OUTPUT_JSON = "/data/netops-runtime/LCORE-D/work/window-boundary-algorithm-benchmark.json"
DEFAULT_OUTPUT_PNG = "/data/Netops-causality-remediation/documentation/images/window_boundary_algorithm_benchmark.png"


def run(args: argparse.Namespace) -> dict[str, Any]:
    configs = _default_configs()
    rows = [_evaluate_config(args, config) for config in configs]
    recommended = min(rows, key=_selection_key)
    algorithm_rows = [
        row
        for row in rows
        if str(row["window_mode"]) in {"adaptive", "aics-topology", "aics-evidence", "aics"}
    ]
    recommended_algorithm = min(algorithm_rows, key=_algorithm_selection_key)
    summary = {
        "schema_version": 1,
        "lcore_alert_dir": args.lcore_alert_dir,
        "rcaeval_records_jsonl": args.rcaeval_records_jsonl,
        "selection_rule": (
            "maximize LCORE risk-budget-20 high-value recall, then maximize strict-budget-20 recall, "
            "then minimize LCORE risk-budget-20 external calls, RCAEval incident windows, "
            "single-alert rate, and RCAEval per-dataset window-count variance"
        ),
        "algorithm_selection_rule": (
            "among adaptive and AICS-coupled methods only, maximize LCORE strict-budget-20 recall, "
            "then minimize LCORE risk-budget-20 external calls, single-alert rate, and RCAEval window-count variance"
        ),
        "recommended_config": {
            "name": recommended["name"],
            "display_name": _display_name(recommended["name"]),
            "window_mode": recommended["window_mode"],
            "window_sec": recommended["window_sec"],
            "max_window_sec": recommended["max_window_sec"],
        },
        "recommended_algorithm_config": {
            "name": recommended_algorithm["name"],
            "display_name": _display_name(recommended_algorithm["name"]),
            "window_mode": recommended_algorithm["window_mode"],
            "window_sec": recommended_algorithm["window_sec"],
            "max_window_sec": recommended_algorithm["max_window_sec"],
        },
        "configs": rows,
    }
    output_json = Path(args.output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(summary, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.output_png:
        _render_plot(rows, recommended_name=str(recommended_algorithm["name"]), output_png=Path(args.output_png))
    print(json.dumps(summary, ensure_ascii=True, indent=2, sort_keys=True))
    return summary


def _selection_key(row: dict[str, Any]) -> tuple[float, float, int, int, float, float]:
    return (
        -float(row["lcore"]["risk_budget_20"]["high_value_window_recall"]),
        -float(row["lcore"]["strict_budget_20"]["high_value_window_recall"]),
        int(row["lcore"]["risk_budget_20"]["external_calls"]),
        int(row["rcaeval"]["combined"]["incident_windows"]),
        float(row["lcore"]["single_alert_rate"]),
        float(row["rcaeval"]["window_count_stddev"]),
    )


def _algorithm_selection_key(row: dict[str, Any]) -> tuple[float, int, float, float, int]:
    return (
        -float(row["lcore"]["strict_budget_20"]["high_value_window_recall"]),
        int(row["lcore"]["risk_budget_20"]["external_calls"]),
        float(row["lcore"]["single_alert_rate"]),
        float(row["rcaeval"]["window_count_stddev"]),
        int(row["rcaeval"]["combined"]["incident_windows"]),
    )


def _evaluate_config(args: argparse.Namespace, config: dict[str, Any]) -> dict[str, Any]:
    lcore_report = _run_quality_cost(args, config)
    lcore_windows = read_jsonl(Path(config["lcore_windows_jsonl"]))
    single_alert_windows = sum(1 for window in lcore_windows if int(window.get("alert_count") or 0) <= 1)
    rcaeval_summary = _evaluate_rcaeval(args, config)
    return {
        "name": config["name"],
        "display_name": _display_name(str(config["name"])),
        "window_mode": config["window_mode"],
        "window_sec": config["window_sec"],
        "max_window_sec": config["max_window_sec"],
        "lcore": {
            "incident_windows": int(lcore_report.get("incident_windows") or 0),
            "avg_alerts_per_window": float((lcore_report.get("window_summary") or {}).get("avg_alerts_per_window") or 0.0),
            "single_alert_rate": round(single_alert_windows / max(int(lcore_report.get("incident_windows") or 0), 1), 6),
            "single_alert_windows": single_alert_windows,
            "risk_budget_20": _policy_summary(lcore_report, "budget-risk-20"),
            "strict_budget_20": _policy_summary(lcore_report, "budget-coverage-20"),
            "fault_state_only": _policy_summary(lcore_report, "scenario-only"),
        },
        "rcaeval": rcaeval_summary,
    }


def _policy_summary(report: dict[str, Any], policy: str) -> dict[str, Any]:
    record = (report.get("policies") or {}).get(policy) or {}
    window_metrics = record.get("window_metrics") or {}
    return {
        "external_calls": int(record.get("calls") or 0),
        "call_reduction_percent": float(record.get("call_reduction_percent") or 0.0),
        "high_value_window_recall": float(window_metrics.get("high_value_window_recall") or 0.0),
        "false_skip_rate": float(window_metrics.get("false_skip_rate") or 0.0),
        "pressure_window_skip_rate": float(window_metrics.get("pressure_window_skip_rate") or 0.0),
        "selected_windows": int(window_metrics.get("selected_windows") or 0),
    }


def _run_quality_cost(args: argparse.Namespace, config: dict[str, Any]) -> dict[str, Any]:
    capture = io.StringIO()
    with contextlib.redirect_stdout(capture):
        return run_quality_cost(
            Namespace(
                alert_dir=args.lcore_alert_dir,
                limit_files=args.limit_files,
                max_alerts=args.max_alerts,
                window_sec=config["window_sec"],
                recurrence_threshold=args.recurrence_threshold,
                downstream_threshold=args.downstream_threshold,
                group_by_scenario=False,
                window_mode=config["window_mode"],
                max_window_sec=config["max_window_sec"],
                output_json="",
                output_windows_jsonl=config["lcore_windows_jsonl"],
                output_labels_jsonl="",
            )
        )


def _evaluate_rcaeval(args: argparse.Namespace, config: dict[str, Any]) -> dict[str, Any]:
    records = read_jsonl(Path(args.rcaeval_records_jsonl))
    by_dataset: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        dataset = str(record.get("dataset") or record.get("benchmark") or "unknown")
        by_dataset[dataset].append(record)

    per_dataset: dict[str, dict[str, Any]] = {}
    all_windows: list[dict[str, Any]] = []
    for dataset, items in sorted(by_dataset.items()):
        windows = _dataset_windows(
            items,
            window_sec=config["window_sec"],
            window_mode=config["window_mode"],
            max_window_sec=config["max_window_sec"],
        )
        per_dataset[dataset] = _rcaeval_policy_summary(windows)
        all_windows.extend(windows)

    counts = [int((entry.get("incident_windows") or 0)) for entry in per_dataset.values()]
    return {
        "combined": _rcaeval_policy_summary(all_windows),
        "per_dataset": per_dataset,
        "window_count_mean": round(mean(counts), 6) if counts else 0.0,
        "window_count_stddev": round(pstdev(counts), 6) if len(counts) >= 2 else 0.0,
    }


def _dataset_windows(
    records: list[dict[str, Any]],
    *,
    window_sec: int,
    window_mode: str,
    max_window_sec: int,
) -> list[dict[str, Any]]:
    alerts = [_to_alert(record, idx) for idx, record in enumerate(records)]
    windows, _ = build_incident_window_index(
        alerts,
        window_sec=window_sec,
        window_mode=window_mode,
        max_window_sec=max_window_sec,
    )
    return windows


def _rcaeval_policy_summary(windows: list[dict[str, Any]]) -> dict[str, Any]:
    all_window_ids = {str(window.get("window_id") or "") for window in windows}
    high_value_window_ids = {
        str(window.get("window_id") or "")
        for window in windows
        if int(window.get("high_value_count") or 0) > 0
    }
    strict_budget = select_windows_under_budget(windows, budget_fraction=0.2, min_high_value=False)
    risk_budget = select_windows_under_budget(windows, budget_fraction=0.2, min_high_value=True)
    return {
        "incident_windows": len(windows),
        "fault_state_only": selected_window_metrics(windows, high_value_window_ids, call_mode="high-value-alerts"),
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
        "invoke_all": selected_window_metrics(windows, all_window_ids, call_mode="all-alerts"),
    }


def _default_configs() -> list[dict[str, Any]]:
    base = Path("/data/netops-runtime/LCORE-D/work")
    specs = [
        ("fixed-600", "fixed", 600, 600),
        ("session-900x1800", "session", 900, 1800),
        ("adaptive-600x1800", "adaptive", 600, 1800),
        ("aics-topology-500x1200", "aics-topology", 500, 1200),
        ("aics-topology-600x1800", "aics-topology", 600, 1800),
        ("aics-topology-900x1800", "aics-topology", 900, 1800),
        ("aics-evidence-600x1800", "aics-evidence", 600, 1800),
        ("aics-evidence-900x1800", "aics-evidence", 900, 1800),
        ("aics-hybrid-600x1800", "aics", 600, 1800),
        ("aics-hybrid-900x1800", "aics", 900, 1800),
    ]
    return [
        {
            "name": name,
            "window_mode": mode,
            "window_sec": window_sec,
            "max_window_sec": max_window_sec,
            "lcore_windows_jsonl": str(base / f"window-boundary-benchmark-{name}.jsonl"),
        }
        for name, mode, window_sec, max_window_sec in specs
    ]


def _render_plot(rows: list[dict[str, Any]], *, recommended_name: str, output_png: Path) -> None:
    colors = {
        "fixed": "#7f7f7f",
        "session": "#1f77b4",
        "adaptive": "#d62728",
        "aics-topology": "#2ca02c",
        "aics-evidence": "#ff7f0e",
        "aics": "#9467bd",
    }
    markers = {
        "fixed": "s",
        "session": "D",
        "adaptive": "o",
        "aics-topology": "^",
        "aics-evidence": "P",
        "aics": "X",
    }
    fig, ax = plt.subplots(figsize=(9.2, 6.1))
    important = {
        "fixed-600",
        "session-900x1800",
        "adaptive-600x1800",
        "aics-topology-500x1200",
        "aics-evidence-600x1800",
        "aics-hybrid-600x1800",
    }
    label_offsets = {
        "fixed-600": (8, 10),
        "session-900x1800": (8, 8),
        "adaptive-600x1800": (8, 8),
        "aics-topology-500x1200": (8, 8),
        "aics-evidence-600x1800": (8, 10),
        "aics-hybrid-600x1800": (8, 4),
    }

    for row in rows:
        color = colors.get(str(row["window_mode"]), "#333333")
        marker = "*" if str(row["name"]) == recommended_name else markers.get(str(row["window_mode"]), "o")
        bubble = 80 + 700 * float(row["lcore"]["single_alert_rate"])
        edgecolor = "#111111" if str(row["name"]) == recommended_name else "white"
        linewidth = 1.0 if str(row["name"]) == recommended_name else 0.8
        ax.scatter(
            row["lcore"]["risk_budget_20"]["external_calls"],
            row["lcore"]["strict_budget_20"]["high_value_window_recall"] * 100.0,
            color=color,
            s=300 if marker == "*" else bubble,
            marker=marker,
            alpha=0.9,
            edgecolors=edgecolor,
            linewidths=linewidth,
            zorder=4 if str(row["name"]) == recommended_name else 3,
        )
        if str(row["name"]) in important or str(row["name"]) == recommended_name:
            offset = label_offsets.get(str(row["name"]), (6, 6))
            ax.annotate(
                str(row["display_name"]),
                (
                    row["lcore"]["risk_budget_20"]["external_calls"],
                    row["lcore"]["strict_budget_20"]["high_value_window_recall"] * 100.0,
                ),
                fontsize=8.2,
                xytext=offset,
                textcoords="offset points",
            )

    ax.set_title("Window Boundary Algorithms on LCORE-D")
    ax.set_xlabel("Risk-budget 20% external calls")
    ax.set_ylabel("Strict-budget 20% high-value recall (%)")
    ax.grid(alpha=0.25)
    ax.set_xlim(430, 610)
    ax.set_ylim(74, 93)
    ax.axvline(500, color="#bbbbbb", linestyle="--", linewidth=0.8, zorder=1)
    ax.axhline(84.52, color="#bbbbbb", linestyle=":", linewidth=0.8, zorder=1)
    ax.text(
        0.02,
        0.98,
        "Marker size: single-alert window rate\n"
        "Color/shape: boundary family\n"
        "RCAEval transfer: all dynamic methods keep 375 windows; fixed bucket yields 377",
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=8.0,
        bbox={"facecolor": "white", "edgecolor": "#cccccc", "pad": 2.5, "alpha": 0.95},
    )

    handles = [
        plt.Line2D(
            [0],
            [0],
            marker=markers.get(mode, "o"),
            color="w",
            label=_family_label(mode),
            markerfacecolor=color,
            markeredgecolor="white",
            markersize=9,
        )
        for mode, color in colors.items()
    ]
    ax.legend(handles=handles, loc="lower right", frameon=False, ncol=2)
    fig.tight_layout()
    output_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_png, dpi=200, bbox_inches="tight")
    plt.close(fig)


def _display_name(name: str) -> str:
    labels = {
        "fixed-600": "Fixed 10m Bucket",
        "session-900x1800": "Long Session",
        "adaptive-600x1800": "Gap-Adaptive Session",
        "aics-topology-500x1200": "Topology-Coupled AiCS",
        "aics-topology-600x1800": "Topology-Coupled Wide",
        "aics-topology-900x1800": "Topology-Coupled Loose",
        "aics-evidence-600x1800": "Evidence-Coupled AiCS",
        "aics-evidence-900x1800": "Evidence-Coupled Loose",
        "aics-hybrid-600x1800": "Hybrid AiCS",
        "aics-hybrid-900x1800": "Hybrid Loose",
    }
    return labels.get(name, name)


def _family_label(mode: str) -> str:
    labels = {
        "fixed": "Fixed bucket",
        "session": "Session window",
        "adaptive": "Gap-adaptive session",
        "aics-topology": "Topology-coupled",
        "aics-evidence": "Evidence-coupled",
        "aics": "Hybrid AICS",
    }
    return labels.get(mode, mode)


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark multiple incident-window boundary algorithms on LCORE-D and RCAEval.")
    parser.add_argument("--lcore-alert-dir", default=DEFAULT_LCORE_ALERT_DIR)
    parser.add_argument("--rcaeval-records-jsonl", default=DEFAULT_RCAEVAL_RECORDS)
    parser.add_argument("--limit-files", type=int, default=0)
    parser.add_argument("--max-alerts", type=int, default=0)
    parser.add_argument("--recurrence-threshold", type=int, default=3)
    parser.add_argument("--downstream-threshold", type=int, default=10)
    parser.add_argument("--output-json", default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-png", default=DEFAULT_OUTPUT_PNG)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
