from core.aiops_agent.alert_reasoning_runtime.phase_context_router import build_phase_context_payload
from core.aiops_agent.evidence_bundle import build_alert_evidence_bundle
from core.aiops_agent.inference_schema import build_alert_inference_request
from core.aiops_agent.provider_routing import build_provider_routing_hint
from tests.core.test_aiops_agent import _config


def _lcore_alert(scenario: str, severity: str = "critical") -> dict:
    return {
        "alert_id": f"lcore-{scenario}",
        "rule_id": "annotated_fault_v1",
        "severity": severity,
        "alert_ts": "2026-04-10T00:00:00+00:00",
        "dimensions": {
            "src_device_key": "CORE-R3",
            "fault_scenario": scenario,
        },
        "metrics": {
            "label_value": scenario,
            "annotation_confidence": 1.0,
        },
        "event_excerpt": {
            "src_device_key": "CORE-R3",
            "service": "lcore-telemetry",
        },
        "topology_context": {
            "src_device_key": "CORE-R3",
            "service": "lcore-telemetry",
            "path_signature": "CORE-R3->CORE-R4->EDGE-MS",
            "neighbor_refs": ["CORE-R2", "CORE-R4"],
            "hop_to_server": "4",
            "hop_to_core": "2",
            "downstream_dependents": "10",
        },
        "device_profile": {
            "src_device_key": "CORE-R3",
            "device_name": "CORE-R3",
            "device_role": "core_router",
        },
    }


def test_topology_subgraph_marks_root_symptom_and_external_llm_gate() -> None:
    evidence = build_alert_evidence_bundle(
        _lcore_alert("routing_misconfiguration"),
        recent_similar_1h=4,
    )
    subgraph = evidence["topology_subgraph"]
    gate = subgraph["llm_invocation_gate"]

    assert subgraph["fault_scenario"] == "routing_misconfiguration"
    assert subgraph["root_candidate_nodes"][0]["node_role"] == "root_candidate"
    assert {node["node_role"] for node in subgraph["symptom_nodes"]} == {"symptom"}
    assert gate["should_invoke_llm"] is True
    assert gate["budget_tier"] == "external_llm"
    assert evidence["evidence_pack_v2"]["summary"]["supporting_count"] >= 3


def test_topology_subgraph_keeps_single_transient_fault_local() -> None:
    evidence = build_alert_evidence_bundle(
        _lcore_alert("transient_fault", severity="warning"),
        recent_similar_1h=0,
    )
    subgraph = evidence["topology_subgraph"]
    gate = subgraph["llm_invocation_gate"]

    assert gate["should_invoke_llm"] is False
    assert gate["budget_tier"] == "template_only"
    assert subgraph["noise_nodes"]
    assert any(node["node_type"] == "self_healing_candidate" for node in subgraph["noise_nodes"])


def test_stage_context_and_routing_carry_subgraph_gate() -> None:
    evidence = build_alert_evidence_bundle(
        _lcore_alert("single_node_failure"),
        recent_similar_1h=2,
    )
    request = build_alert_inference_request(_lcore_alert("single_node_failure"), evidence, provider="template")
    phase_context = build_phase_context_payload("hypothesis_critique", evidence)
    routing = build_provider_routing_hint(_config("/tmp"), request)

    assert phase_context["topology_subgraph"]["root_candidate_nodes"]
    assert phase_context["context"]["topology_subgraph"]["llm_invocation_gate"]["should_invoke_llm"] is True
    assert routing["topology_subgraph_id"] == evidence["topology_subgraph"]["subgraph_id"]
    assert routing["should_invoke_llm"] is True
