from typing import Any

from core.aiops_agent.evidence_pack_v2 import select_evidence_pack_v2_view
from core.aiops_agent.alert_reasoning_runtime.topology_subgraph import summarize_topology_subgraph


def build_phase_context_payload(stage: str, evidence_bundle: dict[str, Any]) -> dict[str, Any]:
    normalized_stage = str(stage or "").strip().lower()
    reasoning_seed = evidence_bundle.get("reasoning_runtime_seed") or {}
    candidate_event_graph = reasoning_seed.get("candidate_event_graph") or {}
    topology_subgraph = reasoning_seed.get("topology_subgraph") or evidence_bundle.get("topology_subgraph") or {}
    investigation_session = reasoning_seed.get("investigation_session") or {}
    runbook_plan_outline = reasoning_seed.get("runbook_plan_outline") or {}
    evidence_pack_v2 = evidence_bundle.get("evidence_pack_v2") or {}
    context_views = evidence_bundle.get("context_views") or {}
    prompt_contracts = evidence_bundle.get("prompt_contracts") or {}

    base = {
        "stage": normalized_stage,
        "bundle_id": evidence_bundle.get("bundle_id") or "",
        "bundle_scope": evidence_bundle.get("bundle_scope") or "",
        "alert_ref": evidence_bundle.get("alert_ref") or {},
        "context_views": context_views,
        "prompt_contract": prompt_contracts.get(normalized_stage) or {},
        "evidence_pack_v2": select_evidence_pack_v2_view(
            normalized_stage,
            evidence_pack_v2,
        ),
        "candidate_event_graph": _graph_summary(candidate_event_graph),
        "topology_subgraph": summarize_topology_subgraph(topology_subgraph),
        "investigation_session": _session_summary(investigation_session),
    }

    if normalized_stage == "hypothesis_generate":
        base["context"] = {
            "historical_context": _pick_mapping(
                evidence_bundle.get("historical_context") or {},
                [
                    "recent_similar_1h",
                    "cluster_size",
                    "cluster_window_sec",
                    "cluster_first_alert_ts",
                    "cluster_last_alert_ts",
                    "cluster_sample_alert_ids",
                    "recent_change_records",
                ],
            ),
            "rule_context": evidence_bundle.get("rule_context") or {},
            "path_context": evidence_bundle.get("path_context") or {},
            "device_context": evidence_bundle.get("device_context") or {},
        }
        return base

    if normalized_stage == "hypothesis_critique":
        base["context"] = {
            "rule_context": evidence_bundle.get("rule_context") or {},
            "path_context": evidence_bundle.get("path_context") or {},
            "policy_context": evidence_bundle.get("policy_context") or {},
            "sample_context": evidence_bundle.get("sample_context") or {},
            "change_context": evidence_bundle.get("change_context") or {},
            "topology_subgraph": summarize_topology_subgraph(topology_subgraph),
        }
        return base

    if normalized_stage in {"runbook_retrieve", "runbook_draft"}:
        base["context"] = {
            "device_context": evidence_bundle.get("device_context") or {},
            "policy_context": evidence_bundle.get("policy_context") or {},
            "change_context": evidence_bundle.get("change_context") or {},
            "runbook_plan_outline": runbook_plan_outline,
        }
        return base

    if normalized_stage == "runbook_review":
        base["context"] = {
            "runbook_plan_outline": runbook_plan_outline,
            "change_context": evidence_bundle.get("change_context") or {},
            "historical_context": _pick_mapping(
                evidence_bundle.get("historical_context") or {},
                [
                    "recent_similar_1h",
                    "cluster_size",
                    "recent_change_records",
                ],
            ),
        }
        return base

    base["context"] = {
        "historical_context": evidence_bundle.get("historical_context") or {},
        "rule_context": evidence_bundle.get("rule_context") or {},
    }
    return base


def _graph_summary(candidate_event_graph: dict[str, Any]) -> dict[str, Any]:
    return {
        "graph_id": candidate_event_graph.get("graph_id") or "",
        "graph_scope": candidate_event_graph.get("graph_scope") or "",
        "node_count": int(candidate_event_graph.get("node_count") or 0),
        "edge_count": int(candidate_event_graph.get("edge_count") or 0),
    }


def _session_summary(investigation_session: dict[str, Any]) -> dict[str, Any]:
    return {
        "session_id": investigation_session.get("session_id") or "",
        "session_scope": investigation_session.get("session_scope") or "",
        "current_stage": investigation_session.get("current_stage") or "",
        "selected_node_ids": investigation_session.get("selected_node_ids") or [],
    }


def _pick_mapping(source: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    return {key: source.get(key) for key in keys}
