from __future__ import annotations

from typing import Any


BOUNDARY_REVIEW_SCHEMA = {
    "boundary_status": "accepted|needs_more_evidence|over_scoped|under_scoped",
    "missing_evidence": ["string"],
    "selected_evidence_issues": ["string"],
    "excluded_evidence_issues": ["string"],
    "topology_consistency": "consistent|weak|conflicted",
    "timeline_consistency": "consistent|weak|conflicted",
    "external_reasoning_needed": "bool",
    "reason": "string",
}

INCIDENT_INTERPRETATION_SCHEMA = {
    "summary": "string",
    "hypotheses": ["string"],
    "recommended_actions": ["string"],
    "confidence_score": "float[0,1]",
    "confidence_label": "low|medium|high",
    "confidence_reason": "string",
}

OUTPUT_REVIEW_SCHEMA = {
    "output_status": "accepted|overclaim|missing_evidence|unsafe_action",
    "evidence_reference_issues": ["string"],
    "overclaim_issues": ["string"],
    "unsafe_action_issues": ["string"],
    "root_symptom_confusion": "bool",
    "revision_required": "bool",
}


def build_prompt_contracts(context_views: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "boundary_review": _contract(
            stage="boundary_review",
            task=(
                "Review whether the alert/window evidence boundary is sufficient before diagnosis. "
                "Do not diagnose the incident; decide whether the selected evidence is scoped, "
                "whether exclusions are defensible, and whether missing evidence blocks external reasoning."
            ),
            required_views=[
                "alert_view",
                "topology_view",
                "timeline_view",
                "history_view",
                "missing_evidence_view",
                "excluded_evidence_view",
            ],
            output_schema=BOUNDARY_REVIEW_SCHEMA,
        ),
        "incident_interpretation": _contract(
            stage="incident_interpretation",
            task=(
                "Interpret only the supplied bounded incident evidence. Cite the seed device, "
                "path, and timeline when present. Keep all remediation human-reviewed and do "
                "not invent devices, links, metrics, commands, or root-cause accuracy claims."
            ),
            required_views=[
                "alert_view",
                "topology_view",
                "timeline_view",
                "history_view",
                "missing_evidence_view",
            ],
            output_schema=INCIDENT_INTERPRETATION_SCHEMA,
        ),
        "output_review": _contract(
            stage="output_review",
            task=(
                "Review the generated interpretation against the same evidence boundary. "
                "Flag missing evidence, unsupported claims, unsafe execution language, and "
                "cases where symptoms are presented as roots."
            ),
            required_views=[
                "alert_view",
                "topology_view",
                "timeline_view",
                "history_view",
                "excluded_evidence_view",
            ],
            output_schema=OUTPUT_REVIEW_SCHEMA,
        ),
        "context_view_summary": _context_view_summary(context_views),
    }


def _contract(
    *,
    stage: str,
    task: str,
    required_views: list[str],
    output_schema: dict[str, Any],
) -> dict[str, Any]:
    return {
        "stage": stage,
        "system_prompt": (
            "You are a bounded NetOps post-alert reasoning assistant. "
            "Use only the supplied evidence views. Preserve deterministic alerting, "
            "keep remediation human-approved, and return strict JSON."
        ),
        "task_prompt": task,
        "required_context_views": required_views,
        "forbidden_behavior": [
            "do not decide whether the deterministic alert exists",
            "do not invent devices, topology links, metrics, or commands",
            "do not claim root-cause accuracy",
            "do not produce executable remediation",
        ],
        "output_schema": output_schema,
    }


def _context_view_summary(context_views: dict[str, Any]) -> dict[str, Any]:
    topology = context_views.get("topology_view") or {}
    timeline = context_views.get("timeline_view") or {}
    incident_window = timeline.get("incident_window") or {}
    history = context_views.get("history_view") or {}
    return {
        "has_seed_device": bool(str(topology.get("src_device_key") or "").strip()),
        "has_path_signature": bool(str(topology.get("path_signature") or "").strip()),
        "timeline_alert_count": int(incident_window.get("alert_count") or 0),
        "recent_similar_1h": int(history.get("recent_similar_1h") or 0),
        "missing_evidence_count": len(context_views.get("missing_evidence_view") or []),
        "excluded_evidence_count": len(context_views.get("excluded_evidence_view") or []),
    }
