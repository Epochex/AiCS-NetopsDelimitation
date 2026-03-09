import json
import logging
from datetime import datetime, timezone
from typing import Any

from core.aiops_agent.app_config import AgentConfig
from core.aiops_agent.cluster_aggregator import AlertClusterAggregator
from core.aiops_agent.context_lookup import recent_similar_count
from core.aiops_agent.output_sink import append_jsonl_line, hourly_file_path
from core.aiops_agent.suggestion_engine import build_cluster_suggestion

LOGGER = logging.getLogger(__name__)


def commit_if_needed(consumer: Any, should_commit: bool, stats: dict[str, int]) -> None:
    if not should_commit:
        return
    try:
        consumer.commit()
    except Exception:
        stats["commit_error"] += 1
        LOGGER.exception("offset commit failed")


def run_agent_loop(config: AgentConfig, consumer: Any, producer: Any, clickhouse_client: Any) -> None:
    stats = {
        "ingested": 0,
        "suggestions_emitted": 0,
        "skipped_by_severity": 0,
        "json_error": 0,
        "publish_error": 0,
        "sink_error": 0,
        "commit_error": 0,
    }
    tick = datetime.now(timezone.utc)
    aggregator = AlertClusterAggregator(
        window_sec=config.cluster_window_sec,
        min_alerts=config.cluster_min_alerts,
        cooldown_sec=config.cluster_cooldown_sec,
    )

    LOGGER.info(
        "aiops-agent started: topic_alerts=%s topic_suggestions=%s min_severity=%s cluster=[window=%ds,min=%d,cooldown=%ds] clickhouse_enabled=%s",
        config.topic_alerts,
        config.topic_suggestions,
        config.min_severity,
        config.cluster_window_sec,
        config.cluster_min_alerts,
        config.cluster_cooldown_sec,
        config.clickhouse_enabled,
    )

    for msg in consumer:
        stats["ingested"] += 1
        should_commit = False

        try:
            alert = json.loads(msg.value)
        except json.JSONDecodeError:
            stats["json_error"] += 1
            should_commit = True
            commit_if_needed(consumer, should_commit, stats)
            continue

        severity = str(alert.get("severity") or "unknown").lower()
        if not config.should_process_severity(severity):
            stats["skipped_by_severity"] += 1
            should_commit = True
            commit_if_needed(consumer, should_commit, stats)
            continue

        trigger = aggregator.observe(alert)
        if trigger is None:
            should_commit = True
            commit_if_needed(consumer, should_commit, stats)
            continue

        similar_1h = recent_similar_count(
            clickhouse_client,
            config.clickhouse_db,
            config.clickhouse_alerts_table,
            trigger.key.rule_id,
            trigger.key.service,
        )
        suggestion = build_cluster_suggestion(alert, trigger, similar_1h)
        payload = json.dumps(suggestion, ensure_ascii=True, separators=(",", ":"))

        if _publish_suggestion(producer, config.topic_suggestions, payload, suggestion["suggestion_id"], stats):
            should_commit = _sink_suggestion(config.output_dir, payload, stats)

        commit_if_needed(consumer, should_commit, stats)

        now = datetime.now(timezone.utc)
        if (now - tick).total_seconds() >= config.log_interval_sec:
            LOGGER.info("aiops-agent stats: %s", json.dumps(stats, ensure_ascii=True, sort_keys=True))
            tick = now


def _publish_suggestion(producer: Any, topic: str, payload: str, suggestion_id: str, stats: dict[str, int]) -> bool:
    try:
        producer.send(topic, key=suggestion_id.encode("utf-8"), value=payload).get(timeout=30)
        return True
    except Exception:
        stats["publish_error"] += 1
        LOGGER.exception("failed to publish aiops suggestion")
        return False


def _sink_suggestion(output_dir: str, payload: str, stats: dict[str, int]) -> bool:
    try:
        append_jsonl_line(hourly_file_path(output_dir), payload)
        stats["suggestions_emitted"] += 1
        return True
    except Exception:
        stats["sink_error"] += 1
        LOGGER.exception("failed to persist aiops suggestion")
        return False
