from __future__ import annotations

from typing import Any


HIGH_VALUE_SCENARIOS = {
    "induced_fault",
    "single_link_failure",
    "multiple_link_failure",
    "node_failure",
    "multiple_nodes_failures",
    "single_node_failure",
    "routing_misconfiguration",
    "misconfiguration",
    "line_card_failure",
    "icmp_blocked_firewall",
    "snmp_agent_failure",
}
SELF_HEALING_SCENARIOS = {"transient_fault", "transient_healthy"}


def assess_self_healing_decision(
    *,
    alert: dict[str, Any],
    recent_similar_1h: int = 0,
    incident_window: dict[str, Any] | None = None,
    recurrence_threshold: int = 3,
    downstream_threshold: int = 10,
) -> dict[str, Any]:
    scenario = _scenario(alert)
    severity = str(alert.get("severity") or "unknown").lower()
    topology = alert.get("topology_context") or {}
    window = incident_window or {}
    window_alert_count = int(window.get("alert_count") or 1)
    window_device_count = int(window.get("device_count") or 1)
    max_downstream = int(window.get("max_downstream_dependents") or _downstream_dependents(topology))
    window_label = str(window.get("window_label") or "")
    recurrence_pressure = (
        int(recent_similar_1h) >= recurrence_threshold
        or window_alert_count >= recurrence_threshold
        or bool(window.get("recurrence_pressure"))
    )
    topology_pressure = (
        bool(window.get("topology_pressure"))
        or max_downstream >= downstream_threshold
        or bool(_neighbor_refs(topology))
    )
    multi_device_spread = bool(window.get("multi_device_spread")) or window_device_count >= 2
    is_self_healing = scenario in SELF_HEALING_SCENARIOS

    if severity == "critical":
        decision = "external_critical_alert"
        should_invoke = True
    elif scenario in HIGH_VALUE_SCENARIOS:
        decision = "external_induced_fault"
        should_invoke = True
    elif is_self_healing and window_label == "mixed_fault_and_transient":
        decision = "external_fault_context_window"
        should_invoke = True
    elif is_self_healing and multi_device_spread:
        decision = "external_multi_device_spread"
        should_invoke = True
    elif is_self_healing and recurrence_pressure:
        decision = "external_repeated_transient"
        should_invoke = True
    elif is_self_healing and topology_pressure:
        decision = "local_transient_with_pressure"
        should_invoke = False
    elif is_self_healing:
        decision = "local_single_transient"
        should_invoke = False
    elif recurrence_pressure or topology_pressure:
        decision = "external_unknown_with_pressure"
        should_invoke = True
    else:
        decision = "local_low_evidence"
        should_invoke = False

    return {
        "schema_version": 1,
        "scenario": scenario,
        "severity": severity,
        "is_self_healing_candidate": is_self_healing,
        "recurrence_pressure": recurrence_pressure,
        "topology_pressure": topology_pressure,
        "multi_device_spread": multi_device_spread,
        "window_alert_count": window_alert_count,
        "window_device_count": window_device_count,
        "max_downstream_dependents": max_downstream,
        "window_label": window_label,
        "decision": decision,
        "should_invoke_external": should_invoke,
        "budget_tier": "external_llm" if should_invoke else "local_bounded",
        "reason": _reason_for(
            decision=decision,
            scenario=scenario,
            recent_similar_1h=recent_similar_1h,
            window_alert_count=window_alert_count,
            window_device_count=window_device_count,
            max_downstream=max_downstream,
        ),
        "evidence_refs": _evidence_refs(
            recurrence_pressure=recurrence_pressure,
            topology_pressure=topology_pressure,
            multi_device_spread=multi_device_spread,
        ),
    }


def _scenario(alert: dict[str, Any]) -> str:
    dimensions = alert.get("dimensions") or {}
    metrics = alert.get("metrics") or {}
    return str(
        dimensions.get("fault_scenario")
        or metrics.get("label_value")
        or metrics.get("scenario")
        or "unknown"
    ).strip().lower()


def _downstream_dependents(topology: dict[str, Any]) -> int:
    try:
        return int(str(topology.get("downstream_dependents") or "0"))
    except ValueError:
        return 0


def _neighbor_refs(topology: dict[str, Any]) -> list[str]:
    refs = topology.get("neighbor_refs")
    if not isinstance(refs, list):
        return []
    return [str(item).strip() for item in refs if str(item).strip()]


def _evidence_refs(
    *,
    recurrence_pressure: bool,
    topology_pressure: bool,
    multi_device_spread: bool,
) -> list[str]:
    refs = ["dimensions.fault_scenario", "alert.severity"]
    if recurrence_pressure:
        refs.extend(["historical_context.recent_similar_1h", "incident_window.alert_count"])
    if topology_pressure:
        refs.extend(["topology_context.downstream_dependents", "topology_context.neighbor_refs"])
    if multi_device_spread:
        refs.append("incident_window.devices")
    return sorted(set(refs))


def _reason_for(
    *,
    decision: str,
    scenario: str,
    recent_similar_1h: int,
    window_alert_count: int,
    window_device_count: int,
    max_downstream: int,
) -> str:
    if decision == "external_induced_fault":
        return f"{scenario} is retained for model-assisted analysis."
    if decision == "external_critical_alert":
        return "critical severity is retained for external reasoning."
    if decision == "external_fault_context_window":
        return "transient-looking alert is in a window that also contains high-value fault evidence."
    if decision == "external_multi_device_spread":
        return f"transient-looking alerts span {window_device_count} devices in the incident window."
    if decision == "external_repeated_transient":
        return (
            "transient-looking alerts repeat enough to require external review "
            f"(recent_similar_1h={recent_similar_1h}, window_alerts={window_alert_count})."
        )
    if decision == "local_transient_with_pressure":
        return (
            "transient alert remains local, but topology pressure is recorded "
            f"(max_downstream_dependents={max_downstream})."
        )
    if decision == "local_single_transient":
        return "single transient alert is handled by the bounded local path."
    if decision == "external_unknown_with_pressure":
        return "unknown or weak scenario has recurrence or topology pressure."
    return "low-evidence alert remains on the bounded local path."
