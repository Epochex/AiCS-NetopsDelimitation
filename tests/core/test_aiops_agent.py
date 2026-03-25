import json

from core.aiops_agent.app_config import AgentConfig
from core.aiops_agent.cluster_aggregator import ClusterKey, ClusterTrigger
from core.aiops_agent.context_lookup import recent_similar_count
from core.aiops_agent.evidence_bundle import build_alert_evidence_bundle, build_cluster_evidence_bundle
from core.aiops_agent.inference_queue import InMemoryInferenceQueue
from core.aiops_agent.inference_schema import build_alert_inference_request, build_cluster_inference_request
from core.aiops_agent.inference_worker import InferenceWorker
from core.aiops_agent.providers import TemplateProvider
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
    assert suggestion["inference"]["provider_name"] == "template"
    assert suggestion["confidence_label"] in {"medium", "high"}


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


def test_commit_if_needed_success_and_failure_paths() -> None:
    stats = {"commit_error": 0}
    c1 = _ConsumerOK()
    commit_if_needed(c1, should_commit=True, stats=stats)
    assert c1.committed == 1
    assert stats["commit_error"] == 0

    c2 = _ConsumerFail()
    commit_if_needed(c2, should_commit=True, stats=stats)
    assert stats["commit_error"] == 1
