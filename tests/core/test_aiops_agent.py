from core.aiops_agent.cluster_aggregator import ClusterKey, ClusterTrigger
from core.aiops_agent.context_lookup import recent_similar_count
from core.aiops_agent.service import commit_if_needed
from core.aiops_agent.suggestion_engine import build_cluster_suggestion, build_suggestion


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
    count = recent_similar_count(_ClientOK(), "netops", "alerts", "deny_burst_v1", "udp/3702")
    assert count == 23


def test_recent_similar_returns_zero_on_query_error() -> None:
    count = recent_similar_count(_ClientFail(), "netops", "alerts", "deny_burst_v1", "udp/3702")
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
    s = build_suggestion(alert, recent_similar_1h=25)
    assert s["alert_id"] == "a-1"
    assert s["priority"] == "P2"
    assert s["context"]["recent_similar_1h"] == 25
    assert s["confidence"] == 0.75
    assert len(s["recommended_actions"]) >= 1


def test_build_cluster_suggestion_contains_cluster_context() -> None:
    alert = {"alert_id": "a-9"}
    trigger = ClusterTrigger(
        key=ClusterKey(rule_id="deny_burst_v1", severity="warning", service="udp/3702", src_device_key="dev-1"),
        cluster_size=5,
        first_alert_ts="2026-03-09T00:00:00+00:00",
        last_alert_ts="2026-03-09T00:00:59+00:00",
        window_sec=300,
        sample_alert_ids=["a-1", "a-2", "a-3", "a-4", "a-5"],
    )
    s = build_cluster_suggestion(alert, trigger, recent_similar_1h=30)
    assert s["suggestion_scope"] == "cluster"
    assert s["context"]["cluster_size"] == 5
    assert s["context"]["service"] == "udp/3702"
    assert s["context"]["recent_similar_1h"] == 30
    assert s["confidence"] >= 0.7


def test_commit_if_needed_success_and_failure_paths() -> None:
    stats = {"commit_error": 0}
    c1 = _ConsumerOK()
    commit_if_needed(c1, should_commit=True, stats=stats)
    assert c1.committed == 1
    assert stats["commit_error"] == 0

    c2 = _ConsumerFail()
    commit_if_needed(c2, should_commit=True, stats=stats)
    assert stats["commit_error"] == 1
