from core.correlator.quality_gate import QualityGate


def _base_event(event_id: str = "evt-1") -> dict:
    return {
        "event_id": event_id,
        "event_ts": "2026-03-08T00:00:00Z",
        "type": "traffic",
        "subtype": "session",
        "parse_status": "ok",
    }


def test_quality_gate_accepts_valid_event() -> None:
    gate = QualityGate(dedup_cache_size=10000)
    accepted, reason = gate.evaluate(_base_event())
    assert accepted is True
    assert reason == "accepted"


def test_quality_gate_drops_duplicate_event_id() -> None:
    gate = QualityGate(dedup_cache_size=10000)
    first = gate.evaluate(_base_event("dup-1"))
    second = gate.evaluate(_base_event("dup-1"))
    assert first == (True, "accepted")
    assert second == (False, "duplicate_event_id")


def test_quality_gate_drops_missing_required_field() -> None:
    gate = QualityGate(dedup_cache_size=10000)
    event = _base_event()
    del event["type"]
    accepted, reason = gate.evaluate(event)
    assert accepted is False
    assert reason == "missing_type"


def test_quality_gate_drops_parse_status_not_ok() -> None:
    gate = QualityGate(dedup_cache_size=10000)
    event = _base_event()
    event["parse_status"] = "error"
    accepted, reason = gate.evaluate(event)
    assert accepted is False
    assert reason == "parse_status_not_ok"
