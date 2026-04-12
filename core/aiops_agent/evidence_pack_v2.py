import hashlib
from typing import Any

SCHEMA_VERSION = 2
GROUP_ORDER = (
    "direct_evidence",
    "supporting_evidence",
    "contradictory_evidence",
    "missing_evidence",
)
ENTRY_FIELDS = (
    "evidence_id",
    "kind",
    "status",
    "label",
    "value",
    "source_section",
    "source_field",
    "source_ref",
    "rationale",
)
STAGE_EVIDENCE_FIELDS = {
    "hypothesis_generate": GROUP_ORDER,
    "hypothesis_critique": (
        "direct_evidence",
        "supporting_evidence",
        "contradictory_evidence",
    ),
    "runbook_retrieve": (
        "direct_evidence",
        "supporting_evidence",
        "missing_evidence",
    ),
    "runbook_draft": (
        "direct_evidence",
        "supporting_evidence",
        "missing_evidence",
    ),
    "runbook_review": (
        "direct_evidence",
        "contradictory_evidence",
        "missing_evidence",
    ),
}


def build_evidence_pack_v2(evidence_bundle: dict[str, Any]) -> dict[str, Any]:
    bundle_id = str(evidence_bundle.get("bundle_id") or "")
    bundle_scope = str(evidence_bundle.get("bundle_scope") or "")
    alert_ref = evidence_bundle.get("alert_ref") or {}
    topology = evidence_bundle.get("topology_context") or {}
    history = evidence_bundle.get("historical_context") or {}
    rule_context = evidence_bundle.get("rule_context") or {}
    path_context = evidence_bundle.get("path_context") or {}
    policy_context = evidence_bundle.get("policy_context") or {}
    device_context = evidence_bundle.get("device_context") or {}
    change_context = evidence_bundle.get("change_context") or {}
    topology_subgraph = evidence_bundle.get("topology_subgraph") or {}
    invocation_gate = topology_subgraph.get("llm_invocation_gate") or {}

    pack_id = hashlib.sha1(
        f"evidence-pack-v2|{bundle_id}|{bundle_scope}|{alert_ref.get('alert_id') or ''}".encode(
            "utf-8"
        ),
        usedforsecurity=False,
    ).hexdigest()

    direct_evidence = _non_empty_entries(
        [
            _entry(
                kind="direct",
                label="alert.rule_id",
                value=alert_ref.get("rule_id"),
                source_section="alert_ref",
                source_field="rule_id",
                rationale="confirmed rule emitted by deterministic alert path",
            ),
            _entry(
                kind="direct",
                label="alert.severity",
                value=alert_ref.get("severity"),
                source_section="alert_ref",
                source_field="severity",
                rationale="confirmed severity on the alert contract",
            ),
            _entry(
                kind="direct",
                label="topology.service",
                value=topology.get("service"),
                source_section="topology_context",
                source_field="service",
                rationale="service carried by deterministic alert evidence",
            ),
            _entry(
                kind="direct",
                label="topology.src_device_key",
                value=topology.get("src_device_key"),
                source_section="topology_context",
                source_field="src_device_key",
                rationale="source device identity on the current path",
            ),
            _entry(
                kind="direct",
                label="path.path_signature",
                value=path_context.get("path_signature"),
                source_section="path_context",
                source_field="path_signature",
                rationale="normalized path signature for the current slice",
            ),
            _entry(
                kind="direct",
                label="rule.metrics",
                value=rule_context.get("metrics"),
                source_section="rule_context",
                source_field="metrics",
                rationale="rule metrics attached to the alert contract",
            ),
        ]
    )

    supporting_evidence = _non_empty_entries(
        [
            _entry(
                kind="supporting",
                label="history.recent_similar_1h",
                value=history.get("recent_similar_1h"),
                source_section="historical_context",
                source_field="recent_similar_1h",
                rationale="hot-history recurrence count for the same slice",
            ),
            _entry(
                kind="supporting",
                label="history.cluster_size",
                value=history.get("cluster_size"),
                source_section="historical_context",
                source_field="cluster_size",
                rationale="current repeated-pattern spread count",
            ),
            _entry(
                kind="supporting",
                label="topology.neighbor_refs",
                value=topology.get("neighbor_refs"),
                source_section="topology_context",
                source_field="neighbor_refs",
                rationale="topology neighbors around the current path",
            ),
            _entry(
                kind="supporting",
                label="history.recent_alert_samples",
                value=history.get("recent_alert_samples"),
                source_section="historical_context",
                source_field="recent_alert_samples",
                rationale="recent samples that support recurrence or concentration",
            ),
            _entry(
                kind="supporting",
                label="change.change_refs",
                value=change_context.get("change_refs"),
                source_section="change_context",
                source_field="change_refs",
                rationale="recent change references aligned with the current slice",
            ),
            _entry(
                kind="supporting",
                label="device.known_services",
                value=device_context.get("known_services"),
                source_section="device_context",
                source_field="known_services",
                rationale="device profile that confirms the current service is expected",
            ),
            _entry(
                kind="supporting",
                label="policy.recent_policy_hits",
                value=policy_context.get("recent_policy_hits"),
                source_section="policy_context",
                source_field="recent_policy_hits",
                rationale="policy history attached to this service/path combination",
            ),
            _entry(
                kind="supporting",
                label="topology.subgraph_root_candidates",
                value=[
                    item.get("node_id")
                    for item in topology_subgraph.get("root_candidate_nodes") or []
                    if isinstance(item, dict)
                ],
                source_section="topology_subgraph",
                source_field="root_candidate_nodes",
                rationale="minimal topology-aware subgraph root candidates selected before LLM invocation",
            ),
            _entry(
                kind="supporting",
                label="topology.llm_invocation_gate",
                value=invocation_gate.get("budget_tier"),
                source_section="topology_subgraph",
                source_field="llm_invocation_gate",
                rationale="selective invocation decision for reducing low-value LLM calls",
            ),
        ]
    )

    contradictory_evidence = _non_empty_entries(
        [
            _entry(
                kind="contradictory",
                label="history.no_recent_recurrence",
                value="recent_similar_1h=0"
                if int(history.get("recent_similar_1h") or 0) == 0
                else "",
                source_section="historical_context",
                source_field="recent_similar_1h",
                rationale="weakens repeated-pattern claims",
            ),
            _entry(
                kind="contradictory",
                label="history.cluster_gate_not_reached",
                value=f"cluster_size={int(history.get('cluster_size') or 0)}"
                if int(history.get("cluster_size") or 0) <= 1
                else "",
                source_section="historical_context",
                source_field="cluster_size",
                rationale="shows the current slice has not widened into a cluster yet",
            ),
            _entry(
                kind="contradictory",
                label="change.no_change_signal",
                value="suspected_change=false"
                if not bool(change_context.get("suspected_change"))
                else "",
                source_section="change_context",
                source_field="suspected_change",
                rationale="weakens change-driven root-cause claims",
            ),
            _entry(
                kind="contradictory",
                label="topology.low_value_llm_gate",
                value=invocation_gate.get("reason")
                if invocation_gate and not bool(invocation_gate.get("should_invoke_llm"))
                else "",
                source_section="topology_subgraph",
                source_field="llm_invocation_gate",
                rationale="marks cases where topology evidence is too thin for external LLM escalation",
            ),
        ]
    )

    missing_evidence = _non_empty_entries(
        [
            _missing("device.device_name", "device_context", "device_name", device_context.get("device_name")),
            _missing("topology.srcip", "topology_context", "srcip", topology.get("srcip")),
            _missing("topology.dstip", "topology_context", "dstip", topology.get("dstip")),
            _missing(
                "topology.neighbor_refs",
                "topology_context",
                "neighbor_refs",
                topology.get("neighbor_refs"),
            ),
            _missing(
                "topology.topology_subgraph",
                "topology_subgraph",
                "selected_node_ids",
                topology_subgraph.get("selected_node_ids"),
            ),
            _missing(
                "history.recent_alert_samples",
                "historical_context",
                "recent_alert_samples",
                history.get("recent_alert_samples"),
            ),
            _missing(
                "change.change_refs",
                "change_context",
                "change_refs",
                change_context.get("change_refs"),
            ),
        ]
    )

    freshness = {
        "observed_at": str(evidence_bundle.get("bundle_ts") or ""),
        "sections": [
            _freshness("alert_ref", "live_bundle_window", evidence_bundle.get("bundle_ts")),
            _freshness("topology_context", "live_bundle_window", evidence_bundle.get("bundle_ts")),
            _freshness(
                "historical_context",
                "hot_lookup_window" if int(history.get("recent_similar_1h") or 0) > 0 else "no_recent_support",
                evidence_bundle.get("bundle_ts"),
            ),
            _freshness(
                "change_context",
                "recent_change_window"
                if bool(change_context.get("suspected_change")) or _has_value(change_context.get("change_refs"))
                else "not_attached",
                evidence_bundle.get("bundle_ts"),
            ),
        ],
    }

    source_reliability = {
        "sections": [
            _reliability("alert_ref", "deterministic_alert_contract", 0.99),
            _reliability("rule_context", "deterministic_rule_output", 0.98),
            _reliability("topology_context", "normalized_runtime_context", 0.88),
            _reliability("device_context", "normalized_device_profile", 0.84),
            _reliability("historical_context", "clickhouse_hot_history_lookup", 0.8),
            _reliability("change_context", "bounded_change_heuristic", 0.74),
        ],
    }

    lineage = [
        _lineage("alert_ref", "core.correlator", "netops.alerts.v1"),
        _lineage("rule_context", "core.correlator", "netops.alerts.v1"),
        _lineage("historical_context", "core.alerts_store", "clickhouse"),
        _lineage("topology_context", "core.aiops_agent.evidence_bundle", "alert bundle assembly"),
        _lineage("device_context", "core.aiops_agent.evidence_bundle", "device profile assembly"),
        _lineage("change_context", "core.aiops_agent.evidence_bundle", "change context assembly"),
    ]

    return {
        "schema_version": SCHEMA_VERSION,
        "pack_id": pack_id,
        "pack_scope": bundle_scope,
        "group_order": list(GROUP_ORDER),
        "entry_fields": list(ENTRY_FIELDS),
        "alert_ref": alert_ref,
        "direct_evidence": direct_evidence,
        "supporting_evidence": supporting_evidence,
        "contradictory_evidence": contradictory_evidence,
        "missing_evidence": missing_evidence,
        "freshness": freshness,
        "source_reliability": source_reliability,
        "lineage": lineage,
        "summary": {
            "direct_count": len(direct_evidence),
            "supporting_count": len(supporting_evidence),
            "contradictory_count": len(contradictory_evidence),
            "missing_count": len(missing_evidence),
        },
    }


def select_evidence_pack_v2_view(stage: str, evidence_pack_v2: dict[str, Any]) -> dict[str, Any]:
    normalized_stage = str(stage or "").strip().lower()
    base = {
        "schema_version": evidence_pack_v2.get("schema_version") or SCHEMA_VERSION,
        "pack_id": evidence_pack_v2.get("pack_id") or "",
        "pack_scope": evidence_pack_v2.get("pack_scope") or "",
        "group_order": evidence_pack_v2.get("group_order") or list(GROUP_ORDER),
        "entry_fields": evidence_pack_v2.get("entry_fields") or list(ENTRY_FIELDS),
        "alert_ref": evidence_pack_v2.get("alert_ref") or {},
        "freshness": evidence_pack_v2.get("freshness") or {},
        "source_reliability": evidence_pack_v2.get("source_reliability") or {},
        "lineage": evidence_pack_v2.get("lineage") or [],
        "summary": evidence_pack_v2.get("summary") or {},
    }
    allowed_groups = STAGE_EVIDENCE_FIELDS.get(normalized_stage, ("direct_evidence",))
    for group_name in allowed_groups:
        base[group_name] = evidence_pack_v2.get(group_name) or []
    return base


def _entry(
    *,
    kind: str,
    label: str,
    value: Any,
    source_section: str,
    source_field: str,
    rationale: str,
) -> dict[str, Any]:
    source_ref = f"{source_section}.{source_field}"
    return {
        "evidence_id": hashlib.sha1(
            f"{kind}|{source_section}|{source_field}|{label}".encode("utf-8"),
            usedforsecurity=False,
        ).hexdigest(),
        "kind": kind,
        "status": "missing" if kind == "missing" else "observed",
        "label": label,
        "value": value,
        "source_section": source_section,
        "source_field": source_field,
        "source_ref": source_ref,
        "rationale": rationale,
    }


def _missing(label: str, source_section: str, source_field: str, value: Any) -> dict[str, Any]:
    return _entry(
        kind="missing",
        label=label,
        value="missing" if not _has_value(value) else "",
        source_section=source_section,
        source_field=source_field,
        rationale="required context is absent from the current evidence bundle",
    )


def _freshness(source_section: str, state: str, observed_at: Any) -> dict[str, Any]:
    return {
        "source_section": source_section,
        "freshness_state": state,
        "observed_at": str(observed_at or ""),
    }


def _reliability(source_section: str, source_kind: str, score: float) -> dict[str, Any]:
    return {
        "source_section": source_section,
        "source_kind": source_kind,
        "score": round(float(score), 2),
    }


def _lineage(source_section: str, upstream_component: str, source_ref: str) -> dict[str, str]:
    return {
        "source_section": source_section,
        "upstream_component": upstream_component,
        "source_ref": source_ref,
    }


def _non_empty_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [entry for entry in entries if _has_value(entry.get("value"))]


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return len(value) > 0
    if isinstance(value, dict):
        return len(value) > 0
    return True
