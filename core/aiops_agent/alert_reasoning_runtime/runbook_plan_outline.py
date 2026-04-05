import hashlib
from typing import Any


def build_runbook_plan_outline(
    alert: dict[str, Any],
    session_scope: str,
) -> dict[str, Any]:
    excerpt = alert.get("event_excerpt") or {}
    topology = alert.get("topology_context") or {}
    service = str(excerpt.get("service") or topology.get("service") or "unknown")
    path_signature = str(
        topology.get("path_signature")
        or f"{excerpt.get('srcintf') or topology.get('srcintf') or 'unknown'}->{excerpt.get('dstintf') or topology.get('dstintf') or 'unknown'}"
    )
    plan_id = hashlib.sha1(
        f"runbook-outline|{alert.get('alert_id','')}|{session_scope}|{service}|{path_signature}".encode("utf-8"),
        usedforsecurity=False,
    ).hexdigest()
    return {
        "schema_version": 1,
        "plan_id": plan_id,
        "plan_scope": session_scope,
        "plan_status": "outline_only",
        "title": f"Runbook outline for {service} on {path_signature}",
        "applicability": {
            "rule_id": str(alert.get("rule_id") or "unknown"),
            "service": service,
            "path_signature": path_signature,
        },
        "prechecks": [
            "Confirm the triggering tuple, rule, service, and interface path from deterministic evidence.",
            "Check whether the alert aligns with recent changes before choosing any remediation path.",
            "Verify that the target asset and policy intent are still current.",
        ],
        "operator_actions": [
            "Review related evidence and select the most plausible hypothesis before touching any control surface.",
            "Choose only read-only diagnostics by default; do not jump directly to write-path changes.",
            "Prepare rollback prerequisites before any approval-seeking recommendation is surfaced.",
        ],
        "approval_boundary": {
            "approval_required": True,
            "execution_mode": "human_gated",
            "write_path_allowed": False,
        },
        "rollback_guidance": [
            "Document the current policy/path state before any proposed change.",
            "Ensure blast-radius estimation and rollback steps are attached before execution approval is requested.",
        ],
    }
