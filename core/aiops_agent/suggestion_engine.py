import hashlib
from datetime import datetime, timezone
from typing import Any

from core.aiops_agent.cluster_aggregator import ClusterTrigger


def _priority_for_severity(severity: str) -> str:
    return "P2" if severity == "warning" else "P1"


def _confidence_for_context(severity: str, recent_similar_1h: int) -> float:
    confidence = 0.65 if severity == "warning" else 0.8
    if recent_similar_1h > 20:
        confidence = min(confidence + 0.1, 0.95)
    return round(confidence, 2)


def build_suggestion(alert: dict[str, Any], recent_similar_1h: int) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    alert_id = str(alert.get("alert_id") or "")
    rule_id = str(alert.get("rule_id") or "unknown")
    severity = str(alert.get("severity") or "unknown").lower()
    excerpt = alert.get("event_excerpt") or {}
    service = str(excerpt.get("service") or "unknown")
    srcip = str(excerpt.get("srcip") or "unknown")
    src_key = str(excerpt.get("src_device_key") or "unknown")

    seed = f"{alert_id}|{now.isoformat()}"
    suggestion_id = hashlib.sha1(seed.encode("utf-8"), usedforsecurity=False).hexdigest()

    return {
        "schema_version": 1,
        "suggestion_id": suggestion_id,
        "suggestion_ts": now.isoformat(),
        "alert_id": alert_id,
        "rule_id": rule_id,
        "severity": severity,
        "priority": _priority_for_severity(severity),
        "summary": f"{rule_id} triggered for service={service} src={srcip}",
        "context": {
            "service": service,
            "srcip": srcip,
            "src_device_key": src_key,
            "recent_similar_1h": recent_similar_1h,
        },
        "hypotheses": [
            "Edge-side noise filter may need refinement for this traffic class.",
            "Device policy baseline may be outdated for current service behavior.",
        ],
        "recommended_actions": [
            "Check edge-forwarder drop counters and recent scan mix for local/broadcast deny traffic.",
            "Inspect top source device/session traces for the last 15 minutes in ClickHouse.",
            "If repeated and expected, tune rule profile threshold/cooldown with canary rollout.",
        ],
        "confidence": _confidence_for_context(severity, recent_similar_1h),
    }


def build_cluster_suggestion(alert: dict[str, Any], trigger: ClusterTrigger, recent_similar_1h: int) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    alert_id = str(alert.get("alert_id") or "")
    summary = (
        f"{trigger.key.rule_id} clustered {trigger.cluster_size} alerts in "
        f"{trigger.window_sec}s for service={trigger.key.service} device={trigger.key.src_device_key}"
    )
    seed = f"{trigger.key.rule_id}|{trigger.key.service}|{trigger.key.src_device_key}|{now.isoformat()}"
    suggestion_id = hashlib.sha1(seed.encode("utf-8"), usedforsecurity=False).hexdigest()
    confidence = min(_confidence_for_context(trigger.key.severity, recent_similar_1h) + 0.05, 0.98)

    return {
        "schema_version": 1,
        "suggestion_id": suggestion_id,
        "suggestion_ts": now.isoformat(),
        "suggestion_scope": "cluster",
        "alert_id": alert_id,
        "rule_id": trigger.key.rule_id,
        "severity": trigger.key.severity,
        "priority": _priority_for_severity(trigger.key.severity),
        "summary": summary,
        "context": {
            "service": trigger.key.service,
            "src_device_key": trigger.key.src_device_key,
            "cluster_size": trigger.cluster_size,
            "cluster_window_sec": trigger.window_sec,
            "cluster_first_alert_ts": trigger.first_alert_ts,
            "cluster_last_alert_ts": trigger.last_alert_ts,
            "cluster_sample_alert_ids": trigger.sample_alert_ids,
            "recent_similar_1h": recent_similar_1h,
        },
        "hypotheses": [
            "Repeated pattern indicates a clustered anomaly rather than a single isolated event.",
            "Threshold/cooldown for this traffic class may require profile tuning.",
        ],
        "recommended_actions": [
            "Validate whether this alert cluster is expected maintenance traffic or abnormal repetition.",
            "Inspect correlated source devices/services in ClickHouse for last 15 minutes.",
            "If expected, tune correlator profile with canary rollout and monitor warning-rate impact.",
        ],
        "confidence": round(confidence, 2),
    }
