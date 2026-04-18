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
    fig, axes = plt.subplots(1, 2, figsize=(12.2, 4.8), constrained_layout=True)
    _plot_policy_family(axes[0], _budget_rows(rows, "budget-coverage-"), "A. Strict coverage budget")
    _plot_policy_family(axes[1], _budget_rows(rows, "budget-risk-"), "B. Risk budget with safety floor")
    fig.suptitle("Window-level admission quality-cost frontier", fontsize=15, fontweight="bold")

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


def _plot_policy_family(ax: Any, rows: list[dict[str, Any]], title: str) -> None:
    x = [row["budget_percent"] for row in rows]
    series = [
        (
            "High-value recall",
            [100 * row["high_value_window_recall"] for row in rows],
            "#7b61b6",
            "o",
            "-",
        ),
        (
            "Call reduction",
            [row["call_reduction"] for row in rows],
            "#4f83d1",
            "D",
            "-",
        ),
        (
            "Pressure coverage",
            [100 * (1 - row["pressure_skip"]) for row in rows],
            "#d95f02",
            "^",
            "-",
        ),
        (
            "Evidence coverage",
            [100 * row["evidence_coverage"] for row in rows],
            "#6b8e23",
            None,
            "--",
        ),
    ]
    for label, values, color, marker, linestyle in series:
        ax.plot(
            x,
            values,
            color=color,
            marker=marker,
            linestyle=linestyle,
            linewidth=2.0,
            markersize=5.5 if marker else 0,
            label=label,
            alpha=0.96,
        )
        _direct_label(ax, x[-1], values[-1], label, color)

    _annotate_operating_point(ax, rows)
    ax.set_xlabel("External-call budget (% of windows)")
    ax.set_ylabel("Rate (%)")
    ax.set_ylim(-3, 108)
    _budget_xaxis(ax)
    ax.set_title(title, loc="left", fontweight="bold")
    ax.grid(True, axis="both", color="#d8d8d8", linestyle=":", linewidth=0.9)


def _direct_label(ax: Any, x: float, y: float, label: str, color: str) -> None:
    offsets = {
        "High-value recall": 6.4,
        "Call reduction": -4.8,
        "Pressure coverage": 4.0,
        "Evidence coverage": -7.0,
    }
    ax.annotate(
        label,
        xy=(x, y),
        xytext=(8, offsets.get(label, 0)),
        textcoords="offset points",
        color=color,
        fontsize=7,
        va="center",
        clip_on=False,
    )


def _annotate_operating_point(ax: Any, rows: list[dict[str, Any]]) -> None:
    target = next((row for row in rows if row["budget_percent"] == 20), rows[min(len(rows) - 1, 3)])
    x = target["budget_percent"]
    y = target["call_reduction"]
    text = (
        f"{target['call_reduction']:.1f}% reduction\n"
        f"{100 * target['high_value_window_recall']:.1f}% window recall"
    )
    ax.annotate(
        text,
        xy=(x, y),
        xytext=(22, -66),
        textcoords="offset points",
        fontsize=7,
        arrowprops={"arrowstyle": "->", "lw": 0.9, "color": "#333"},
        bbox={"boxstyle": "round,pad=0.2", "fc": "white", "ec": "#cccccc", "alpha": 0.88},
    )


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


def main() -> None:
    parser = argparse.ArgumentParser(description="Render paper-style PNG/PDF quality-cost frontier plots.")
    parser.add_argument("--report-json", required=True)
    parser.add_argument("--output-dir", default="documentation/images")
    parser.add_argument("--output-json", default="")
    run(parser.parse_args())


if __name__ == "__main__":
    main()
