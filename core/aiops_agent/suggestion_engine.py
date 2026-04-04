import hashlib
from datetime import datetime, timezone
from typing import Any

from core.aiops_agent.cluster_aggregator import ClusterTrigger
from core.aiops_agent.inference_schema import InferenceRequest, InferenceResult


def _priority_for_severity(severity: str) -> str:
    return "P2" if severity == "warning" else "P1"


def _confidence_for_context(severity: str, recent_similar_1h: int) -> float:
    confidence = 0.65 if severity == "warning" else 0.8
    if recent_similar_1h > 20:
        confidence = min(confidence + 0.1, 0.95)
    return round(confidence, 2)


def build_pipeline_suggestion(
    alert: dict[str, Any],
    trigger: ClusterTrigger,
    evidence_bundle: dict[str, Any],
    inference_request: InferenceRequest,
    inference_result: InferenceResult,
) -> dict[str, Any]:
    history = evidence_bundle.get("historical_context") or {}
    topology = evidence_bundle.get("topology_context") or {}
    return _build_pipeline_suggestion_payload(
        alert=alert,
        rule_id=trigger.key.rule_id,
        severity=trigger.key.severity,
        service=topology.get("service") or trigger.key.service,
        src_device_key=topology.get("src_device_key") or trigger.key.src_device_key,
        cluster_size=int(history.get("cluster_size") or trigger.cluster_size),
        cluster_window_sec=int(history.get("cluster_window_sec") or trigger.window_sec),
        cluster_first_alert_ts=str(history.get("cluster_first_alert_ts") or trigger.first_alert_ts),
        cluster_last_alert_ts=str(history.get("cluster_last_alert_ts") or trigger.last_alert_ts),
        cluster_sample_alert_ids=history.get("cluster_sample_alert_ids") or trigger.sample_alert_ids,
        recent_similar_1h=int(history.get("recent_similar_1h") or 0),
        evidence_bundle=evidence_bundle,
        inference_request=inference_request,
        inference_result=inference_result,
    )


def build_alert_pipeline_suggestion(
    alert: dict[str, Any],
    evidence_bundle: dict[str, Any],
    inference_request: InferenceRequest,
    inference_result: InferenceResult,
) -> dict[str, Any]:
    excerpt = alert.get("event_excerpt") or {}
    history = evidence_bundle.get("historical_context") or {}
    topology = evidence_bundle.get("topology_context") or {}
    return _build_pipeline_suggestion_payload(
        alert=alert,
        rule_id=str(alert.get("rule_id") or "unknown"),
        severity=str(alert.get("severity") or "unknown").lower(),
        service=topology.get("service") or excerpt.get("service") or "",
        src_device_key=topology.get("src_device_key") or excerpt.get("src_device_key") or "",
        cluster_size=int(history.get("cluster_size") or 1),
        cluster_window_sec=int(history.get("cluster_window_sec") or 0),
        cluster_first_alert_ts=str(history.get("cluster_first_alert_ts") or alert.get("alert_ts") or ""),
        cluster_last_alert_ts=str(history.get("cluster_last_alert_ts") or alert.get("alert_ts") or ""),
        cluster_sample_alert_ids=history.get("cluster_sample_alert_ids") or [str(alert.get("alert_id") or "")],
        recent_similar_1h=int(history.get("recent_similar_1h") or 0),
        evidence_bundle=evidence_bundle,
        inference_request=inference_request,
        inference_result=inference_result,
    )


def _build_pipeline_suggestion_payload(
    alert: dict[str, Any],
    rule_id: str,
    severity: str,
    service: str,
    src_device_key: str,
    cluster_size: int,
    cluster_window_sec: int,
    cluster_first_alert_ts: str,
    cluster_last_alert_ts: str,
    cluster_sample_alert_ids: list[str],
    recent_similar_1h: int,
    evidence_bundle: dict[str, Any],
    inference_request: InferenceRequest,
    inference_result: InferenceResult,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    alert_id = str(alert.get("alert_id") or "")
    seed = f"{inference_request.request_id}|{inference_result.provider_name}|{now.isoformat()}"
    suggestion_id = hashlib.sha1(seed.encode("utf-8"), usedforsecurity=False).hexdigest()

    return {
        "schema_version": 2,
        "suggestion_id": suggestion_id,
        "suggestion_ts": now.isoformat(),
        "suggestion_scope": inference_request.suggestion_scope,
        "alert_id": alert_id,
        "rule_id": rule_id,
        "severity": severity,
        "priority": inference_request.priority,
        "summary": inference_result.summary,
        "context": {
            "service": service,
            "src_device_key": src_device_key,
            "cluster_size": cluster_size,
            "cluster_window_sec": cluster_window_sec,
            "cluster_first_alert_ts": cluster_first_alert_ts,
            "cluster_last_alert_ts": cluster_last_alert_ts,
            "cluster_sample_alert_ids": cluster_sample_alert_ids,
            "recent_similar_1h": recent_similar_1h,
            "evidence_bundle_id": evidence_bundle.get("bundle_id"),
            "inference_request_id": inference_request.request_id,
            "provider": inference_result.provider_name,
        },
        "evidence_bundle": evidence_bundle,
        "projection_basis": inference_result.raw_response.get("projection_basis", {}),
        "inference": inference_result.to_payload(),
        "hypotheses": inference_result.hypotheses,
        "recommended_actions": inference_result.recommended_actions,
        "confidence": inference_result.confidence_score,
        "confidence_label": inference_result.confidence_label,
        "confidence_reason": inference_result.confidence_reason,
    }
