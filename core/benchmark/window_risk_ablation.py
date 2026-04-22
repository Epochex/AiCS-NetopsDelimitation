from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt

from core.aiops_agent.alert_reasoning_runtime.budget_controller import select_windows_under_budget
from core.aiops_agent.alert_reasoning_runtime.incident_window import build_incident_window_index
from core.aiops_agent.alert_reasoning_runtime.window_risk import HIGH_RISK_LABELS, MEDIUM_RISK_LABELS
from core.benchmark.admission_metrics import selected_window_metrics
from core.benchmark.topology_subgraph_ablation import _iter_alerts


DEFAULT_OUTPUT_JSON = "/data/netops-runtime/LCORE-D/work/window-risk-ablation-summary.json"
DEFAULT_OUTPUT_PNG = "/data/netops-runtime/LCORE-D/work/window-risk-ablation-summary.png"
BUDGET_FRACTIONS = (1, 2, 5, 10, 20, 40, 60)
DEFAULT_ABLATIONS = (
    "full",
    "no-mixed-fault",
    "no-recurrence",
    "no-topology",
    "no-missing-evidence",
    "no-self-healing-offset",
)
ABLATIONS = {
    "full": {
        "description": "keep the full risk atom set",
        "remove_atom_patterns": (),
        "remove_offset_patterns": (),
    },
    "no-mixed-fault": {
        "description": "remove the mixed fault/transient interaction atom",
        "remove_atom_patterns": ("context:mixed_fault_transient",),
        "remove_offset_patterns": (),
    },
    "no-recurrence": {
        "description": "remove recurrence-pressure atoms",
        "remove_atom_patterns": ("pressure:recurrence",),
        "remove_offset_patterns": (),
    },
    "no-topology": {
        "description": "remove topology-driven pressure and path-scope atoms",
        "remove_atom_patterns": ("pressure:topology", "scope:multi_path", "impact:downstream_fanout", "scope:path:"),
        "remove_offset_patterns": (),
    },
    "no-missing-evidence": {
        "description": "remove missing-evidence atoms",
        "remove_atom_patterns": ("missing:",),
        "remove_offset_patterns": (),
    },
    "no-self-healing-offset": {
        "description": "remove the self-healing dominant mitigation offset",
        "remove_atom_patterns": (),
        "remove_offset_patterns": ("mitigation:self_healing_dominant",),
    },
}


def run(args: argparse.Namespace) -> dict[str, Any]:
    alerts = _iter_alerts(Path(args.alert_dir), args.limit_files)
    if args.max_alerts > 0:
        alerts = alerts[: args.max_alerts]
    if not alerts:
        raise ValueError("no alerts found for window risk ablation")

    windows, _ = build_incident_window_index(
        alerts,
        window_sec=args.window_sec,
        group_by_scenario=bool(getattr(args, "group_by_scenario", False)),
        window_mode=str(getattr(args, "window_mode", "session") or "session"),
        max_window_sec=getattr(args, "max_window_sec", None),
    )

    ablations = [_summarize_ablation(name=name, windows=windows) for name in _parse_ablations(args.ablation)]
    report = {
        "schema_version": 1,
        "alert_dir": args.alert_dir,
        "alerts_scanned": len(alerts),
        "incident_windows": len(windows),
        "window_sec": args.window_sec,
        "window_mode": str(getattr(args, "window_mode", "session") or "session"),
        "max_window_sec": getattr(args, "max_window_sec", None) or args.window_sec,
        "ablations": ablations,
        "recommended_report_view": _recommend_primary_view(ablations),
    }
    output_json = Path(args.output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.output_png:
        _render_plot(ablations, output_png=Path(args.output_png))
    print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
    return report


def _parse_ablations(spec: str) -> list[str]:
    values = [token.strip() for token in str(spec or "").split(",") if token.strip()]
    if not values:
        values = list(DEFAULT_ABLATIONS)
    unknown = [value for value in values if value not in ABLATIONS]
    if unknown:
        raise ValueError(f"unknown ablations: {', '.join(unknown)}")
    return values


def _summarize_ablation(*, name: str, windows: list[dict[str, Any]]) -> dict[str, Any]:
    config = ABLATIONS[name]
    ablated_windows = [_ablated_window(window, config=config) for window in windows]
    budgets = {}
    strict_budgets = {}
    for value in BUDGET_FRACTIONS:
        policy = f"budget-risk-{value}"
        admission = select_windows_under_budget(ablated_windows, budget_fraction=value / 100.0)
        budgets[policy] = selected_window_metrics(
            ablated_windows,
            set(admission.get("selected_window_ids") or set()),
            call_mode="representative-alerts",
            admission=admission,
        )
        strict_policy = f"budget-coverage-{value}"
        strict_admission = select_windows_under_budget(
            ablated_windows,
            budget_fraction=value / 100.0,
            min_high_value=False,
        )
        strict_budgets[strict_policy] = selected_window_metrics(
            ablated_windows,
            set(strict_admission.get("selected_window_ids") or set()),
            call_mode="representative-alerts",
            admission=strict_admission,
        )
    full_recall = _min_calls_at_full_recall(budgets)
    return {
        "ablation": name,
        "description": config["description"],
        "removed_atom_instances": _removed_atom_instances(windows, ablated_windows),
        "removed_offset_instances": _removed_offset_instances(windows, ablated_windows),
        "risk_tiers": dict(Counter(str(window.get("risk_tier") or "unknown") for window in ablated_windows).most_common()),
        "avg_risk_score": round(_avg(float(window.get("risk_score") or 0.0) for window in ablated_windows), 6),
        "budget_risk_20": budgets["budget-risk-20"],
        "strict_budget_20": strict_budgets["budget-coverage-20"],
        "min_full_recall_external_calls": full_recall["external_calls"],
        "min_full_recall_budget_fraction": full_recall["budget_fraction"],
        "budgets": budgets,
        "strict_budgets": strict_budgets,
    }


def _ablated_window(window: dict[str, Any], *, config: dict[str, Any]) -> dict[str, Any]:
    remove_atom_patterns = tuple(config.get("remove_atom_patterns") or ())
    remove_offset_patterns = tuple(config.get("remove_offset_patterns") or ())
    atoms = [
        atom
        for atom in list(window.get("risk_atoms") or [])
        if isinstance(atom, dict) and not _matches_any(str(atom.get("key") or ""), remove_atom_patterns)
    ]
    offsets = [
        offset
        for offset in list(window.get("risk_offsets") or [])
        if isinstance(offset, dict) and not _matches_any(str(offset.get("key") or ""), remove_offset_patterns)
    ]
    score = max(
        sum(int(atom.get("weight") or 0) for atom in atoms)
        + sum(int(offset.get("weight") or 0) for offset in offsets),
        0,
    )
    updated = dict(window)
    updated["risk_atoms"] = atoms
    updated["risk_offsets"] = offsets
    updated["risk_score"] = score
    updated["risk_tier"] = _tier_for(score=score, label=str(window.get("window_label") or ""))
    updated["risk_reasons"] = _risk_reasons(atoms, offsets)
    return updated


def _matches_any(key: str, patterns: tuple[str, ...]) -> bool:
    for pattern in patterns:
        if pattern.endswith(":"):
            if key.startswith(pattern):
                return True
        elif key == pattern:
            return True
    return False


def _tier_for(*, score: int, label: str) -> str:
    if label in HIGH_RISK_LABELS or score >= 12:
        return "high"
    if label in MEDIUM_RISK_LABELS or score >= 3:
        return "medium"
    return "low"


def _risk_reasons(atoms: list[dict[str, Any]], offsets: list[dict[str, Any]]) -> list[str]:
    reasons: list[str] = []
    for item in [*atoms, *offsets]:
        reason = str(item.get("reason") or "")
        if reason and reason not in reasons:
            reasons.append(reason)
    return reasons or ["low evidence risk"]


def _removed_atom_instances(original: list[dict[str, Any]], ablated: list[dict[str, Any]]) -> int:
    return sum(len(list(before.get("risk_atoms") or [])) - len(list(after.get("risk_atoms") or [])) for before, after in zip(original, ablated))


def _removed_offset_instances(original: list[dict[str, Any]], ablated: list[dict[str, Any]]) -> int:
    return sum(len(list(before.get("risk_offsets") or [])) - len(list(after.get("risk_offsets") or [])) for before, after in zip(original, ablated))


def _min_calls_at_full_recall(budgets: dict[str, dict[str, Any]]) -> dict[str, Any]:
    eligible = [
        {
            "policy": policy,
            "budget_fraction": int(policy.rsplit("-", 1)[-1]),
            "external_calls": int(metrics.get("external_calls") or 0),
        }
        for policy, metrics in budgets.items()
        if float(metrics.get("high_value_window_recall") or 0.0) >= 0.999999
    ]
    if not eligible:
        return {"policy": "", "budget_fraction": None, "external_calls": None}
    best = min(eligible, key=lambda item: (item["external_calls"], item["budget_fraction"]))
    return best


def _recommend_primary_view(ablations: list[dict[str, Any]]) -> dict[str, Any]:
    if not ablations:
        return {}
    baseline = next((item for item in ablations if item.get("ablation") == "full"), ablations[0])
    ranked = sorted(
        [item for item in ablations if item is not baseline],
        key=lambda item: (
            -abs(
                float(((item.get("strict_budget_20") or {}).get("high_value_window_recall") or 0.0))
                - float(((baseline.get("strict_budget_20") or {}).get("high_value_window_recall") or 0.0))
            ),
            -abs(
                float(((item.get("strict_budget_20") or {}).get("pressure_window_skip_rate") or 0.0))
                - float(((baseline.get("strict_budget_20") or {}).get("pressure_window_skip_rate") or 0.0))
            ),
        ),
    )
    focus = ranked[0] if ranked else baseline
    return {
        "baseline": baseline.get("ablation") or "",
        "focus_ablation": focus.get("ablation") or "",
        "reason": "largest strict-budget-20 behavioral shift relative to the full risk atom set",
    }


def _avg(values: Any) -> float:
    values = list(values)
    if not values:
        return 0.0
    return float(sum(float(value) for value in values) / len(values))


def _render_plot(ablations: list[dict[str, Any]], *, output_png: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))

    for item in ablations:
        budgets = item.get("strict_budgets") or {}
        rows = [
            {
                "fraction": int(policy.rsplit("-", 1)[-1]),
                "calls": float(metrics.get("external_calls") or 0.0),
                "recall": float(metrics.get("high_value_window_recall") or 0.0),
            }
            for policy, metrics in budgets.items()
        ]
        rows.sort(key=lambda row: row["fraction"])
        axes[0].plot(
            [row["calls"] for row in rows],
            [row["recall"] for row in rows],
            marker="o",
            label=str(item.get("ablation") or ""),
        )

    axes[0].set_title("Strict-Budget Ablation Frontier")
    axes[0].set_xlabel("External calls")
    axes[0].set_ylabel("High-value window recall")
    axes[0].set_ylim(0.0, 1.05)
    axes[0].grid(alpha=0.25)
    axes[0].legend(frameon=False, fontsize=8)

    labels = [str(item.get("ablation") or "") for item in ablations]
    x = list(range(len(labels)))
    axes[1].bar(
        [value - 0.18 for value in x],
        [float(((item.get("strict_budget_20") or {}).get("high_value_window_recall") or 0.0)) for item in ablations],
        width=0.36,
        color="#d62728",
        label="strict 20% recall",
    )
    axes[1].bar(
        [value + 0.18 for value in x],
        [
            1.0 - float(((item.get("strict_budget_20") or {}).get("pressure_window_skip_rate") or 0.0))
            for item in ablations
        ],
        width=0.36,
        color="#1f77b4",
        label="strict 20% pressure keep",
    )
    axes[1].set_title("Strict-Budget 20% Sensitivity")
    axes[1].set_xticks(x, labels, rotation=20, ha="right")
    axes[1].grid(axis="y", alpha=0.25)
    axes[1].legend(frameon=False)

    fig.tight_layout()
    output_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_png, dpi=180, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run risk-atom ablations over the admission frontier.")
    parser.add_argument("--alert-dir", default="/data/netops-runtime/LCORE-D/work/alerts-lcore-corepatched-full-20260412T152119Z")
    parser.add_argument("--limit-files", type=int, default=0)
    parser.add_argument("--max-alerts", type=int, default=0)
    parser.add_argument("--window-sec", type=int, default=600)
    parser.add_argument("--window-mode", choices=["session", "fixed", "adaptive"], default="session")
    parser.add_argument("--max-window-sec", type=int, default=0)
    parser.add_argument("--group-by-scenario", action="store_true")
    parser.add_argument("--ablation", default=",".join(DEFAULT_ABLATIONS))
    parser.add_argument("--output-json", default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-png", default=DEFAULT_OUTPUT_PNG)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
