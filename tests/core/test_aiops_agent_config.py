from core.aiops_agent.app_config import AgentConfig, load_config


def test_should_process_severity_respects_min_rank() -> None:
    cfg = AgentConfig(
        bootstrap_servers="kafka:9092",
        topic_alerts="netops.alerts.v1",
        topic_suggestions="netops.aiops.suggestions.v1",
        consumer_group="core-aiops-agent-v1",
        auto_offset_reset="latest",
        min_severity="critical",
        output_dir="/tmp",
        log_interval_sec=30,
        clickhouse_enabled=False,
        clickhouse_host="clickhouse",
        clickhouse_http_port=8123,
        clickhouse_user="default",
        clickhouse_password="",
        clickhouse_db="netops",
        clickhouse_alerts_table="alerts",
        cluster_window_sec=300,
        cluster_min_alerts=3,
        cluster_cooldown_sec=300,
    )
    assert cfg.should_process_severity("warning") is False
    assert cfg.should_process_severity("critical") is True


def test_load_config_fallbacks_invalid_values(monkeypatch) -> None:
    monkeypatch.setenv("KAFKA_AUTO_OFFSET_RESET", "bad-value")
    monkeypatch.setenv("AIOPS_MIN_SEVERITY", "notice")
    cfg = load_config()
    assert cfg.auto_offset_reset == "latest"
    assert cfg.min_severity == "warning"
    assert cfg.cluster_window_sec >= 10
    assert cfg.cluster_min_alerts >= 2
    assert cfg.cluster_cooldown_sec >= 10
