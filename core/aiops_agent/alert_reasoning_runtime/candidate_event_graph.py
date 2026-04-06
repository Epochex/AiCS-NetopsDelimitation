import hashlib
from typing import Any

from core.aiops_agent.cluster_aggregator import ClusterTrigger


def build_alert_candidate_event_graph(
    alert: dict[str, Any],
    recent_similar_1h: int,
    history_support: dict[str, Any] | None = None,
) -> dict[str, Any]:
    history_support = history_support or {}
    alert_id = str(alert.get("alert_id") or "")
    rule_id = str(alert.get("rule_id") or "unknown")
    scope = "alert"
    graph_id = _hash_id(f"{scope}|{alert_id}|{rule_id}")
    nodes = _build_base_nodes(alert, history_support)
    edges = _build_base_edges(alert, history_support)

    if recent_similar_1h > 0:
        edges.append(
            {
                "edge_id": _hash_id(f"{graph_id}|recent-pattern"),
                "source_node_id": _alert_node_id(alert_id),
                "target_node_id": _pattern_node_id(rule_id),
                "relation_type": "matches_recent_pattern",
                "basis": "rule_id+service recurrence in hot history lookup",
                "deterministic_score": 0.9,
                "evidence_refs": ["historical_context.recent_similar_1h"],
            }
        )
        nodes.append(
            {
                "node_id": _pattern_node_id(rule_id),
                "node_type": "historical_pattern",
                "title": f"pattern:{rule_id}",
                "source_ref": "clickhouse.recent_similar_count",
                "payload_ref": "historical_context.recent_similar_1h",
            }
        )

    return {
        "schema_version": 1,
        "graph_id": graph_id,
        "graph_scope": scope,
        "seed_alert_id": alert_id,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "nodes": nodes,
        "edges": edges,
        "graph_notes": [
            "This is a deterministic candidate graph seeded from an already-confirmed alert.",
            "The graph is intended to support downstream graph-aware retrieval and review-driven reasoning.",
        ],
    }


def build_cluster_candidate_event_graph(
    alert: dict[str, Any],
    trigger: ClusterTrigger,
    recent_similar_1h: int,
    history_support: dict[str, Any] | None = None,
) -> dict[str, Any]:
    history_support = history_support or {}
    alert_id = str(alert.get("alert_id") or "")
    scope = "cluster"
    graph_id = _hash_id(
        f"{scope}|{alert_id}|{trigger.key.rule_id}|{trigger.last_alert_ts}|{trigger.cluster_size}"
    )
    nodes = _build_base_nodes(alert, history_support)
    edges = _build_base_edges(alert, history_support)

    cluster_node_id = _cluster_node_id(graph_id)
    nodes.insert(
        0,
        {
            "node_id": cluster_node_id,
            "node_type": "incident_cluster",
            "title": f"cluster:{trigger.key.rule_id}:{trigger.cluster_size}",
            "source_ref": "core.aiops_agent.cluster_aggregator",
            "payload_ref": "historical_context.cluster_sample_alert_ids",
        },
    )
    edges.insert(
        0,
        {
            "edge_id": _hash_id(f"{graph_id}|cluster-contains-seed"),
            "source_node_id": cluster_node_id,
            "target_node_id": _alert_node_id(alert_id),
            "relation_type": "contains_seed_alert",
            "basis": "cluster aggregator same-key trigger",
            "deterministic_score": 0.95,
            "evidence_refs": ["window_context.sample_alert_ids"],
        },
    )

    for sample_alert_id in trigger.sample_alert_ids:
        if not sample_alert_id or sample_alert_id == alert_id:
            continue
        sample_node_id = _alert_node_id(sample_alert_id)
        nodes.append(
            {
                "node_id": sample_node_id,
                "node_type": "alert_event",
                "title": f"alert:{sample_alert_id}",
                "source_ref": "netops.alerts.v1",
                "payload_ref": "historical_context.cluster_sample_alert_ids",
            }
        )
        edges.append(
            {
                "edge_id": _hash_id(f"{graph_id}|cluster-member|{sample_alert_id}"),
                "source_node_id": cluster_node_id,
                "target_node_id": sample_node_id,
                "relation_type": "contains_related_alert",
                "basis": "cluster window membership",
                "deterministic_score": 0.92,
                "evidence_refs": ["historical_context.cluster_sample_alert_ids"],
            }
        )

    if recent_similar_1h > 0:
        nodes.append(
            {
                "node_id": _pattern_node_id(trigger.key.rule_id),
                "node_type": "historical_pattern",
                "title": f"pattern:{trigger.key.rule_id}",
                "source_ref": "clickhouse.recent_similar_count",
                "payload_ref": "historical_context.recent_similar_1h",
            }
        )
        edges.append(
            {
                "edge_id": _hash_id(f"{graph_id}|cluster-pattern"),
                "source_node_id": cluster_node_id,
                "target_node_id": _pattern_node_id(trigger.key.rule_id),
                "relation_type": "matches_repeating_cluster_pattern",
                "basis": "cluster trigger plus recent-similar lookup",
                "deterministic_score": 0.93,
                "evidence_refs": ["historical_context.recent_similar_1h"],
            }
        )

    return {
        "schema_version": 1,
        "graph_id": graph_id,
        "graph_scope": scope,
        "seed_alert_id": alert_id,
        "cluster_key": {
            "rule_id": trigger.key.rule_id,
            "severity": trigger.key.severity,
            "service": trigger.key.service,
            "src_device_key": trigger.key.src_device_key,
        },
        "node_count": len(nodes),
        "edge_count": len(edges),
        "nodes": nodes,
        "edges": edges,
        "graph_notes": [
            "This is a deterministic cluster candidate graph built from same-key alert aggregation.",
            "The graph is intended to be refined by downstream reasoning rather than generated from free-form model speculation.",
        ],
    }


def _build_base_nodes(alert: dict[str, Any], history_support: dict[str, Any]) -> list[dict[str, Any]]:
    excerpt = alert.get("event_excerpt") or {}
    topology = alert.get("topology_context") or {}
    change_context = alert.get("change_context") or {}
    alert_id = str(alert.get("alert_id") or "")
    rule_id = str(alert.get("rule_id") or "unknown")
    service = str(excerpt.get("service") or topology.get("service") or "unknown")
    device_key = str(excerpt.get("src_device_key") or topology.get("src_device_key") or "unknown")
    path_signature = str(
        topology.get("path_signature")
        or f"{excerpt.get('srcintf') or topology.get('srcintf') or 'unknown'}->{excerpt.get('dstintf') or topology.get('dstintf') or 'unknown'}"
    )
    nodes = [
        {
            "node_id": _alert_node_id(alert_id),
            "node_type": "alert_event",
            "title": f"alert:{alert_id or 'unknown'}",
            "source_ref": "netops.alerts.v1",
            "payload_ref": "alert_ref.alert_id",
        },
        {
            "node_id": _service_node_id(service),
            "node_type": "service",
            "title": f"service:{service}",
            "source_ref": "event_excerpt.service",
            "payload_ref": "topology_context.service",
        },
        {
            "node_id": _device_node_id(device_key),
            "node_type": "device",
            "title": f"device:{device_key}",
            "source_ref": "event_excerpt.src_device_key",
            "payload_ref": "device_context.src_device_key",
        },
        {
            "node_id": _rule_node_id(rule_id),
            "node_type": "alert_rule",
            "title": f"rule:{rule_id}",
            "source_ref": "core.correlator.rules",
            "payload_ref": "rule_context.rule_id",
        },
        {
            "node_id": _path_node_id(path_signature),
            "node_type": "network_path",
            "title": f"path:{path_signature}",
            "source_ref": "topology_context.path_signature",
            "payload_ref": "path_context.path_signature",
        },
    ]

    for change_ref in _normalize_str_list(change_context.get("change_refs"))[:3]:
        nodes.append(
            {
                "node_id": _change_node_id(change_ref),
                "node_type": "change_record",
                "title": f"change:{change_ref}",
                "source_ref": "change_context.change_refs",
                "payload_ref": "historical_context.recent_change_records",
            }
        )

    for sample in (history_support.get("recent_alert_samples") or [])[:2]:
        sample_alert_id = str(sample.get("alert_id") or "")
        if not sample_alert_id or sample_alert_id == alert_id:
            continue
        nodes.append(
            {
                "node_id": _alert_node_id(sample_alert_id),
                "node_type": "historical_alert",
                "title": f"historical-alert:{sample_alert_id}",
                "source_ref": "clickhouse.alert_history",
                "payload_ref": "sample_context.recent_alert_samples",
            }
        )
    return nodes


def _build_base_edges(alert: dict[str, Any], history_support: dict[str, Any]) -> list[dict[str, Any]]:
    excerpt = alert.get("event_excerpt") or {}
    topology = alert.get("topology_context") or {}
    change_context = alert.get("change_context") or {}
    alert_id = str(alert.get("alert_id") or "")
    rule_id = str(alert.get("rule_id") or "unknown")
    service = str(excerpt.get("service") or topology.get("service") or "unknown")
    device_key = str(excerpt.get("src_device_key") or topology.get("src_device_key") or "unknown")
    path_signature = str(
        topology.get("path_signature")
        or f"{excerpt.get('srcintf') or topology.get('srcintf') or 'unknown'}->{excerpt.get('dstintf') or topology.get('dstintf') or 'unknown'}"
    )

    edges = [
        {
            "edge_id": _hash_id(f"{alert_id}|service"),
            "source_node_id": _alert_node_id(alert_id),
            "target_node_id": _service_node_id(service),
            "relation_type": "targets_service",
            "basis": "event_excerpt.service carried by deterministic alert payload",
            "deterministic_score": 1.0,
            "evidence_refs": ["topology_context.service"],
        },
        {
            "edge_id": _hash_id(f"{alert_id}|device"),
            "source_node_id": _alert_node_id(alert_id),
            "target_node_id": _device_node_id(device_key),
            "relation_type": "originates_from_device",
            "basis": "event_excerpt.src_device_key carried by deterministic alert payload",
            "deterministic_score": 1.0,
            "evidence_refs": ["device_context.src_device_key"],
        },
        {
            "edge_id": _hash_id(f"{alert_id}|rule"),
            "source_node_id": _alert_node_id(alert_id),
            "target_node_id": _rule_node_id(rule_id),
            "relation_type": "emitted_by_rule",
            "basis": "correlator rule_id emitted in alert contract",
            "deterministic_score": 1.0,
            "evidence_refs": ["rule_context.rule_id"],
        },
        {
            "edge_id": _hash_id(f"{alert_id}|path"),
            "source_node_id": _alert_node_id(alert_id),
            "target_node_id": _path_node_id(path_signature),
            "relation_type": "traverses_path",
            "basis": "topology_context/path_context path signature",
            "deterministic_score": 0.96,
            "evidence_refs": ["path_context.path_signature"],
        },
    ]

    for change_ref in _normalize_str_list(change_context.get("change_refs"))[:3]:
        edges.append(
            {
                "edge_id": _hash_id(f"{alert_id}|change|{change_ref}"),
                "source_node_id": _alert_node_id(alert_id),
                "target_node_id": _change_node_id(change_ref),
                "relation_type": "temporally_adjacent_to_change",
                "basis": "change_context populated upstream of reasoning stage",
                "deterministic_score": 0.82,
                "evidence_refs": ["change_context.change_refs"],
            }
        )

    for sample in (history_support.get("recent_alert_samples") or [])[:2]:
        sample_alert_id = str(sample.get("alert_id") or "")
        if not sample_alert_id or sample_alert_id == alert_id:
            continue
        edges.append(
            {
                "edge_id": _hash_id(f"{alert_id}|history|{sample_alert_id}"),
                "source_node_id": _alert_node_id(alert_id),
                "target_node_id": _alert_node_id(sample_alert_id),
                "relation_type": "resembles_recent_alert",
                "basis": "clickhouse local history lookup by rule/service/entity slice",
                "deterministic_score": 0.84,
                "evidence_refs": ["sample_context.recent_alert_samples"],
            }
        )
    return edges


def _alert_node_id(alert_id: str) -> str:
    return f"alert::{alert_id or 'unknown'}"


def _cluster_node_id(graph_id: str) -> str:
    return f"cluster::{graph_id}"


def _service_node_id(service: str) -> str:
    return f"service::{service or 'unknown'}"


def _device_node_id(device_key: str) -> str:
    return f"device::{device_key or 'unknown'}"


def _rule_node_id(rule_id: str) -> str:
    return f"rule::{rule_id or 'unknown'}"


def _path_node_id(path_signature: str) -> str:
    return f"path::{path_signature or 'unknown->unknown'}"


def _change_node_id(change_ref: str) -> str:
    return f"change::{change_ref or 'unknown'}"


def _pattern_node_id(rule_id: str) -> str:
    return f"pattern::{rule_id or 'unknown'}"


def _hash_id(seed: str) -> str:
    return hashlib.sha1(seed.encode("utf-8"), usedforsecurity=False).hexdigest()


def _normalize_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]
