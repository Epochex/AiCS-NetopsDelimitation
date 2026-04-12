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


def test_annotated_fault_rule_triggers_on_fault_transition_only() -> None:
    engine = RuleEngine(
        RuleConfig(
            deny_window_sec=60,
            deny_threshold=999999,
            bytes_window_sec=300,
            bytes_threshold=10**12,
            cooldown_sec=0,
        )
    )

    healthy = _event("l1", "2026-03-08T00:00:00Z")
    healthy.update({"fault_context": {"is_fault": False, "scenario": "healthy", "label_field": "Fault"}})
    first_fault = _event("l2", "2026-03-08T00:00:01Z", src_device_key="router-1")
    first_fault.update(
        {
            "fault_context": {
                "is_fault": True,
                "scenario": "single link failure",
                "label_field": "Fault",
                "label_value": "Single Link Failure",
                "confidence": 1.0,
            }
        }
    )
    repeated_fault = _event("l3", "2026-03-08T00:00:02Z", src_device_key="router-1")
    repeated_fault.update({"fault_context": first_fault["fault_context"]})
    next_fault = _event("l4", "2026-03-08T00:00:03Z", src_device_key="router-1")
    next_fault.update(
        {
            "fault_context": {
                "is_fault": True,
                "scenario": "routing misconfiguration",
                "label_field": "Fault",
                "label_value": "Routing Misconfiguration",
            }
        }
    )

    assert engine.process(healthy) == []
    r1 = engine.process(first_fault)
    r2 = engine.process(repeated_fault)
    r3 = engine.process(next_fault)

    assert len(r1) == 1
    assert r1[0]["rule_id"] == "annotated_fault_v1"
    assert r1[0]["severity"] == "warning"
    assert r1[0]["dimensions"]["fault_scenario"] == "single_link_failure"
    assert r2 == []
    assert len(r3) == 1
    assert r3[0]["severity"] == "critical"
    assert r3[0]["dimensions"]["fault_scenario"] == "routing_misconfiguration"


def test_annotated_fault_rule_preserves_lcore_d_ten_scenarios() -> None:
    labels_to_scenarios = {
        "Single link failure": "single_link_failure",
        "Multiple Link Failure": "multiple_link_failure",
        "Misconfiguration": "misconfiguration",
        "Routing Misconfiguration": "routing_misconfiguration",
        "Line card Failure": "line_card_failure",
        "ICMP Blocked (Firewall)": "icmp_blocked_firewall",
        "Node failure": "node_failure",
        "Multiple nodes failures": "multiple_nodes_failures",
        "Single Node Failure": "single_node_failure",
        "SNMP agent failure": "snmp_agent_failure",
    }
    engine = RuleEngine(
        RuleConfig(
            deny_window_sec=60,
            deny_threshold=999999,
            bytes_window_sec=300,
            bytes_threshold=10**12,
            cooldown_sec=0,
        )
    )

    observed = {}
    for idx, (label, expected) in enumerate(labels_to_scenarios.items()):
        event = _event(
            f"fault-{idx}",
            f"2026-03-08T00:00:{idx:02d}Z",
            src_device_key=f"router-{idx}",
        )
        event.update({"fault_context": {"is_fault": True, "label_value": label}})
        alerts = engine.process(event)
        assert len(alerts) == 1
        observed[label] = alerts[0]["dimensions"]["fault_scenario"]

    assert observed == labels_to_scenarios


def test_invalid_event_ts_returns_no_alert() -> None:
    engine = RuleEngine(RuleConfig())
    result = engine.process(_event("x1", "not-a-time", action="deny"))
    assert result == []


def test_alert_includes_enriched_topology_device_and_change_context() -> None:
    engine = RuleEngine(
        RuleConfig(
            deny_window_sec=60,
            deny_threshold=1,
            bytes_window_sec=300,
            bytes_threshold=10**12,
            cooldown_sec=0,
        )
    )

    event = _event("e100", "2026-03-08T00:00:00Z", action="deny")
    event.update(
        {
            "service": "https",
            "dstip": "10.0.0.99",
            "srcintf": "lan",
            "dstintf": "wan1",
            "srcintfrole": "lan",
            "srcname": "cam-01",
            "srcmac": "aa:bb:cc:dd:ee:ff",
            "osname": "Linux",
            "devtype": "camera",
            "srcfamily": "iot",
            "srchwvendor": "Dahua",
            "srchwmodel": "IPC-123",
            "srchwversion": "1.0.0",
            "crscore": "30",
            "craction": "quarantine",
            "crlevel": "high",
        }
    )

    result = engine.process(event)

    assert len(result) == 1
    alert = result[0]
    assert alert["topology_context"]["service"] == "https"
    assert alert["topology_context"]["srcintf"] == "lan"
    assert alert["topology_context"]["zone"] == "lan"
    assert alert["device_profile"]["device_role"] == "camera"
    assert alert["device_profile"]["vendor"] == "Dahua"
    assert alert["device_profile"]["device_name"] == "cam-01"
    assert alert["device_profile"]["asset_tags"] == ["camera", "iot"]
    assert alert["device_profile"]["known_services"] == ["https"]
    assert alert["change_context"]["suspected_change"] is True
    assert alert["change_context"]["score"] == 30
    assert alert["change_context"]["action"] == "quarantine"
    assert alert["change_context"]["level"] == "high"
    assert "crscore:30" in alert["change_context"]["change_refs"]


def test_alert_prefers_structured_context_when_event_already_contains_it() -> None:
    engine = RuleEngine(
        RuleConfig(
            deny_window_sec=60,
            deny_threshold=1,
            bytes_window_sec=300,
            bytes_threshold=10**12,
            cooldown_sec=0,
        )
    )

    event = _event("e101", "2026-03-08T00:00:00Z", action="deny")
    event.update(
        {
            "service": "rtsp",
            "topology_context": {"site": "lab-a", "zone": "edge", "neighbor_refs": ["sw-1"]},
            "device_profile": {
                "device_role": "camera",
                "vendor": "Hikvision",
                "asset_tags": ["iot", "lab"],
                "known_services": ["rtsp"],
            },
            "change_context": {
                "suspected_change": True,
                "change_window_min": 30,
                "change_refs": ["chg-1"],
            },
        }
    )

    result = engine.process(event)

    assert len(result) == 1
    alert = result[0]
    assert alert["topology_context"]["site"] == "lab-a"
    assert alert["topology_context"]["neighbor_refs"] == ["sw-1"]
    assert alert["device_profile"]["vendor"] == "Hikvision"
    assert alert["device_profile"]["asset_tags"] == ["iot", "lab"]
    assert alert["change_context"]["change_window_min"] == 30
    assert alert["change_context"]["change_refs"] == ["chg-1"]
