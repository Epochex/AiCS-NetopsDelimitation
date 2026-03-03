import json
import logging

from kafka import KafkaConsumer, KafkaProducer

from core.infra.config import env_int, env_str
from core.infra.logging_utils import configure_logging
from core.correlator.rules import RuleConfig, RuleEngine

LOGGER = logging.getLogger(__name__)


def _build_consumer(bootstrap_servers: str, topic: str, group_id: str) -> KafkaConsumer:
    return KafkaConsumer(
        topic,
        bootstrap_servers=[x.strip() for x in bootstrap_servers.split(",") if x.strip()],
        group_id=group_id,
        enable_auto_commit=True,
        auto_offset_reset="earliest",
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
    consumer_group = env_str("CORRELATOR_GROUP_ID", "core-correlator-v1")

    rules = RuleConfig(
        deny_window_sec=env_int("RULE_DENY_WINDOW_SEC", 60),
        deny_threshold=env_int("RULE_DENY_THRESHOLD", 30),
        bytes_window_sec=env_int("RULE_BYTES_WINDOW_SEC", 300),
        bytes_threshold=env_int("RULE_BYTES_THRESHOLD", 20_000_000),
        cooldown_sec=env_int("RULE_ALERT_COOLDOWN_SEC", 60),
    )

    engine = RuleEngine(rules)
    consumer = _build_consumer(bootstrap_servers, topic_raw, consumer_group)
    producer = _build_producer(bootstrap_servers)

    LOGGER.info(
        "correlator started: topic_raw=%s topic_alerts=%s group=%s",
        topic_raw,
        topic_alerts,
        consumer_group,
    )

    for msg in consumer:
        try:
            event = json.loads(msg.value)
        except json.JSONDecodeError:
            LOGGER.warning("skip invalid json message partition=%s offset=%s", msg.partition, msg.offset)
            continue

        alerts = engine.process(event)
        if not alerts:
            continue

        for alert in alerts:
            payload = json.dumps(alert, separators=(",", ":"), ensure_ascii=True)
            alert_key = str(alert.get("alert_id", "unknown")).encode("utf-8")
            producer.send(topic_alerts, key=alert_key, value=payload)
            LOGGER.info(
                "alert emitted rule=%s severity=%s source_event_id=%s",
                alert.get("rule_id"),
                alert.get("severity"),
                alert.get("source_event_id"),
            )

        producer.flush()


if __name__ == "__main__":
    main()
