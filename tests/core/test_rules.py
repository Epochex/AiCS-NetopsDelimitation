from core.correlator.rules import RuleConfig, RuleEngine


def _event(
    event_id: str,
    event_ts: str,
    action: str = "allow",
    src_device_key: str = "dev-1",
    srcip: str = "10.0.0.1",
    bytes_total: int = 0,
) -> dict:
    return {
        "event_id": event_id,
        "event_ts": event_ts,
        "type": "traffic",
        "subtype": "session",
        "action": action,
        "src_device_key": src_device_key,
        "srcip": srcip,
        "bytes_total": bytes_total,
    }


def test_deny_burst_threshold_and_cooldown() -> None:
    engine = RuleEngine(
        RuleConfig(
            deny_window_sec=60,
            deny_threshold=2,
            bytes_window_sec=300,
            bytes_threshold=10**12,
            cooldown_sec=60,
        )
    )

    r1 = engine.process(_event("e1", "2026-03-08T00:00:00Z", action="deny"))
    r2 = engine.process(_event("e2", "2026-03-08T00:00:01Z", action="deny"))
    r3 = engine.process(_event("e3", "2026-03-08T00:00:10Z", action="deny"))
    r4 = engine.process(_event("e4", "2026-03-08T00:01:02Z", action="deny"))

    assert r1 == []
    assert len(r2) == 1
    assert r2[0]["rule_id"] == "deny_burst_v1"
    assert r3 == []
    assert len(r4) == 1


def test_bytes_spike_rule_triggers() -> None:
    engine = RuleEngine(
        RuleConfig(
            deny_window_sec=60,
            deny_threshold=999999,
            bytes_window_sec=300,
            bytes_threshold=100,
            cooldown_sec=0,
        )
    )

    r1 = engine.process(_event("b1", "2026-03-08T00:00:00Z", bytes_total=60))
    r2 = engine.process(_event("b2", "2026-03-08T00:00:01Z", bytes_total=50))

    assert r1 == []
    assert len(r2) == 1
    assert r2[0]["rule_id"] == "bytes_spike_v1"


def test_invalid_event_ts_returns_no_alert() -> None:
    engine = RuleEngine(RuleConfig())
    result = engine.process(_event("x1", "not-a-time", action="deny"))
    assert result == []
