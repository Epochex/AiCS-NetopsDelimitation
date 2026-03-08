import sys
import types
from datetime import datetime, timezone

if "clickhouse_connect" not in sys.modules:
    stub = types.ModuleType("clickhouse_connect")
    stub.get_client = lambda *args, **kwargs: None
    sys.modules["clickhouse_connect"] = stub

if "kafka" not in sys.modules:
    kafka_stub = types.ModuleType("kafka")
    kafka_stub.KafkaConsumer = object
    sys.modules["kafka"] = kafka_stub

from core.alerts_store.main import _parse_dt, _to_row


def test_parse_dt_valid_iso_utc() -> None:
    dt = _parse_dt("2026-03-08T12:34:56Z")
    assert dt == datetime(2026, 3, 8, 12, 34, 56, tzinfo=timezone.utc)


def test_parse_dt_invalid_fallbacks_to_now_utc() -> None:
    dt = _parse_dt("not-a-time")
    assert dt.tzinfo == timezone.utc
    assert abs((datetime.now(timezone.utc) - dt).total_seconds()) < 5


def test_to_row_maps_alert_fields() -> None:
    alert = {
        "alert_ts": "2026-03-08T12:00:00Z",
        "alert_id": "a-1",
        "rule_id": "deny_burst_v1",
        "severity": "warning",
        "source_event_id": "e-1",
        "metrics": {"count": 12},
        "dimensions": {"src_device_key": "dev-1"},
        "event_excerpt": {
            "service": "udp/3702",
            "src_device_key": "dev-1",
            "srcip": "192.168.1.10",
            "dstip": "192.168.1.20",
        },
    }
    row = _to_row(alert)

    assert len(row) == 14
    assert row[2] == "a-1"
    assert row[3] == "deny_burst_v1"
    assert row[4] == "warning"
    assert row[5] == "e-1"
    assert row[6] == "udp/3702"
    assert row[7] == "dev-1"
    assert row[8] == "192.168.1.10"
    assert row[9] == "192.168.1.20"
    assert '"count":12' in row[10]
    assert '"src_device_key":"dev-1"' in row[11]
    assert '"service":"udp/3702"' in row[12]
