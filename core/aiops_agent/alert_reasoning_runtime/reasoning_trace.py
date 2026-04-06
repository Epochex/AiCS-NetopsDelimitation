import hashlib


def build_reasoning_trace_seed(session_id: str, session_scope: str) -> dict[str, object]:
    trace_id = hashlib.sha1(
        f"trace|{session_id}|{session_scope}".encode("utf-8"),
        usedforsecurity=False,
    ).hexdigest()
    return {
        "schema_version": 1,
        "trace_id": trace_id,
        "trace_scope": session_scope,
        "trace_status": "seeded",
        "completed_stages": [],
        "pending_stages": [
            "context_assemble",
            "evidence_pack_build",
            "hypothesis_generate",
            "hypothesis_critique",
            "runbook_retrieve",
            "runbook_draft",
            "runbook_review",
            "suggestion_projection",
        ],
    }
