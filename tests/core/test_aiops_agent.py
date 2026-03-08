import sys
import types

if "clickhouse_connect" not in sys.modules:
    stub = types.ModuleType("clickhouse_connect")
    stub.get_client = lambda *args, **kwargs: None
    sys.modules["clickhouse_connect"] = stub

if "kafka" not in sys.modules:
    kafka_stub = types.ModuleType("kafka")
    kafka_stub.KafkaConsumer = object
    kafka_stub.KafkaProducer = object
    sys.modules["kafka"] = kafka_stub

from core.aiops_agent.main import _build_suggestion, _commit_if_needed, _recent_similar


class _Result:
    def __init__(self, first_item: int) -> None:
        self.first_item = first_item


class _ClientOK:
    def query(self, _sql: str, parameters: dict) -> _Result:
        assert parameters["rule_id"] == "deny_burst_v1"
        assert parameters["service"] == "udp/3702"
        return _Result(23)


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


def test_recent_similar_returns_count_when_query_ok() -> None:
    count = _recent_similar(_ClientOK(), "netops", "alerts", "deny_burst_v1", "udp/3702")
    assert count == 23


def test_recent_similar_returns_zero_on_query_error() -> None:
    count = _recent_similar(_ClientFail(), "netops", "alerts", "deny_burst_v1", "udp/3702")
    assert count == 0


def test_build_suggestion_uses_severity_and_recent_context() -> None:
    alert = {
        "alert_id": "a-1",
        "rule_id": "deny_burst_v1",
        "severity": "warning",
        "event_excerpt": {
            "service": "udp/3702",
            "srcip": "192.168.1.10",
            "src_device_key": "dev-1",
        },
    }
    s = _build_suggestion(alert, recent_similar_1h=25)
    assert s["alert_id"] == "a-1"
    assert s["priority"] == "P2"
    assert s["context"]["recent_similar_1h"] == 25
    assert s["confidence"] == 0.75
    assert len(s["recommended_actions"]) >= 1


def test_commit_if_needed_success_and_failure_paths() -> None:
    stats = {"commit_error": 0}
    c1 = _ConsumerOK()
    _commit_if_needed(c1, should_commit=True, stats=stats)
    assert c1.committed == 1
    assert stats["commit_error"] == 0

    c2 = _ConsumerFail()
    _commit_if_needed(c2, should_commit=True, stats=stats)
    assert stats["commit_error"] == 1
