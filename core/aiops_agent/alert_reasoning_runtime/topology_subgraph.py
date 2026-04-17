import hashlib
from typing import Any

from core.aiops_agent.alert_reasoning_runtime.self_healing_policy import assess_self_healing_decision


HIGH_VALUE_SCENARIOS = {
    "induced_fault",
    "single_link_failure",
    "multiple_link_failure",
    "node_failure",
    "multiple_nodes_failures",
    "single_node_failure",
    "routing_misconfiguration",
    "misconfiguration",
    "line_card_failure",
    "icmp_blocked_firewall",
    "snmp_agent_failure",
}
SELF_HEALING_SCENARIOS = {
    "transient_fault",
    "transient_healthy",
}


def extract_topology_aware_subgraph(
    *,
    alert: dict[str, Any],
    candidate_event_graph: dict[str, Any],
    recent_similar_1h: int,
    history_support: dict[str, Any] | None = None,
    cluster_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    history_support = history_support or {}
    cluster_context = cluster_context or {}
    alert_id = str(alert.get("alert_id") or "")
    topology = alert.get("topology_context") or {}
    excerpt = alert.get("event_excerpt") or {}
    dimensions = alert.get("dimensions") or {}
    metrics = alert.get("metrics") or {}
    device_profile = alert.get("device_profile") or {}
    severity = str(alert.get("severity") or "unknown").lower()
    scenario = str(
        dimensions.get("fault_scenario")
        or metrics.get("label_value")
        or metrics.get("scenario")
        or "unknown"
    ).strip().lower()
    device_key = _first_text(
        excerpt.get("src_device_key"),
        topology.get("src_device_key"),
        device_profile.get("src_device_key"),
        dimensions.get("src_device_key"),
        "unknown",
    )
    path_signature = _path_signature(excerpt, topology)
    neighbor_refs = _string_list(topology.get("neighbor_refs"))
    recent_samples = history_support.get("recent_alert_samples") or []
    cluster_size = int(cluster_context.get("cluster_size") or 1)

    root_score, reasons = _root_score(
        severity=severity,
        scenario=scenario,
        recent_similar_1h=recent_similar_1h,
        cluster_size=cluster_size,
        neighbor_refs=neighbor_refs,
        topology=topology,
    )
    self_healing_decision = assess_self_healing_decision(
        alert=alert,
        recent_similar_1h=recent_similar_1h,
        incident_window=_cluster_as_window(cluster_context),
    )
    root_node = _node(
        node_id=f"device::{device_key}",
        node_role="root_candidate",
        node_type="device",
        title=f"device:{device_key}",
        score=root_score,
        evidence_refs=["topology_context.src_device_key", "device_context.src_device_key"],
        rationale="seed device selected from the confirmed alert slice",
    )
    path_node = _node(
        node_id=f"path::{path_signature}",
        node_role="symptom",
        node_type="network_path",
        title=f"path:{path_signature}",
        score=0.7,
        evidence_refs=["path_context.path_signature"],
        rationale="path-level symptom attached to the alert",
    )

    symptom_nodes = [path_node]
    for neighbor in neighbor_refs[:4]:
        symptom_nodes.append(
            _node(
                node_id=f"device::{neighbor}",
                node_role="symptom",
                node_type="topology_neighbor",
                title=f"neighbor:{neighbor}",
                score=0.58,
                evidence_refs=["topology_context.neighbor_refs"],
                rationale="neighbor retained because it is directly adjacent to the seed slice",
            )
        )

    for sample in recent_samples[:2]:
        sample_id = str(sample.get("alert_id") or "")
        if not sample_id or sample_id == alert_id:
            continue
        symptom_nodes.append(
            _node(
                node_id=f"alert::{sample_id}",
                node_role="symptom",
                node_type="historical_alert",
                title=f"historical-alert:{sample_id}",
                score=0.52,
                evidence_refs=["historical_context.recent_alert_samples"],
                rationale="recent similar alert retained as temporal symptom evidence",
            )
        )

    noise_nodes = _noise_nodes(
        alert_id=alert_id,
        scenario=scenario,
        recent_similar_1h=recent_similar_1h,
        cluster_size=cluster_size,
        neighbor_refs=neighbor_refs,
    )
    selected_nodes = [root_node] + symptom_nodes
    all_nodes = _dedupe_nodes(selected_nodes + noise_nodes)
    edges = _subgraph_edges(root_node, selected_nodes[1:], candidate_event_graph)
    should_invoke, gate_reason = _should_invoke_llm(
        score=root_score,
        scenario=scenario,
        cluster_size=cluster_size,
        severity=severity,
    )
    subgraph_id = _hash_id(
        f"topology-subgraph|{alert_id}|{candidate_event_graph.get('graph_id') or ''}|{scenario}|{cluster_size}"
    )
    return {
        "schema_version": 1,
        "subgraph_id": subgraph_id,
        "extraction_strategy": "topology_aware_minimal_incident_subgraph",
        "source_graph_id": candidate_event_graph.get("graph_id") or "",
        "seed_alert_id": alert_id,
        "fault_scenario": scenario,
        "node_count": len(all_nodes),
        "edge_count": len(edges),
        "selected_node_count": len(selected_nodes),
        "noise_node_count": len(noise_nodes),
        "root_candidate_nodes": [root_node],
        "symptom_nodes": symptom_nodes,
        "noise_nodes": noise_nodes,
        "selected_node_ids": [node["node_id"] for node in selected_nodes],
        "selected_edge_ids": [edge["edge_id"] for edge in edges],
        "nodes": all_nodes,
        "edges": edges,
        "llm_invocation_gate": {
            "policy": "topology_aware_selective_invocation",
            "should_invoke_llm": should_invoke,
            "decision_score": root_score,
            "budget_tier": "external_llm" if should_invoke else "template_only",
            "reason": gate_reason,
            "score_reasons": reasons,
            "self_healing_decision": self_healing_decision,
        },
    }


def summarize_topology_subgraph(subgraph: dict[str, Any]) -> dict[str, Any]:
    gate = subgraph.get("llm_invocation_gate") or {}
    return {
        "subgraph_id": subgraph.get("subgraph_id") or "",
        "extraction_strategy": subgraph.get("extraction_strategy") or "",
        "fault_scenario": subgraph.get("fault_scenario") or "",
        "selected_node_count": int(subgraph.get("selected_node_count") or 0),
        "noise_node_count": int(subgraph.get("noise_node_count") or 0),
        "root_candidate_nodes": _compact_nodes(subgraph.get("root_candidate_nodes") or []),
        "symptom_nodes": _compact_nodes(subgraph.get("symptom_nodes") or []),
        "noise_nodes": _compact_nodes(subgraph.get("noise_nodes") or []),
        "llm_invocation_gate": {
            "should_invoke_llm": bool(gate.get("should_invoke_llm")),
            "decision_score": float(gate.get("decision_score") or 0.0),
            "budget_tier": str(gate.get("budget_tier") or ""),
            "reason": str(gate.get("reason") or ""),
        },
    }


def _root_score(
    *,
    severity: str,
    scenario: str,
    recent_similar_1h: int,
    cluster_size: int,
    neighbor_refs: list[str],
    topology: dict[str, Any],
) -> tuple[float, list[str]]:
    score = 0.35
    reasons = ["confirmed alert seed"]
    if severity == "critical":
        score += 0.18
        reasons.append("critical severity")
    if scenario in HIGH_VALUE_SCENARIOS:
        score += 0.25
        reasons.append(f"high-value scenario:{scenario}")
    if scenario in SELF_HEALING_SCENARIOS:
        score -= 0.22
        reasons.append(f"self-healing candidate:{scenario}")
    if cluster_size >= 3:
        score += 0.18
        reasons.append(f"cluster_size={cluster_size}")
    if recent_similar_1h > 0:
        score += 0.08
        reasons.append(f"recent_similar_1h={recent_similar_1h}")
    if neighbor_refs:
        score += 0.08
        reasons.append("topology neighbors present")
    if _has_topology_depth(topology):
        score += 0.06
        reasons.append("topology depth metadata present")
    return round(min(max(score, 0.05), 0.99), 3), reasons


def _should_invoke_llm(
    *,
    score: float,
    scenario: str,
    cluster_size: int,
    severity: str,
) -> tuple[bool, str]:
    if scenario in SELF_HEALING_SCENARIOS and cluster_size < 3:
        return False, "single-slice transient fault is handled by bounded template path"
    if score >= 0.65:
        return True, "root-candidate subgraph has enough topology or recurrence evidence"
    if severity == "critical" and scenario not in SELF_HEALING_SCENARIOS:
        return True, "critical alert retained for external reasoning"
    return False, "low-evidence slice kept local to reduce LLM budget"


def _noise_nodes(
    *,
    alert_id: str,
    scenario: str,
    recent_similar_1h: int,
    cluster_size: int,
    neighbor_refs: list[str],
) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    if recent_similar_1h == 0 and cluster_size <= 1:
        nodes.append(
            _node(
                node_id=f"noise::single-slice::{alert_id or 'unknown'}",
                node_role="noise",
                node_type="single_slice_low_recurrence",
                title="noise:single-slice-low-recurrence",
                score=0.2,
                evidence_refs=["historical_context.recent_similar_1h", "historical_context.cluster_size"],
                rationale="no recurrence or cluster support is present",
            )
        )
    if scenario in SELF_HEALING_SCENARIOS:
        nodes.append(
            _node(
                node_id=f"noise::self-healing::{scenario}",
                node_role="noise",
                node_type="self_healing_candidate",
                title=f"noise:{scenario}",
                score=0.18,
                evidence_refs=["rule_context.metrics.label_value", "alert_ref.rule_id"],
                rationale="transient label is likely to self-heal unless it spreads",
            )
        )
    if not neighbor_refs:
        nodes.append(
            _node(
                node_id=f"noise::missing-neighbor::{alert_id or 'unknown'}",
                node_role="noise",
                node_type="missing_topology_neighbor",
                title="noise:missing-neighbor-context",
                score=0.24,
                evidence_refs=["topology_context.neighbor_refs"],
                rationale="no explicit neighbor reference is available for propagation reasoning",
            )
        )
    return nodes


def _subgraph_edges(
    root_node: dict[str, Any],
    symptom_nodes: list[dict[str, Any]],
    candidate_event_graph: dict[str, Any],
) -> list[dict[str, Any]]:
    root_id = root_node["node_id"]
    edges = []
    for node in symptom_nodes:
        edges.append(
            {
                "edge_id": _hash_id(f"{root_id}|{node['node_id']}"),
                "source_node_id": root_id,
                "target_node_id": node["node_id"],
                "relation_type": "explains_symptom",
                "basis": "minimal topology-aware subgraph extraction",
                "deterministic_score": round(min(root_node["score"], node["score"]), 3),
                "evidence_refs": sorted(set(root_node["evidence_refs"] + node["evidence_refs"])),
            }
        )
    for edge in candidate_event_graph.get("edges") or []:
        if not isinstance(edge, dict):
            continue
        source = str(edge.get("source_node_id") or "")
        target = str(edge.get("target_node_id") or "")
        if source == root_id or target == root_id:
            edges.append(edge)
    return _dedupe_edges(edges)


def _node(
    *,
    node_id: str,
    node_role: str,
    node_type: str,
    title: str,
    score: float,
    evidence_refs: list[str],
    rationale: str,
) -> dict[str, Any]:
    return {
        "node_id": node_id,
        "node_role": node_role,
        "node_type": node_type,
        "title": title,
        "score": round(score, 3),
        "evidence_refs": evidence_refs,
        "rationale": rationale,
    }


def _compact_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact = []
    for node in nodes[:4]:
        compact.append(
            {
                "node_id": str(node.get("node_id") or ""),
                "node_role": str(node.get("node_role") or ""),
                "node_type": str(node.get("node_type") or ""),
                "score": float(node.get("score") or 0.0),
            }
        )
    return compact


def _dedupe_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped = []
    seen: set[str] = set()
    for node in nodes:
        node_id = str(node.get("node_id") or "")
        if not node_id or node_id in seen:
            continue
        seen.add(node_id)
        deduped.append(node)
    return deduped


def _dedupe_edges(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped = []
    seen: set[str] = set()
    for edge in edges:
        edge_id = str(edge.get("edge_id") or "")
        if not edge_id or edge_id in seen:
            continue
        seen.add(edge_id)
        deduped.append(edge)
    return deduped


def _path_signature(excerpt: dict[str, Any], topology: dict[str, Any]) -> str:
    path = str(topology.get("path_signature") or "").strip()
    if path:
        return path
    srcintf = str(excerpt.get("srcintf") or topology.get("srcintf") or "unknown").strip()
    dstintf = str(excerpt.get("dstintf") or topology.get("dstintf") or "unknown").strip()
    return f"{srcintf or 'unknown'}->{dstintf or 'unknown'}"


def _has_topology_depth(topology: dict[str, Any]) -> bool:
    for key in ("hop_to_server", "hop_to_core", "downstream_dependents"):
        value = topology.get(key)
        if str(value or "").strip():
            return True
    return False


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    items = []
    seen: set[str] = set()
    for item in value:
        text = str(item or "").strip()
        if text and text not in seen:
            seen.add(text)
            items.append(text)
    return items


def _hash_id(seed: str) -> str:
    return hashlib.sha1(seed.encode("utf-8"), usedforsecurity=False).hexdigest()


def _cluster_as_window(cluster_context: dict[str, Any]) -> dict[str, Any] | None:
    if not cluster_context:
        return None
    cluster_size = int(cluster_context.get("cluster_size") or 1)
    device = str(cluster_context.get("src_device_key") or "")
    return {
        "alert_count": cluster_size,
        "device_count": 1 if device else 0,
        "devices": [device] if device else [],
        "recurrence_pressure": cluster_size >= 3,
        "topology_pressure": False,
        "multi_device_spread": False,
        "max_downstream_dependents": 0,
    }
