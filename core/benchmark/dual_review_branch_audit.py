from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

from core.aiops_agent.alert_reasoning_runtime.budget_controller import select_windows_under_budget
from core.aiops_agent.alert_reasoning_runtime.incident_window import build_incident_window_index
from core.benchmark.admission_metrics import selected_window_metrics
from core.benchmark.topology_subgraph_ablation import _iter_alerts


DEFAULT_ALERT_DIR = "/data/netops-runtime/LCORE-D/work/alerts-lcore-corepatched-full-20260412T152119Z"
DEFAULT_MASTER_JSONL = "/data/netops-runtime/LCORE-D/work/window-dual-review-packet-v1/window_dual_review_master.jsonl"
DEFAULT_ADJUDICATED_JSONL = "/data/netops-runtime/LCORE-D/work/window-dual-review-packet-v1/window_dual_review_adjudicated.jsonl"
DEFAULT_AGREEMENT_JSON = "/data/netops-runtime/LCORE-D/work/window-dual-review-packet-v1/window_dual_review_agreement.json"
DEFAULT_OUTPUT_JSON = "/data/netops-runtime/LCORE-D/work/dual_review_branch_audit.json"
DEFAULT_OUTPUT_PNG = "/data/Netops-causality-remediation/documentation/images/dual_review_branch_audit.png"
DEFAULT_VARIANTS = "legacy:2,legacy:3,branch-preserving:2,branch-preserving:3,branch-preserving:4,branch-preserving:5"


def run(args: argparse.Namespace) -> dict[str, Any]:
    agreement = json.loads(Path(args.agreement_json).read_text(encoding="utf-8"))
    master_rows = {
        record["window_id"]: record
        for record in _read_jsonl(Path(args.master_jsonl))
    }
    adjudicated_rows = _read_jsonl(Path(args.adjudicated_jsonl))
    challenge = _challenge_summary(adjudicated_rows, master_rows)

    alerts = _iter_alerts(Path(args.alert_dir), args.limit_files)
    if args.max_alerts > 0:
        alerts = alerts[: args.max_alerts]

    variants: list[dict[str, Any]] = []
    for strategy, max_items in _parse_variants(args.variants):
        windows, _ = build_incident_window_index(
            alerts,
            window_sec=args.window_sec,
            window_mode=args.window_mode,
            max_window_sec=args.max_window_sec or None,
            representative_max_items=max_items,
            representative_strategy=strategy,
        )
        window_by_id = {str(window.get("window_id") or ""): window for window in windows}
        reviewed_ids = set(challenge["reviewed_window_ids"])
        missing = sorted(reviewed_ids - set(window_by_id))
        if missing:
            raise ValueError(
                f"variant {strategy}:{max_items} could not reproduce {len(missing)} reviewed windows; "
                f"first missing id: {missing[0]}"
            )
        admission = select_windows_under_budget(windows, budget_fraction=float(args.budget_fraction))
        metrics = selected_window_metrics(
            windows,
            set(admission.get("selected_window_ids") or set()),
            call_mode="representative-alerts",
            admission=admission,
        )
        variants.append(
            _variant_summary(
                label=_variant_label(strategy, max_items),
                strategy=strategy,
                max_items=max_items,
                windows=window_by_id,
                challenge=challenge,
                replay_metrics=metrics,
            )
        )

    report = {
        "schema_version": 1,
        "agreement": {
            "windows_reviewed": agreement.get("windows_reviewed"),
            "windows_needing_adjudication": agreement.get("windows_needing_adjudication"),
            "fields": agreement.get("fields") or {},
        },
        "challenge_audit": challenge,
        "variants": variants,
        "recommended_variant": _recommend_variant(variants),
    }
    output_json = Path(args.output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.output_png:
        _render_plot(
            agreement_fields=agreement.get("fields") or {},
            variants=variants,
            output_png=Path(args.output_png),
        )
    print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
    return report


def _challenge_summary(
    adjudicated_rows: list[dict[str, Any]],
    master_rows: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    label_counts: Counter[str] = Counter()
    rep_false_by_label: Counter[str] = Counter()
    false_skip_by_label: Counter[str] = Counter()
    strata_counts: Counter[str] = Counter()
    rep_false_strata: Counter[str] = Counter()
    reviewed_window_ids: list[str] = []
    rep_false_ids: list[str] = []

    for record in adjudicated_rows:
        window = record.get("window") or {}
        window_id = str(record.get("window_id") or window.get("window_id") or "")
        reviewed_window_ids.append(window_id)
        label = str(window.get("window_label") or "unknown")
        label_counts[label] += 1
        strata = list((master_rows.get(window_id) or {}).get("review_strata") or [])
        for value in strata:
            strata_counts[str(value)] += 1
        adjudicated = record.get("adjudicated_label") or {}
        if adjudicated.get("false_skip_if_local") is True:
            false_skip_by_label[label] += 1
        if adjudicated.get("representative_alert_sufficient") is False:
            rep_false_ids.append(window_id)
            rep_false_by_label[label] += 1
            for value in strata:
                rep_false_strata[str(value)] += 1

    return {
        "windows_reviewed": len(adjudicated_rows),
        "reviewed_window_ids": reviewed_window_ids,
        "representative_failure_window_ids": rep_false_ids,
        "representative_failure_windows": len(rep_false_ids),
        "representative_failure_by_label": dict(rep_false_by_label),
        "false_skip_if_local_true": sum(false_skip_by_label.values()),
        "false_skip_if_local_by_label": dict(false_skip_by_label),
        "window_label_counts": dict(label_counts),
        "review_strata_counts": dict(strata_counts),
        "representative_failure_review_strata": dict(rep_false_strata),
    }


def _variant_summary(
    *,
    label: str,
    strategy: str,
    max_items: int,
    windows: dict[str, dict[str, Any]],
    challenge: dict[str, Any],
    replay_metrics: dict[str, Any],
) -> dict[str, Any]:
    pass_count = 0
    repaired_count = 0
    mixed_repaired_count = 0
    rep_false_ids = set(challenge["representative_failure_window_ids"])
    for window_id in challenge["reviewed_window_ids"]:
        window = windows[window_id]
        passed = _passes_branch_audit(window)
        pass_count += int(passed)
        if window_id in rep_false_ids and passed:
            repaired_count += 1
            if str(window.get("window_label") or "") == "mixed_fault_and_transient":
                mixed_repaired_count += 1

    reviewed_total = max(len(challenge["reviewed_window_ids"]), 1)
    repaired_total = max(len(rep_false_ids), 1)
    mixed_total = max(int(challenge["representative_failure_by_label"].get("mixed_fault_and_transient") or 0), 1)
    return {
        "label": label,
        "strategy": strategy,
        "representative_max_items": max_items,
        "challenge_branch_pass_rate": round(pass_count / reviewed_total, 6),
        "challenge_branch_pass_windows": pass_count,
        "representative_failure_repaired": repaired_count,
        "representative_failure_repair_rate": round(repaired_count / repaired_total, 6),
        "mixed_failure_repaired": mixed_repaired_count,
        "mixed_failure_repair_rate": round(mixed_repaired_count / mixed_total, 6),
        "risk_budget_20_external_calls": int(replay_metrics.get("external_calls") or 0),
        "risk_budget_20_high_value_recall": float(replay_metrics.get("high_value_window_recall") or 0.0),
        "risk_budget_20_pressure_skip_rate": float(replay_metrics.get("pressure_window_skip_rate") or 0.0),
        "risk_budget_20_selected_windows": int(replay_metrics.get("selected_windows") or 0),
    }


def _passes_branch_audit(window: dict[str, Any]) -> bool:
    selection = ((window.get("selected_evidence_targets") or {}).get("representative_selection") or {})
    branch = selection.get("branch_coverage") or {}
    try:
        return float(branch.get("coverage_rate") or 0.0) >= 0.999999
    except (TypeError, ValueError):
        return False


def _parse_variants(spec: str) -> list[tuple[str, int]]:
    pairs: list[tuple[str, int]] = []
    for raw in str(spec or DEFAULT_VARIANTS).split(","):
        token = raw.strip()
        if not token:
            continue
        strategy, value = token.split(":", 1)
        pairs.append((strategy.strip().lower(), max(1, int(value.strip()))))
    if not pairs:
        raise ValueError("no selector variants configured")
    return pairs


def _variant_label(strategy: str, max_items: int) -> str:
    prefix = "Legacy" if strategy == "legacy" else "Branch-preserving"
    return f"{prefix} $k={max_items}$"


def _recommend_variant(variants: list[dict[str, Any]]) -> dict[str, Any]:
    if not variants:
        return {}
    ordered = sorted(
        variants,
        key=lambda item: (
            -int(item.get("representative_failure_repaired") or 0),
            -float(item.get("risk_budget_20_high_value_recall") or 0.0),
            int(item.get("risk_budget_20_external_calls") or 0),
        ),
    )
    best = ordered[0]
    return {
        "label": best.get("label"),
        "reason": (
            "maximizes repaired adjudicated representative failures, "
            "then preserves high-value recall, then minimizes risk-budget representative calls"
        ),
    }


def _render_plot(
    *,
    agreement_fields: dict[str, Any],
    variants: list[dict[str, Any]],
    output_png: Path,
) -> None:
    fields = [
        "should_invoke_external",
        "representative_alert_sufficient",
        "selected_device_covered",
        "selected_path_covered",
        "timeline_sufficient",
        "false_skip_if_local",
        "boundary_should_split_further",
        "boundary_should_merge_adjacent",
    ]
    field_labels = ["invoke", "rep", "device", "path", "timeline", "false-skip", "split", "merge"]
    exact = [float((agreement_fields.get(field) or {}).get("pairwise_exact_agreement") or 0.0) for field in fields]
    kappa = [float((agreement_fields.get(field) or {}).get("cohen_kappa") or 0.0) for field in fields]

    fig, axes = plt.subplots(1, 2, figsize=(12.4, 4.8), gridspec_kw={"width_ratios": [1.05, 1.2]})

    x = list(range(len(fields)))
    highlight = "#d55e00"
    colors = [highlight if field == "representative_alert_sufficient" else "#9fb6c6" for field in fields]
    axes[0].bar(x, exact, color=colors, width=0.72, edgecolor="white", linewidth=0.8)
    axes[0].set_ylim(0.0, 1.05)
    axes[0].set_ylabel("Exact agreement")
    axes[0].set_xticks(x, field_labels, rotation=22, ha="right")
    axes[0].grid(axis="y", alpha=0.2)
    twin = axes[0].twinx()
    twin.plot(x, kappa, color="#1b4f72", marker="o", linewidth=1.8)
    twin.set_ylim(0.0, 1.05)
    twin.set_ylabel("Cohen's kappa")
    axes[0].set_title("Dual-Review Agreement")

    strategy_colors = {"legacy": "#7f8c8d", "branch-preserving": "#0f8b8d"}
    strategy_markers = {2: "o", 3: "s"}
    for variant in variants:
        strategy = str(variant.get("strategy") or "legacy")
        max_items = int(variant.get("representative_max_items") or 1)
        calls = float(variant.get("risk_budget_20_external_calls") or 0.0)
        repaired = float(variant.get("representative_failure_repair_rate") or 0.0) * 100.0
        size = 220 + 420 * float(variant.get("challenge_branch_pass_rate") or 0.0)
        axes[1].scatter(
            calls,
            repaired,
            s=size,
            marker=strategy_markers.get(max_items, "o"),
            color=strategy_colors.get(strategy, "#555555"),
            edgecolor="white",
            linewidth=1.0,
            alpha=0.95,
        )
        axes[1].annotate(
            str(variant.get("label") or ""),
            xy=(calls, repaired),
            xytext=(6, 6),
            textcoords="offset points",
            fontsize=9,
        )
    axes[1].set_xlabel("Risk-budget 20% representative calls")
    axes[1].set_ylabel("Adjudicated rep-failure repair (%)")
    axes[1].set_title("Selector Repair vs Cost")
    axes[1].grid(alpha=0.2)

    legend_items = [
        Line2D([0], [0], marker="o", color="w", markerfacecolor="#7f8c8d", markersize=9, label="Legacy"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor="#0f8b8d", markersize=9, label="Branch-preserving"),
        Line2D([0], [0], marker="o", color="#444444", linestyle="None", markersize=8, label="$k=2$"),
        Line2D([0], [0], marker="s", color="#444444", linestyle="None", markersize=8, label="$k=3$"),
    ]
    axes[1].legend(handles=legend_items, frameon=False, loc="lower right")

    fig.tight_layout()
    output_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_png, dpi=220, bbox_inches="tight")
    plt.close(fig)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit dual review outcomes and branch-preserving representative selection.")
    parser.add_argument("--alert-dir", default=DEFAULT_ALERT_DIR)
    parser.add_argument("--limit-files", type=int, default=0)
    parser.add_argument("--max-alerts", type=int, default=0)
    parser.add_argument("--master-jsonl", default=DEFAULT_MASTER_JSONL)
    parser.add_argument("--adjudicated-jsonl", default=DEFAULT_ADJUDICATED_JSONL)
    parser.add_argument("--agreement-json", default=DEFAULT_AGREEMENT_JSON)
    parser.add_argument("--window-sec", type=int, default=600)
    parser.add_argument("--window-mode", default="session")
    parser.add_argument("--max-window-sec", type=int, default=0)
    parser.add_argument("--budget-fraction", type=float, default=0.2)
    parser.add_argument("--variants", default=DEFAULT_VARIANTS)
    parser.add_argument("--output-json", default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-png", default=DEFAULT_OUTPUT_PNG)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
