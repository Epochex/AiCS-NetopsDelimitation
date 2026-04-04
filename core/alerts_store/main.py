import json
import logging
from datetime import datetime, timezone
from typing import Any

import clickhouse_connect
from kafka import KafkaConsumer

from common.infra.config import env_int, env_str
from common.infra.logging_utils import configure_logging

LOGGER = logging.getLogger(__name__)


def _build_consumer(bootstrap_servers: str, topic: str, group_id: str, auto_offset_reset: str) -> KafkaConsumer:
    return KafkaConsumer(
        topic,
        bootstrap_servers=[x.strip() for x in bootstrap_servers.split(",") if x.strip()],
        group_id=group_id,
        enable_auto_commit=False,
        auto_offset_reset=auto_offset_reset,
        value_deserializer=lambda b: b.decode("utf-8"),
    )


def _ensure_schema(client: Any, database: str, table: str) -> None:
    client.command(f"CREATE DATABASE IF NOT EXISTS {database}")
    client.command(
        f"""
        CREATE TABLE IF NOT EXISTS {database}.{table} (
            emit_ts DateTime64(3, 'UTC'),
            alert_ts DateTime64(3, 'UTC'),
            alert_id String,
            rule_id LowCardinality(String),
            severity LowCardinality(String),
            source_event_id String,
            service LowCardinality(String),
            src_device_key String,
            srcip String,
            dstip String,
            metrics_json String,
            dimensions_json String,
            event_excerpt_json String,
            topology_context_json String,
            device_profile_json String,
            change_context_json String,
            ingest_ts DateTime64(3, 'UTC')
        )
        ENGINE = MergeTree
        ORDER BY (emit_ts, rule_id, severity, alert_id)
        """
    )
    for column_name in (
        "topology_context_json",
        "device_profile_json",
        "change_context_json",
    ):
        client.command(
            f"ALTER TABLE {database}.{table} ADD COLUMN IF NOT EXISTS {column_name} String DEFAULT ''"
        )


def _parse_dt(raw: Any) -> datetime:
    if isinstance(raw, str) and raw:
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _to_row(alert: dict[str, Any]) -> list[Any]:
    excerpt = alert.get("event_excerpt") or {}
    return [
        datetime.now(timezone.utc),
        _parse_dt(alert.get("alert_ts")),
        str(alert.get("alert_id") or ""),
        str(alert.get("rule_id") or "unknown"),
        str(alert.get("severity") or "unknown"),
        str(alert.get("source_event_id") or ""),
        str(excerpt.get("service") or "unknown"),
        str(excerpt.get("src_device_key") or ""),
        str(excerpt.get("srcip") or ""),
        str(excerpt.get("dstip") or ""),
        json.dumps(alert.get("metrics") or {}, ensure_ascii=True, separators=(",", ":")),
        json.dumps(alert.get("dimensions") or {}, ensure_ascii=True, separators=(",", ":")),
        json.dumps(excerpt, ensure_ascii=True, separators=(",", ":")),
        json.dumps(alert.get("topology_context") or {}, ensure_ascii=True, separators=(",", ":")),
        json.dumps(alert.get("device_profile") or {}, ensure_ascii=True, separators=(",", ":")),
        json.dumps(alert.get("change_context") or {}, ensure_ascii=True, separators=(",", ":")),
        datetime.now(timezone.utc),
    ]


def main() -> None:
    configure_logging("core-alerts-store")

    bootstrap_servers = env_str("KAFKA_BOOTSTRAP_SERVERS", "netops-kafka.netops-core.svc.cluster.local:9092")
    topic_alerts = env_str("KAFKA_TOPIC_ALERTS", "netops.alerts.v1")
    consumer_group = env_str("ALERTS_STORE_GROUP_ID", "core-alerts-store-v1")
    auto_offset_reset = env_str("KAFKA_AUTO_OFFSET_RESET", "latest").lower()
    if auto_offset_reset not in {"earliest", "latest"}:
        auto_offset_reset = "latest"

    ch_host = env_str("CLICKHOUSE_HOST", "clickhouse.netops-core.svc.cluster.local")
    ch_port = env_int("CLICKHOUSE_HTTP_PORT", 8123)
    ch_user = env_str("CLICKHOUSE_USER", "default")
    ch_pass = env_str("CLICKHOUSE_PASSWORD", "")
    ch_db = env_str("CLICKHOUSE_DB", "netops")
    ch_table = env_str("CLICKHOUSE_ALERTS_TABLE", "alerts")
    log_interval_sec = env_int("ALERTS_STORE_LOG_INTERVAL_SEC", 30)

    client = clickhouse_connect.get_client(host=ch_host, port=ch_port, username=ch_user, password=ch_pass)
    _ensure_schema(client, ch_db, ch_table)
    consumer = _build_consumer(bootstrap_servers, topic_alerts, consumer_group, auto_offset_reset)
    target_table = f"{ch_db}.{ch_table}"

    stats = {"ingested": 0, "stored": 0, "json_error": 0, "store_error": 0, "commit_error": 0}
    tick = datetime.now(timezone.utc)
    LOGGER.info("alerts-store started: topic=%s group=%s clickhouse=%s:%d table=%s", topic_alerts, consumer_group, ch_host, ch_port, target_table)

    for msg in consumer:
        stats["ingested"] += 1
        should_commit = False
        try:
            alert = json.loads(msg.value)
        except json.JSONDecodeError:
            stats["json_error"] += 1
            should_commit = True
            _commit_if_needed(consumer, should_commit, stats)
            continue

        row = _to_row(alert)
        try:
            client.insert(
                target_table,
                [row],
                column_names=[
                    "emit_ts",
                    "alert_ts",
                    "alert_id",
                    "rule_id",
                    "severity",
                    "source_event_id",
                    "service",
                    "src_device_key",
                    "srcip",
                    "dstip",
                    "metrics_json",
                    "dimensions_json",
                    "event_excerpt_json",
                    "topology_context_json",
                    "device_profile_json",
                    "change_context_json",
                    "ingest_ts",
                ],
            )
            stats["stored"] += 1
            should_commit = True
        except Exception as exc:
            LOGGER.exception("failed to store alert offset=%s err=%s", msg.offset, exc)
            stats["store_error"] += 1

        _commit_if_needed(consumer, should_commit, stats)
        now = datetime.now(timezone.utc)
        if (now - tick).total_seconds() >= log_interval_sec:
            LOGGER.info("alerts-store stats: %s", json.dumps(stats, ensure_ascii=True, sort_keys=True))
            tick = now


def _commit_if_needed(consumer: KafkaConsumer, should_commit: bool, stats: dict[str, int]) -> None:
    if not should_commit:
        return
    try:
        consumer.commit()
    except Exception:
        stats["commit_error"] += 1
        LOGGER.exception("offset commit failed")


if __name__ == "__main__":
    main()
