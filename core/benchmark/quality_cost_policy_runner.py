from __future__ import annotations

import argparse
import json
from collections import Counter, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from core.aiops_agent.alert_reasoning_runtime.incident_window import build_incident_window_index
from core.aiops_agent.alert_reasoning_runtime.context_views import build_context_views
from core.aiops_agent.alert_reasoning_runtime.budget_controller import select_windows_under_budget
from core.aiops_agent.alert_reasoning_runtime.self_healing_policy import (
    SELF_HEALING_SCENARIOS,
    assess_self_healing_decision,
)
from core.aiops_agent.alert_reasoning_runtime.window_labeling import build_weak_window_label
from core.aiops_agent.evidence_bundle import build_alert_evidence_bundle
from core.benchmark.topology_subgraph_ablation import _is_high_value, _iter_alerts, _parse_ts


BUDGET_FRACTIONS = (1, 2, 5, 10, 20, 40, 60)
BUDGET_POLICIES = tuple(f"budget-risk-{value}" for value in BUDGET_FRACTIONS)
BUDGET_COVERAGE_POLICIES = tuple(f"budget-coverage-{value}" for value in BUDGET_FRACTIONS)

POLICIES = (
    "invoke-all",
    "severity-only",
    "scenario-only",
    "recurrence-only",
    "self-healing-aware",
    "topology-aware",
    "topology+timeline",
    "window-risk-tier",
    *BUDGET_POLICIES,
    *BUDGET_COVERAGE_POLICIES,
    "oracle",
)


def run(args: argparse.Namespace) -> dict[str, Any]:
    alerts = _iter_alerts(Path(args.alert_dir), args.limit_files)
    if args.max_alerts > 0:
        alerts = alerts[: args.max_alerts]
    windows, window_index = build_incident_window_index(
        alerts,
        window_sec=args.window_sec,
        group_by_scenario=bool(getattr(args, "group_by_scenario", False)),
        window_mode=str(getattr(args, "window_mode", "session") or "session"),
        max_window_sec=getattr(args, "max_window_sec", None),
    )
    history: deque[tuple[datetime, str, str]] = deque()
    policy_stats = {policy: _empty_stats() for policy in POLICIES}
    window_policy_selected = {policy: {} for policy in POLICIES}
    budget_admissions = _build_budget_admissions(windows)
    decision_counts: Counter[str] = Counter()
    pressure_counts: Counter[str] = Counter()
    window_label_counts: Counter[str] = Counter(str(window.get("window_label") or "unknown") for window in windows)
    window_quality_counts: Counter[str] = Counter(str(window.get("quality_proxy_label") or "unknown") for window in windows)
    window_risk_counts: Counter[str] = Counter(str(window.get("risk_tier") or "unknown") for window in windows)

    for alert in alerts:
        alert_ts = _parse_ts(alert.get("alert_ts"))
        rule_id = str(alert.get("rule_id") or "unknown")
        excerpt = alert.get("event_excerpt") or {}
        service = str(excerpt.get("service") or "unknown")
        recent_similar_1h = 0
        if alert_ts is not None:
            while history and history[0][0] < (alert_ts - timedelta(hours=1)):
                history.popleft()
            recent_similar_1h = sum(
                1 for _, hist_rule, hist_service in history if hist_rule == rule_id and hist_service == service
            )
            history.append((alert_ts, rule_id, service))

        evidence = build_alert_evidence_bundle(alert, recent_similar_1h=recent_similar_1h)
        alert_id = str(alert.get("alert_id") or "")
        incident_window = window_index.get(alert_id)
        context_views = build_context_views(evidence, incident_window=incident_window)
        self_healing = assess_self_healing_decision(
            alert=alert,
            recent_similar_1h=recent_similar_1h,
            incident_window=incident_window,
            recurrence_threshold=args.recurrence_threshold,
            downstream_threshold=args.downstream_threshold,
        )
        decision_counts[str(self_healing.get("decision") or "unknown")] += 1
        if self_healing.get("topology_pressure"):
            pressure_counts["topology_pressure"] += 1
        if self_healing.get("recurrence_pressure"):
            pressure_counts["recurrence_pressure"] += 1
        if self_healing.get("multi_device_spread"):
            pressure_counts["multi_device_spread"] += 1

        high_value = _is_high_value(alert)
        for policy in POLICIES:
            selected = _selected_by_policy(
                policy=policy,
                alert=alert,
                evidence=evidence,
                context_views=context_views,
                incident_window=incident_window,
                self_healing=self_healing,
                recent_similar_1h=recent_similar_1h,
                recurrence_threshold=args.recurrence_threshold,
                budget_admissions=budget_admissions,
            )
            _update_stats(
                stats=policy_stats[policy],
                selected=selected,
                high_value=high_value,
                evidence_covered=_evidence_covered(context_views, incident_window),
                pressure=bool(
                    self_healing.get("topology_pressure")
                    or self_healing.get("recurrence_pressure")
                    or self_healing.get("multi_device_spread")
                ),
            )
            _update_window_selection(
                selected_by_policy=window_policy_selected[policy],
                incident_window=incident_window,
                alert_id=alert_id,
                selected=selected,
            )

    total = len(alerts)
    window_metrics = {
        policy: _window_metrics(windows, window_policy_selected[policy])
        for policy in POLICIES
    }
    report = {
        "evaluation_ts": datetime.now(timezone.utc).isoformat(),
        "alert_dir": args.alert_dir,
        "alerts_scanned": total,
        "window_sec": args.window_sec,
        "window_mode": str(getattr(args, "window_mode", "session") or "session"),
        "max_window_sec": getattr(args, "max_window_sec", None) or args.window_sec,
        "incident_windows": len(windows),
        "window_summary": _window_summary(windows),
        "window_labels": dict(window_label_counts.most_common()),
        "window_quality_proxy_labels": dict(window_quality_counts.most_common()),
        "window_risk_tiers": dict(window_risk_counts.most_common()),
        "self_healing_decisions": dict(decision_counts.most_common()),
        "pressure_counts": dict(pressure_counts.most_common()),
        "budget_admissions": {
            policy: _budget_admission_summary(admission)
            for policy, admission in budget_admissions.items()
        },
        "policies": {
            policy: {
                **_finalize_stats(policy_stats[policy], total),
                "window_metrics": window_metrics[policy],
            }
            for policy in POLICIES
        },
    }
    if getattr(args, "output_windows_jsonl", ""):
        _write_windows_jsonl(Path(args.output_windows_jsonl), windows)
    if getattr(args, "output_labels_jsonl", ""):
        _write_labels_jsonl(Path(args.output_labels_jsonl), windows)
    if args.output_json:
        path = Path(args.output_json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
    return report


def _selected_by_policy(
    *,
    policy: str,
    alert: dict[str, Any],
    evidence: dict[str, Any],
    context_views: dict[str, Any],
    incident_window: dict[str, Any] | None,
    self_healing: dict[str, Any],
    recent_similar_1h: int,
    recurrence_threshold: int,
    budget_admissions: dict[str, dict[str, Any]],
) -> bool:
    if policy == "invoke-all":
        return True
    if policy == "severity-only":
        return str(alert.get("severity") or "").lower() == "critical"
    scenario = _scenario(alert)
    if policy == "scenario-only":
        return scenario not in SELF_HEALING_SCENARIOS and scenario not in {"healthy", "normal", "unknown", ""}
    if policy == "recurrence-only":
        return recent_similar_1h >= recurrence_threshold or int((incident_window or {}).get("alert_count") or 0) >= recurrence_threshold
    if policy == "self-healing-aware":
        return bool(self_healing.get("should_invoke_external"))
    if policy == "topology-aware":
        gate = ((evidence.get("topology_subgraph") or {}).get("llm_invocation_gate") or {})
        return bool(gate.get("should_invoke_llm"))
    if policy == "topology+timeline":
        return _topology_timeline_selected(alert, context_views, incident_window, self_healing)
    if policy == "window-risk-tier":
        return _window_risk_tier_selected(alert, incident_window)
    if policy.startswith("budget-risk-") or policy.startswith("budget-coverage-"):
        admission = budget_admissions.get(policy) or {}
        return _alert_id(alert) in (admission.get("representative_alert_ids") or set())
    if policy == "oracle":
        return _is_high_value(alert)
    raise ValueError(f"unknown policy: {policy}")


def _build_budget_admissions(windows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    admissions: dict[str, dict[str, Any]] = {}
    for value in BUDGET_FRACTIONS:
        fraction = value / 100.0
        admissions[f"budget-risk-{value}"] = select_windows_under_budget(windows, budget_fraction=fraction)
        admissions[f"budget-coverage-{value}"] = select_windows_under_budget(
            windows,
            budget_fraction=fraction,
            min_high_value=False,
        )
    return admissions


def _budget_admission_summary(admission: dict[str, Any]) -> dict[str, Any]:
    return {
        "admission_strategy": admission.get("admission_strategy"),
        "budget_fraction": admission.get("budget_fraction"),
        "budget_windows": admission.get("budget_windows"),
        "budget_external_calls": admission.get("budget_external_calls"),
        "used_external_calls": admission.get("used_external_calls"),
        "safety_floor_extra_calls": admission.get("safety_floor_extra_calls"),
        "windows_total": admission.get("windows_total"),
        "selected_windows": admission.get("selected_windows"),
        "selected_representative_alerts": admission.get("selected_representative_alerts"),
        "covered_risk_atom_count": admission.get("covered_risk_atom_count"),
        "selected_risk_weight": admission.get("selected_risk_weight"),
    }


def _window_risk_tier_selected(alert: dict[str, Any], incident_window: dict[str, Any] | None) -> bool:
    if _is_high_value(alert):
        return True
    window = incident_window or {}
    if str(window.get("recommended_action") or "local") != "external":
        return False
    label = str(window.get("window_label") or "")
    if label == "external_unknown_with_pressure":
        return _alert_id(alert) in _representative_ids(window)
    if label in {"external_multi_device_spread", "external_repeated_transient", "mixed_fault_and_transient"}:
        return _alert_id(alert) in _representative_ids(window)
    return False


def _topology_timeline_selected(
    alert: dict[str, Any],
    context_views: dict[str, Any],
    incident_window: dict[str, Any] | None,
    self_healing: dict[str, Any],
) -> bool:
    if _is_high_value(alert):
        return True
    scenario = _scenario(alert)
    if scenario not in SELF_HEALING_SCENARIOS:
        return bool(self_healing.get("recurrence_pressure") or self_healing.get("topology_pressure"))
    window = incident_window or {}
    return bool(
        self_healing.get("multi_device_spread")
        or (
            self_healing.get("recurrence_pressure")
            and self_healing.get("topology_pressure")
            and int(window.get("alert_count") or 0) >= 3
        )
        or _has_blocking_missing_evidence(context_views)
    )


def _has_blocking_missing_evidence(context_views: dict[str, Any]) -> bool:
    missing = context_views.get("missing_evidence_view") or []
    missing_fields = {str(item.get("field") or "") for item in missing if isinstance(item, dict)}
    return "path_signature" in missing_fields or "src_device_key" in missing_fields


def _empty_stats() -> dict[str, int]:
    return {
        "calls": 0,
        "high_value_total": 0,
        "high_value_retained": 0,
        "false_skips": 0,
        "self_healing_skips": 0,
        "pressure_skips": 0,
        "covered_selected": 0,
        "selected_total": 0,
    }


def _update_stats(
    *,
    stats: dict[str, int],
    selected: bool,
    high_value: bool,
    evidence_covered: bool,
    pressure: bool,
) -> None:
    if high_value:
        stats["high_value_total"] += 1
    if selected:
        stats["calls"] += 1
        stats["selected_total"] += 1
        if high_value:
            stats["high_value_retained"] += 1
        if evidence_covered:
            stats["covered_selected"] += 1
    else:
        if high_value:
            stats["false_skips"] += 1
        else:
            stats["self_healing_skips"] += 1
        if pressure:
            stats["pressure_skips"] += 1


def _update_window_selection(
    *,
    selected_by_policy: dict[str, set[str]],
    incident_window: dict[str, Any] | None,
    alert_id: str,
    selected: bool,
) -> None:
    if not selected or not incident_window:
        return
    window_id = str(incident_window.get("window_id") or "")
    if not window_id:
        return
    selected_by_policy.setdefault(window_id, set()).add(alert_id)


def _finalize_stats(stats: dict[str, int], total: int) -> dict[str, Any]:
    total_safe = max(total, 1)
    high_value_total = max(stats["high_value_total"], 1)
    selected_total = max(stats["selected_total"], 1)
    high_value_recall = stats["high_value_retained"] / high_value_total
    evidence_coverage = stats["covered_selected"] / selected_total
    false_skip_rate = stats["false_skips"] / high_value_total
    pressure_skip_rate = stats["pressure_skips"] / total_safe
    return {
        "calls": stats["calls"],
        "call_reduction_percent": round((1 - stats["calls"] / total_safe) * 100, 2),
        "high_value_retained": stats["high_value_retained"],
        "high_value_total": stats["high_value_total"],
        "high_value_recall": round(high_value_recall, 6),
        "false_skips": stats["false_skips"],
        "false_skip_rate": round(false_skip_rate, 6),
        "self_healing_skips": stats["self_healing_skips"],
        "pressure_skips": stats["pressure_skips"],
        "pressure_skip_rate": round(pressure_skip_rate, 6),
        "evidence_coverage_rate": round(evidence_coverage, 6),
        "quality_loss_proxy": round(false_skip_rate + min(pressure_skip_rate, 0.25), 6),
    }


def _window_metrics(windows: list[dict[str, Any]], selected_by_window: dict[str, set[str]]) -> dict[str, Any]:
    total = len(windows)
    total_safe = max(total, 1)
    selected_windows = 0
    high_value_total = 0
    high_value_retained = 0
    pressure_total = 0
    pressure_skipped = 0
    self_healing_total = 0
    self_healing_skipped = 0
    covered = 0

    for window in windows:
        window_id = str(window.get("window_id") or "")
        selected_ids = selected_by_window.get(window_id, set())
        selected = bool(selected_ids)
        if selected:
            selected_windows += 1
        high_value = int(window.get("high_value_count") or 0) > 0
        pressure = bool(
            window.get("topology_pressure")
            or window.get("recurrence_pressure")
            or window.get("multi_device_spread")
        )
        self_healing = bool(window.get("self_healing_dominant"))
        if high_value:
            high_value_total += 1
            if selected:
                high_value_retained += 1
        if pressure:
            pressure_total += 1
            if not selected:
                pressure_skipped += 1
        if self_healing:
            self_healing_total += 1
            if not selected:
                self_healing_skipped += 1
        if selected and _window_evidence_targets_covered(window, selected_ids):
            covered += 1

    selected_safe = max(selected_windows, 1)
    high_safe = max(high_value_total, 1)
    pressure_safe = max(pressure_total, 1)
    return {
        "windows_total": total,
        "windows_selected": selected_windows,
        "window_reduction_percent": round((1 - selected_windows / total_safe) * 100, 2),
        "high_value_windows_total": high_value_total,
        "high_value_windows_retained": high_value_retained,
        "high_value_window_recall": round(high_value_retained / high_safe, 6),
        "pressure_windows_total": pressure_total,
        "pressure_windows_skipped": pressure_skipped,
        "pressure_window_skip_rate": round(pressure_skipped / pressure_safe, 6),
        "self_healing_windows_total": self_healing_total,
        "self_healing_windows_skipped": self_healing_skipped,
        "evidence_target_coverage_rate": round(covered / selected_safe, 6),
    }


def _window_evidence_targets_covered(window: dict[str, Any], selected_ids: set[str]) -> bool:
    targets = window.get("selected_evidence_targets") or {}
    target_ids = [str(item) for item in targets.get("representative_alert_ids") or targets.get("alert_ids") or []]
    if not target_ids:
        return bool(selected_ids)
    return bool(set(target_ids) & selected_ids)


def _evidence_covered(context_views: dict[str, Any], incident_window: dict[str, Any] | None) -> bool:
    topology = context_views.get("topology_view") or {}
    timeline = (context_views.get("timeline_view") or {}).get("incident_window") or {}
    return bool(
        str(topology.get("src_device_key") or "").strip()
        and str(topology.get("path_signature") or "").strip()
        and int((incident_window or timeline or {}).get("alert_count") or 0) >= 1
    )


def _representative_ids(window: dict[str, Any]) -> set[str]:
    targets = window.get("selected_evidence_targets") or {}
    values = targets.get("representative_alert_ids") or targets.get("alert_ids") or []
    return {str(value) for value in values if str(value)}


def _alert_id(alert: dict[str, Any]) -> str:
    return str(alert.get("alert_id") or "")


def _window_summary(windows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(windows)
    total_safe = max(total, 1)
    multi_device = sum(1 for window in windows if bool(window.get("multi_device_spread")))
    pressure = sum(1 for window in windows if bool(window.get("topology_pressure") or window.get("recurrence_pressure")))
    self_healing = sum(1 for window in windows if bool(window.get("self_healing_dominant")))
    avg_alerts = sum(int(window.get("alert_count") or 0) for window in windows) / total_safe
    avg_pressure = sum(int(window.get("pressure_score") or 0) for window in windows) / total_safe
    return {
        "total": total,
        "multi_device_windows": multi_device,
        "pressure_windows": pressure,
        "self_healing_dominant_windows": self_healing,
        "avg_alerts_per_window": round(avg_alerts, 3),
        "avg_pressure_score": round(avg_pressure, 3),
    }


def _write_windows_jsonl(path: Path, windows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fp:
        for window in windows:
            record = {
                "window_id": window.get("window_id") or "",
                "window_mode": window.get("window_mode") or "",
                "max_window_sec": window.get("max_window_sec") or 0,
                "window_start": window.get("window_start") or "",
                "window_end": window.get("window_end") or "",
                "window_label": window.get("window_label") or "",
                "recommended_action": window.get("recommended_action") or "local",
                "quality_proxy_label": window.get("quality_proxy_label") or "",
                "risk_score": window.get("risk_score") or 0,
                "risk_tier": window.get("risk_tier") or "low",
                "risk_atoms": window.get("risk_atoms") or [],
                "risk_offsets": window.get("risk_offsets") or [],
                "risk_weights": window.get("risk_weights") or {},
                "risk_reasons": window.get("risk_reasons") or [],
                "decision_reason": window.get("decision_reason") or "",
                "alert_count": window.get("alert_count") or 0,
                "device_count": window.get("device_count") or 0,
                "path_count": window.get("path_count") or 0,
                "high_value_count": window.get("high_value_count") or 0,
                "self_healing_count": window.get("self_healing_count") or 0,
                "self_healing_dominant": bool(window.get("self_healing_dominant")),
                "recurrence_pressure": bool(window.get("recurrence_pressure")),
                "topology_pressure": bool(window.get("topology_pressure")),
                "multi_device_spread": bool(window.get("multi_device_spread")),
                "max_downstream_dependents": window.get("max_downstream_dependents") or 0,
                "scenario_counts": window.get("scenario_counts") or {},
                "pressure_score": window.get("pressure_score") or 0,
                "selected_evidence_targets": window.get("selected_evidence_targets") or {},
                "excluded_evidence_targets": window.get("excluded_evidence_targets") or [],
                "timeline": window.get("timeline") or [],
            }
            fp.write(json.dumps(record, ensure_ascii=True, sort_keys=True) + "\n")


def _write_labels_jsonl(path: Path, windows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fp:
        for window in windows:
            fp.write(json.dumps(build_weak_window_label(window), ensure_ascii=True, sort_keys=True) + "\n")


def _scenario(alert: dict[str, Any]) -> str:
    dimensions = alert.get("dimensions") or {}
    metrics = alert.get("metrics") or {}
    return str(
        dimensions.get("fault_scenario")
        or metrics.get("label_value")
        or metrics.get("scenario")
        or "unknown"
    ).strip().lower()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate quality-cost policies over deterministic NetOps alerts."
    )
    parser.add_argument("--alert-dir", default="/data/netops-runtime/LCORE-D/work/alerts-lcore-corepatched-full-20260412T152119Z")
    parser.add_argument("--limit-files", type=int, default=0)
    parser.add_argument("--max-alerts", type=int, default=0)
    parser.add_argument("--window-sec", type=int, default=600)
    parser.add_argument(
        "--window-mode",
        choices=[
            "session",
            "fixed",
            "adaptive",
            "aics-topology",
            "aics-evidence",
            "aics",
        ],
        default="session",
    )
    parser.add_argument("--max-window-sec", type=int, default=0)
    parser.add_argument("--group-by-scenario", action="store_true")
    parser.add_argument("--recurrence-threshold", type=int, default=12)
    parser.add_argument("--downstream-threshold", type=int, default=10)
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-windows-jsonl", default="")
    parser.add_argument("--output-labels-jsonl", default="")
    run(parser.parse_args())


if __name__ == "__main__":
    main()
