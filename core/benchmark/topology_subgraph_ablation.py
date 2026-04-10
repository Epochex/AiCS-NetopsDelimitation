from __future__ import annotations

import argparse
import json
from collections import Counter, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from core.aiops_agent.evidence_bundle import build_alert_evidence_bundle


def _parse_ts(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iter_alerts(alert_dir: Path, limit_files: int) -> list[dict[str, Any]]:
    files = sorted(alert_dir.glob("alerts-*.jsonl"))
    if limit_files > 0:
        files = files[-limit_files:]
    alerts: list[dict[str, Any]] = []
    for path in files:
        with path.open(encoding="utf-8") as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                try:
                    alert = json.loads(line)
                except json.JSONDecodeError:
                    continue
                alert["_source_file"] = path.name
                alerts.append(alert)
    alerts.sort(
        key=lambda item: (
            _parse_ts(item.get("alert_ts")) or datetime.min.replace(tzinfo=timezone.utc),
            str(item.get("alert_id") or ""),
        )
    )
    return alerts


def _is_high_value(alert: dict[str, Any]) -> bool:
    severity = str(alert.get("severity") or "").lower()
    dimensions = alert.get("dimensions") or {}
    metrics = alert.get("metrics") or {}
    scenario = str(
        dimensions.get("fault_scenario")
        or metrics.get("label_value")
        or metrics.get("scenario")
        or ""
    ).lower()
    if severity == "critical":
        return True
    if scenario and scenario not in {"healthy", "transient_fault", "transient_healthy"}:
        return True
    return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare invoke-all reasoning with topology-aware selective LLM invocation."
    )
    parser.add_argument("--alert-dir", default="/data/netops-runtime/alerts")
    parser.add_argument("--limit-files", type=int, default=24)
    parser.add_argument("--output-json", default="")
    args = parser.parse_args()

    alerts = _iter_alerts(Path(args.alert_dir), args.limit_files)
    total = 0
    kept = 0
    high_value = 0
    high_value_kept = 0
    selected_nodes_total = 0
    noise_nodes_total = 0
    gate_reasons: Counter[str] = Counter()
    rule_counts: Counter[str] = Counter()
    history: deque[tuple[datetime, str, str]] = deque()

    for alert in alerts:
        alert_ts = _parse_ts(alert.get("alert_ts"))
        total += 1
        rule_id = str(alert.get("rule_id") or "unknown")
        excerpt = alert.get("event_excerpt") or {}
        service = str(excerpt.get("service") or "unknown")
        rule_counts[rule_id] += 1
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
        should_invoke = bool(gate.get("should_invoke_llm"))
        if should_invoke:
            kept += 1
        if _is_high_value(alert):
            high_value += 1
            if should_invoke:
                high_value_kept += 1
        selected_nodes_total += int(subgraph.get("selected_node_count") or 0)
        noise_nodes_total += int(subgraph.get("noise_node_count") or 0)
        gate_reasons[str(gate.get("reason") or "unknown")] += 1

    total_safe = max(total, 1)
    high_value_safe = max(high_value, 1)
    report = {
        "evaluation_ts": datetime.now(timezone.utc).isoformat(),
        "alert_dir": str(args.alert_dir),
        "limit_files": args.limit_files,
        "alerts_scanned": total,
        "full_invocation_requests": total,
        "topology_gated_requests": kept,
        "llm_call_reduction_ratio": round(1 - (kept / total_safe), 6),
        "llm_call_reduction_percent": round((1 - (kept / total_safe)) * 100, 2),
        "high_value_alerts": high_value,
        "high_value_alert_recall": round(high_value_kept / high_value_safe, 6),
        "avg_selected_nodes": round(selected_nodes_total / total_safe, 3),
        "avg_noise_nodes": round(noise_nodes_total / total_safe, 3),
        "gate_reasons": dict(gate_reasons.most_common()),
        "rule_counts": dict(rule_counts.most_common()),
    }
    if args.output_json:
        path = Path(args.output_json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
