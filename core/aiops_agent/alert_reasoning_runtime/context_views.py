from __future__ import annotations

from typing import Any

from core.aiops_agent.alert_reasoning_runtime.incident_window import (
    build_window_evidence_boundary,
    summarize_incident_window,
)
from core.aiops_agent.alert_reasoning_runtime.self_healing_policy import assess_self_healing_decision


def build_context_views(
    evidence_bundle: dict[str, Any],
    incident_window: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build fixed model-facing context views from an evidence bundle."""

    alert_ref = evidence_bundle.get("alert_ref") or {}
    rule_context = evidence_bundle.get("rule_context") or {}
    topology_context = evidence_bundle.get("topology_context") or {}
    path_context = evidence_bundle.get("path_context") or {}
    historical_context = evidence_bundle.get("historical_context") or {}
    topology_subgraph = evidence_bundle.get("topology_subgraph") or {}
    invocation_gate = topology_subgraph.get("llm_invocation_gate") or {}
    summarized_window = summarize_incident_window(incident_window)
    window_boundary = build_window_evidence_boundary(incident_window)
    self_healing = assess_self_healing_decision(
        alert=_alert_from_bundle(evidence_bundle),
        recent_similar_1h=int(historical_context.get("recent_similar_1h") or 0),
        incident_window=incident_window,
    )

    missing = _missing_evidence(
        topology_context=topology_context,
        path_context=path_context,
        historical_context=historical_context,
        incident_window=summarized_window,
    )
    excluded = _excluded_evidence(
        topology_subgraph=topology_subgraph,
        self_healing=self_healing,
    )
    return {
        "schema_version": 1,
        "alert_view": {
            "alert_id": alert_ref.get("alert_id") or "",
            "rule_id": alert_ref.get("rule_id") or "",
            "severity": alert_ref.get("severity") or "",
            "scenario": _scenario_from_bundle(evidence_bundle),
            "metrics": (rule_context.get("metrics") or {}),
            "dimensions": (rule_context.get("dimensions") or {}),
        },
        "topology_view": {
            "src_device_key": topology_context.get("src_device_key") or "",
            "path_signature": topology_context.get("path_signature") or path_context.get("path_signature") or "",
            "hop_to_core": topology_context.get("hop_to_core") or "",
            "hop_to_server": topology_context.get("hop_to_server") or "",
            "path_up": topology_context.get("path_up") or "",
            "downstream_dependents": topology_context.get("downstream_dependents") or "",
            "neighbor_refs": topology_context.get("neighbor_refs") or [],
            "root_candidate_nodes": topology_subgraph.get("root_candidate_nodes") or [],
            "symptom_nodes": topology_subgraph.get("symptom_nodes") or [],
            "window_devices": (window_boundary.get("selected_surface") or {}).get("devices") or [],
            "window_path_signatures": (window_boundary.get("selected_surface") or {}).get("path_signatures") or [],
        },
        "timeline_view": {
            "incident_window": summarized_window,
            "window_boundary": window_boundary,
            "recent_alert_samples": historical_context.get("recent_alert_samples") or [],
            "cluster_sample_alert_ids": historical_context.get("cluster_sample_alert_ids") or [],
        },
        "history_view": {
            "recent_similar_1h": int(historical_context.get("recent_similar_1h") or 0),
            "cluster_size": int(historical_context.get("cluster_size") or 1),
            "cluster_window_sec": int(historical_context.get("cluster_window_sec") or 0),
            "historical_baseline": historical_context.get("historical_baseline") or {},
            "recent_change_records": historical_context.get("recent_change_records") or [],
            "self_healing_decision": self_healing,
            "window_label": window_boundary.get("window_label") or "",
            "window_quality_proxy_label": window_boundary.get("quality_proxy_label") or "",
        },
        "missing_evidence_view": missing,
        "excluded_evidence_view": excluded + list(window_boundary.get("excluded_surface") or []),
        "serving_view": {
            "should_invoke_llm": bool(invocation_gate.get("should_invoke_llm")),
            "budget_tier": invocation_gate.get("budget_tier") or "",
            "gate_reason": invocation_gate.get("reason") or "",
            "self_healing_budget_tier": self_healing.get("budget_tier") or "",
            "self_healing_reason": self_healing.get("reason") or "",
            "window_recommended_action": window_boundary.get("recommended_action") or "local",
            "window_decision_reason": window_boundary.get("decision_reason") or "",
        },
    }


def _alert_from_bundle(evidence_bundle: dict[str, Any]) -> dict[str, Any]:
    alert_ref = evidence_bundle.get("alert_ref") or {}
    rule_context = evidence_bundle.get("rule_context") or {}
    topology_context = evidence_bundle.get("topology_context") or {}
    device_context = evidence_bundle.get("device_context") or {}
    return {
        "alert_id": alert_ref.get("alert_id") or "",
        "rule_id": alert_ref.get("rule_id") or "",
        "severity": alert_ref.get("severity") or "unknown",
        "dimensions": rule_context.get("dimensions") or {},
        "metrics": rule_context.get("metrics") or {},
        "topology_context": topology_context,
        "device_profile": device_context,
        "event_excerpt": {"src_device_key": topology_context.get("src_device_key") or ""},
    }


def _scenario_from_bundle(evidence_bundle: dict[str, Any]) -> str:
    rule_context = evidence_bundle.get("rule_context") or {}
    dimensions = rule_context.get("dimensions") or {}
    metrics = rule_context.get("metrics") or {}
    return str(
        dimensions.get("fault_scenario")
        or metrics.get("label_value")
        or metrics.get("scenario")
        or "unknown"
    ).strip().lower()


def _missing_evidence(
    *,
    topology_context: dict[str, Any],
    path_context: dict[str, Any],
    historical_context: dict[str, Any],
    incident_window: dict[str, Any],
) -> list[dict[str, str]]:
    missing: list[dict[str, str]] = []
    if not str(topology_context.get("src_device_key") or "").strip():
        missing.append(_missing("topology_view", "src_device_key", "missing seed device identity"))
    if not str(topology_context.get("path_signature") or path_context.get("path_signature") or "").strip():
        missing.append(_missing("topology_view", "path_signature", "missing normalized path signature"))
    if not topology_context.get("neighbor_refs"):
        missing.append(_missing("topology_view", "neighbor_refs", "no explicit neighbor references available"))
    if int(historical_context.get("recent_similar_1h") or 0) == 0:
        missing.append(_missing("history_view", "recent_similar_1h", "no recurrence support in one-hour history"))
    if int(incident_window.get("alert_count") or 0) <= 1:
        missing.append(_missing("timeline_view", "incident_window", "no multi-alert incident window available"))
    return missing


def _excluded_evidence(
    *,
    topology_subgraph: dict[str, Any],
    self_healing: dict[str, Any],
) -> list[dict[str, Any]]:
    excluded = []
    for node in topology_subgraph.get("noise_nodes") or []:
        excluded.append(
            {
                "kind": "topology_noise_node",
                "node_id": node.get("node_id") or "",
                "node_type": node.get("node_type") or "",
                "rationale": node.get("rationale") or "",
            }
        )
    if str(self_healing.get("decision") or "").startswith("local_"):
        excluded.append(
            {
                "kind": "self_healing_local_decision",
                "decision": self_healing.get("decision") or "",
                "rationale": self_healing.get("reason") or "",
            }
        )
    return excluded


def _missing(view: str, field: str, reason: str) -> dict[str, str]:
    return {"view": view, "field": field, "reason": reason}
