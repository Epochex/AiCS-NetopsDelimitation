import hashlib
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from core.aiops_agent.cluster_aggregator import ClusterTrigger


@dataclass(frozen=True)
class InferenceRequest:
    schema_version: int
    request_id: str
    request_ts: str
    request_kind: str
    provider: str
    alert_id: str
    rule_id: str
    severity: str
    priority: str
    suggestion_scope: str
    evidence_bundle: dict[str, Any]
    expected_response_schema: dict[str, Any]

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class InferenceResult:
    schema_version: int
    request_id: str
    provider_name: str
    provider_kind: str
    inference_ts: str
    summary: str
    hypotheses: list[str]
    recommended_actions: list[str]
    confidence_score: float
    confidence_label: str
    confidence_reason: str
    raw_response: dict[str, Any]

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


def build_alert_inference_request(
    alert: dict[str, Any],
    evidence_bundle: dict[str, Any],
    provider: str,
) -> InferenceRequest:
    now = datetime.now(timezone.utc)
    alert_id = str(alert.get("alert_id") or "")
    rule_id = str(alert.get("rule_id") or "unknown")
    severity = str(alert.get("severity") or "unknown").lower()
    seed = f"{alert_id}|{rule_id}|alert|{provider}"
    request_id = hashlib.sha1(seed.encode("utf-8"), usedforsecurity=False).hexdigest()

    return InferenceRequest(
        schema_version=1,
        request_id=request_id,
        request_ts=now.isoformat(),
        request_kind="alert_triage",
        provider=provider,
        alert_id=alert_id,
        rule_id=rule_id,
        severity=severity,
        priority=_priority_for_severity(severity),
        suggestion_scope="alert",
        evidence_bundle=evidence_bundle,
        expected_response_schema={
            "summary": "string",
            "hypotheses": ["string"],
            "recommended_actions": ["string"],
            "confidence_score": "float[0,1]",
            "confidence_label": "low|medium|high",
            "confidence_reason": "string",
        },
    )


def build_cluster_inference_request(
    alert: dict[str, Any],
    trigger: ClusterTrigger,
    evidence_bundle: dict[str, Any],
    provider: str,
) -> InferenceRequest:
    now = datetime.now(timezone.utc)
    alert_id = str(alert.get("alert_id") or "")
    seed = f"{alert_id}|{trigger.key.rule_id}|{trigger.last_alert_ts}|{provider}"
    request_id = hashlib.sha1(seed.encode("utf-8"), usedforsecurity=False).hexdigest()

    return InferenceRequest(
        schema_version=1,
        request_id=request_id,
        request_ts=now.isoformat(),
        request_kind="cluster_triage",
        provider=provider,
        alert_id=alert_id,
        rule_id=trigger.key.rule_id,
        severity=trigger.key.severity,
        priority=_priority_for_severity(trigger.key.severity),
        suggestion_scope="cluster",
        evidence_bundle=evidence_bundle,
        expected_response_schema={
            "summary": "string",
            "hypotheses": ["string"],
            "recommended_actions": ["string"],
            "confidence_score": "float[0,1]",
            "confidence_label": "low|medium|high",
            "confidence_reason": "string",
        },
    )


def inference_result_from_payload(
    request_id: str,
    provider_name: str,
    provider_kind: str,
    payload: dict[str, Any],
) -> InferenceResult:
    hypotheses = _normalize_str_list(payload.get("hypotheses"))
    recommended_actions = _normalize_str_list(payload.get("recommended_actions"))
    confidence_score = _clamp_float(payload.get("confidence_score"), 0.5)
    return InferenceResult(
        schema_version=1,
        request_id=request_id,
        provider_name=provider_name,
        provider_kind=provider_kind,
        inference_ts=datetime.now(timezone.utc).isoformat(),
        summary=str(payload.get("summary") or ""),
        hypotheses=hypotheses,
        recommended_actions=recommended_actions,
        confidence_score=confidence_score,
        confidence_label=_normalize_confidence_label(payload.get("confidence_label"), confidence_score),
        confidence_reason=str(payload.get("confidence_reason") or ""),
        raw_response=payload,
    )


def _priority_for_severity(severity: str) -> str:
    return "P2" if severity == "warning" else "P1"


def _normalize_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    items = []
    for item in value:
        text = str(item).strip()
        if text:
            items.append(text)
    return items


def _clamp_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return round(min(max(parsed, 0.0), 1.0), 2)


def _normalize_confidence_label(raw: Any, score: float) -> str:
    label = str(raw or "").lower()
    if label in {"low", "medium", "high"}:
        return label
    if score >= 0.85:
        return "high"
    if score >= 0.6:
        return "medium"
    return "low"
