from core.aiops_agent.cluster_aggregator import AlertClusterAggregator


def _alert(idx: int, ts: str, service: str = "udp/3702", src_device_key: str = "dev-1") -> dict:
    return {
        "alert_id": f"a-{idx}",
        "alert_ts": ts,
        "rule_id": "deny_burst_v1",
        "severity": "warning",
        "event_excerpt": {
            "service": service,
            "src_device_key": src_device_key,
        },
    }


def test_cluster_trigger_threshold_and_cooldown() -> None:
    agg = AlertClusterAggregator(window_sec=600, min_alerts=3, cooldown_sec=120)

    assert agg.observe(_alert(1, "2026-03-09T00:00:00Z")) is None
    assert agg.observe(_alert(2, "2026-03-09T00:00:01Z")) is None

    trigger1 = agg.observe(_alert(3, "2026-03-09T00:00:02Z"))
    assert trigger1 is not None
    assert trigger1.cluster_size == 3
    assert trigger1.key.rule_id == "deny_burst_v1"
    assert trigger1.key.service == "udp/3702"

    assert agg.observe(_alert(4, "2026-03-09T00:00:10Z")) is None

    trigger2 = agg.observe(_alert(5, "2026-03-09T00:02:10Z"))
    assert trigger2 is not None
    assert trigger2.cluster_size >= 3


def test_cluster_key_separates_different_dimensions() -> None:
    agg = AlertClusterAggregator(window_sec=300, min_alerts=2, cooldown_sec=60)
    assert agg.observe(_alert(1, "2026-03-09T00:00:00Z", service="udp/3702")) is None
    assert agg.observe(_alert(2, "2026-03-09T00:00:01Z", service="udp/5353")) is None
    trigger = agg.observe(_alert(3, "2026-03-09T00:00:02Z", service="udp/3702"))
    assert trigger is not None
    assert trigger.key.service == "udp/3702"
