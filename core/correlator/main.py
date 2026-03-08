import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

from kafka import KafkaConsumer, KafkaProducer

from core.infra.config import env_int, env_str
from core.correlator.quality_gate import QualityGate
from core.infra.logging_utils import configure_logging
from core.correlator.rules import RuleConfig, RuleEngine

LOGGER = logging.getLogger(__name__)


def _build_consumer(
    bootstrap_servers: str,
    topic: str,
    group_id: str,
    auto_offset_reset: str,
) -> KafkaConsumer:
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


def main() -> None:
    configure_logging("core-correlator")

    bootstrap_servers = env_str("KAFKA_BOOTSTRAP_SERVERS", "netops-kafka.netops-core.svc.cluster.local:9092")
    topic_raw = env_str("KAFKA_TOPIC_RAW", "netops.facts.raw.v1")
    topic_alerts = env_str("KAFKA_TOPIC_ALERTS", "netops.alerts.v1")
    topic_dlq = env_str("KAFKA_TOPIC_DLQ", "netops.dlq.v1")
    consumer_group = env_str("CORRELATOR_GROUP_ID", "core-correlator-v1")
    auto_offset_reset = env_str("KAFKA_AUTO_OFFSET_RESET", "latest").lower()
    if auto_offset_reset not in {"earliest", "latest"}:
        LOGGER.warning("invalid KAFKA_AUTO_OFFSET_RESET=%s, fallback to latest", auto_offset_reset)
        auto_offset_reset = "latest"
    dedup_cache_size = env_int("CORRELATOR_DEDUP_CACHE_SIZE", 200_000)
    log_interval_sec = env_int("CORRELATOR_LOG_INTERVAL_SEC", 30)

    rules = RuleConfig(
        deny_window_sec=env_int("RULE_DENY_WINDOW_SEC", 60),
        deny_threshold=env_int("RULE_DENY_THRESHOLD", 30),
        bytes_window_sec=env_int("RULE_BYTES_WINDOW_SEC", 300),
        bytes_threshold=env_int("RULE_BYTES_THRESHOLD", 20_000_000),
        cooldown_sec=env_int("RULE_ALERT_COOLDOWN_SEC", 60),
    )

    gate = QualityGate(dedup_cache_size=dedup_cache_size)
    engine = RuleEngine(rules)
    consumer = _build_consumer(bootstrap_servers, topic_raw, consumer_group, auto_offset_reset)
    producer = _build_producer(bootstrap_servers)
    stats = {
        "ingested": 0,
        "accepted": 0,
        "drop_duplicate_event_id": 0,
        "drop_parse_status_not_ok": 0,
        "drop_missing_event_id": 0,
        "drop_missing_event_ts": 0,
        "drop_missing_type": 0,
        "drop_missing_subtype": 0,
        "alerts_emitted": 0,
        "json_error": 0,
        "dlq_emitted": 0,
        "commit_error": 0,
    }
    stats_tick = time.time()

    LOGGER.info(
        (
            "correlator started: topic_raw=%s topic_alerts=%s group=%s offset_reset=%s "
            "dedup_cache_size=%d"
        ),
        topic_raw,
        topic_alerts,
        consumer_group,
        auto_offset_reset,
        dedup_cache_size,
    )

    for msg in consumer:
        stats["ingested"] += 1
        should_commit = False
        raw = msg.value
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            stats["json_error"] += 1
            LOGGER.warning("skip invalid json message partition=%s offset=%s", msg.partition, msg.offset)
            if _send_dlq(producer, topic_dlq, msg, "invalid_json", raw):
                stats["dlq_emitted"] += 1
                should_commit = True
            _commit_if_needed(consumer, should_commit, stats)
            continue

        accepted, reason = gate.evaluate(event)
        if not accepted:
            key = f"drop_{reason}"
            stats[key] = stats.get(key, 0) + 1
            should_commit = True
            _commit_if_needed(consumer, should_commit, stats)
            continue
        stats["accepted"] += 1

        try:
            alerts = engine.process(event)
        except Exception as exc:
            LOGGER.exception("rule processing failed partition=%s offset=%s err=%s", msg.partition, msg.offset, exc)
            if _send_dlq(producer, topic_dlq, msg, "rule_processing_error", raw):
                stats["dlq_emitted"] += 1
                should_commit = True
            _commit_if_needed(consumer, should_commit, stats)
            continue

        if not alerts:
            should_commit = True
            _commit_if_needed(consumer, should_commit, stats)
            now = time.time()
            if now - stats_tick >= log_interval_sec:
                LOGGER.info("correlator stats: %s", json.dumps(stats, ensure_ascii=True, sort_keys=True))
                stats_tick = now
            continue

        send_ok = True
        for alert in alerts:
            payload = json.dumps(alert, separators=(",", ":"), ensure_ascii=True)
            alert_key = str(alert.get("alert_id", "unknown")).encode("utf-8")
            try:
                producer.send(topic_alerts, key=alert_key, value=payload).get(timeout=30)
            except Exception as exc:
                LOGGER.exception(
                    "failed to publish alert partition=%s offset=%s err=%s",
                    msg.partition,
                    msg.offset,
                    exc,
                )
                send_ok = False
                break
            stats["alerts_emitted"] += 1
            LOGGER.info(
                "alert emitted rule=%s severity=%s source_event_id=%s",
                alert.get("rule_id"),
                alert.get("severity"),
                alert.get("source_event_id"),
            )

        if send_ok:
            should_commit = True
        else:
            if _send_dlq(producer, topic_dlq, msg, "alert_publish_error", raw):
                stats["dlq_emitted"] += 1
                should_commit = True

        _commit_if_needed(consumer, should_commit, stats)
        now = time.time()
        if now - stats_tick >= log_interval_sec:
            LOGGER.info("correlator stats: %s", json.dumps(stats, ensure_ascii=True, sort_keys=True))
            stats_tick = now


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
