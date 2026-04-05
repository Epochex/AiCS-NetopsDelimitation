import hashlib
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from core.aiops_agent.alert_reasoning_runtime.phase_context_router import (
    build_phase_context_payload,
)
from core.aiops_agent.app_config import AgentConfig
from core.aiops_agent.inference_schema import InferenceRequest
from core.aiops_agent.provider_routing import build_provider_routing_hint


@dataclass(frozen=True)
class ReasoningStageRequest:
    schema_version: int
    stage_request_id: str
    parent_request_id: str
    request_ts: str
    stage: str
    provider: str
    suggestion_scope: str
    routing_hint: dict[str, Any]
    input_contract: dict[str, Any]
    expected_response_schema: dict[str, Any]

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


def build_reasoning_stage_requests(
    config: AgentConfig,
    inference_request: InferenceRequest,
    suggestion_payload: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    evidence_bundle = suggestion_payload.get("evidence_bundle") or {}
    hypothesis_set = suggestion_payload.get("hypothesis_set") or {}
    review_verdict = suggestion_payload.get("review_verdict") or {}
    runbook_plan_outline = suggestion_payload.get("runbook_plan_outline") or {}
    runbook_draft = suggestion_payload.get("runbook_draft") or {}

    stage_requests = [
        _build_hypothesis_critique_request(
            config=config,
            inference_request=inference_request,
            evidence_bundle=evidence_bundle,
            hypothesis_set=hypothesis_set,
        ),
        _build_runbook_draft_request(
            config=config,
            inference_request=inference_request,
            evidence_bundle=evidence_bundle,
            hypothesis_set=hypothesis_set,
            review_verdict=review_verdict,
            runbook_plan_outline=runbook_plan_outline,
            runbook_draft=runbook_draft,
        ),
    ]
    return {
        stage_request.stage: stage_request.to_payload()
        for stage_request in stage_requests
    }


def _build_hypothesis_critique_request(
    *,
    config: AgentConfig,
    inference_request: InferenceRequest,
    evidence_bundle: dict[str, Any],
    hypothesis_set: dict[str, Any],
) -> ReasoningStageRequest:
    stage = "hypothesis_critique"
    return ReasoningStageRequest(
        schema_version=1,
        stage_request_id=_stage_request_id(inference_request.request_id, stage),
        parent_request_id=inference_request.request_id,
        request_ts=datetime.now(timezone.utc).isoformat(),
        stage=stage,
        provider=inference_request.provider,
        suggestion_scope=inference_request.suggestion_scope,
        routing_hint=_stage_routing_hint(config, inference_request, stage),
        input_contract={
            "task_brief": (
                "Critique the currently ranked hypotheses against direct, supporting, "
                "and contradictory evidence. Surface gaps that require a return to "
                "evidence gathering."
            ),
            "phase_context": build_phase_context_payload(stage, evidence_bundle),
            "reasoning_objects": {
                "hypothesis_set": _summarize_hypothesis_set(hypothesis_set),
            },
        },
        expected_response_schema={
            "primary_hypothesis_id": "string",
            "stage_status": "accepted|needs_evidence|conflicted",
            "per_hypothesis_review": [
                {
                    "hypothesis_id": "string",
                    "verdict": "support|weaken|reject|needs_evidence",
                    "support_evidence_refs": ["string"],
                    "contradict_evidence_refs": ["string"],
                    "missing_evidence_refs": ["string"],
                    "critic_summary": "string",
                }
            ],
            "review_summary": "string",
            "return_to_evidence": "bool",
        },
    )


def _build_runbook_draft_request(
    *,
    config: AgentConfig,
    inference_request: InferenceRequest,
    evidence_bundle: dict[str, Any],
    hypothesis_set: dict[str, Any],
    review_verdict: dict[str, Any],
    runbook_plan_outline: dict[str, Any],
    runbook_draft: dict[str, Any],
) -> ReasoningStageRequest:
    stage = "runbook_draft"
    return ReasoningStageRequest(
        schema_version=1,
        stage_request_id=_stage_request_id(inference_request.request_id, stage),
        parent_request_id=inference_request.request_id,
        request_ts=datetime.now(timezone.utc).isoformat(),
        stage=stage,
        provider=inference_request.provider,
        suggestion_scope=inference_request.suggestion_scope,
        routing_hint=_stage_routing_hint(config, inference_request, stage),
        input_contract={
            "task_brief": (
                "Draft a bounded operator-facing runbook from the current hypothesis, "
                "review verdict, and deterministic plan outline. Keep execution human-gated."
            ),
            "phase_context": build_phase_context_payload(stage, evidence_bundle),
            "reasoning_objects": {
                "hypothesis_set": _summarize_hypothesis_set(hypothesis_set),
                "review_verdict": _summarize_review_verdict(review_verdict),
                "runbook_plan_outline": _summarize_runbook_outline(runbook_plan_outline),
                "deterministic_runbook_seed": _summarize_runbook_draft(runbook_draft),
            },
        },
        expected_response_schema={
            "title": "string",
            "plan_status": "draft_ready|needs_evidence|operator_review",
            "prechecks": ["string"],
            "operator_actions": ["string"],
            "boundaries": ["string"],
            "rollback_guidance": ["string"],
            "approval_boundary": {
                "approval_required": "bool",
                "execution_mode": "string",
                "write_path_allowed": "bool",
            },
            "evidence_refs": ["string"],
            "missing_information": ["string"],
        },
    )


def _stage_request_id(parent_request_id: str, stage: str) -> str:
    return hashlib.sha1(
        f"reasoning-stage|{parent_request_id}|{stage}".encode("utf-8"),
        usedforsecurity=False,
    ).hexdigest()


def _stage_routing_hint(
    config: AgentConfig,
    inference_request: InferenceRequest,
    stage: str,
) -> dict[str, Any]:
    routing_hint = build_provider_routing_hint(config, inference_request)
    routing_hint["request_kind"] = stage
    routing_hint["stage"] = stage
    return routing_hint


def _summarize_hypothesis_set(hypothesis_set: dict[str, Any]) -> dict[str, Any]:
    items = hypothesis_set.get("items") or []
    normalized_items: list[dict[str, Any]] = []
    if isinstance(items, list):
        for item in items[:3]:
            if not isinstance(item, dict):
                continue
            normalized_items.append(
                {
                    "hypothesis_id": str(item.get("hypothesis_id") or ""),
                    "rank": int(item.get("rank") or 0),
                    "statement": str(item.get("statement") or ""),
                    "confidence_label": str(item.get("confidence_label") or ""),
                    "support_evidence_refs": list(item.get("support_evidence_refs") or [])[:4],
                    "contradict_evidence_refs": list(item.get("contradict_evidence_refs") or [])[:4],
                    "missing_evidence_refs": list(item.get("missing_evidence_refs") or [])[:4],
                    "next_best_action": str(item.get("next_best_action") or ""),
                    "review_state": str(item.get("review_state") or ""),
                }
            )
    return {
        "set_id": str(hypothesis_set.get("set_id") or ""),
        "primary_hypothesis_id": str(hypothesis_set.get("primary_hypothesis_id") or ""),
        "summary": hypothesis_set.get("summary") or {},
        "items": normalized_items,
    }


def _summarize_review_verdict(review_verdict: dict[str, Any]) -> dict[str, Any]:
    return {
        "verdict_id": str(review_verdict.get("verdict_id") or ""),
        "verdict_status": str(review_verdict.get("verdict_status") or ""),
        "recommended_disposition": str(review_verdict.get("recommended_disposition") or ""),
        "approval_required": bool(review_verdict.get("approval_required")),
        "blocking_issues": list(review_verdict.get("blocking_issues") or [])[:4],
        "checks": review_verdict.get("checks") or {},
        "review_summary": str(review_verdict.get("review_summary") or ""),
    }


def _summarize_runbook_outline(runbook_plan_outline: dict[str, Any]) -> dict[str, Any]:
    return {
        "plan_id": str(runbook_plan_outline.get("plan_id") or ""),
        "applicability": runbook_plan_outline.get("applicability") or {},
        "prechecks": list(runbook_plan_outline.get("prechecks") or [])[:4],
        "operator_actions": list(runbook_plan_outline.get("operator_actions") or [])[:4],
        "approval_boundary": runbook_plan_outline.get("approval_boundary") or {},
        "rollback_guidance": list(runbook_plan_outline.get("rollback_guidance") or [])[:4],
    }


def _summarize_runbook_draft(runbook_draft: dict[str, Any]) -> dict[str, Any]:
    return {
        "plan_id": str(runbook_draft.get("plan_id") or ""),
        "plan_status": str(runbook_draft.get("plan_status") or ""),
        "title": str(runbook_draft.get("title") or ""),
        "prechecks": list(runbook_draft.get("prechecks") or [])[:4],
        "operator_actions": list(runbook_draft.get("operator_actions") or [])[:4],
        "approval_boundary": runbook_draft.get("approval_boundary") or {},
        "evidence_refs": list(runbook_draft.get("evidence_refs") or [])[:6],
    }
