import json
import logging
from datetime import datetime, timezone
from typing import Any

from core.aiops_agent.app_config import AgentConfig
from core.aiops_agent.cluster_aggregator import AlertClusterAggregator
from core.aiops_agent.context_lookup import recent_similar_count
from core.aiops_agent.evidence_bundle import build_alert_evidence_bundle, build_cluster_evidence_bundle
from core.aiops_agent.inference_queue import InMemoryInferenceQueue
from core.aiops_agent.inference_schema import build_alert_inference_request, build_cluster_inference_request
from core.aiops_agent.inference_worker import InferenceWorker
from core.aiops_agent.output_sink import append_jsonl_line, hourly_file_path
from core.aiops_agent.providers import build_provider
from core.aiops_agent.suggestion_engine import build_alert_pipeline_suggestion, build_pipeline_suggestion

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
        "alert_suggestions_emitted": 0,
        "cluster_suggestions_emitted": 0,
        "skipped_by_severity": 0,
        "cluster_triggers": 0,
        "json_error": 0,
        "inference_requests": 0,
        "inference_completed": 0,
        "inference_error": 0,
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
    provider = build_provider(config)
    queue = InMemoryInferenceQueue()
    worker = InferenceWorker(provider)

    LOGGER.info(
        (
            "aiops-agent started: topic_alerts=%s topic_suggestions=%s min_severity=%s "
            "cluster=[window=%ds,min=%d,cooldown=%ds] clickhouse_enabled=%s provider=%s"
        ),
        config.topic_alerts,
        config.topic_suggestions,
        config.min_severity,
        config.cluster_window_sec,
        config.cluster_min_alerts,
        config.cluster_cooldown_sec,
        config.clickhouse_enabled,
        provider.name,
    )

    for msg in consumer:
        stats["ingested"] += 1
        should_commit = False
        try:
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

            excerpt = alert.get("event_excerpt") or {}
            service = str(excerpt.get("service") or "unknown")
            rule_id = str(alert.get("rule_id") or "unknown")
            recent_similar_1h = recent_similar_count(
                clickhouse_client,
                config.clickhouse_db,
                config.clickhouse_alerts_table,
                rule_id,
                service,
            )

            alert_evidence = build_alert_evidence_bundle(alert, recent_similar_1h)
            alert_request = build_alert_inference_request(alert, alert_evidence, provider.name)
            should_commit = _run_inference_and_emit(
                queue=queue,
                worker=worker,
                producer=producer,
                topic=config.topic_suggestions,
                output_dir=config.output_dir,
                inference_request=alert_request,
                build_suggestion_fn=lambda result: build_alert_pipeline_suggestion(
                    alert,
                    alert_evidence,
                    alert_request,
                    result,
                ),
                stats=stats,
            )

            trigger = aggregator.observe(alert)
            if trigger is not None:
                stats["cluster_triggers"] += 1
                cluster_evidence = build_cluster_evidence_bundle(alert, trigger, recent_similar_1h)
                cluster_request = build_cluster_inference_request(alert, trigger, cluster_evidence, provider.name)
                cluster_ok = _run_inference_and_emit(
                    queue=queue,
                    worker=worker,
                    producer=producer,
                    topic=config.topic_suggestions,
                    output_dir=config.output_dir,
                    inference_request=cluster_request,
                    build_suggestion_fn=lambda result: build_pipeline_suggestion(
                        alert,
                        trigger,
                        cluster_evidence,
                        cluster_request,
                        result,
                    ),
                    stats=stats,
                )
                should_commit = should_commit or cluster_ok

            commit_if_needed(consumer, should_commit, stats)
        finally:
            tick = _log_stats_if_due(config.log_interval_sec, stats, tick)


def _run_inference_and_emit(
    queue: InMemoryInferenceQueue,
    worker: InferenceWorker,
    producer: Any,
    topic: str,
    output_dir: str,
    inference_request: Any,
    build_suggestion_fn: Any,
    stats: dict[str, int],
) -> bool:
    queue.enqueue(inference_request)
    stats["inference_requests"] += 1

    try:
        inference_result = worker.run_once(queue)
    except Exception:
        stats["inference_error"] += 1
        LOGGER.exception("aiops inference failed")
        return False

    if inference_result is None:
        stats["inference_error"] += 1
        return False

    stats["inference_completed"] += 1
    suggestion = build_suggestion_fn(inference_result)
    payload = json.dumps(suggestion, ensure_ascii=True, separators=(",", ":"))

    if not _publish_suggestion(producer, topic, payload, suggestion["suggestion_id"], stats):
        return False
    return _sink_suggestion(output_dir, payload, stats, str(suggestion.get("suggestion_scope") or "unknown"))


def _publish_suggestion(producer: Any, topic: str, payload: str, suggestion_id: str, stats: dict[str, int]) -> bool:
    try:
        producer.send(topic, key=suggestion_id.encode("utf-8"), value=payload).get(timeout=30)
        return True
    except Exception:
        stats["publish_error"] += 1
        LOGGER.exception("failed to publish aiops suggestion")
        return False


def _sink_suggestion(output_dir: str, payload: str, stats: dict[str, int], suggestion_scope: str) -> bool:
    try:
        append_jsonl_line(hourly_file_path(output_dir), payload)
        stats["suggestions_emitted"] += 1
        if suggestion_scope == "alert":
            stats["alert_suggestions_emitted"] += 1
        elif suggestion_scope == "cluster":
            stats["cluster_suggestions_emitted"] += 1
        return True
    except Exception:
        stats["sink_error"] += 1
        LOGGER.exception("failed to persist aiops suggestion")
        return False


def _log_stats_if_due(log_interval_sec: int, stats: dict[str, int], tick: datetime) -> datetime:
    now = datetime.now(timezone.utc)
    if (now - tick).total_seconds() >= log_interval_sec:
        LOGGER.info("aiops-agent stats: %s", json.dumps(stats, ensure_ascii=True, sort_keys=True))
        return now
    return tick
