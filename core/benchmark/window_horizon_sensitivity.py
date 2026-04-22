from __future__ import annotations

import argparse
import contextlib
import io
import json
from argparse import Namespace
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt

from core.benchmark.quality_cost_policy_runner import run as run_quality_cost


DEFAULT_ALERT_DIR = "/data/netops-runtime/LCORE-D/work/alerts-lcore-corepatched-full-20260412T152119Z"
DEFAULT_OUTPUT_JSON = "/data/netops-runtime/LCORE-D/work/window-horizon-sensitivity.json"
DEFAULT_OUTPUT_PNG = "/data/netops-runtime/LCORE-D/work/window-horizon-sensitivity.png"


def run(args: argparse.Namespace) -> dict[str, Any]:
    configs = _default_configs()
    rows = [_evaluate_config(args, config) for config in configs]
    recommended = min(
        rows,
        key=lambda row: (
            -float(row["risk_budget_20"]["high_value_window_recall"]),
            int(row["risk_budget_20"]["external_calls"]),
            float(row["single_alert_rate"]),
            float(row["strict_budget_20"]["false_skip_rate"]),
            float(row["risk_budget_20"]["pressure_window_skip_rate"]),
            int(row["incident_windows"]),
        ),
    )
    summary = {
        "schema_version": 1,
        "alert_dir": args.alert_dir,
        "selection_rule": (
            "maximize risk-budget-20 high-value recall, then minimize risk-budget-20 external calls, "
            "single-alert rate, strict-budget false skips, and residual pressure skips"
        ),
        "recommended_config": {
            "name": recommended["name"],
            "window_mode": recommended["window_mode"],
            "window_sec": recommended["window_sec"],
            "max_window_sec": recommended["max_window_sec"],
        },
        "configs": rows,
    }
    output_json = Path(args.output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(summary, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.output_png:
        _render_plot(rows, recommended_name=str(recommended["name"]), output_png=Path(args.output_png))
    print(json.dumps(summary, ensure_ascii=True, indent=2, sort_keys=True))
    return summary


def _evaluate_config(args: argparse.Namespace, config: dict[str, Any]) -> dict[str, Any]:
    report = _run_quality_cost(args, config)
    windows_path = Path(config["windows_jsonl"])
    windows = _read_jsonl(windows_path)
    single_alert_windows = sum(1 for window in windows if int(window.get("alert_count") or 0) <= 1)
    missing_timeline_windows = sum(1 for window in windows if len(window.get("timeline") or []) <= 1)
    return {
        "name": config["name"],
        "window_mode": config["window_mode"],
        "window_sec": config["window_sec"],
        "max_window_sec": config["max_window_sec"],
        "incident_windows": int(report.get("incident_windows") or 0),
        "avg_alerts_per_window": float((report.get("window_summary") or {}).get("avg_alerts_per_window") or 0.0),
        "pressure_windows": int((report.get("window_summary") or {}).get("pressure_windows") or 0),
        "single_alert_windows": single_alert_windows,
        "single_alert_rate": round(single_alert_windows / max(int(report.get("incident_windows") or 0), 1), 6),
        "missing_timeline_windows": missing_timeline_windows,
        "risk_budget_20": _policy_summary(report, "budget-risk-20"),
        "strict_budget_20": _policy_summary(report, "budget-coverage-20"),
        "window_risk_tier": _policy_summary(report, "window-risk-tier"),
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
                alert_dir=args.alert_dir,
                limit_files=args.limit_files,
                max_alerts=args.max_alerts,
                window_sec=config["window_sec"],
                recurrence_threshold=args.recurrence_threshold,
                downstream_threshold=args.downstream_threshold,
                group_by_scenario=False,
                window_mode=config["window_mode"],
                max_window_sec=config["max_window_sec"],
                output_json="",
                output_windows_jsonl=config["windows_jsonl"],
                output_labels_jsonl="",
            )
        )


def _default_configs() -> list[dict[str, Any]]:
    base = Path("/data/netops-runtime/LCORE-D/work")
    specs = [
        ("fixed-300", "fixed", 300, 300),
        ("fixed-600", "fixed", 600, 600),
        ("fixed-900", "fixed", 900, 900),
        ("session-300x900", "session", 300, 900),
        ("session-600x900", "session", 600, 900),
        ("session-900x1800", "session", 900, 1800),
        ("adaptive-300x900", "adaptive", 300, 900),
        ("adaptive-600x900", "adaptive", 600, 900),
        ("adaptive-600x1800", "adaptive", 600, 1800),
    ]
    return [
        {
            "name": name,
            "window_mode": mode,
            "window_sec": window_sec,
            "max_window_sec": max_window_sec,
            "windows_jsonl": str(base / f"window-horizon-{name}.jsonl"),
        }
        for name, mode, window_sec, max_window_sec in specs
    ]


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _render_plot(rows: list[dict[str, Any]], *, recommended_name: str, output_png: Path) -> None:
    colors = {"fixed": "#7f7f7f", "session": "#1f77b4", "adaptive": "#d62728"}
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))

    for row in rows:
        color = colors.get(str(row["window_mode"]), "#333333")
        marker = "*" if str(row["name"]) == recommended_name else "o"
        axes[0].scatter(
            row["risk_budget_20"]["external_calls"],
            row["risk_budget_20"]["high_value_window_recall"] * 100.0,
            color=color,
            s=160 if marker == "*" else 90,
            marker=marker,
            alpha=0.9,
        )
        axes[0].annotate(str(row["name"]), (row["risk_budget_20"]["external_calls"], row["risk_budget_20"]["high_value_window_recall"] * 100.0), fontsize=8, xytext=(4, 4), textcoords="offset points")
        axes[1].scatter(
            row["incident_windows"],
            row["single_alert_rate"] * 100.0,
            color=color,
            s=160 if marker == "*" else 90,
            marker=marker,
            alpha=0.9,
        )
        axes[1].annotate(str(row["name"]), (row["incident_windows"], row["single_alert_rate"] * 100.0), fontsize=8, xytext=(4, 4), textcoords="offset points")

    axes[0].set_title("Risk-Budget 20% Operating Point")
    axes[0].set_xlabel("Representative external calls")
    axes[0].set_ylabel("High-value window recall (%)")
    axes[0].grid(alpha=0.25)
    axes[1].set_title("Window Fragmentation")
    axes[1].set_xlabel("Incident windows")
    axes[1].set_ylabel("Single-alert window rate (%)")
    axes[1].grid(alpha=0.25)

    handles = [
        plt.Line2D([0], [0], marker="o", color="w", label=mode, markerfacecolor=color, markersize=9)
        for mode, color in colors.items()
    ]
    axes[0].legend(handles=handles, loc="lower right", frameon=False)
    fig.tight_layout()
    output_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_png, dpi=180, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate fixed/session/adaptive incident-window horizons on LCORE-D.")
    parser.add_argument("--alert-dir", default=DEFAULT_ALERT_DIR)
    parser.add_argument("--limit-files", type=int, default=0)
    parser.add_argument("--max-alerts", type=int, default=0)
    parser.add_argument("--recurrence-threshold", type=int, default=3)
    parser.add_argument("--downstream-threshold", type=int, default=10)
    parser.add_argument("--output-json", default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-png", default=DEFAULT_OUTPUT_PNG)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
