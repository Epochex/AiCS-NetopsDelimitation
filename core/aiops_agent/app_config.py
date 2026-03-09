from dataclasses import dataclass

from core.infra.config import env_int, env_str

SEVERITY_RANK = {"warning": 1, "critical": 2}


@dataclass(frozen=True)
class AgentConfig:
    bootstrap_servers: str
    topic_alerts: str
    topic_suggestions: str
    consumer_group: str
    auto_offset_reset: str
    min_severity: str
    output_dir: str
    log_interval_sec: int
    clickhouse_enabled: bool
    clickhouse_host: str
    clickhouse_http_port: int
    clickhouse_user: str
    clickhouse_password: str
    clickhouse_db: str
    clickhouse_alerts_table: str
    cluster_window_sec: int
    cluster_min_alerts: int
    cluster_cooldown_sec: int

    @property
    def min_severity_rank(self) -> int:
        return SEVERITY_RANK.get(self.min_severity, 1)

    def should_process_severity(self, severity: str) -> bool:
        return SEVERITY_RANK.get(severity.lower(), 0) >= self.min_severity_rank


def load_config() -> AgentConfig:
    auto_offset_reset = env_str("KAFKA_AUTO_OFFSET_RESET", "latest").lower()
    if auto_offset_reset not in {"earliest", "latest"}:
        auto_offset_reset = "latest"

    min_severity = env_str("AIOPS_MIN_SEVERITY", "warning").lower()
    if min_severity not in SEVERITY_RANK:
        min_severity = "warning"

    return AgentConfig(
        bootstrap_servers=env_str("KAFKA_BOOTSTRAP_SERVERS", "netops-kafka.netops-core.svc.cluster.local:9092"),
        topic_alerts=env_str("KAFKA_TOPIC_ALERTS", "netops.alerts.v1"),
        topic_suggestions=env_str("KAFKA_TOPIC_AIOPS_SUGGESTIONS", "netops.aiops.suggestions.v1"),
        consumer_group=env_str("AIOPS_AGENT_GROUP_ID", "core-aiops-agent-v1"),
        auto_offset_reset=auto_offset_reset,
        min_severity=min_severity,
        output_dir=env_str("AIOPS_OUTPUT_DIR", "/data/netops-runtime/aiops"),
        log_interval_sec=env_int("AIOPS_LOG_INTERVAL_SEC", 30),
        clickhouse_enabled=env_str("AIOPS_CLICKHOUSE_ENABLED", "true").lower() in {"1", "true", "yes"},
        clickhouse_host=env_str("CLICKHOUSE_HOST", "clickhouse.netops-core.svc.cluster.local"),
        clickhouse_http_port=env_int("CLICKHOUSE_HTTP_PORT", 8123),
        clickhouse_user=env_str("CLICKHOUSE_USER", "default"),
        clickhouse_password=env_str("CLICKHOUSE_PASSWORD", ""),
        clickhouse_db=env_str("CLICKHOUSE_DB", "netops"),
        clickhouse_alerts_table=env_str("CLICKHOUSE_ALERTS_TABLE", "alerts"),
        cluster_window_sec=max(10, env_int("AIOPS_CLUSTER_WINDOW_SEC", 300)),
        cluster_min_alerts=max(2, env_int("AIOPS_CLUSTER_MIN_ALERTS", 3)),
        cluster_cooldown_sec=max(10, env_int("AIOPS_CLUSTER_COOLDOWN_SEC", 300)),
    )
