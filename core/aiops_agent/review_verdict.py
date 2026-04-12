import hashlib
from typing import Any

from core.aiops_agent.inference_schema import InferenceRequest, InferenceResult


def build_review_verdict(
    inference_request: InferenceRequest,
    evidence_bundle: dict[str, Any],
    inference_result: InferenceResult,
    hypothesis_set: dict[str, Any],
    runbook_plan_outline: dict[str, Any],
) -> dict[str, Any]:
    evidence_pack = evidence_bundle.get("evidence_pack_v2") or {}
    summary = evidence_pack.get("summary") or {}
    direct_count = int(summary.get("direct_count") or 0)
    supporting_count = int(summary.get("supporting_count") or 0)
    contradictory_count = int(summary.get("contradictory_count") or 0)
    missing_count = int(summary.get("missing_count") or 0)
    approval_boundary = runbook_plan_outline.get("approval_boundary") or {}
    topology_subgraph = evidence_bundle.get("topology_subgraph") or {}
    invocation_gate = topology_subgraph.get("llm_invocation_gate") or {}
    approval_required = bool(approval_boundary.get("approval_required"))
    rollback_guidance = runbook_plan_outline.get("rollback_guidance") or []
    freshness_sections = (evidence_pack.get("freshness") or {}).get("sections") or []
    topology_refs = {
        entry.get("label")
        for entry in (evidence_pack.get("direct_evidence") or [])
        if isinstance(entry, dict)
    }

    evidence_sufficiency = (
        "sufficient"
        if direct_count >= 4 and supporting_count >= 1
        else "needs_evidence"
    )
    temporal_freshness = (
        "fresh"
        if any(
            str(section.get("freshness_state") or "").strip()
            in {"live_bundle_window", "hot_lookup_window", "recent_change_window"}
            for section in freshness_sections
            if isinstance(section, dict)
        )
        else "stale"
    )
    topology_consistency = (
        "consistent"
        if {"topology.service", "topology.src_device_key", "path.path_signature"}.issubset(topology_refs)
        and int(topology_subgraph.get("selected_node_count") or 0) > 0
        else "partial"
    )
    llm_budget_fit = "external_llm" if bool(invocation_gate.get("should_invoke_llm")) else "template_only"
    overreach_risk = "guarded" if approval_required else "bounded"
    remediation_executability = (
        "bounded"
        if runbook_plan_outline.get("prechecks") and runbook_plan_outline.get("operator_actions")
        else "draft_only"
    )
    rollback_readiness = "ready" if rollback_guidance else "missing"

    blocking_issues: list[str] = []
    if evidence_sufficiency != "sufficient":
        blocking_issues.append("evidence pack is still missing required support")
    if contradictory_count > supporting_count and contradictory_count > 0:
        blocking_issues.append("contradictory evidence outweighs supporting evidence")
    if invocation_gate and not bool(invocation_gate.get("should_invoke_llm")) and "low-evidence" in str(
        invocation_gate.get("reason") or ""
    ):
        blocking_issues.append("topology gate indicates low-value or low-evidence external LLM escalation")
    if rollback_readiness != "ready":
        blocking_issues.append("rollback guidance is incomplete")

    if blocking_issues:
        verdict_status = "needs_evidence"
        recommended_disposition = "return_to_evidence_gather"
    elif approval_required:
        verdict_status = "operator_review"
        recommended_disposition = "project_with_operator_boundary"
    else:
        verdict_status = "accepted"
        recommended_disposition = "ready_for_projection"

    verdict_id = hashlib.sha1(
        f"review-verdict|{inference_request.request_id}|{hypothesis_set.get('set_id') or ''}|{verdict_status}".encode(
            "utf-8"
        ),
        usedforsecurity=False,
    ).hexdigest()

    return {
        "schema_version": 1,
        "verdict_id": verdict_id,
        "suggestion_scope": inference_request.suggestion_scope,
        "verdict_status": verdict_status,
        "recommended_disposition": recommended_disposition,
        "approval_required": approval_required,
        "blocking_issues": blocking_issues,
        "checks": {
            "evidence_sufficiency": _check(
                evidence_sufficiency,
                f"direct={direct_count}, supporting={supporting_count}, missing={missing_count}",
            ),
            "temporal_freshness": _check(
                temporal_freshness,
                f"freshness_sections={len(freshness_sections)}",
            ),
            "topology_consistency": _check(
                topology_consistency,
                f"topology_refs={len(topology_refs)}, selected_nodes={int(topology_subgraph.get('selected_node_count') or 0)}",
            ),
            "llm_budget_fit": _check(
                llm_budget_fit,
                f"decision_score={float(invocation_gate.get('decision_score') or 0.0):.3f}",
            ),
            "overreach_risk": _check(
                overreach_risk,
                f"approval_required={str(approval_required).lower()}",
            ),
            "remediation_executability": _check(
                remediation_executability,
                f"actions={len(runbook_plan_outline.get('operator_actions') or [])}",
            ),
            "rollback_readiness": _check(
                rollback_readiness,
                f"rollback_steps={len(rollback_guidance)}",
            ),
        },
        "review_summary": (
            inference_result.confidence_reason
            or "review verdict derived from evidence coverage and runbook boundary"
        ),
    }


def _check(status: str, detail: str) -> dict[str, str]:
    return {
        "status": status,
        "detail": detail,
    }
