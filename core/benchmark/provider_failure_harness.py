from __future__ import annotations

import argparse
import json
import time
from collections import Counter, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from core.aiops_agent.evidence_bundle import build_alert_evidence_bundle
from core.aiops_agent.inference_schema import build_alert_inference_request, inference_result_from_payload
from core.aiops_agent.providers import TemplateProvider
from core.benchmark.topology_gated_llm_replay import (
    _event_record,
    _percentile,
    _response_schema_valid,
    _stratified_sample,
)
from core.benchmark.topology_subgraph_ablation import _is_high_value, _iter_alerts, _parse_ts


DEFAULT_ALERT_DIR = "/data/netops-runtime/LCORE-D/work/alerts-sample"
DEFAULT_OUTPUT_JSON = "/data/netops-runtime/LCORE-D/work/provider-failure-harness-summary.json"
DEFAULT_OUTPUT_JSONL = "/data/netops-runtime/LCORE-D/work/provider-failure-harness-events.jsonl"


def run(args: argparse.Namespace) -> dict[str, Any]:
    template = TemplateProvider()
    fallback = TemplateProvider(name="failure_fallback")
    alerts = _iter_alerts(Path(args.alert_dir), args.limit_files)
    alerts = _stratified_sample(alerts, args.sample_per_scenario_device)
    if args.max_alerts > 0:
        alerts = alerts[: args.max_alerts]

    history: deque[tuple[datetime, str, str]] = deque()
    events: list[dict[str, Any]] = []
    failure_counts: Counter[str] = Counter()
    latencies: list[float] = []
    external_latencies: list[float] = []
    fallback_calls = 0

    for idx, alert in enumerate(alerts, start=1):
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
        gate = ((evidence.get("topology_subgraph") or {}).get("llm_invocation_gate") or {})
        should_invoke = bool(gate.get("should_invoke_llm"))
        attempted_external = should_invoke
        inference_request = build_alert_inference_request(alert, evidence, provider="failure_harness")

        error_text = ""
        provider_name = template.name
        provider_kind = template.kind
        started = time.perf_counter()
        try:
            if should_invoke:
                result, injected = _run_injected_provider(
                    template=template,
                    inference_request=inference_request,
                    failure_mode=args.failure_mode,
                    fail_every=max(1, args.fail_every),
                    event_index=idx,
                    extra_latency_ms=max(0, args.extra_latency_ms),
                )
            else:
                result = template.infer(inference_request)
                injected = False
            raw_response = result.raw_response
            provider_name = result.provider_name
            provider_kind = result.provider_kind
            if injected:
                failure_counts[str(args.failure_mode)] += 1
            if args.fallback_on_invalid_schema and not _response_schema_valid(raw_response):
                failure_counts["invalid_schema_fallback"] += 1
                fallback_result = fallback.infer(inference_request)
                raw_response = fallback_result.raw_response
                provider_name = fallback_result.provider_name
                provider_kind = "failure_injected_template_fallback"
                fallback_calls += 1
        except Exception as exc:
            failure_counts[str(args.failure_mode)] += 1
            error_text = str(exc)
            fallback_result = fallback.infer(inference_request)
            raw_response = fallback_result.raw_response
            provider_name = fallback_result.provider_name
            provider_kind = "failure_injected_template_fallback"
            fallback_calls += 1
        latency_ms = (time.perf_counter() - started) * 1000
        latencies.append(latency_ms)
        if attempted_external:
            external_latencies.append(latency_ms)

        event = _event_record(
            alert=alert,
            evidence=evidence,
            gate=gate,
            high_value=_is_high_value(alert),
            recent_similar_1h=recent_similar_1h,
            attempted_external=attempted_external,
            latency_ms=latency_ms,
            provider_name=provider_name,
            provider_kind=provider_kind,
            raw_response=raw_response,
            error_text=error_text,
            capture_raw_response=True,
            capture_evidence=False,
            max_capture_chars=8000,
        )
        event["failure_mode"] = args.failure_mode
        event["fallback_used"] = provider_kind == "failure_injected_template_fallback"
        events.append(event)

    total = len(events)
    total_safe = max(total, 1)
    planned_external = sum(1 for event in events if event["should_invoke_llm"])
    schema_valid = sum(1 for event in events if event["response_schema_valid"])
    high_value = sum(1 for event in events if event["high_value_label"])
    high_value_kept = sum(1 for event in events if event["high_value_label"] and event["should_invoke_llm"])
    summary = {
        "schema_version": 1,
        "evaluation_ts": datetime.now(timezone.utc).isoformat(),
        "alert_dir": args.alert_dir,
        "failure_mode": args.failure_mode,
        "alerts_scanned": total,
        "planned_external_calls": planned_external,
        "failure_counts": dict(failure_counts.most_common()),
        "fallback_calls": fallback_calls,
        "local_windows_untouched": total - planned_external,
        "gate_decision_drift": 0,
        "high_value_recall": round(high_value_kept / max(high_value, 1), 6),
        "response_schema_valid_rate": round(schema_valid / total_safe, 6),
        "latency_ms": {
            "avg": round(sum(latencies) / total_safe, 2),
            "p50": _percentile(latencies, 0.50),
            "p95": _percentile(latencies, 0.95),
        },
        "external_latency_ms": {
            "avg": round(sum(external_latencies) / max(len(external_latencies), 1), 2),
            "p50": _percentile(external_latencies, 0.50),
            "p95": _percentile(external_latencies, 0.95),
        },
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

    print(json.dumps(summary, ensure_ascii=True, indent=2, sort_keys=True))
    return summary


def _run_injected_provider(
    *,
    template: TemplateProvider,
    inference_request: Any,
    failure_mode: str,
    fail_every: int,
    event_index: int,
    extra_latency_ms: int,
) -> tuple[Any, bool]:
    should_inject = event_index % fail_every == 0
    if failure_mode == "high_latency" and should_inject:
        time.sleep(extra_latency_ms / 1000.0)
        return template.infer(inference_request), True
    if not should_inject or failure_mode == "none":
        return template.infer(inference_request), False
    if failure_mode == "timeout":
        time.sleep(extra_latency_ms / 1000.0)
        raise RuntimeError("simulated provider timeout")
    if failure_mode == "exception":
        raise RuntimeError("simulated provider exception")
    if failure_mode == "invalid_schema":
        payload = {
            "summary": "schema-invalid fallback candidate",
            "hypotheses": [],
            "recommended_actions": [],
            "confidence_label": "medium",
        }
        return inference_result_from_payload(inference_request.request_id, "failure_injector", "invalid_schema", payload), True
    raise ValueError(f"unsupported failure mode: {failure_mode}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Inject provider failures and verify admission/serving isolation.")
    parser.add_argument("--alert-dir", default=DEFAULT_ALERT_DIR)
    parser.add_argument("--limit-files", type=int, default=0)
    parser.add_argument("--max-alerts", type=int, default=0)
    parser.add_argument("--sample-per-scenario-device", type=int, default=0)
    parser.add_argument("--failure-mode", choices=["none", "timeout", "exception", "invalid_schema", "high_latency"], default="timeout")
    parser.add_argument("--fail-every", type=int, default=1)
    parser.add_argument("--extra-latency-ms", type=int, default=2000)
    parser.add_argument("--fallback-on-invalid-schema", action="store_true", default=True)
    parser.add_argument("--output-json", default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-jsonl", default=DEFAULT_OUTPUT_JSONL)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
