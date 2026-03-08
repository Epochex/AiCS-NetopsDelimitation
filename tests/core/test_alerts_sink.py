import json
from pathlib import Path

from core.alerts_sink.main import _append_jsonl, _hourly_file


def test_hourly_file_uses_alert_ts_when_valid(tmp_path: Path) -> None:
    path = _hourly_file(str(tmp_path), "2026-03-08T12:34:56Z")
    assert path.endswith("alerts-20260308-12.jsonl")


def test_hourly_file_falls_back_to_now_when_invalid(tmp_path: Path) -> None:
    path = _hourly_file(str(tmp_path), "invalid")
    assert str(tmp_path) in path
    assert path.endswith(".jsonl")


def test_append_jsonl_writes_line(tmp_path: Path) -> None:
    path = tmp_path / "alerts-20260308-12.jsonl"
    payload = {"alert_id": "a1", "rule_id": "deny_burst_v1"}
    _append_jsonl(str(path), json.dumps(payload, separators=(",", ":"), ensure_ascii=True))
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["alert_id"] == "a1"
