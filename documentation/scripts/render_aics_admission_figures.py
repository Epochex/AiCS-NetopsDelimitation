from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np


ROOT = Path("/data")
IMAGE_DIR = ROOT / "Netops-causality-remediation" / "documentation" / "images"
RESULT_DIR = ROOT / "Netops-causality-remediation" / "documentation" / "results"
AUDIT_JSON = ROOT / "netops-runtime" / "LCORE-D" / "work" / "deterministic-layer-audit-v1.json"
LCORE_POLICY_JSON = ROOT / "Netops-causality-remediation" / "outputs" / "lcore_admission_baselines.json"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def set_style() -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "font.family": "DejaVu Sans",
            "font.size": 7.0,
            "axes.titlesize": 7.5,
            "axes.labelsize": 7.1,
            "xtick.labelsize": 6.3,
            "ytick.labelsize": 6.3,
            "legend.fontsize": 5.9,
            "axes.linewidth": 0.65,
            "grid.color": "#d4d4d4",
            "grid.linewidth": 0.48,
            "savefig.facecolor": "white",
            "figure.dpi": 180,
            "savefig.dpi": 300,
        }
    )


def pct(value: float, total: float) -> float:
    return 100.0 * value / total if total else 0.0


def fmt_int(value: int | float) -> str:
    return f"{int(value):,}"


def display_policy_name(policy: str) -> str:
    labels = {
        "invoke-all": "Invoke all",
        "scenario-only": "Fault-state only",
        "topology+timeline": "Topology+timeline",
        "window-risk-tier": "Window-risk-tier",
        "budget-coverage-20": "Strict budget 20%",
        "budget-risk-20": "Risk-budget 20% (proposed)",
    }
    return labels.get(policy, policy)


def deterministic_boundary_figure(audit: dict[str, Any]) -> Path:
    raw = audit["raw"]
    facts = audit["canonical_facts"]
    alerts = audit["deterministic_alerts"]
    windows = audit["incident_windows"]

    colors = {
        "normal": "#5DA5DA",
        "induced": "#D95F02",
        "transient": "#1B9E77",
        "mixed": "#E6AB02",
        "topology": "#756BB1",
        "scope": "#2C7FB8",
        "missing": "#737373",
        "impact": "#A6761D",
        "grid": "#D4D4D4",
    }

    fig, axes = plt.subplots(2, 2, figsize=(7.25, 6.1), constrained_layout=True)
    fig.set_constrained_layout_pads(w_pad=0.05, h_pad=0.08, wspace=0.11, hspace=0.15)

    ax = axes[0, 0]
    stages = [
        ("Source rows", raw["total_rows"]),
        ("Canonical facts", facts["total_facts"]),
        ("Fault facts", facts["is_fault_counts"]["true"]),
        ("Deterministic alerts", alerts["total_alerts"]),
        ("Incident windows", windows["total_windows"]),
    ]
    y = np.arange(len(stages))[::-1]
    x = [value for _, value in stages]
    ax.plot(x, y, color="#2F4B7C", lw=1.3, marker="o", ms=3.2, zorder=3)
    for yi, (label, value) in zip(y, stages):
        ax.hlines(yi, 1, value, color="#C7D0DE", lw=3.8, zorder=1)
        ax.text(1.18, yi + 0.03, label, ha="left", va="bottom", fontweight="bold", fontsize=6.8)
        ax.text(value * 1.07, yi, fmt_int(value), ha="left", va="center", fontsize=6.9)
    ax.set_xscale("log")
    ax.set_xlim(1, 340000)
    ax.set_ylim(-0.28, 4.45)
    ax.set_yticks([])
    ax.set_xlabel("Count, log scale")
    ax.grid(axis="x", which="major")
    ax.set_title("A  Denominator and compression", loc="left", fontweight="bold", pad=5)

    ax = axes[0, 1]
    stage_rows = [
        (
            "Canonical\nfacts",
            [
                ("normal", facts["is_fault_counts"]["false"], colors["normal"]),
                ("induced", facts["scenario_counts"]["induced_fault"], colors["induced"]),
                ("transient", facts["scenario_counts"]["transient_fault"], colors["transient"]),
            ],
            facts["total_facts"],
        ),
        (
            "Alerts",
            [
                ("induced", alerts["scenario_counts"]["induced_fault"], colors["induced"]),
                ("transient", alerts["scenario_counts"]["transient_fault"], colors["transient"]),
            ],
            alerts["total_alerts"],
        ),
    ]
    for row, (name, segments, total) in enumerate(stage_rows):
        left = 0.0
        for _, value, color in segments:
            width = pct(value, total)
            ax.barh(row, width, left=left, height=0.42, color=color, edgecolor="white", lw=0.55)
            if width >= 10:
                ax.text(
                    left + width / 2,
                    row,
                    f"{width:.1f}%\n{fmt_int(value)}",
                    ha="center",
                    va="center",
                    color="white" if color != colors["normal"] else "#17324D",
                    fontsize=6.0,
                    fontweight="bold",
                )
            left += width
        ax.text(-2.6, row, name, ha="right", va="center", fontweight="bold", fontsize=6.5)
    ax.set_xlim(-17, 124)
    ax.set_ylim(-0.65, 1.62)
    ax.set_yticks([])
    ax.set_xlabel("Share within stage (%)")
    ax.xaxis.set_major_locator(mticker.MultipleLocator(25))
    ax.grid(axis="x")
    handles = [plt.Rectangle((0, 0), 1, 1, color=colors[k]) for k in ["normal", "induced", "transient"]]
    ax.legend(handles, ["normal", "induced fault", "transient fault"], loc="upper right", frameon=True)
    ax.set_title("B  Fault-state composition", loc="left", fontweight="bold", pad=5)

    ax = axes[1, 0]
    label_counts = windows["window_label_counts"]
    order = [
        "local_transient_with_pressure",
        "external_multi_device_spread",
        "local_single_transient",
        "external_induced_fault",
        "mixed_fault_and_transient",
        "external_repeated_transient",
    ]
    labels = [
        "local transient\n+ pressure",
        "multi-device\nspread",
        "single\ntransient",
        "induced\nfault",
        "mixed fault\n+ transient",
        "repeated\ntransient",
    ]
    values = [label_counts[key] for key in order]
    bar_colors = [
        colors["transient"],
        colors["topology"],
        "#B2DF8A",
        colors["induced"],
        colors["mixed"],
        "#66C2A5",
    ]
    x_pos = np.arange(len(values))
    ax.bar(x_pos, values, color=bar_colors, edgecolor="white", lw=0.5, width=0.72)
    for xi, value in zip(x_pos, values):
        ax.text(
            xi,
            value + 32,
            f"{fmt_int(value)}\n{pct(value, windows['total_windows']):.1f}%",
            ha="center",
            va="bottom",
            fontsize=5.6,
        )
    ax.set_ylim(0, 1510)
    ax.set_xticks(x_pos)
    ax.set_xticklabels(labels, rotation=35, ha="right", rotation_mode="anchor")
    ax.tick_params(axis="x", length=0, pad=2)
    ax.set_ylabel("Incident windows")
    ax.grid(axis="y")
    ax.set_title("C  Correlated window labels", loc="left", fontweight="bold", pad=5)

    ax = axes[1, 1]
    atoms = windows["top_risk_atoms"]
    atom_rows = [
        ("topology\npressure", "pressure:topology", colors["topology"]),
        ("multi-device\nspread", "spread:multi_device", colors["topology"]),
        ("downstream\nfanout", "impact:downstream_fanout", colors["impact"]),
        ("missing\ntimeline", "missing:timeline", colors["missing"]),
        ("path\nscope c9", "scope:path:c9abcb4dc6", colors["scope"]),
        ("device\nscope 748", "scope:device:748005f94e", colors["scope"]),
        ("device\nscope 04f", "scope:device:04fef58513", colors["scope"]),
        ("multi-path\nscope", "scope:multi_path", colors["scope"]),
    ]
    values = [atoms[key] for _, key, _ in atom_rows]
    x_pos = np.arange(len(values))
    ax.bar(x_pos, values, color=[color for _, _, color in atom_rows], edgecolor="white", lw=0.5, width=0.72)
    for xi, value in zip(x_pos, values):
        ax.text(xi, value + 42, fmt_int(value), ha="center", va="bottom", fontsize=5.5)
    ax.set_ylim(0, 2920)
    ax.set_xticks(x_pos)
    ax.set_xticklabels([label for label, _, _ in atom_rows], rotation=38, ha="right", rotation_mode="anchor")
    ax.tick_params(axis="x", length=0, pad=2)
    ax.set_ylabel("Windows carrying atom")
    ax.grid(axis="y")
    coverage = windows["selected_evidence_coverage"]
    total = windows["total_windows"]
    ax.text(
        0.35,
        0.90,
        "Evidence coverage\n"
        f"representative/device/path: {fmt_int(total)}/{fmt_int(total)} windows\n"
        f"timeline missing: {fmt_int(coverage['single_alert_windows_with_missing_timeline'])} single-alert windows",
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=5.6,
        bbox={"facecolor": "white", "edgecolor": "#CCCCCC", "pad": 1.7, "alpha": 0.96},
    )
    ax.set_title("D  Risk atoms and boundary coverage", loc="left", fontweight="bold", pad=5)

    for ax in axes.ravel():
        for side in ["top", "right"]:
            ax.spines[side].set_visible(False)

    path = IMAGE_DIR / "aics_deterministic_boundary_audit.png"
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def policy_budget(name: str) -> int:
    return int(name.rsplit("-", 1)[-1])


def budget_rows(report: dict[str, Any], prefix: str) -> list[dict[str, float]]:
    rows: list[dict[str, float]] = []
    for name, policy in report["policies"].items():
        if not name.startswith(prefix):
            continue
        rows.append(
            {
                "budget": float(policy_budget(name)),
                "calls_pct": pct(float(policy["context_units"]), float(report["alerts"])),
                "high_value_recall": 100.0 * float(policy["high_value_window_recall"]),
                "high_value_miss": 100.0 * (1.0 - float(policy["high_value_window_recall"])),
                "pressure_coverage": 100.0 * (1.0 - float(policy["pressure_window_skip_rate"])),
                "pressure_uncovered": 100.0 * float(policy["pressure_window_skip_rate"]),
            }
        )
    return sorted(rows, key=lambda row: row["budget"])


def lcore_admission_tradeoff_figure(policy_report: dict[str, Any], audit_report: dict[str, Any]) -> Path:
    strict = budget_rows(policy_report, "coverage-only-")
    risk = budget_rows(policy_report, "risk-coverage-")
    audit_policies = audit_report["policy_report"]["policies"]
    alerts = float(audit_report["deterministic_alerts"]["total_alerts"])

    fig, axes = plt.subplots(
        1,
        2,
        figsize=(7.25, 3.55),
        constrained_layout=True,
        gridspec_kw={"width_ratios": [1.18, 1.0]},
    )
    fig.set_constrained_layout_pads(w_pad=0.05, h_pad=0.08, wspace=0.09, hspace=0.05)
    colors = {
        "strict": "#D95F02",
        "risk": "#1B9E77",
        "calls": "#D9D9D9",
        "recall": "#2C7FB8",
        "pressure": "#756BB1",
        "false": "#B2182B",
    }

    ax = axes[0]
    curves = [
        (strict, "strict: high-value missed", "high_value_miss", colors["strict"], "o", "-"),
        (risk, "risk floor: high-value missed", "high_value_miss", colors["risk"], "o", "--"),
        (strict, "strict: pressure left uncovered", "pressure_uncovered", "#A6761D", "s", "-"),
        (risk, "risk floor: pressure left uncovered", "pressure_uncovered", "#756BB1", "s", "--"),
    ]
    for rows, label, metric, color, marker, linestyle in curves:
        ax.plot(
            [row["budget"] for row in rows],
            [row[metric] for row in rows],
            marker=marker,
            ms=3.2,
            lw=1.35,
            color=color,
            linestyle=linestyle,
            label=label,
            alpha=0.96,
        )
    ax.axhline(0, color="#9A9A9A", lw=0.7, ls=":")
    ax.set_xscale("log")
    ax.set_xlim(0.8, 70)
    ax.set_ylim(-4, 104)
    ax.set_xticks([1, 2, 5, 10, 20, 40, 60])
    ax.set_xticklabels(["1", "2", "5", "10", "20", "40", "60"])
    ax.set_xlabel("Nominal external-call budget (% incident windows)")
    ax.set_ylabel("Windows left uncovered (%)")
    ax.grid(True, which="major")
    ax.axvline(20, color="#555555", lw=0.75, ls=":")
    ax.text(20.4, 101.0, "20% point used in B", ha="left", va="top", fontsize=5.5, color="#333333")
    ax.annotate(
        "risk floor keeps high-value miss at 0%",
        xy=(10, 0),
        xytext=(5.2, 18),
        arrowprops={"arrowstyle": "->", "lw": 0.7, "color": colors["risk"]},
        fontsize=5.6,
        color=colors["risk"],
    )
    ax.legend(loc="upper center", bbox_to_anchor=(0.52, -0.18), frameon=True, ncol=2, handlelength=1.8)
    ax.set_title("A  Budgeted uncovered risk", loc="left", fontweight="bold", pad=5)

    ax = axes[1]
    policies = [
        ("invoke-all", "invoke-all"),
        ("scenario-only", "scenario-only"),
        ("topology+timeline", "topology+timeline"),
        ("window-risk-tier", "window-risk-tier"),
        ("budget-coverage-20", "budget-coverage-20"),
        ("budget-risk-20", "budget-risk-20"),
    ]
    group_y = np.arange(len(policies))[::-1]
    calls = [pct(audit_policies[key]["calls"], alerts) for _, key in policies]
    recall = [100.0 * audit_policies[key]["window_metrics"]["high_value_window_recall"] for _, key in policies]
    pressure = [100.0 * (1.0 - audit_policies[key]["window_metrics"]["pressure_window_skip_rate"]) for _, key in policies]
    high_value_false_skip = [100.0 - value for value in recall]
    bar_height = 0.18
    offsets = [0.21, 0.0, -0.21]
    series = [
        ("calls kept", calls, colors["calls"], offsets[0]),
        ("high-value recall", recall, colors["recall"], offsets[1]),
        ("pressure covered", pressure, colors["pressure"], offsets[2]),
    ]
    for label, values, color, offset in series:
        yy = group_y + offset
        ax.barh(yy, values, color=color, edgecolor="white", height=bar_height, label=label)
        for yi, value in zip(yy, values):
            x_text = min(value + 1.2, 117.0)
            ha = "left" if value < 116 else "right"
            ax.text(x_text, yi, f"{value:.1f}", ha=ha, va="center", fontsize=4.9, color="#222222")
    for yi, value in zip(group_y, high_value_false_skip):
        if value > 0.01:
            ax.text(104, yi, f"HV skip {value:.1f}%", ha="left", va="center", fontsize=5.4, color=colors["false"])
    ax.set_yticks(group_y)
    ax.set_yticklabels([display_policy_name(policy) for policy, _ in policies])
    ax.tick_params(axis="y", length=0, pad=2)
    ax.set_xlim(0, 122)
    ax.set_ylim(-0.8, len(policies) - 0.2)
    ax.set_xlabel("Rate over alert baseline (%)")
    ax.grid(axis="x")
    ax.legend(loc="upper center", bbox_to_anchor=(0.50, -0.18), frameon=True, ncol=3, handlelength=1.4)
    ax.set_title("B  Operating point comparison", loc="left", fontweight="bold", pad=5)

    for ax in axes:
        for side in ["top", "right"]:
            ax.spines[side].set_visible(False)

    path = IMAGE_DIR / "aics_lcore_admission_tradeoff.png"
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def main() -> None:
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    set_style()
    audit = load_json(AUDIT_JSON)
    policy = load_json(LCORE_POLICY_JSON)
    deterministic_path = deterministic_boundary_figure(audit)
    admission_path = lcore_admission_tradeoff_figure(policy, audit)
    summary = {
        "schema_version": 1,
        "figures": {
            "deterministic_boundary_audit": str(deterministic_path),
            "lcore_admission_tradeoff": str(admission_path),
        },
        "sources": {
            "deterministic_audit": str(AUDIT_JSON),
            "lcore_policy_report": str(LCORE_POLICY_JSON),
        },
        "display_names": {
            "scenario-only": display_policy_name("scenario-only"),
            "budget-coverage-20": display_policy_name("budget-coverage-20"),
            "budget-risk-20": display_policy_name("budget-risk-20"),
        },
        "proposed_operating_point": {
            "policy_key": "budget-risk-20",
            "display_name": display_policy_name("budget-risk-20"),
        },
    }
    summary_path = RESULT_DIR / "aics_admission_figure_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
