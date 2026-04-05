import hashlib
from typing import Any


def build_alert_investigation_session(
    alert: dict[str, Any],
    candidate_event_graph: dict[str, Any],
) -> dict[str, Any]:
    alert_id = str(alert.get("alert_id") or "")
    graph_id = str(candidate_event_graph.get("graph_id") or "")
    session_id = _hash_id(f"alert-session|{alert_id}|{graph_id}")
    return {
        "schema_version": 1,
        "session_id": session_id,
        "session_scope": "alert",
        "entrypoint": "rule_confirmed_alert",
        "selected_node_ids": [f"alert::{alert_id or 'unknown'}"],
        "expanded_node_ids": [],
        "current_stage": "context_assemble_pending",
        "recommended_retrievers": [
            "historical_pattern_retriever",
            "topology_neighborhood_retriever",
            "runbook_applicability_retriever",
        ],
        "working_memory_seed": {
            "accepted_hypotheses": [],
            "rejected_hypotheses": [],
            "missing_evidence": [
                "topology neighbor validation",
                "runbook applicability selection",
            ],
            "risk_flags": ["human approval required for write-path actions"],
            "pending_checks": ["policy intent validation", "rollback boundary review"],
        },
    }


def build_cluster_investigation_session(
    alert: dict[str, Any],
    candidate_event_graph: dict[str, Any],
) -> dict[str, Any]:
    alert_id = str(alert.get("alert_id") or "")
    graph_id = str(candidate_event_graph.get("graph_id") or "")
    session_id = _hash_id(f"cluster-session|{alert_id}|{graph_id}")
    return {
        "schema_version": 1,
        "session_id": session_id,
        "session_scope": "cluster",
        "entrypoint": "rule_confirmed_cluster_trigger",
        "selected_node_ids": [f"cluster::{graph_id}", f"alert::{alert_id or 'unknown'}"],
        "expanded_node_ids": [],
        "current_stage": "cluster_refine_pending",
        "recommended_retrievers": [
            "historical_pattern_retriever",
            "change_window_retriever",
            "topology_neighborhood_retriever",
            "runbook_applicability_retriever",
        ],
        "working_memory_seed": {
            "accepted_hypotheses": [],
            "rejected_hypotheses": [],
            "missing_evidence": [
                "cluster boundary validation",
                "common-cause confirmation across member alerts",
                "runbook applicability selection",
            ],
            "risk_flags": ["human approval required for write-path actions"],
            "pending_checks": ["cluster breadth review", "rollback boundary review"],
        },
    }


def _hash_id(seed: str) -> str:
    return hashlib.sha1(seed.encode("utf-8"), usedforsecurity=False).hexdigest()
