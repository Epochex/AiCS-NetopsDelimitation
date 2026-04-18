from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def run(args: argparse.Namespace) -> dict[str, Any]:
    import matplotlib.pyplot as plt
    import seaborn as sns

    report = json.loads(Path(args.report_json).read_text(encoding="utf-8"))
    rows = _budget_rows(report)
    baselines = _baseline_rows(report)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    sns.set_theme(style="whitegrid", context="paper", font_scale=1.12)
    fig, axes = plt.subplots(1, 2, figsize=(12.4, 4.9), constrained_layout=True)
    _plot_frontier(axes[0], rows)
    _plot_baselines(axes[1], baselines)
    fig.suptitle("RCAEval RE1 external validation: admission quality-cost behavior", fontsize=14, fontweight="bold")

    png_path = output_dir / "rcaeval_external_validation_frontier.png"
    pdf_path = output_dir / "rcaeval_external_validation_frontier.pdf"
    fig.savefig(png_path, dpi=240, bbox_inches="tight")
    fig.savefig(pdf_path, bbox_inches="tight")
    plt.close(fig)

    summary = {
        "schema_version": 1,
        "report_json": args.report_json,
        "png": str(png_path),
        "pdf": str(pdf_path),
        "budget_policies": [row["policy"] for row in rows],
        "baselines": [row["policy"] for row in baselines],
    }
    if args.output_json:
        Path(args.output_json).write_text(
            json.dumps(summary, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(summary, ensure_ascii=True, indent=2, sort_keys=True))
    return summary


def _plot_frontier(ax: Any, rows: list[dict[str, Any]]) -> None:
    x = [row["calls"] for row in rows]
    budget = [row["budget_percent"] for row in rows]
    series = [
        ("High-value recall", [100 * row["recall"] for row in rows], "#7b61b6", "o", "-"),
        ("Call reduction", [row["call_reduction"] for row in rows], "#4f83d1", "D", "-"),
        ("Pressure coverage", [100 * (1 - row["pressure_skip"]) for row in rows], "#d95f02", "^", "-"),
        ("Evidence coverage", [100 * row["evidence_coverage"] for row in rows], "#6b8e23", None, "--"),
    ]
    for label, values, color, marker, linestyle in series:
        ax.plot(
            x,
            values,
            label=label,
            color=color,
            marker=marker,
            linewidth=2.0,
            markersize=5.5 if marker else 0,
            linestyle=linestyle,
            alpha=0.96,
        )
    for xi, pct in zip(x, budget):
        ax.annotate(f"{pct}%", xy=(xi, 2.0), ha="center", va="bottom", fontsize=6.7, color="#555")
    ax.set_title("A. Coverage-budget frontier", loc="left", fontweight="bold")
    ax.set_xlabel("External model calls")
    ax.set_ylabel("Rate (%)")
    ax.set_ylim(-4, 108)
    ax.grid(True, axis="both", linestyle=":", linewidth=0.9, color="#d8d8d8")
    ax.margins(x=0.08)
    ax.legend(
        loc="upper center",
        bbox_to_anchor=(0.5, -0.13),
        ncol=4,
        frameon=False,
        fontsize=7.2,
        handlelength=2.2,
        columnspacing=1.0,
    )


def _plot_baselines(ax: Any, rows: list[dict[str, Any]]) -> None:
    policies = [row["label"] for row in rows]
    call_reduction = [row["call_reduction"] for row in rows]
    recall = [100 * row["recall"] for row in rows]
    x = list(range(len(rows)))
    width = 0.36
    ax.bar([i - width / 2 for i in x], call_reduction, width=width, color="#4f83d1", label="Call reduction")
    ax.bar([i + width / 2 for i in x], recall, width=width, color="#7b61b6", label="High-value recall")
    for i, row in enumerate(rows):
        ax.annotate(
            f"{row['calls']}",
            xy=(i - width / 2, call_reduction[i]),
            xytext=(0, 3),
            textcoords="offset points",
            ha="center",
            fontsize=6.8,
            color="#333",
        )
    ax.set_title("B. Admission baselines", loc="left", fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels(policies, rotation=18, ha="right")
    ax.set_ylim(0, 112)
    ax.set_ylabel("Rate (%)")
    ax.legend(frameon=True, fontsize=7, loc="lower right")
    ax.grid(True, axis="y", linestyle=":", linewidth=0.9, color="#d8d8d8")
    ax.text(
        0.02,
        0.95,
        "Numbers above blue bars are external calls.",
        transform=ax.transAxes,
        va="top",
        fontsize=7,
        color="#444",
        bbox={"boxstyle": "round,pad=0.2", "fc": "white", "ec": "#dddddd", "alpha": 0.9},
    )


def _budget_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    policies = report.get("policies") or {}
    rows: list[dict[str, Any]] = []
    for name, item in policies.items():
        if not name.startswith("budget-coverage-"):
            continue
        rows.append(_row(name, item))
    return sorted(rows, key=lambda row: row["budget_percent"])


def _baseline_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    labels = {
        "invoke-all": "invoke-all",
        "scenario-only": "scenario-only",
        "window-risk-tier": "risk-tier",
        "oracle": "oracle",
    }
    policies = report.get("policies") or {}
    return [
        {**_row(name, policies[name]), "label": label}
        for name, label in labels.items()
        if name in policies
    ]


def _row(policy: str, item: dict[str, Any]) -> dict[str, Any]:
    return {
        "policy": policy,
        "budget_percent": _budget_percent(policy),
        "calls": int(item.get("external_calls") or 0),
        "call_reduction": float(item.get("call_reduction_percent") or 0),
        "recall": float(item.get("high_value_window_recall") or 0),
        "pressure_skip": float(item.get("pressure_window_skip_rate") or 0),
        "evidence_coverage": float(item.get("evidence_target_coverage_rate") or 0),
    }


def _budget_percent(policy: str) -> int:
    try:
        return int(policy.rsplit("-", 1)[-1])
    except ValueError:
        return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Render RCAEval external validation frontier plot.")
    parser.add_argument("--report-json", required=True)
    parser.add_argument("--output-dir", default="documentation/images")
    parser.add_argument("--output-json", default="")
    run(parser.parse_args())


if __name__ == "__main__":
    main()
