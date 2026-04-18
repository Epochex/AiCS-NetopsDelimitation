from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def run(args: argparse.Namespace) -> dict[str, Any]:
    import matplotlib.pyplot as plt
    import seaborn as sns

    report = json.loads(Path(args.report_json).read_text(encoding="utf-8"))
    rows = _rows(report)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    sns.set_theme(style="whitegrid", context="paper", font_scale=1.15)
    fig, axes = plt.subplots(1, 3, figsize=(14.5, 4.6), constrained_layout=True)
    _plot_recall_budget(axes[0], rows)
    _plot_pressure_budget(axes[1], rows)
    _plot_call_budget(axes[2], rows)
    fig.suptitle("Window-level admission under external-call budgets", fontsize=15, fontweight="bold")

    png_path = output_dir / "window_admission_quality_cost_frontier.png"
    pdf_path = output_dir / "window_admission_quality_cost_frontier.pdf"
    fig.savefig(png_path, dpi=220, bbox_inches="tight")
    fig.savefig(pdf_path, bbox_inches="tight")
    plt.close(fig)

    summary = {
        "schema_version": 1,
        "report_json": args.report_json,
        "png": str(png_path),
        "pdf": str(pdf_path),
        "policies_plotted": [row["policy"] for row in rows],
    }
    if args.output_json:
        Path(args.output_json).write_text(
            json.dumps(summary, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(summary, ensure_ascii=True, indent=2, sort_keys=True))
    return summary


def _plot_recall_budget(ax: Any, rows: list[dict[str, Any]]) -> None:
    safety = _budget_rows(rows, "budget-risk-")
    strict = _budget_rows(rows, "budget-coverage-")
    ax.plot(
        [row["budget_percent"] for row in strict],
        [row["high_value_window_recall"] for row in strict],
        marker="o",
        linewidth=2.2,
        color="#1b9e77",
        label="strict budget",
    )
    ax.plot(
        [row["budget_percent"] for row in safety],
        [row["high_value_window_recall"] for row in safety],
        marker="s",
        linewidth=2.2,
        color="#d95f02",
        label="risk budget + safety floor",
    )
    _baseline_line(ax, rows, "scenario-only", "scenario-only")
    _baseline_line(ax, rows, "window-risk-tier", "risk-tier")
    ax.set_xlabel("Nominal external-call budget (% windows)")
    ax.set_ylabel("High-value window recall")
    ax.set_ylim(-0.03, 1.06)
    _budget_xaxis(ax)
    ax.set_title("A. High-value coverage", loc="left", fontweight="bold")
    ax.legend(frameon=True, loc="lower right", fontsize=7)


def _plot_pressure_budget(ax: Any, rows: list[dict[str, Any]]) -> None:
    safety = _budget_rows(rows, "budget-risk-")
    strict = _budget_rows(rows, "budget-coverage-")
    ax.plot(
        [row["budget_percent"] for row in strict],
        [row["pressure_skip"] for row in strict],
        marker="o",
        linewidth=2.2,
        color="#1b9e77",
        label="strict budget",
    )
    ax.plot(
        [row["budget_percent"] for row in safety],
        [row["pressure_skip"] for row in safety],
        marker="s",
        linewidth=2.2,
        color="#d95f02",
        label="risk budget + safety floor",
    )
    _baseline_line(ax, rows, "scenario-only", "scenario-only")
    _baseline_line(ax, rows, "window-risk-tier", "risk-tier")
    _baseline_line(ax, rows, "topology+timeline", "topology+timeline")
    ax.set_xlabel("Nominal external-call budget (% windows)")
    ax.set_ylabel("Pressure-window skip rate")
    ax.set_ylim(-0.03, 1.06)
    _budget_xaxis(ax)
    ax.set_title("B. Residual pressure risk", loc="left", fontweight="bold")
    ax.legend(frameon=True, loc="upper right", fontsize=7)


def _plot_call_budget(ax: Any, rows: list[dict[str, Any]]) -> None:
    safety = _budget_rows(rows, "budget-risk-")
    strict = _budget_rows(rows, "budget-coverage-")
    ax.plot(
        [row["budget_percent"] for row in strict],
        [row["calls"] for row in strict],
        marker="o",
        linewidth=2.2,
        color="#1b9e77",
        label="strict budget",
    )
    ax.plot(
        [row["budget_percent"] for row in safety],
        [row["calls"] for row in safety],
        marker="s",
        linewidth=2.2,
        color="#d95f02",
        label="risk budget + safety floor",
    )
    _baseline_line(ax, rows, "scenario-only", "scenario-only", field="calls")
    _baseline_line(ax, rows, "window-risk-tier", "risk-tier", field="calls")
    ax.set_xlabel("Nominal external-call budget (% windows)")
    ax.set_ylabel("External LLM calls")
    _budget_xaxis(ax)
    ax.set_title("C. Actual provider load", loc="left", fontweight="bold")
    ax.legend(frameon=True, loc="upper left", fontsize=7)


def _baseline_line(ax: Any, rows: list[dict[str, Any]], policy: str, label: str, *, field: str | None = None) -> None:
    row = _row(rows, policy)
    if not row:
        return
    value = row[field] if field else row["high_value_window_recall"] if "coverage" in ax.get_title().lower() else row["pressure_skip"]
    ax.axhline(value, color="#6b7280", linestyle="--", linewidth=1.0, alpha=0.55, label=label)


def _budget_xaxis(ax: Any) -> None:
    ticks = [1, 2, 5, 10, 20, 40, 60]
    ax.set_xscale("log")
    ax.set_xlim(0.8, 75)
    ax.set_xticks(ticks)
    ax.set_xticklabels([str(tick) for tick in ticks])


def _rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    policies = report.get("policies") or {}
    rows: list[dict[str, Any]] = []
    for policy, item in sorted(policies.items()):
        metrics = item.get("window_metrics") or {}
        rows.append(
            {
                "policy": policy,
                "budget_percent": _budget_percent(policy),
                "calls": int(item.get("calls") or 0),
                "call_reduction": float(item.get("call_reduction_percent") or 0),
                "high_value_window_recall": float(metrics.get("high_value_window_recall") or 0),
                "pressure_skip": float(metrics.get("pressure_window_skip_rate") or 0),
                "evidence_coverage": float(metrics.get("evidence_target_coverage_rate") or 0),
                "windows_selected": int(metrics.get("windows_selected") or 0),
            }
        )
    return rows


def _budget_rows(rows: list[dict[str, Any]], prefix: str) -> list[dict[str, Any]]:
    return sorted(
        [row for row in rows if row["policy"].startswith(prefix)],
        key=lambda row: row["budget_percent"],
    )


def _budget_percent(policy: str) -> int:
    try:
        return int(policy.rsplit("-", 1)[-1])
    except ValueError:
        return 0


def _row(rows: list[dict[str, Any]], policy: str) -> dict[str, Any] | None:
    for row in rows:
        if row["policy"] == policy:
            return row
    return None


def _short(policy: str) -> str:
    return {
        "scenario-only": "scenario",
        "self-healing-aware": "self-healing",
        "window-risk-tier": "risk-tier",
        "topology+timeline": "topology+timeline",
        "invoke-all": "invoke-all",
    }.get(policy, policy)


def main() -> None:
    parser = argparse.ArgumentParser(description="Render paper-style PNG/PDF quality-cost frontier plots.")
    parser.add_argument("--report-json", required=True)
    parser.add_argument("--output-dir", default="documentation/images")
    parser.add_argument("--output-json", default="")
    run(parser.parse_args())


if __name__ == "__main__":
    main()
