import json
import logging
from collections import Counter
from statistics import mean
from typing import Any

LOGGER = logging.getLogger(__name__)


def recent_similar_count(client: Any, db: str, table: str, rule_id: str, service: str) -> int:
    if client is None:
        return 0
    try:
        result = client.query(
            f"""
            SELECT count()
            FROM {db}.{table}
            WHERE rule_id = %(rule_id)s
              AND service = %(service)s
              AND emit_ts >= now() - INTERVAL 1 HOUR
            """,
            parameters={"rule_id": rule_id, "service": service},
        )
        value = getattr(result, "first_item", 0)
        if isinstance(value, dict):
            value = next(iter(value.values()), 0)
        return int(value or 0)
    except Exception:
        LOGGER.exception("failed to query clickhouse context")
        return 0


def build_alert_history_context(
    client: Any,
    db: str,
    table: str,
    alert: dict[str, Any],
    *,
    local_limit: int = 5,
    baseline_limit: int = 40,
) -> dict[str, Any]:
    excerpt = alert.get("event_excerpt") or {}
    metrics = alert.get("metrics") or {}
    topology = alert.get("topology_context") or {}
    current_rule = str(alert.get("rule_id") or "unknown")
    current_service = str(excerpt.get("service") or topology.get("service") or "unknown")
    current_device = str(excerpt.get("src_device_key") or topology.get("src_device_key") or "")
    current_srcip = str(excerpt.get("srcip") or topology.get("srcip") or "")

    fallback = {
        "recent_alert_samples": [],
        "historical_baseline": _build_historical_baseline(current_rule, metrics, []),
        "recent_policy_hits": [],
        "recent_path_hits": [],
        "recent_change_records": [],
    }
    if client is None:
        return fallback

    try:
        local_rows = _query_alert_rows(
            client,
            db,
            table,
            rule_id=current_rule,
            service=current_service,
            src_device_key=current_device,
            srcip=current_srcip,
            limit=local_limit,
            constrain_entity=True,
        )
        baseline_rows = _query_alert_rows(
            client,
            db,
            table,
            rule_id=current_rule,
            service=current_service,
            src_device_key=current_device,
            srcip=current_srcip,
            limit=baseline_limit,
            constrain_entity=False,
        )
    except Exception:
        LOGGER.exception("failed to query alert history context")
        return fallback

    recent_alert_samples = [_compact_alert_row(row) for row in local_rows]
    policy_hits = _policy_hits(local_rows)
    path_hits = _path_hits(local_rows)
    change_records = _change_records(baseline_rows)

    return {
        "recent_alert_samples": recent_alert_samples,
        "historical_baseline": _build_historical_baseline(current_rule, metrics, baseline_rows),
        "recent_policy_hits": policy_hits,
        "recent_path_hits": path_hits,
        "recent_change_records": change_records,
    }


def _query_alert_rows(
    client: Any,
    db: str,
    table: str,
    *,
    rule_id: str,
    service: str,
    src_device_key: str,
    srcip: str,
    limit: int,
    constrain_entity: bool,
) -> list[dict[str, Any]]:
    extra_filter = ""
    if constrain_entity and (src_device_key or srcip):
        extra_filter = (
            "AND (src_device_key = %(src_device_key)s"
            " OR srcip = %(srcip)s)"
        )

    result = client.query(
        f"""
        SELECT
            alert_id,
            alert_ts,
            severity,
            source_event_id,
            service,
            src_device_key,
            srcip,
            dstip,
            metrics_json,
            dimensions_json,
            event_excerpt_json,
            topology_context_json,
            device_profile_json,
            change_context_json
        FROM {db}.{table}
        WHERE rule_id = %(rule_id)s
          AND service = %(service)s
          AND emit_ts >= now() - INTERVAL 24 HOUR
          {extra_filter}
        ORDER BY alert_ts DESC
        LIMIT %(limit)s
        """,
        parameters={
            "rule_id": rule_id,
            "service": service,
            "src_device_key": src_device_key,
            "srcip": srcip,
            "limit": max(limit, 1),
        },
    )
    return _result_rows(result)


def _result_rows(result: Any) -> list[dict[str, Any]]:
    rows = getattr(result, "result_rows", None)
    columns = list(getattr(result, "column_names", []) or [])
    if not rows:
        return []
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, dict):
            normalized.append(dict(row))
            continue
        if columns and isinstance(row, (list, tuple)) and len(row) == len(columns):
            normalized.append(dict(zip(columns, row)))
    return normalized


def _json_mapping(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _json_scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return " · ".join(str(item).strip() for item in value if str(item).strip())
    return str(value).strip()


def _compact_alert_row(row: dict[str, Any]) -> dict[str, Any]:
    excerpt = _json_mapping(row.get("event_excerpt_json"))
    topology = _json_mapping(row.get("topology_context_json"))
    metrics = _json_mapping(row.get("metrics_json"))
    return {
        "alert_id": str(row.get("alert_id") or ""),
        "alert_ts": str(row.get("alert_ts") or ""),
        "service": str(row.get("service") or excerpt.get("service") or ""),
        "src_device_key": str(row.get("src_device_key") or excerpt.get("src_device_key") or ""),
        "srcip": str(row.get("srcip") or excerpt.get("srcip") or ""),
        "dstip": str(row.get("dstip") or excerpt.get("dstip") or ""),
        "policyid": _json_scalar(excerpt.get("policyid") or topology.get("policyid")),
        "sessionid": _json_scalar(excerpt.get("sessionid")),
        "srcintf": _json_scalar(excerpt.get("srcintf") or topology.get("srcintf")),
        "dstintf": _json_scalar(excerpt.get("dstintf") or topology.get("dstintf")),
        "srcintfrole": _json_scalar(excerpt.get("srcintfrole") or topology.get("srcintfrole")),
        "dstintfrole": _json_scalar(excerpt.get("dstintfrole") or topology.get("dstintfrole")),
        "action": _json_scalar(excerpt.get("action")),
        "proto": _json_scalar(excerpt.get("proto")),
        "srcport": _json_scalar(excerpt.get("srcport")),
        "dstport": _json_scalar(excerpt.get("dstport")),
        "deny_count": _safe_int(metrics.get("deny_count")),
        "bytes_sum": _safe_int(metrics.get("bytes_sum")),
        "threshold": _safe_int(metrics.get("threshold")),
        "window_sec": _safe_int(metrics.get("window_sec")),
    }


def _policy_hits(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    for row in rows:
        excerpt = _json_mapping(row.get("event_excerpt_json"))
        topology = _json_mapping(row.get("topology_context_json"))
        policy_id = _json_scalar(excerpt.get("policyid") or topology.get("policyid")) or "unknown"
        counts[policy_id] += 1
    return [
        {"policyid": policy_id, "count": count}
        for policy_id, count in counts.most_common(3)
    ]


def _path_hits(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    for row in rows:
        excerpt = _json_mapping(row.get("event_excerpt_json"))
        topology = _json_mapping(row.get("topology_context_json"))
        srcintf = _json_scalar(excerpt.get("srcintf") or topology.get("srcintf")) or "unknown"
        dstintf = _json_scalar(excerpt.get("dstintf") or topology.get("dstintf")) or "unknown"
        counts[f"{srcintf}->{dstintf}"] += 1
    return [
        {"path": path, "count": count}
        for path, count in counts.most_common(3)
    ]


def _change_records(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row in rows:
        change_context = _json_mapping(row.get("change_context_json"))
        if not change_context or not bool(change_context.get("suspected_change")):
            continue
        records.append(
            {
                "alert_ts": str(row.get("alert_ts") or ""),
                "level": _json_scalar(change_context.get("level")),
                "action": _json_scalar(change_context.get("action")),
                "change_refs": change_context.get("change_refs") if isinstance(change_context.get("change_refs"), list) else [],
            }
        )
        if len(records) >= 3:
            break
    return records


def _build_historical_baseline(
    rule_id: str,
    current_metrics: dict[str, Any],
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    metric_key = "deny_count" if rule_id == "deny_burst_v1" else "bytes_sum"
    current_metric_value = _safe_int(current_metrics.get(metric_key)) or 0
    threshold = _safe_int(current_metrics.get("threshold")) or 0

    values: list[int] = []
    for row in rows:
        metrics = _json_mapping(row.get("metrics_json"))
        value = _safe_int(metrics.get(metric_key))
        if value and value > 0:
            values.append(value)

    sample_count = len(values)
    avg_value = round(mean(values), 2) if values else 0
    max_value = max(values) if values else 0
    min_value = min(values) if values else 0
    threshold_ratio = round(current_metric_value / threshold, 2) if threshold > 0 else 0
    vs_recent_max_ratio = round(current_metric_value / max_value, 2) if max_value > 0 else None

    return {
        "metric_key": metric_key,
        "current_value": current_metric_value,
        "threshold": threshold,
        "threshold_ratio": threshold_ratio,
        "sample_count_24h": sample_count,
        "avg_24h": avg_value,
        "max_24h": max_value,
        "min_24h": min_value,
        "vs_recent_max_ratio": vs_recent_max_ratio,
    }


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
