import json
from dataclasses import replace

from core.aiops_agent.app_config import AgentConfig
from core.aiops_agent.cluster_aggregator import ClusterKey, ClusterTrigger
from core.aiops_agent.alert_reasoning_runtime.phase_context_router import build_phase_context_payload
from core.aiops_agent.context_lookup import recent_similar_count
from core.aiops_agent.evidence_bundle import build_alert_evidence_bundle, build_cluster_evidence_bundle
from core.aiops_agent.inference_queue import InMemoryInferenceQueue
from core.aiops_agent.inference_schema import build_alert_inference_request, build_cluster_inference_request
from core.aiops_agent.inference_worker import InferenceWorker
from core.aiops_agent.providers import TemplateProvider, build_provider
import core.aiops_agent.providers as providers_module
from core.aiops_agent.reasoning_stage_requests import build_reasoning_stage_requests
from core.aiops_agent.service import commit_if_needed, run_agent_loop
from core.aiops_agent.suggestion_engine import (
    build_alert_pipeline_suggestion,
    build_pipeline_suggestion,
)


class _Result:
    def __init__(self, first_item: int) -> None:
        self.first_item = first_item


class _ClientOK:
    def query(self, _sql: str, parameters: dict) -> _Result:
        assert parameters["rule_id"] == "deny_burst_v1"
        assert parameters["service"] == "udp/3702"
        return _Result(23)


class _ClientDict:
    def query(self, _sql: str, parameters: dict) -> _Result:
        assert parameters["rule_id"] == "deny_burst_v1"
        assert parameters["service"] == "udp/3702"
        return _Result({"count()": 17})


class _ClientFail:
    def query(self, _sql: str, parameters: dict) -> _Result:
        raise RuntimeError("query failed")


class _ConsumerOK:
    def __init__(self) -> None:
        self.committed = 0

    def commit(self) -> None:
        self.committed += 1


class _ConsumerFail:
    def commit(self) -> None:
        raise RuntimeError("commit failed")


class _Message:
    def __init__(self, value: str) -> None:
        self.value = value


class _IterableConsumer(_ConsumerOK):
    def __init__(self, payloads: list[dict]) -> None:
        super().__init__()
        self._messages = [_Message(json.dumps(payload, ensure_ascii=True)) for payload in payloads]

    def __iter__(self):
        return iter(self._messages)


class _ProducerFuture:
    def get(self, timeout: int = 30) -> None:
        return None


class _Producer:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    def send(self, topic: str, key: bytes, value: str) -> _ProducerFuture:
        self.sent.append(
            {
                "topic": topic,
                "key": key.decode("utf-8"),
                "payload": json.loads(value),
            }
        )
        return _ProducerFuture()


class _HTTPResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload, ensure_ascii=True).encode("utf-8")


def _config(output_dir: str, cluster_min_alerts: int = 3) -> AgentConfig:
    return AgentConfig(
        bootstrap_servers="localhost:9092",
        topic_alerts="netops.alerts.v1",
        topic_suggestions="netops.aiops.suggestions.v1",
        consumer_group="core-aiops-agent-v1",
        auto_offset_reset="latest",
        min_severity="warning",
        output_dir=output_dir,
        log_interval_sec=3600,
        clickhouse_enabled=False,
        clickhouse_host="",
        clickhouse_http_port=8123,
        clickhouse_user="default",
        clickhouse_password="",
        clickhouse_db="netops",
        clickhouse_alerts_table="alerts",
        cluster_window_sec=600,
        cluster_min_alerts=cluster_min_alerts,
        cluster_cooldown_sec=300,
        provider="template",
        provider_endpoint_url="",
        provider_api_key="",
        provider_model="generic-aiops",
        provider_timeout_sec=30,
        provider_compute_target="local_cpu",
        provider_max_parallelism=1,
    )


def test_recent_similar_returns_count_when_query_ok() -> None:
    count = recent_similar_count(_ClientOK(), "netops", "alerts", "deny_burst_v1", "udp/3702")
    assert count == 23


def test_recent_similar_accepts_dict_like_first_item() -> None:
    count = recent_similar_count(_ClientDict(), "netops", "alerts", "deny_burst_v1", "udp/3702")
    assert count == 17


def test_recent_similar_returns_zero_on_query_error() -> None:
    count = recent_similar_count(_ClientFail(), "netops", "alerts", "deny_burst_v1", "udp/3702")
    assert count == 0


def test_evidence_bundle_and_inference_request_capture_pipeline_context() -> None:
    alert = {
        "alert_id": "a-42",
        "rule_id": "deny_burst_v1",
        "severity": "warning",
        "metrics": {"deny_count": 12},
        "dimensions": {"src_device_key": "dev-1"},
        "event_excerpt": {
            "service": "udp/3702",
            "srcip": "192.168.1.10",
            "dstip": "239.255.255.250",
            "src_device_key": "dev-1",
        },
        "topology_context": {"site": "lab-a", "zone": "edge"},
        "device_profile": {"device_role": "camera", "vendor": "hikvision", "asset_tags": ["iot", "lab"]},
        "change_context": {"suspected_change": True, "change_window_min": 30, "change_refs": ["chg-1"]},
    }
    trigger = ClusterTrigger(
        key=ClusterKey(rule_id="deny_burst_v1", severity="warning", service="udp/3702", src_device_key="dev-1"),
        cluster_size=4,
        first_alert_ts="2026-03-09T00:00:00+00:00",
        last_alert_ts="2026-03-09T00:00:59+00:00",
        window_sec=300,
        sample_alert_ids=["a-1", "a-2", "a-3", "a-4"],
    )
    evidence = build_cluster_evidence_bundle(alert, trigger, recent_similar_1h=18)
    req = build_cluster_inference_request(alert, trigger, evidence, provider="template")
    assert evidence["topology_context"]["site"] == "lab-a"
    assert evidence["historical_context"]["recent_similar_1h"] == 18
    assert evidence["device_context"]["device_role"] == "camera"
    assert evidence["change_context"]["suspected_change"] is True
    assert req.request_kind == "cluster_triage"
    assert req.evidence_bundle["bundle_scope"] == "cluster"
    assert req.expected_response_schema["confidence_label"] == "low|medium|high"


def test_alert_evidence_bundle_and_inference_request_capture_alert_scope_context() -> None:
    alert = {
        "alert_id": "a-11",
        "rule_id": "deny_burst_v1",
        "severity": "warning",
        "metrics": {"deny_count": 5},
        "dimensions": {"src_device_key": "dev-1"},
        "event_excerpt": {
            "service": "Dahua SDK",
            "srcip": "192.168.1.20",
            "dstip": "192.168.30.35",
            "src_device_key": "d4:43:0e:1a:c5:88",
        },
        "topology_context": {"site": "lab-a", "zone": "edge"},
        "device_profile": {"device_role": "camera", "vendor": "dahua", "srcmac": "d4:43:0e:1a:c5:88"},
        "change_context": {"suspected_change": True, "score": 30, "change_refs": ["crscore:30"]},
    }
    evidence = build_alert_evidence_bundle(alert, recent_similar_1h=7)
    req = build_alert_inference_request(alert, evidence, provider="template")
    assert evidence["bundle_scope"] == "alert"
    assert evidence["topology_context"]["service"] == "Dahua SDK"
    assert evidence["historical_context"]["recent_similar_1h"] == 7
    assert evidence["device_context"]["vendor"] == "dahua"
    assert evidence["change_context"]["score"] == 30
    assert evidence["evidence_pack_v2"]["schema_version"] == 2
    assert evidence["evidence_pack_v2"]["group_order"] == [
        "direct_evidence",
        "supporting_evidence",
        "contradictory_evidence",
        "missing_evidence",
    ]
    assert "source_ref" in evidence["evidence_pack_v2"]["entry_fields"]
    assert evidence["evidence_pack_v2"]["summary"]["direct_count"] >= 5
    assert evidence["evidence_pack_v2"]["summary"]["supporting_count"] >= 1
    assert evidence["reasoning_runtime_seed"]["candidate_event_graph"]["graph_scope"] == "alert"
    assert evidence["reasoning_runtime_seed"]["investigation_session"]["session_scope"] == "alert"
    assert req.request_kind == "alert_triage"
    assert req.suggestion_scope == "alert"


def test_template_provider_worker_pipeline_builds_structured_suggestion() -> None:
    alert = {
        "alert_id": "a-77",
        "event_excerpt": {
            "service": "udp/3702",
            "src_device_key": "dev-1",
        },
    }
    trigger = ClusterTrigger(
        key=ClusterKey(rule_id="deny_burst_v1", severity="warning", service="udp/3702", src_device_key="dev-1"),
        cluster_size=5,
        first_alert_ts="2026-03-09T00:00:00+00:00",
        last_alert_ts="2026-03-09T00:00:59+00:00",
        window_sec=300,
        sample_alert_ids=["a-1", "a-2", "a-3", "a-4", "a-5"],
    )
    evidence = build_cluster_evidence_bundle(alert, trigger, recent_similar_1h=25)
    req = build_cluster_inference_request(alert, trigger, evidence, provider="template")
    queue = InMemoryInferenceQueue()
    queue.enqueue(req)
    result = InferenceWorker(TemplateProvider()).run_once(queue)
    assert result is not None
    suggestion = build_pipeline_suggestion(alert, trigger, evidence, req, result)
    assert suggestion["schema_version"] == 2
    assert suggestion["context"]["recent_similar_1h"] == 25
    assert suggestion["inference"]["provider_name"] == "template"
    assert suggestion["confidence"] >= 0.75


def test_gpu_http_provider_respects_topology_template_only_gate(monkeypatch) -> None:
    alert = {
        "alert_id": "lcore-transient-1",
        "rule_id": "annotated_fault_v1",
        "severity": "warning",
        "dimensions": {
            "src_device_key": "CORE-R4",
            "fault_scenario": "transient_fault",
        },
        "metrics": {
            "label_value": "transient_fault",
        },
        "event_excerpt": {
            "src_device_key": "CORE-R4",
            "service": "lcore-telemetry",
        },
        "topology_context": {
            "src_device_key": "CORE-R4",
            "service": "lcore-telemetry",
            "path_signature": "CORE-R4|hop_core=3|hop_server=5|path_up=1",
            "hop_to_core": "3",
            "hop_to_server": "5",
            "downstream_dependents": "4",
            "path_up": "1",
        },
        "device_profile": {
            "src_device_key": "CORE-R4",
            "device_name": "CORE-R4",
        },
    }
    evidence = build_alert_evidence_bundle(alert, recent_similar_1h=0)
    gate = evidence["topology_subgraph"]["llm_invocation_gate"]
    assert gate["should_invoke_llm"] is False
    assert gate["budget_tier"] == "template_only"

    config = replace(
        _config("/tmp"),
        provider="gpu_http",
        provider_endpoint_url="http://127.0.0.1:9/infer",
        provider_model="glm-fast",
        provider_compute_target="external_gpu_service",
    )
    provider = build_provider(config)
    req = build_alert_inference_request(alert, evidence, provider=provider.name)

    def fail_urlopen(*_args, **_kwargs):
        raise AssertionError("topology-gated template_only alert must not call the GPU endpoint")

    monkeypatch.setattr(providers_module.request, "urlopen", fail_urlopen)
    result = provider.infer(req)

    assert result.provider_name == "gpu_http"
    assert result.provider_kind == "topology_gate_template_fallback"
    assert result.raw_response["external_provider_skipped"] is True
    assert result.raw_response["routing"]["should_invoke_llm"] is False


def test_gpu_http_provider_calls_endpoint_for_high_value_topology_gate(monkeypatch) -> None:
    alert = {
        "alert_id": "lcore-root-1",
        "rule_id": "annotated_fault_v1",
        "severity": "critical",
        "dimensions": {
            "src_device_key": "CORE-R4",
            "fault_scenario": "single_node_failure",
        },
        "metrics": {
            "label_value": "single_node_failure",
        },
        "event_excerpt": {
            "src_device_key": "CORE-R4",
            "service": "lcore-telemetry",
        },
        "topology_context": {
            "src_device_key": "CORE-R4",
            "service": "lcore-telemetry",
            "path_signature": "CORE-R4|hop_core=3|hop_server=5|path_up=1",
            "neighbor_refs": ["CORE-R3", "CORE-R5"],
            "hop_to_core": "3",
            "hop_to_server": "5",
            "downstream_dependents": "4",
            "path_up": "1",
        },
        "device_profile": {
            "src_device_key": "CORE-R4",
            "device_name": "CORE-R4",
        },
    }
    evidence = build_alert_evidence_bundle(alert, recent_similar_1h=2)
    gate = evidence["topology_subgraph"]["llm_invocation_gate"]
    assert gate["should_invoke_llm"] is True

    config = replace(
        _config("/tmp"),
        provider="gpu_http",
        provider_endpoint_url="http://127.0.0.1:18080/infer",
        provider_model="glm-fast",
        provider_compute_target="external_gpu_service",
    )
    provider = build_provider(config)
    req = build_alert_inference_request(alert, evidence, provider=provider.name)
    captured = {}

    def fake_urlopen(http_request, timeout):
        captured["timeout"] = timeout
        captured["body"] = json.loads(http_request.data.decode("utf-8"))
        return _HTTPResponse(
            {
                "output": {
                    "summary": "CORE-R4 is the root candidate.",
                    "hypotheses": ["CORE-R4 single-node failure is the primary candidate."],
                    "recommended_actions": ["Validate adjacent symptoms before operator-approved remediation."],
                    "confidence_score": 0.81,
                    "confidence_label": "high",
                    "confidence_reason": "topology-gated high-value alert",
                }
            }
        )

    monkeypatch.setattr(providers_module.request, "urlopen", fake_urlopen)
    result = provider.infer(req)

    assert captured["timeout"] == 30
    assert captured["body"]["routing"]["should_invoke_llm"] is True
    assert captured["body"]["routing"]["llm_budget_tier"] == "external_llm"
    assert result.provider_name == "gpu_http"
    assert result.provider_kind == "external_model_service"
    assert result.confidence_label == "high"


def test_template_provider_worker_builds_alert_scope_suggestion() -> None:
    alert = {
        "alert_id": "a-88",
        "rule_id": "deny_burst_v1",
        "severity": "warning",
        "alert_ts": "2026-03-09T00:00:59+00:00",
        "event_excerpt": {
            "service": "Dahua SDK",
            "src_device_key": "d4:43:0e:1a:c5:88",
        },
        "device_profile": {"srcmac": "d4:43:0e:1a:c5:88"},
        "change_context": {"suspected_change": True, "change_refs": ["crscore:30"]},
    }
    evidence = build_alert_evidence_bundle(alert, recent_similar_1h=12)
    req = build_alert_inference_request(alert, evidence, provider="template")
    queue = InMemoryInferenceQueue()
    queue.enqueue(req)
    result = InferenceWorker(TemplateProvider()).run_once(queue)
    assert result is not None
    suggestion = build_alert_pipeline_suggestion(alert, evidence, req, result)
    assert suggestion["schema_version"] == 2
    assert suggestion["suggestion_scope"] == "alert"
    assert suggestion["context"]["service"] == "Dahua SDK"
    assert suggestion["context"]["recent_similar_1h"] == 12
    assert suggestion["context"]["candidate_event_graph_id"]
    assert suggestion["context"]["investigation_session_id"]
    assert suggestion["context"]["hypothesis_set_id"]
    assert suggestion["context"]["review_verdict_id"]
    assert suggestion["context"]["runbook_draft_id"]
    assert suggestion["hypothesis_set"]["primary_hypothesis_id"]
    assert suggestion["hypothesis_set"]["items"]
    assert suggestion["hypothesis_set"]["items"][0]["support_evidence_refs"]
    assert suggestion["runbook_plan_outline"]["approval_boundary"]["approval_required"] is True
    assert suggestion["runbook_draft"]["plan_id"]
    assert suggestion["runbook_draft"]["operator_actions"]
    assert suggestion["runbook_draft"]["approval_boundary"]["approval_required"] is True
    assert suggestion["review_verdict"]["approval_required"] is True
    assert suggestion["review_verdict"]["verdict_status"] in {"operator_review", "needs_evidence"}
    assert suggestion["review_verdict"]["checks"]["overreach_risk"]["status"] == "guarded"
    stage_requests = build_reasoning_stage_requests(_config("/tmp"), req, suggestion)
    assert stage_requests["hypothesis_critique"]["routing_hint"]["request_kind"] == "hypothesis_critique"
    assert stage_requests["hypothesis_critique"]["input_contract"]["reasoning_objects"]["hypothesis_set"][
        "primary_hypothesis_id"
    ] == suggestion["hypothesis_set"]["primary_hypothesis_id"]
    assert stage_requests["runbook_draft"]["routing_hint"]["request_kind"] == "runbook_draft"
    assert stage_requests["runbook_draft"]["input_contract"]["reasoning_objects"]["review_verdict"][
        "verdict_status"
    ] == suggestion["review_verdict"]["verdict_status"]
    assert stage_requests["runbook_draft"]["input_contract"]["reasoning_objects"]["deterministic_runbook_seed"][
        "plan_id"
    ] == suggestion["runbook_draft"]["plan_id"]
    assert suggestion["inference"]["provider_name"] == "template"
    assert suggestion["confidence_label"] in {"medium", "high"}


def test_phase_context_router_keeps_stage_specific_payloads() -> None:
    alert = {
        "alert_id": "a-ctx",
        "rule_id": "deny_burst_v1",
        "severity": "warning",
        "alert_ts": "2026-03-09T00:00:59+00:00",
        "event_excerpt": {
            "service": "Dahua SDK",
            "src_device_key": "d4:43:0e:1a:c5:88",
        },
        "topology_context": {"site": "lab-a", "zone": "edge", "service": "Dahua SDK"},
        "device_profile": {"srcmac": "d4:43:0e:1a:c5:88", "device_role": "camera"},
        "change_context": {"suspected_change": True, "change_refs": ["crscore:30"]},
    }
    evidence = build_alert_evidence_bundle(alert, recent_similar_1h=12)
    hypothesis_context = build_phase_context_payload("hypothesis_generate", evidence)
    runbook_context = build_phase_context_payload("runbook_review", evidence)
    assert hypothesis_context["evidence_pack_v2"]["summary"]["direct_count"] >= 1
    assert hypothesis_context["evidence_pack_v2"]["contradictory_evidence"]
    assert hypothesis_context["context"]["device_context"]["device_role"] == "camera"
    assert "runbook_plan_outline" not in hypothesis_context["context"]
    assert runbook_context["context"]["runbook_plan_outline"]["approval_boundary"]["approval_required"] is True
    assert runbook_context["evidence_pack_v2"]["missing_evidence"]
    assert "supporting_evidence" not in runbook_context["evidence_pack_v2"]
    assert runbook_context["investigation_session"]["session_scope"] == "alert"


def test_evidence_pack_v2_marks_missing_and_contradictory_inputs_explicitly() -> None:
    alert = {
        "alert_id": "a-v2",
        "rule_id": "deny_burst_v1",
        "severity": "warning",
        "alert_ts": "2026-03-09T00:00:59+00:00",
        "event_excerpt": {
            "service": "udp/3702",
            "src_device_key": "dev-1",
        },
        "topology_context": {"service": "udp/3702"},
        "device_profile": {},
        "change_context": {"suspected_change": False},
    }
    evidence = build_alert_evidence_bundle(alert, recent_similar_1h=0)
    pack = evidence["evidence_pack_v2"]
    contradictory_labels = {item["label"] for item in pack["contradictory_evidence"]}
    missing_labels = {item["label"] for item in pack["missing_evidence"]}
    reliability_sections = {
        item["source_section"] for item in pack["source_reliability"]["sections"]
    }
    lineage_sections = {item["source_section"] for item in pack["lineage"]}
    status_values = {
        item["status"] for item in pack["contradictory_evidence"] + pack["missing_evidence"]
    }

    assert "history.no_recent_recurrence" in contradictory_labels
    assert "history.cluster_gate_not_reached" in contradictory_labels
    assert "change.no_change_signal" in contradictory_labels
    assert "device.device_name" in missing_labels
    assert "change.change_refs" in missing_labels
    assert {"alert_ref", "rule_context", "historical_context"}.issubset(
        reliability_sections
    )
    assert {"alert_ref", "historical_context", "device_context"}.issubset(
        lineage_sections
    )
    assert status_values == {"missing", "observed"}
    assert all("." in item["source_ref"] for item in pack["direct_evidence"])


def test_review_verdict_returns_needs_evidence_when_support_is_too_thin() -> None:
    alert = {
        "alert_id": "a-thin",
        "rule_id": "deny_burst_v1",
        "severity": "warning",
        "alert_ts": "2026-03-09T00:00:59+00:00",
        "event_excerpt": {
            "service": "udp/3702",
            "src_device_key": "dev-1",
        },
        "topology_context": {"service": "udp/3702"},
        "device_profile": {},
        "change_context": {"suspected_change": False},
    }
    evidence = build_alert_evidence_bundle(alert, recent_similar_1h=0)
    req = build_alert_inference_request(alert, evidence, provider="template")
    queue = InMemoryInferenceQueue()
    queue.enqueue(req)
    result = InferenceWorker(TemplateProvider()).run_once(queue)
    assert result is not None
    suggestion = build_alert_pipeline_suggestion(alert, evidence, req, result)

    assert suggestion["review_verdict"]["verdict_status"] == "needs_evidence"
    assert suggestion["review_verdict"]["recommended_disposition"] == "return_to_evidence_gather"
    assert suggestion["review_verdict"]["blocking_issues"]
    assert suggestion["runbook_draft"]["plan_status"] == "needs_evidence"


def test_build_provider_accepts_external_gpu_alias() -> None:
    config = _config("/tmp")
    config = AgentConfig(
        bootstrap_servers=config.bootstrap_servers,
        topic_alerts=config.topic_alerts,
        topic_suggestions=config.topic_suggestions,
        consumer_group=config.consumer_group,
        auto_offset_reset=config.auto_offset_reset,
        min_severity=config.min_severity,
        output_dir=config.output_dir,
        log_interval_sec=config.log_interval_sec,
        clickhouse_enabled=config.clickhouse_enabled,
        clickhouse_host=config.clickhouse_host,
        clickhouse_http_port=config.clickhouse_http_port,
        clickhouse_user=config.clickhouse_user,
        clickhouse_password=config.clickhouse_password,
        clickhouse_db=config.clickhouse_db,
        clickhouse_alerts_table=config.clickhouse_alerts_table,
        cluster_window_sec=config.cluster_window_sec,
        cluster_min_alerts=config.cluster_min_alerts,
        cluster_cooldown_sec=config.cluster_cooldown_sec,
        provider="gpu_http",
        provider_endpoint_url="http://gpu.example/v1/infer",
        provider_api_key="secret",
        provider_model="generic-aiops-gpu",
        provider_timeout_sec=45,
        provider_compute_target="external_gpu_service",
        provider_max_parallelism=1,
    )
    provider = build_provider(config)
    assert provider.name == "gpu_http"
    assert provider.kind == "external_model_service"


def test_run_agent_loop_emits_alert_scope_suggestion_for_single_alert(tmp_path) -> None:
    alert = {
        "alert_id": "a-100",
        "rule_id": "deny_burst_v1",
        "severity": "warning",
        "alert_ts": "2026-03-09T00:00:01+00:00",
        "event_excerpt": {
            "event_ts": "2026-03-09T00:00:01+00:00",
            "service": "udp/3702",
            "srcip": "192.168.1.10",
            "dstip": "239.255.255.250",
            "src_device_key": "dev-1",
        },
    }
    consumer = _IterableConsumer([alert])
    producer = _Producer()
    run_agent_loop(_config(str(tmp_path)), consumer, producer, clickhouse_client=None)
    assert consumer.committed == 1
    assert len(producer.sent) == 1
    assert producer.sent[0]["payload"]["suggestion_scope"] == "alert"
    assert producer.sent[0]["payload"]["reasoning_stage_requests"]["hypothesis_critique"]["stage"] == "hypothesis_critique"
    assert producer.sent[0]["payload"]["reasoning_stage_requests"]["runbook_draft"]["routing_hint"]["stage"] == "runbook_draft"


def test_run_agent_loop_emits_alert_and_cluster_suggestions_when_cluster_triggers(tmp_path) -> None:
    base = {
        "rule_id": "deny_burst_v1",
        "severity": "warning",
        "event_excerpt": {
            "service": "udp/3702",
            "srcip": "192.168.1.10",
            "dstip": "239.255.255.250",
            "src_device_key": "dev-1",
        },
    }
    alerts = [
        base | {"alert_id": "a-1", "alert_ts": "2026-03-09T00:00:01+00:00"},
        base | {"alert_id": "a-2", "alert_ts": "2026-03-09T00:05:00+00:00"},
        base | {"alert_id": "a-3", "alert_ts": "2026-03-09T00:10:00+00:00"},
    ]
    consumer = _IterableConsumer(alerts)
    producer = _Producer()
    run_agent_loop(_config(str(tmp_path)), consumer, producer, clickhouse_client=None)
    scopes = [item["payload"]["suggestion_scope"] for item in producer.sent]
    assert consumer.committed == 3
    assert scopes.count("alert") == 3
    assert scopes.count("cluster") == 1
    cluster_payload = [item["payload"] for item in producer.sent if item["payload"]["suggestion_scope"] == "cluster"][0]
    assert cluster_payload["context"]["cluster_size"] == 3
    assert cluster_payload["reasoning_stage_requests"]["runbook_draft"]["suggestion_scope"] == "cluster"


def test_commit_if_needed_success_and_failure_paths() -> None:
    stats = {"commit_error": 0}
    c1 = _ConsumerOK()
    commit_if_needed(c1, should_commit=True, stats=stats)
    assert c1.committed == 1
    assert stats["commit_error"] == 0

    c2 = _ConsumerFail()
    commit_if_needed(c2, should_commit=True, stats=stats)
    assert stats["commit_error"] == 1
