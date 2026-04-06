import hashlib
from typing import Any

from core.aiops_agent.inference_schema import InferenceRequest, InferenceResult


def build_hypothesis_set(
    inference_request: InferenceRequest,
    evidence_bundle: dict[str, Any],
    inference_result: InferenceResult,
) -> dict[str, Any]:
    evidence_pack = evidence_bundle.get("evidence_pack_v2") or {}
    direct_refs = _source_refs(evidence_pack.get("direct_evidence"), limit=3)
    supporting_refs = _source_refs(evidence_pack.get("supporting_evidence"), limit=4)
    contradictory_refs = _source_refs(
        evidence_pack.get("contradictory_evidence"), limit=3
    )
    missing_refs = _source_refs(evidence_pack.get("missing_evidence"), limit=3)
    raw_hypotheses = inference_result.hypotheses or [inference_result.summary]
    set_id = hashlib.sha1(
        f"hypothesis-set|{inference_request.request_id}|{inference_request.suggestion_scope}".encode(
            "utf-8"
        ),
        usedforsecurity=False,
    ).hexdigest()

    items = []
    for index, statement in enumerate(raw_hypotheses):
        confidence_score = max(
            0.35,
            round(inference_result.confidence_score - (index * 0.08), 2),
        )
        item_id = hashlib.sha1(
            f"{set_id}|{index}|{statement}".encode("utf-8"),
            usedforsecurity=False,
        ).hexdigest()
        items.append(
            {
                "hypothesis_id": item_id,
                "rank": index + 1,
                "statement": str(statement).strip(),
                "confidence_score": confidence_score,
                "confidence_label": _confidence_label(confidence_score),
                "support_evidence_refs": direct_refs + supporting_refs,
                "contradict_evidence_refs": contradictory_refs,
                "missing_evidence_refs": missing_refs,
                "next_best_action": _action_for_rank(
                    inference_result.recommended_actions,
                    index,
                ),
                "review_state": "pending_review" if index == 0 else "candidate",
            }
        )

    return {
        "schema_version": 1,
        "set_id": set_id,
        "suggestion_scope": inference_request.suggestion_scope,
        "primary_hypothesis_id": items[0]["hypothesis_id"] if items else "",
        "items": items,
        "summary": {
            "total_hypotheses": len(items),
            "direct_ref_count": len(direct_refs),
            "supporting_ref_count": len(supporting_refs),
            "contradictory_ref_count": len(contradictory_refs),
            "missing_ref_count": len(missing_refs),
        },
    }


def _source_refs(entries: Any, *, limit: int) -> list[str]:
    if not isinstance(entries, list):
        return []
    refs: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        source_ref = str(entry.get("source_ref") or "").strip()
        if source_ref:
            refs.append(source_ref)
        if len(refs) >= limit:
            break
    return refs


def _action_for_rank(actions: list[str], index: int) -> str:
    if not actions:
        return ""
    if index < len(actions):
        return actions[index]
    return actions[0]


def _confidence_label(score: float) -> str:
    if score >= 0.85:
        return "high"
    if score >= 0.6:
        return "medium"
    return "low"
