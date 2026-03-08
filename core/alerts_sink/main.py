import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from kafka import KafkaConsumer, KafkaProducer

from core.infra.config import env_int, env_str
from core.infra.logging_utils import configure_logging

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


def _build_producer(bootstrap_servers: str) -> KafkaProducer:
    return KafkaProducer(
        bootstrap_servers=[x.strip() for x in bootstrap_servers.split(",") if x.strip()],
        acks="all",
        retries=10,
        compression_type="gzip",
        value_serializer=lambda x: x.encode("utf-8"),
    )


def _hourly_file(base_dir: str, alert_ts: str | None) -> str:
    ts = None
    if isinstance(alert_ts, str) and alert_ts:
        text = alert_ts.replace("Z", "+00:00")
        try:
            ts = datetime.fromisoformat(text)
        except ValueError:
            ts = None
    if ts is None:
        ts = datetime.now(timezone.utc)
    ts = ts.astimezone(timezone.utc)
    filename = f"alerts-{ts.strftime('%Y%m%d-%H')}.jsonl"
    return os.path.join(base_dir, filename)


def _append_jsonl(path: str, payload: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as fp:
        fp.write(payload)
        fp.write("\n")


def main() -> None:
    configure_logging("core-alerts-sink")

    bootstrap_servers = env_str("KAFKA_BOOTSTRAP_SERVERS", "netops-kafka.netops-core.svc.cluster.local:9092")
    topic_alerts = env_str("KAFKA_TOPIC_ALERTS", "netops.alerts.v1")
    topic_dlq = env_str("KAFKA_TOPIC_DLQ", "netops.dlq.v1")
    consumer_group = env_str("ALERTS_SINK_GROUP_ID", "core-alerts-sink-v1")
    auto_offset_reset = env_str("KAFKA_AUTO_OFFSET_RESET", "latest").lower()
    if auto_offset_reset not in {"earliest", "latest"}:
        LOGGER.warning("invalid KAFKA_AUTO_OFFSET_RESET=%s, fallback to latest", auto_offset_reset)
        auto_offset_reset = "latest"

    output_dir = env_str("ALERTS_OUTPUT_DIR", "/data/netops-runtime/alerts")
    log_interval_sec = env_int("ALERTS_SINK_LOG_INTERVAL_SEC", 30)

    consumer = _build_consumer(bootstrap_servers, topic_alerts, consumer_group, auto_offset_reset)
    producer = _build_producer(bootstrap_servers)
    stats = {"ingested": 0, "written": 0, "json_error": 0, "dlq_emitted": 0, "commit_error": 0}
    last_log_ts = datetime.now(timezone.utc)

    LOGGER.info(
        "alerts-sink started: topic=%s group=%s offset_reset=%s output_dir=%s",
        topic_alerts,
        consumer_group,
        auto_offset_reset,
        output_dir,
    )

    for msg in consumer:
        stats["ingested"] += 1
        should_commit = False
        raw = msg.value

        try:
            alert = json.loads(raw)
        except json.JSONDecodeError:
            stats["json_error"] += 1
            if _send_dlq(producer, topic_dlq, msg, "invalid_alert_json", raw):
                stats["dlq_emitted"] += 1
                should_commit = True
            _commit_if_needed(consumer, should_commit, stats)
            continue

        try:
            path = _hourly_file(output_dir, alert.get("alert_ts"))
            _append_jsonl(path, json.dumps(alert, separators=(",", ":"), ensure_ascii=True))
            stats["written"] += 1
            should_commit = True
        except Exception as exc:
            LOGGER.exception("failed to persist alert partition=%s offset=%s err=%s", msg.partition, msg.offset, exc)
            if _send_dlq(producer, topic_dlq, msg, "alerts_sink_write_error", raw):
                stats["dlq_emitted"] += 1
                should_commit = True

        _commit_if_needed(consumer, should_commit, stats)

        now = datetime.now(timezone.utc)
        if (now - last_log_ts).total_seconds() >= log_interval_sec:
            LOGGER.info("alerts-sink stats: %s", json.dumps(stats, ensure_ascii=True, sort_keys=True))
            last_log_ts = now


def _send_dlq(
    producer: KafkaProducer,
    topic_dlq: str,
    msg: Any,
    reason: str,
    raw: str,
) -> bool:
    payload = {
        "schema_version": 1,
        "reason": reason,
        "source_topic": msg.topic,
        "partition": msg.partition,
        "offset": msg.offset,
        "ingest_ts": datetime.now(timezone.utc).isoformat(),
        "raw": raw,
    }
    try:
        key = f"{msg.topic}:{msg.partition}:{msg.offset}".encode("utf-8")
        producer.send(
            topic_dlq,
            key=key,
            value=json.dumps(payload, separators=(",", ":"), ensure_ascii=True),
        ).get(timeout=30)
        return True
    except Exception:
        LOGGER.exception("failed to publish dlq message partition=%s offset=%s", msg.partition, msg.offset)
        return False


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
