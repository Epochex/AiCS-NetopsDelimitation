from typing import Any

from core.aiops_agent.alert_reasoning_runtime.candidate_event_graph import (
    build_alert_candidate_event_graph,
    build_cluster_candidate_event_graph,
)
from core.aiops_agent.alert_reasoning_runtime.investigation_session import (
    build_alert_investigation_session,
    build_cluster_investigation_session,
)
from core.aiops_agent.alert_reasoning_runtime.reasoning_trace import build_reasoning_trace_seed
from core.aiops_agent.alert_reasoning_runtime.runbook_plan_outline import build_runbook_plan_outline
from core.aiops_agent.alert_reasoning_runtime.topology_subgraph import extract_topology_aware_subgraph
from core.aiops_agent.cluster_aggregator import ClusterTrigger


def build_alert_runtime_seed(
    alert: dict[str, Any],
    recent_similar_1h: int,
    history_support: dict[str, Any] | None = None,
) -> dict[str, Any]:
    candidate_event_graph = build_alert_candidate_event_graph(
        alert=alert,
        recent_similar_1h=recent_similar_1h,
        history_support=history_support,
    )
    topology_subgraph = extract_topology_aware_subgraph(
        alert=alert,
        candidate_event_graph=candidate_event_graph,
        recent_similar_1h=recent_similar_1h,
        history_support=history_support,
    )
    investigation_session = build_alert_investigation_session(
        alert=alert,
        candidate_event_graph=candidate_event_graph,
    )
    return {
        "schema_version": 1,
        "runtime_seed_kind": "alert_reasoning_seed",
        "candidate_event_graph": candidate_event_graph,
        "topology_subgraph": topology_subgraph,
        "investigation_session": investigation_session,
        "reasoning_trace_seed": build_reasoning_trace_seed(
            investigation_session["session_id"],
            investigation_session["session_scope"],
        ),
        "runbook_plan_outline": build_runbook_plan_outline(alert, investigation_session["session_scope"]),
    }


def build_cluster_runtime_seed(
    alert: dict[str, Any],
    trigger: ClusterTrigger,
    recent_similar_1h: int,
    history_support: dict[str, Any] | None = None,
) -> dict[str, Any]:
    candidate_event_graph = build_cluster_candidate_event_graph(
        alert=alert,
        trigger=trigger,
        recent_similar_1h=recent_similar_1h,
        history_support=history_support,
    )
    cluster_context = {
        "rule_id": trigger.key.rule_id,
        "severity": trigger.key.severity,
        "service": trigger.key.service,
        "src_device_key": trigger.key.src_device_key,
        "cluster_size": trigger.cluster_size,
        "window_sec": trigger.window_sec,
    }
    topology_subgraph = extract_topology_aware_subgraph(
        alert=alert,
        candidate_event_graph=candidate_event_graph,
        recent_similar_1h=recent_similar_1h,
        history_support=history_support,
        cluster_context=cluster_context,
    )
    investigation_session = build_cluster_investigation_session(
        alert=alert,
        candidate_event_graph=candidate_event_graph,
    )
    return {
        "schema_version": 1,
        "runtime_seed_kind": "cluster_reasoning_seed",
        "candidate_event_graph": candidate_event_graph,
        "topology_subgraph": topology_subgraph,
        "investigation_session": investigation_session,
        "reasoning_trace_seed": build_reasoning_trace_seed(
            investigation_session["session_id"],
            investigation_session["session_scope"],
        ),
        "runbook_plan_outline": build_runbook_plan_outline(alert, investigation_session["session_scope"]),
        "cluster_context": cluster_context,
    }
