from typing import Any

from core.aiops_agent.app_config import AgentConfig
from core.aiops_agent.inference_schema import InferenceRequest


def build_provider_routing_hint(config: AgentConfig, inference_request: InferenceRequest) -> dict[str, Any]:
    reasoning_seed = inference_request.evidence_bundle.get("reasoning_runtime_seed") or {}
    candidate_event_graph = reasoning_seed.get("candidate_event_graph") or {}
    investigation_session = reasoning_seed.get("investigation_session") or {}
    runbook_plan_outline = reasoning_seed.get("runbook_plan_outline") or {}
    return {
        "provider_name": config.provider,
        "compute_target": config.provider_compute_target,
        "max_parallelism": config.provider_max_parallelism,
        "request_kind": inference_request.request_kind,
        "suggestion_scope": inference_request.suggestion_scope,
        "evidence_bundle_id": inference_request.evidence_bundle.get("bundle_id") or "",
        "candidate_event_graph_id": candidate_event_graph.get("graph_id") or "",
        "investigation_session_id": investigation_session.get("session_id") or "",
        "runbook_plan_id": runbook_plan_outline.get("plan_id") or "",
        "allowed_execution_surface": "core_plane_only",
        "edge_execution_allowed": False,
    }
