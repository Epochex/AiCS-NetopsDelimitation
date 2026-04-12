from __future__ import annotations

import argparse
import json
import time
from collections import Counter, deque
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from core.aiops_agent.app_config import AgentConfig
from core.aiops_agent.evidence_bundle import build_alert_evidence_bundle
from core.aiops_agent.inference_schema import build_alert_inference_request
from core.aiops_agent.providers import TemplateProvider, build_provider
from core.benchmark.topology_subgraph_ablation import _is_high_value, _iter_alerts, _parse_ts


DEFAULT_ALERT_DIR = "/data/netops-runtime/LCORE-D/work/alerts-sample"
DEFAULT_OUTPUT_JSON = "/data/netops-runtime/LCORE-D/work/llm-provider-replay-summary.json"
DEFAULT_OUTPUT_JSONL = "/data/netops-runtime/LCORE-D/work/llm-provider-replay-events.jsonl"


def _config(args: argparse.Namespace) -> AgentConfig:
    return AgentConfig(
        bootstrap_servers="",
        topic_alerts="",
        topic_suggestions="",
        consumer_group="topology-gated-llm-replay",
        auto_offset_reset="latest",
        min_severity="warning",
        output_dir=str(Path(args.output_json).parent),
        log_interval_sec=3600,
        clickhouse_enabled=False,
        clickhouse_host="",
        clickhouse_http_port=8123,
        clickhouse_user="default",
        clickhouse_password="",
        clickhouse_db="netops",
        clickhouse_alerts_table="alerts",
        cluster_window_sec=600,
        cluster_min_alerts=3,
        cluster_cooldown_sec=300,
        provider=args.provider,
        provider_endpoint_url=args.endpoint_url,
        provider_api_key=args.api_key,
        provider_model=args.model,
        provider_timeout_sec=args.timeout_sec,
        provider_compute_target="external_gpu_service" if args.provider != "template" else "local_cpu",
        provider_max_parallelism=1,
    )


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(max(int(round((len(ordered) - 1) * q)), 0), len(ordered) - 1)
    return round(ordered[index], 2)


def _response_schema_valid(payload: dict[str, Any]) -> bool:
    return (
        bool(str(payload.get("summary") or "").strip())
        and isinstance(payload.get("hypotheses"), list)
        and bool(payload.get("hypotheses"))
        and isinstance(payload.get("recommended_actions"), list)
        and bool(payload.get("recommended_actions"))
        and str(payload.get("confidence_label") or "").lower() in {"low", "medium", "high"}
    )


def _event_record(
    *,
    alert: dict[str, Any],
    gate: dict[str, Any],
    high_value: bool,
    recent_similar_1h: int,
    attempted_external: bool,
    latency_ms: float,
    provider_name: str,
    provider_kind: str,
    raw_response: dict[str, Any],
    error_text: str,
) -> dict[str, Any]:
    dimensions = alert.get("dimensions") or {}
    metrics = alert.get("metrics") or {}
    scenario = str(
        dimensions.get("fault_scenario")
        or metrics.get("label_value")
        or metrics.get("scenario")
        or "unknown"
    )
    return {
        "alert_id": str(alert.get("alert_id") or ""),
        "alert_ts": str(alert.get("alert_ts") or ""),
        "rule_id": str(alert.get("rule_id") or "unknown"),
        "severity": str(alert.get("severity") or "unknown"),
        "fault_scenario": scenario,
        "high_value_label": high_value,
        "recent_similar_1h": recent_similar_1h,
        "should_invoke_llm": bool(gate.get("should_invoke_llm")),
        "llm_budget_tier": str(gate.get("budget_tier") or ""),
        "gate_reason": str(gate.get("reason") or ""),
        "attempted_external_call": attempted_external,
        "provider_name": provider_name,
        "provider_kind": provider_kind,
        "latency_ms": round(latency_ms, 2),
        "response_schema_valid": _response_schema_valid(raw_response),
        "confidence_score": raw_response.get("confidence_score"),
        "confidence_label": raw_response.get("confidence_label"),
        "error": error_text,
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    alerts = _iter_alerts(Path(args.alert_dir), args.limit_files)
    if args.max_alerts > 0:
        alerts = alerts[: args.max_alerts]

    config = _config(args)
    external_provider = build_provider(config)
    template_provider = TemplateProvider(name="dry_run_external" if args.dry_run else "template")
    history: deque[tuple[datetime, str, str]] = deque()
    events: list[dict[str, Any]] = []
    gate_reasons: Counter[str] = Counter()
    scenario_counts: Counter[str] = Counter()
    latencies: list[float] = []
    external_latencies: list[float] = []

    for alert in alerts:
        alert_ts = _parse_ts(alert.get("alert_ts"))
        rule_id = str(alert.get("rule_id") or "unknown")
        excerpt = alert.get("event_excerpt") or {}
        service = str(excerpt.get("service") or "unknown")
        recent_similar_1h = 0
        if alert_ts is not None:
            while history and history[0][0] < (alert_ts - timedelta(hours=1)):
                history.popleft()
            recent_similar_1h = sum(
                1 for _, hist_rule, hist_service in history if hist_rule == rule_id and hist_service == service
            )
            history.append((alert_ts, rule_id, service))

        evidence = build_alert_evidence_bundle(alert, recent_similar_1h=recent_similar_1h)
        subgraph = evidence.get("topology_subgraph") or {}
        gate = subgraph.get("llm_invocation_gate") or {}
        high_value = _is_high_value(alert)
        request_provider_name = external_provider.name if not args.dry_run else template_provider.name
        inference_request = build_alert_inference_request(alert, evidence, provider=request_provider_name)
        should_invoke = bool(gate.get("should_invoke_llm"))
        attempted_external = bool(should_invoke and not args.dry_run and args.provider != "template")
        error_text = ""

        started = time.perf_counter()
        try:
            provider = external_provider if attempted_external else template_provider
            if args.force_template_for_skips and not should_invoke:
                provider = template_provider
            result = provider.infer(inference_request)
            raw_response = result.raw_response
            provider_name = result.provider_name
            provider_kind = result.provider_kind
        except Exception as exc:
            raw_response = {}
            provider_name = external_provider.name
            provider_kind = "error"
            error_text = str(exc)
        latency_ms = (time.perf_counter() - started) * 1000
        latencies.append(latency_ms)
        if attempted_external:
            external_latencies.append(latency_ms)

        event = _event_record(
            alert=alert,
            gate=gate,
            high_value=high_value,
            recent_similar_1h=recent_similar_1h,
            attempted_external=attempted_external,
            latency_ms=latency_ms,
            provider_name=provider_name,
            provider_kind=provider_kind,
            raw_response=raw_response,
            error_text=error_text,
        )
        events.append(event)
        gate_reasons[event["gate_reason"]] += 1
        scenario_counts[event["fault_scenario"]] += 1

    total = len(events)
    total_safe = max(total, 1)
    planned_external = sum(1 for event in events if event["should_invoke_llm"])
    attempted_external = sum(1 for event in events if event["attempted_external_call"])
    external_success = sum(1 for event in events if event["attempted_external_call"] and not event["error"])
    external_error = sum(1 for event in events if event["attempted_external_call"] and event["error"])
    skipped = total - planned_external
    high_value = sum(1 for event in events if event["high_value_label"])
    high_value_kept = sum(1 for event in events if event["high_value_label"] and event["should_invoke_llm"])
    schema_valid = sum(1 for event in events if event["response_schema_valid"])
    summary = {
        "evaluation_ts": datetime.now(timezone.utc).isoformat(),
        "mode": "dry_run" if args.dry_run else args.provider,
        "alert_dir": args.alert_dir,
        "alerts_scanned": total,
        "planned_invoke_all_calls": total,
        "planned_topology_gated_calls": planned_external,
        "planned_template_only_skips": skipped,
        "planned_call_reduction_percent": round((1 - planned_external / total_safe) * 100, 2),
        "external_calls_attempted": attempted_external,
        "external_calls_succeeded": external_success,
        "external_calls_failed": external_error,
        "high_value_alerts": high_value,
        "high_value_kept_by_gate": high_value_kept,
        "high_value_recall": round(high_value_kept / max(high_value, 1), 6),
        "response_schema_valid_count": schema_valid,
        "response_schema_valid_rate": round(schema_valid / total_safe, 6),
        "latency_ms": {
            "avg": round(sum(latencies) / max(len(latencies), 1), 2),
            "p50": _percentile(latencies, 0.50),
            "p95": _percentile(latencies, 0.95),
        },
        "external_latency_ms": {
            "avg": round(sum(external_latencies) / max(len(external_latencies), 1), 2),
            "p50": _percentile(external_latencies, 0.50),
            "p95": _percentile(external_latencies, 0.95),
        },
        "gate_reasons": dict(gate_reasons.most_common()),
        "scenario_counts": dict(scenario_counts.most_common()),
        "output_jsonl": args.output_jsonl,
    }

    output_json = Path(args.output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(summary, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    output_jsonl = Path(args.output_jsonl)
    output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with output_jsonl.open("w", encoding="utf-8") as fp:
        for event in events:
            fp.write(json.dumps(event, ensure_ascii=True, sort_keys=True) + "\n")

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay LCORE alerts through topology-gated LLM provider policy.")
    parser.add_argument("--alert-dir", default=DEFAULT_ALERT_DIR)
    parser.add_argument("--limit-files", type=int, default=0)
    parser.add_argument("--max-alerts", type=int, default=0)
    parser.add_argument("--provider", choices={"template", "gpu_http", "http", "external_model_service"}, default="template")
    parser.add_argument("--endpoint-url", default="")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--model", default="glm-fast")
    parser.add_argument("--timeout-sec", type=int, default=90)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force-template-for-skips", action="store_true", default=True)
    parser.add_argument("--output-json", default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-jsonl", default=DEFAULT_OUTPUT_JSONL)
    summary = run(parser.parse_args())
    print(json.dumps(summary, ensure_ascii=True, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
