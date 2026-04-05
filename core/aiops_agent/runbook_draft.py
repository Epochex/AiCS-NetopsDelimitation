import hashlib
from typing import Any

from core.aiops_agent.inference_schema import InferenceRequest


def build_runbook_draft(
    inference_request: InferenceRequest,
    evidence_bundle: dict[str, Any],
    hypothesis_set: dict[str, Any],
    review_verdict: dict[str, Any],
    runbook_plan_outline: dict[str, Any],
    recommended_actions: list[str],
) -> dict[str, Any]:
    context = evidence_bundle.get("topology_context") or {}
    device_context = evidence_bundle.get("device_context") or {}
    change_context = evidence_bundle.get("change_context") or {}
    service = str(context.get("service") or "unknown")
    device_name = str(
        device_context.get("device_name")
        or device_context.get("src_device_key")
        or context.get("src_device_key")
        or "unknown"
    )
    applicability = runbook_plan_outline.get("applicability") or {}
    prechecks = list(runbook_plan_outline.get("prechecks") or [])
    rollback_guidance = list(runbook_plan_outline.get("rollback_guidance") or [])
    approval_boundary = runbook_plan_outline.get("approval_boundary") or {}
    primary_item = _primary_hypothesis(hypothesis_set)
    operator_actions = _dedupe_lines(
        list(runbook_plan_outline.get("operator_actions") or [])
        + list(recommended_actions or [])
    )
    blocking_issues = list(review_verdict.get("blocking_issues") or [])
    plan_id = hashlib.sha1(
        f"runbook-draft|{inference_request.request_id}|{service}|{device_name}".encode(
            "utf-8"
        ),
        usedforsecurity=False,
    ).hexdigest()

    boundaries = [
        "guidance only; no device write path is opened",
        (
            "approval required before any execution-facing step"
            if approval_boundary.get("approval_required")
            else "approval boundary not asserted by current outline"
        ),
        (
            "review returned blocking issues: " + "; ".join(blocking_issues[:2])
            if blocking_issues
            else "review accepted projection under operator boundary"
        ),
    ]

    evidence_refs = _collect_evidence_refs(evidence_bundle.get("evidence_pack_v2") or {})

    return {
        "schema_version": 1,
        "plan_id": plan_id,
        "plan_scope": inference_request.suggestion_scope,
        "plan_status": (
            "needs_evidence"
            if review_verdict.get("recommended_disposition") == "return_to_evidence_gather"
            else "draft_ready"
        ),
        "title": f"Runbook draft for {service} on {device_name}",
        "applicability": {
            "rule_id": str(applicability.get("rule_id") or inference_request.rule_id),
            "service": str(applicability.get("service") or service),
            "path_signature": str(applicability.get("path_signature") or context.get("path_signature") or ""),
        },
        "hypothesis_ref": primary_item.get("hypothesis_id") or "",
        "hypothesis_statement": primary_item.get("statement") or "",
        "prechecks": prechecks,
        "operator_actions": operator_actions[:4],
        "boundaries": boundaries,
        "rollback_guidance": rollback_guidance,
        "approval_boundary": {
            "approval_required": bool(approval_boundary.get("approval_required")),
            "execution_mode": str(approval_boundary.get("execution_mode") or "human_gated"),
            "write_path_allowed": bool(approval_boundary.get("write_path_allowed")),
        },
        "evidence_refs": evidence_refs[:8],
        "change_summary": {
            "suspected_change": bool(change_context.get("suspected_change")),
            "change_refs": list(change_context.get("change_refs") or [])[:3],
        },
    }


def _primary_hypothesis(hypothesis_set: dict[str, Any]) -> dict[str, Any]:
    items = hypothesis_set.get("items") or []
    if not isinstance(items, list):
        return {}
    primary_id = str(hypothesis_set.get("primary_hypothesis_id") or "")
    for item in items:
        if isinstance(item, dict) and str(item.get("hypothesis_id") or "") == primary_id:
            return item
    for item in items:
        if isinstance(item, dict):
            return item
    return {}


def _collect_evidence_refs(evidence_pack: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for group in (
        "direct_evidence",
        "supporting_evidence",
        "contradictory_evidence",
        "missing_evidence",
    ):
        entries = evidence_pack.get(group) or []
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            source_ref = str(entry.get("source_ref") or "").strip()
            if source_ref and source_ref not in refs:
                refs.append(source_ref)
    return refs


def _dedupe_lines(lines: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for line in lines:
        text = str(line).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        deduped.append(text)
    return deduped
