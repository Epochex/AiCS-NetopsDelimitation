import json
from dataclasses import dataclass
from typing import Any, Protocol
from urllib import error, request

from core.aiops_agent.app_config import AgentConfig
from core.aiops_agent.inference_schema import InferenceRequest, InferenceResult, inference_result_from_payload


class AIOpsProvider(Protocol):
    name: str
    kind: str

    def infer(self, inference_request: InferenceRequest) -> InferenceResult:
        ...


@dataclass(frozen=True)
class TemplateProvider:
    name: str = "template"
    kind: str = "builtin"

    def infer(self, inference_request: InferenceRequest) -> InferenceResult:
        evidence = inference_request.evidence_bundle
        topology = evidence.get("topology_context") or {}
        history = evidence.get("historical_context") or {}
        rule_context = evidence.get("rule_context") or {}
        device = evidence.get("device_context") or {}
        change = evidence.get("change_context") or {}
        recent_similar_1h = int(history.get("recent_similar_1h") or 0)

        if inference_request.suggestion_scope == "alert":
            summary = (
                f"{inference_request.rule_id} triggered for service={topology.get('service') or 'unknown'} "
                f"device={device.get('src_device_key') or 'unknown'}"
            )
            hypotheses = [
                "The alert may indicate a localized policy or traffic anomaly on this source device.",
                "The observed traffic class may have drifted from the current deterministic rule baseline.",
            ]
            if change.get("suspected_change"):
                hypotheses.append("Recent risk/change indicators suggest the device behavior may have changed.")

            recommended_actions = [
                "Inspect the source device session trace and recent deny history in ClickHouse.",
                "Check whether the affected service is expected for this device profile and interface path.",
                "If this repeats, compare it with the cluster-level suggestion stream before tuning thresholds.",
            ]

            confidence_score = 0.66 if inference_request.severity == "warning" else 0.78
            if recent_similar_1h > 20:
                confidence_score += 0.07
            if change.get("suspected_change"):
                confidence_score += 0.05
            confidence_score = round(min(confidence_score, 0.92), 2)

            confidence_reason = (
                "Confidence is based on alert severity, one-hour recurrence, and whether change/risk markers exist."
            )
            payload = {
                "summary": summary,
                "hypotheses": hypotheses,
                "recommended_actions": recommended_actions,
                "confidence_score": confidence_score,
                "confidence_label": "high" if confidence_score >= 0.85 else "medium",
                "confidence_reason": confidence_reason,
                "rule_context": rule_context,
            }
            return inference_result_from_payload(inference_request.request_id, self.name, self.kind, payload)

        summary = (
            f"{inference_request.rule_id} clustered {history.get('cluster_size', 0)} alerts in "
            f"{history.get('cluster_window_sec', 0)}s for service={topology.get('service') or 'unknown'} "
            f"device={device.get('src_device_key') or 'unknown'}"
        )

        hypotheses = [
            "Repeated alerts indicate a persistent pattern rather than an isolated event.",
            "The current rule threshold or cooldown may be too tight for the observed traffic class.",
        ]
        if change.get("suspected_change"):
            hypotheses.append("A recent change may have altered expected service behavior for this device.")

        recommended_actions = [
            "Inspect correlated source device and service activity for the last 15 minutes in ClickHouse.",
            "Validate whether the cluster overlaps with maintenance, rollout, or baseline changes.",
            "If traffic is expected, tune correlator profile thresholds with canary rollout and monitor impact.",
        ]

        cluster_size = int(history.get("cluster_size") or 0)
        confidence_score = 0.7 if inference_request.severity == "warning" else 0.82
        if recent_similar_1h > 20:
            confidence_score += 0.08
        if cluster_size >= 5:
            confidence_score += 0.05
        confidence_score = round(min(confidence_score, 0.96), 2)

        confidence_reason = (
            "Confidence increases when the cluster is large, historical recurrence is high, and the rule context is stable."
        )

        payload = {
            "summary": summary,
            "hypotheses": hypotheses,
            "recommended_actions": recommended_actions,
            "confidence_score": confidence_score,
            "confidence_label": "high" if confidence_score >= 0.85 else "medium",
            "confidence_reason": confidence_reason,
            "rule_context": rule_context,
        }
        return inference_result_from_payload(inference_request.request_id, self.name, self.kind, payload)


@dataclass(frozen=True)
class HTTPInferenceProvider:
    endpoint_url: str
    api_key: str
    model: str
    timeout_sec: int
    name: str = "http"
    kind: str = "external_api"

    def infer(self, inference_request: InferenceRequest) -> InferenceResult:
        body = json.dumps(
            {
                "model": self.model,
                "input": inference_request.to_payload(),
            },
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        req = request.Request(self.endpoint_url, data=body, headers=headers, method="POST")
        try:
            with request.urlopen(req, timeout=self.timeout_sec) as resp:
                raw = resp.read().decode("utf-8")
        except error.URLError as exc:
            raise RuntimeError(f"http provider request failed: {exc}") from exc

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError("http provider returned invalid json") from exc

        output = payload.get("output") if isinstance(payload.get("output"), dict) else payload
        return inference_result_from_payload(inference_request.request_id, self.name, self.kind, output)


def build_provider(config: AgentConfig) -> AIOpsProvider:
    provider = config.provider.lower()
    if provider == "http":
        return HTTPInferenceProvider(
            endpoint_url=config.provider_endpoint_url,
            api_key=config.provider_api_key,
            model=config.provider_model,
            timeout_sec=config.provider_timeout_sec,
        )
    return TemplateProvider()
