import logging
from typing import Any

import clickhouse_connect
from kafka import KafkaConsumer, KafkaProducer

from core.aiops_agent.app_config import AgentConfig

LOGGER = logging.getLogger(__name__)


def _split_bootstrap_servers(raw: str) -> list[str]:
    return [x.strip() for x in raw.split(",") if x.strip()]


def build_consumer(config: AgentConfig) -> KafkaConsumer:
    return KafkaConsumer(
        config.topic_alerts,
        bootstrap_servers=_split_bootstrap_servers(config.bootstrap_servers),
        group_id=config.consumer_group,
        enable_auto_commit=False,
        auto_offset_reset=config.auto_offset_reset,
        value_deserializer=lambda b: b.decode("utf-8"),
    )


def build_producer(config: AgentConfig) -> KafkaProducer:
    return KafkaProducer(
        bootstrap_servers=_split_bootstrap_servers(config.bootstrap_servers),
        acks="all",
        retries=10,
        compression_type="gzip",
        value_serializer=lambda x: x.encode("utf-8"),
    )


def build_clickhouse_client(config: AgentConfig) -> Any:
    if not config.clickhouse_enabled:
        return None
    try:
        return clickhouse_connect.get_client(
            host=config.clickhouse_host,
            port=config.clickhouse_http_port,
            username=config.clickhouse_user,
            password=config.clickhouse_password,
        )
    except Exception:
        LOGGER.exception("failed to init clickhouse client, continue without context lookup")
        return None
