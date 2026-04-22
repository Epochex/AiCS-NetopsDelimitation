from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import median
from typing import Any

import matplotlib.pyplot as plt

from core.aiops_agent.alert_reasoning_runtime.budget_controller import select_windows_under_budget
from core.aiops_agent.alert_reasoning_runtime.incident_window import build_incident_window_index
from core.aiops_agent.alert_reasoning_runtime.prompt_contracts import build_prompt_contracts
from core.benchmark.admission_metrics import representative_cost, selected_window_metrics
from core.benchmark.prompt_quality_runner import (
    _context_views_from_window,
    _score_response,
    _template_response,
)
from core.benchmark.topology_subgraph_ablation import _iter_alerts
from core.benchmark.window_expert_reviewer import review_window


DEFAULT_OUTPUT_JSON = "/data/netops-runtime/LCORE-D/work/representative-sufficiency-summary.json"
DEFAULT_OUTPUT_PNG = "/data/netops-runtime/LCORE-D/work/representative-sufficiency-summary.png"
DEFAULT_K_VALUES = "1,2,3,all"


def run(args: argparse.Namespace) -> dict[str, Any]:
    alerts = _iter_alerts(Path(args.alert_dir), args.limit_files)
    if args.max_alerts > 0:
        alerts = alerts[: args.max_alerts]
    if not alerts:
        raise ValueError("no alerts found for representative sufficiency study")

    variants = []
    max_items_all = max(1, len(alerts))
    for label, max_items in _parse_k_values(args.k_values):
        effective_max_items = max_items_all if max_items is None else max(1, max_items)
        windows, _ = build_incident_window_index(
            alerts,
            window_sec=args.window_sec,
            group_by_scenario=bool(getattr(args, "group_by_scenario", False)),
            window_mode=str(getattr(args, "window_mode", "session") or "session"),
            max_window_sec=getattr(args, "max_window_sec", None),
            representative_max_items=effective_max_items,
        )
        variants.append(
            _summarize_variant(
                label=label,
                max_items=max_items,
                windows=windows,
                budget_fraction=float(args.budget_fraction),
            )
        )

    report = {
        "schema_version": 1,
        "alert_dir": args.alert_dir,
        "alerts_scanned": len(alerts),
        "window_sec": args.window_sec,
        "window_mode": str(getattr(args, "window_mode", "session") or "session"),
        "max_window_sec": getattr(args, "max_window_sec", None) or args.window_sec,
        "budget_fraction": float(args.budget_fraction),
        "variants": variants,
        "recommended_variant": _recommend_variant(variants, target_sufficiency=float(args.target_sufficiency)),
    }
    output_json = Path(args.output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.output_png:
        _render_plot(variants, output_png=Path(args.output_png))
    print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
    return report


def _summarize_variant(
    *,
    label: str,
    max_items: int | None,
    windows: list[dict[str, Any]],
    budget_fraction: float,
) -> dict[str, Any]:
    coverages = [_coverage_rate(window) for window in windows]
    reviews = [review_window(window) for window in windows]
    quality_scores = [_full_contract_quality_score(window) for window in windows]
    external_windows = [
        (window, review, coverage, score)
        for window, review, coverage, score in zip(windows, reviews, coverages, quality_scores)
        if bool(review.get("should_invoke_external"))
    ]
    risk_admission = select_windows_under_budget(windows, budget_fraction=budget_fraction)
    risk_metrics = selected_window_metrics(
        windows,
        set(risk_admission.get("selected_window_ids") or set()),
        call_mode="representative-alerts",
        admission=risk_admission,
    )
    return {
        "label": label,
        "representative_max_items": max_items if max_items is not None else "all",
        "incident_windows": len(windows),
        "invoke_all_external_calls": sum(representative_cost(window) for window in windows),
        "avg_representative_count": round(_avg(len((window.get("selected_evidence_targets") or {}).get("representative_alert_ids") or []) for window in windows), 6),
        "avg_coverage_rate": round(_avg(coverages), 6),
        "median_coverage_rate": round(float(median(coverages)) if coverages else 0.0, 6),
        "avg_external_window_coverage_rate": round(_avg(coverage for _, _, coverage, _ in external_windows), 6),
        "representative_sufficient_rate": round(_avg(int(bool(review.get("representative_alert_sufficient"))) for review in reviews), 6),
        "external_representative_sufficient_rate": round(
            _avg(int(bool(review.get("representative_alert_sufficient"))) for _, review, _, _ in external_windows),
            6,
        ),
        "avg_full_contract_quality_score": round(_avg(quality_scores), 6),
        "external_full_contract_quality_score": round(_avg(score for _, _, _, score in external_windows), 6),
        "risk_budget_policy": risk_metrics,
    }


def _parse_k_values(spec: str) -> list[tuple[str, int | None]]:
    values: list[tuple[str, int | None]] = []
    for raw in str(spec or DEFAULT_K_VALUES).split(","):
        token = raw.strip().lower()
        if not token:
            continue
        if token == "all":
            values.append(("all", None))
            continue
        value = int(token)
        if value <= 0:
            raise ValueError(f"invalid representative k: {raw}")
        values.append((f"k={value}", value))
    if not values:
        raise ValueError("no representative k values were provided")
    return values


def _coverage_rate(window: dict[str, Any]) -> float:
    selection = ((window.get("selected_evidence_targets") or {}).get("representative_selection") or {})
    coverage = selection.get("coverage") or {}
    try:
        return float(coverage.get("coverage_rate") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _full_contract_quality_score(window: dict[str, Any]) -> float:
    views = _context_views_from_window(window)
    contracts = build_prompt_contracts(views)
    response = _template_response(
        strategy="full-contract",
        window=window,
        views=views,
        contracts=contracts,
    )
    score = _score_response(
        strategy="full-contract",
        window=window,
        views=views,
        response=response,
    )
    try:
        return float(score.get("quality_score") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _avg(values: Any) -> float:
    values = list(values)
    if not values:
        return 0.0
    return float(sum(float(value) for value in values) / len(values))


def _recommend_variant(variants: list[dict[str, Any]], *, target_sufficiency: float) -> dict[str, Any]:
    if not variants:
        return {}
    ordered = sorted(
        variants,
        key=lambda item: (
            int(float(item.get("external_representative_sufficient_rate") or 0.0) >= target_sufficiency) * -1,
            float((item.get("risk_budget_policy") or {}).get("external_calls") or 0.0),
            -float(item.get("external_full_contract_quality_score") or 0.0),
            -float(item.get("avg_coverage_rate") or 0.0),
        ),
    )
    best = ordered[0]
    return {
        "label": best.get("label") or "",
        "representative_max_items": best.get("representative_max_items"),
        "target_external_sufficiency": target_sufficiency,
        "external_representative_sufficient_rate": best.get("external_representative_sufficient_rate"),
        "external_calls_at_budget": (best.get("risk_budget_policy") or {}).get("external_calls"),
        "reason": (
            "smallest representative set that meets the external-window sufficiency target, "
            "breaking ties by lower budgeted call count and higher prompt-contract quality"
        ),
    }


def _render_plot(variants: list[dict[str, Any]], *, output_png: Path) -> None:
    labels = [str(item.get("label") or "") for item in variants]
    x = list(range(len(labels)))
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))

    axes[0].plot(x, [item.get("avg_coverage_rate") or 0.0 for item in variants], marker="o", color="#1f77b4", label="avg coverage")
    axes[0].plot(
        x,
        [item.get("external_representative_sufficient_rate") or 0.0 for item in variants],
        marker="o",
        color="#ff7f0e",
        label="external sufficiency",
    )
    axes[0].plot(
        x,
        [item.get("external_full_contract_quality_score") or 0.0 for item in variants],
        marker="o",
        color="#2ca02c",
        label="contract quality",
    )
    axes[0].set_title("Representative Sufficiency")
    axes[0].set_xticks(x, labels)
    axes[0].set_ylim(0.0, 1.05)
    axes[0].grid(axis="y", alpha=0.25)
    axes[0].legend(frameon=False)

    axes[1].bar(x, [item.get("invoke_all_external_calls") or 0.0 for item in variants], color="#c7c7c7", alpha=0.6, label="invoke-all calls")
    axes[1].bar(
        x,
        [((item.get("risk_budget_policy") or {}).get("external_calls") or 0.0) for item in variants],
        color="#d62728",
        alpha=0.8,
        label="risk-budget calls",
    )
    axes[1].set_title("Call Cost by Representative Set Size")
    axes[1].set_xticks(x, labels)
    axes[1].grid(axis="y", alpha=0.25)
    axes[1].legend(frameon=False)

    fig.tight_layout()
    output_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_png, dpi=180, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate how many representative alerts each window needs.")
    parser.add_argument("--alert-dir", default="/data/netops-runtime/LCORE-D/work/alerts-lcore-corepatched-full-20260412T152119Z")
    parser.add_argument("--limit-files", type=int, default=0)
    parser.add_argument("--max-alerts", type=int, default=0)
    parser.add_argument("--window-sec", type=int, default=600)
    parser.add_argument("--window-mode", choices=["session", "fixed", "adaptive"], default="session")
    parser.add_argument("--max-window-sec", type=int, default=0)
    parser.add_argument("--group-by-scenario", action="store_true")
    parser.add_argument("--k-values", default=DEFAULT_K_VALUES)
    parser.add_argument("--budget-fraction", type=float, default=0.2)
    parser.add_argument("--target-sufficiency", type=float, default=0.95)
    parser.add_argument("--output-json", default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-png", default=DEFAULT_OUTPUT_PNG)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
