from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path("/data")
IMAGE_DIR = ROOT / "Netops-causality-remediation" / "documentation" / "images"
LCORE_FRONTIER = ROOT / "netops-runtime" / "LCORE-D" / "work" / "quality-cost-policy-runner-frontier-v2.json"
LCORE_WINDOWS = ROOT / "netops-runtime" / "LCORE-D" / "work" / "incident-windows-frontier-v2.jsonl"
RCAEVAL_FRONTIER = ROOT / "Netops-causality-remediation" / "documentation" / "results" / "rcaeval_re1_external_validation.json"


def set_paper_style(plt: Any) -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "font.family": "sans-serif",
            "font.sans-serif": ["Arial", "DejaVu Sans"],
            "font.size": 9,
            "axes.labelsize": 10,
            "xtick.labelsize": 8,
            "ytick.labelsize": 8,
            "legend.fontsize": 7.2,
            "axes.linewidth": 1.0,
            "xtick.major.width": 0.9,
            "ytick.major.width": 0.9,
            "grid.color": "#d7d7d7",
            "grid.linestyle": "--",
            "grid.linewidth": 0.6,
            "savefig.facecolor": "white",
        }
    )


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_windows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def choose_window(windows: list[dict[str, Any]]) -> dict[str, Any]:
    candidates = [
        w
        for w in windows
        if w.get("window_label") == "mixed_fault_and_transient"
        and w.get("device_count", 0) >= 3
        and w.get("path_count", 0) >= 3
        and w.get("self_healing_count", 0) >= 5
    ]
    return max(candidates, key=lambda w: (w.get("alert_count", 0), w.get("high_value_count", 0)))


def device_layout() -> dict[str, tuple[float, float]]:
    return {
        "CORE-R1": (0.12, 0.78),
        "CORE-R2": (0.30, 0.58),
        "CORE-R3": (0.16, 0.30),
        "CORE-R4": (0.60, 0.75),
        "CORE-R5": (0.78, 0.53),
        "CORE-R6": (0.58, 0.25),
        "EDGE-MS": (0.40, 0.10),
        "SERVER": (0.91, 0.82),
    }


def parse_device(path_signature: str) -> str:
    return path_signature.split("|", 1)[0]


def draw_base_graph(ax: Any, *, dense: bool) -> None:
    pos = device_layout()
    core_edges = [
        ("CORE-R1", "CORE-R2"),
        ("CORE-R1", "CORE-R3"),
        ("CORE-R2", "CORE-R3"),
        ("CORE-R2", "CORE-R4"),
        ("CORE-R3", "EDGE-MS"),
        ("CORE-R4", "CORE-R5"),
        ("CORE-R4", "CORE-R6"),
        ("CORE-R5", "CORE-R6"),
        ("CORE-R5", "SERVER"),
        ("CORE-R6", "EDGE-MS"),
        ("CORE-R2", "CORE-R5"),
        ("CORE-R3", "CORE-R6"),
    ]
    if dense:
        for a, b in core_edges:
            ax.plot(
                [pos[a][0], pos[b][0]],
                [pos[a][1], pos[b][1]],
                color="#c8c8c8",
                linewidth=1.0,
                linestyle="--",
                zorder=1,
            )
    for name, (x, y) in pos.items():
        if dense or name in {"CORE-R4", "CORE-R5", "CORE-R6", "EDGE-MS", "SERVER"}:
            ax.scatter(x, y, s=95, color="white", edgecolor="#303030", linewidth=1.0, zorder=4)
            ax.text(x, y - 0.055, name.replace("CORE-", "R"), ha="center", va="top", fontsize=7)


def draw_alert_stack(ax: Any, x: float, y: float, count: int, color: str, label: str) -> None:
    rows = min(count, 8)
    for i in range(rows):
        dx = (i % 4) * 0.018
        dy = -(i // 4) * 0.032
        ax.scatter(x + dx, y + dy, marker="^", s=55, color=color, edgecolor="white", linewidth=0.45, zorder=7)
    if count > rows:
        ax.text(x + 0.086, y - 0.018, f"+{count - rows}", fontsize=7, color=color, va="center")
    ax.text(x - 0.004, y + 0.055, label, fontsize=7, color=color, ha="left")


def draw_path(ax: Any, start: str, via: list[str], color: str, lw: float, *, alpha: float = 1.0, style: str = "-") -> None:
    pos = device_layout()
    route = [start] + via
    for a, b in zip(route, route[1:]):
        ax.plot(
            [pos[a][0], pos[b][0]],
            [pos[a][1], pos[b][1]],
            color=color,
            linewidth=lw,
            alpha=alpha,
            linestyle=style,
            zorder=3,
        )


def draw_topology_boundary_figure() -> Path:
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch

    set_paper_style(plt)
    windows = load_windows(LCORE_WINDOWS)
    w = choose_window(windows)
    selected_devices = w["selected_evidence_targets"]["devices"]
    selected_paths = w["selected_evidence_targets"]["path_signatures"]
    reps = w["selected_evidence_targets"]["representative_selection"]["representative_count"]
    excluded = sum(len(item.get("alert_ids", [])) for item in w.get("excluded_evidence_targets", []))
    alert_count = w["alert_count"]
    high_value = w["high_value_count"]

    fig, axes = plt.subplots(1, 3, figsize=(12.2, 3.25), constrained_layout=True)
    colors = {
        "selected": "#3f6fb5",
        "held": "#9b9b9b",
        "fault": "#bf5b5b",
        "missing": "#8a8a8a",
        "boundary": "#edf4fb",
    }

    for ax in axes:
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_linewidth(0.9)
            spine.set_color("#555")

    ax = axes[0]
    draw_base_graph(ax, dense=True)
    # Candidate context deliberately shows all locally available routes; selected window paths are embedded in clutter.
    candidate_routes = {
        "CORE-R4": ["CORE-R5", "SERVER"],
        "CORE-R5": ["SERVER"],
        "CORE-R6": ["EDGE-MS"],
        "CORE-R2": ["CORE-R5", "SERVER"],
        "CORE-R3": ["CORE-R6", "EDGE-MS"],
        "CORE-R1": ["CORE-R2", "CORE-R4"],
    }
    for dev, route in candidate_routes.items():
        draw_path(ax, dev, route, "#bdbdbd", 1.2, alpha=0.75, style="--")
    for dev in selected_devices:
        if dev == "CORE-R4":
            draw_path(ax, dev, ["CORE-R5", "SERVER"], colors["fault"], 2.3)
        elif dev == "CORE-R5":
            draw_path(ax, dev, ["SERVER"], colors["fault"], 2.3)
        elif dev == "CORE-R6":
            draw_path(ax, dev, ["EDGE-MS"], colors["fault"], 2.3)
    draw_alert_stack(ax, 0.055, 0.875, alert_count, colors["held"], f"{alert_count} alerts")
    draw_alert_stack(ax, 0.055, 0.735, high_value, colors["fault"], f"{high_value} high-value")
    draw_alert_stack(ax, 0.055, 0.595, excluded, colors["held"], f"{excluded} transient")
    ax.text(0.02, 0.965, "(a) candidate window context", fontsize=8, fontweight="bold", va="top")

    ax = axes[1]
    ax.add_patch(
        FancyBboxPatch(
            (0.035, 0.08),
            0.93,
            0.84,
            boxstyle="round,pad=0.012,rounding_size=0.025",
            facecolor=colors["boundary"],
            edgecolor="#8fb2cf",
            linewidth=1.0,
            zorder=0,
        )
    )
    draw_base_graph(ax, dense=False)
    for dev in selected_devices:
        if dev == "CORE-R4":
            draw_path(ax, dev, ["CORE-R5", "SERVER"], colors["selected"], 2.7)
        elif dev == "CORE-R5":
            draw_path(ax, dev, ["SERVER"], colors["selected"], 2.7)
        elif dev == "CORE-R6":
            draw_path(ax, dev, ["EDGE-MS"], colors["selected"], 2.7)
    # Held-back transient contexts remain visible but do not feed the model-facing route.
    for y in [0.20, 0.27, 0.34, 0.41]:
        ax.plot([0.06, 0.31], [y, y + 0.03], color=colors["held"], linewidth=1.2, linestyle=":", alpha=0.85)
        ax.scatter(0.06, y, marker="^", s=42, color="white", edgecolor=colors["held"], linewidth=1.0)
    ax.text(0.055, 0.50, "held back", color="#666", fontsize=8)
    ax.text(0.59, 0.92, "selected subgraph", color=colors["selected"], fontsize=8, ha="center")
    ax.text(0.05, 0.965, "(b) AiCS evidence boundary", fontsize=8, fontweight="bold", va="top")

    ax = axes[2]
    ax.add_patch(
        FancyBboxPatch(
            (0.10, 0.18),
            0.55,
            0.68,
            boxstyle="round,pad=0.018,rounding_size=0.03",
            facecolor="#f7fbff",
            edgecolor="#8fb2cf",
            linewidth=1.0,
        )
    )
    # A compact model-facing object: representative devices and paths only.
    rep_y = [0.74, 0.56, 0.38]
    rep_labels = selected_devices[:3]
    for y, dev in zip(rep_y, rep_labels):
        ax.scatter(0.18, y, marker="^", s=95, color=colors["selected"], edgecolor="white", linewidth=0.5, zorder=3)
        ax.plot([0.24, 0.50], [y, y], color=colors["selected"], linewidth=2.0)
        ax.scatter(0.55, y, s=76, color="white", edgecolor="#303030", linewidth=1.0, zorder=4)
        ax.text(0.55, y - 0.07, dev.replace("CORE-", "R"), ha="center", fontsize=7)
    ax.text(0.38, 0.83, "model-facing evidence", color=colors["selected"], fontsize=8, ha="center")
    ax.plot([0.70, 0.92], [0.67, 0.67], color=colors["held"], linewidth=1.2, linestyle=":")
    ax.plot([0.70, 0.92], [0.49, 0.49], color=colors["missing"], linewidth=1.2, linestyle="--")
    ax.scatter(0.69, 0.67, marker="x", color=colors["held"], s=50)
    ax.text(0.74, 0.70, "transient held back", fontsize=7, color="#666")
    ax.text(0.74, 0.52, "missing context", fontsize=7, color="#666")
    ax.text(
        0.12,
        0.08,
        f"{alert_count} alerts -> {reps} representatives\n{len(selected_devices)} devices, {len(selected_paths)} paths retained",
        fontsize=8,
        color="#333",
    )
    ax.text(0.05, 0.965, "(c) representative boundary object", fontsize=8, fontweight="bold", va="top")

    png_path = IMAGE_DIR / "topology_boundary_construction.png"
    fig.savefig(png_path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    return png_path


def budget_percent(policy: str) -> int:
    try:
        return int(policy.rsplit("-", 1)[-1])
    except ValueError:
        return 0


def lcore_row(name: str, item: dict[str, Any]) -> dict[str, float | str]:
    m = item.get("window_metrics") or {}
    return {
        "name": name,
        "budget": budget_percent(name),
        "calls_pct": 100.0 * float(item.get("calls", 0)) / 6700.0,
        "call_reduction": float(item.get("call_reduction_percent") or 0.0),
        "recall": 100.0 * float(m.get("high_value_window_recall") or 0.0),
        "false_skip": 100.0 * (1.0 - float(m.get("high_value_window_recall") or 0.0)),
        "pressure_coverage": 100.0 * (1.0 - float(m.get("pressure_window_skip_rate") or 0.0)),
        "evidence": 100.0 * float(m.get("evidence_target_coverage_rate") or 0.0),
    }


def rca_row(name: str, item: dict[str, Any]) -> dict[str, float | str]:
    return {
        "name": name,
        "budget": budget_percent(name),
        "calls_pct": 100.0 * float(item.get("external_calls", 0)) / 2120.0,
        "call_reduction": float(item.get("call_reduction_percent") or 0.0),
        "recall": 100.0 * float(item.get("high_value_window_recall") or 0.0),
        "false_skip": 100.0 * float(item.get("false_skip_rate") or (1.0 - float(item.get("high_value_window_recall") or 0.0))),
        "pressure_coverage": 100.0 * (1.0 - float(item.get("pressure_window_skip_rate") or 0.0)),
        "evidence": 100.0 * float(item.get("evidence_target_coverage_rate") or 0.0),
    }


def budget_rows(report: dict[str, Any], prefix: str, row_fn: Any) -> list[dict[str, float | str]]:
    return sorted(
        [row_fn(name, item) for name, item in report["policies"].items() if name.startswith(prefix)],
        key=lambda r: float(r["budget"]),
    )


def draw_quality_cost_overlay() -> Path:
    import matplotlib.pyplot as plt

    set_paper_style(plt)
    lcore = load_json(LCORE_FRONTIER)
    rca = load_json(RCAEVAL_FRONTIER)
    lc_cov = budget_rows(lcore, "budget-coverage-", lcore_row)
    lc_risk = budget_rows(lcore, "budget-risk-", lcore_row)
    rc_cov = budget_rows(rca, "budget-coverage-", rca_row)
    rc_risk = budget_rows(rca, "budget-risk-", rca_row)

    fig, ax = plt.subplots(1, 1, figsize=(12.1, 4.55), constrained_layout=True)
    metric_style = {
        "recall": ("#6f5aa8", "o"),
        "call_reduction": ("#3f6fb5", "D"),
        "pressure_coverage": ("#4f9aa8", "^"),
        "false_skip": ("#9a6f4f", "v"),
        "calls_pct": ("#666666", "s"),
    }
    curves = [
        ("LCORE strict recall", lc_cov, "recall", "-", 2.2),
        ("LCORE risk recall", lc_risk, "recall", "--", 2.2),
        ("LCORE strict reduction", lc_cov, "call_reduction", "-", 1.9),
        ("LCORE risk reduction", lc_risk, "call_reduction", "--", 1.9),
        ("LCORE strict pressure cover", lc_cov, "pressure_coverage", "-", 1.9),
        ("LCORE risk pressure cover", lc_risk, "pressure_coverage", "--", 1.9),
        ("LCORE risk calls", lc_risk, "calls_pct", ":", 1.7),
        ("RCAEval strict recall", rc_cov, "recall", "-.", 2.0),
        ("RCAEval risk recall", rc_risk, "recall", (0, (5, 2)), 2.0),
        ("RCAEval strict false skip", rc_cov, "false_skip", "-.", 1.8),
        ("RCAEval risk calls", rc_risk, "calls_pct", (0, (1, 2)), 1.8),
    ]
    for label, rows, metric, linestyle, lw in curves:
        rows = sorted(rows, key=lambda r: float(r["calls_pct"]))
        x = [float(r["calls_pct"]) for r in rows]
        y = [float(r[metric]) for r in rows]
        color, marker = metric_style[metric]
        ax.plot(
            x,
            y,
            label=label,
            color=color,
            marker=marker,
            linestyle=linestyle,
            linewidth=lw,
            markersize=4.5,
            alpha=0.94,
        )

    # Baseline markers from non-budget policies.
    baseline_map = {
        "scenario-only": "fault-state-only",
        "topology+timeline": "topology+timeline",
        "window-risk-tier": "window-risk-tier",
        "invoke-all": "invoke-all",
    }
    for policy, label in baseline_map.items():
        if policy in lcore["policies"]:
            r = lcore_row(policy, lcore["policies"][policy])
            ax.scatter(
                [float(r["calls_pct"])],
                [float(r["recall"])],
                s=62,
                marker="*",
                color="#222222" if policy != "invoke-all" else "#999999",
                edgecolor="white",
                linewidth=0.6,
                zorder=8,
            )
            if policy in {"scenario-only", "topology+timeline", "window-risk-tier"}:
                ax.annotate(
                    label,
                    xy=(float(r["calls_pct"]), float(r["recall"])),
                    xytext=(4, -12 if policy != "topology+timeline" else 8),
                    textcoords="offset points",
                    fontsize=7,
                    color="#333",
                )

    ax.set_xscale("log")
    ax.set_xlim(0.35, 105)
    ax.set_ylim(-3, 106)
    ticks = [0.5, 1, 2, 5, 10, 20, 40, 60, 100]
    ax.set_xticks(ticks)
    ax.set_xticklabels(["0.5", "1", "2", "5", "10", "20", "40", "60", "100"])
    ax.set_xlabel("External calls (% of original alert/record stream)")
    ax.set_ylabel("Rate (%)")
    ax.grid(True, axis="both", which="major")
    for spine in ax.spines.values():
        spine.set_linewidth(1.0)
    ax.axhline(100, color="#9a9a9a", linewidth=1.0, linestyle="--", alpha=0.75)
    ax.text(0.42, 101.5, "full high-value coverage", fontsize=7, color="#666")
    ax.annotate(
        "risk floor preserves recall",
        xy=(float(lc_risk[0]["calls_pct"]), float(lc_risk[0]["recall"])),
        xytext=(16, -34),
        textcoords="offset points",
        arrowprops={"arrowstyle": "->", "lw": 0.8, "color": "#333"},
        fontsize=7.5,
        color="#333",
    )
    ax.annotate(
        "strict budget loses recall",
        xy=(float(rc_cov[3]["calls_pct"]), float(rc_cov[3]["recall"])),
        xytext=(-48, 18),
        textcoords="offset points",
        arrowprops={"arrowstyle": "->", "lw": 0.8, "color": "#333"},
        fontsize=7.5,
        color="#333",
    )
    ax.legend(
        loc="center left",
        bbox_to_anchor=(1.01, 0.5),
        frameon=False,
        ncol=1,
        handlelength=2.6,
        borderaxespad=0.2,
    )

    png_path = IMAGE_DIR / "admission_quality_cost_summary.png"
    fig.savefig(png_path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    return png_path


def main() -> None:
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    topology_path = draw_topology_boundary_figure()
    frontier_path = draw_quality_cost_overlay()
    print(json.dumps({"topology": str(topology_path), "frontier": str(frontier_path)}, indent=2))


if __name__ == "__main__":
    main()
