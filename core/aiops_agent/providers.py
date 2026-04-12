import json
from dataclasses import dataclass, replace
from typing import Any, Protocol
from urllib import error, request

from core.aiops_agent.app_config import AgentConfig
from core.aiops_agent.inference_schema import InferenceRequest, InferenceResult, inference_result_from_payload
from core.aiops_agent.provider_routing import build_provider_routing_hint


class AIOpsProvider(Protocol):
    name: str
    kind: str

    def infer(self, inference_request: InferenceRequest) -> InferenceResult:
        ...


def _text(value: Any, default: str = "unknown") -> str:
    if isinstance(value, str):
        text = value.strip()
        return text or default
    if value is None:
        return default
    return str(value).strip() or default


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            items.append(text)
    return items


def _device_label(device: dict[str, Any], fallback: str) -> str:
    for key in ("device_name", "src_device_key", "vendor", "family", "device_role"):
        text = _text(device.get(key), "")
        if text:
            return text
    return fallback


def _path_signature(topology: dict[str, Any], path_context: dict[str, Any]) -> str:
    for key in ("path_signature",):
        text = _text(path_context.get(key), "")
        if text:
            return text
    srcintf = _text(path_context.get("srcintf") or topology.get("srcintf"), "")
    dstintf = _text(path_context.get("dstintf") or topology.get("dstintf"), "")
    if srcintf or dstintf:
        return f"{srcintf or 'unknown'}->{dstintf or 'unknown'}"
    return "unknown->unknown"


def _sample_text(sample: dict[str, Any]) -> str:
    return (
        f"{_text(sample.get('alert_ts'))} "
        f"{_text(sample.get('srcip'))}:{_text(sample.get('srcport'), '-')} -> "
        f"{_text(sample.get('dstip'))}:{_text(sample.get('dstport'), '-')} "
        f"policy={_text(sample.get('policyid'), 'unknown')} "
        f"path={_text(sample.get('srcintf'), 'unknown')}->{_text(sample.get('dstintf'), 'unknown')}"
    )


def _basis(
    label: str,
    section: str,
    field: str,
    value: Any,
    reason: str,
) -> dict[str, str]:
    return {
        "label": label,
        "section": section,
        "field": field,
        "value": _text(value, ""),
        "reason": reason,
    }


def _projection_basis(
    *,
    trigger: list[dict[str, str]],
    aggregate: list[dict[str, str]],
    path: list[dict[str, str]],
    device: list[dict[str, str]],
    inference: list[dict[str, str]],
    action: list[dict[str, str]],
) -> dict[str, list[dict[str, str]]]:
    return {
        "projector-trigger": trigger,
        "projector-aggregate": aggregate,
        "projector-path": path,
        "projector-device": device,
        "projector-inference": inference,
        "projector-action": action,
    }


def _known_service_mismatch(device: dict[str, Any], service: str) -> bool:
    known_services = _string_list(device.get("known_services"))
    return bool(known_services) and service not in known_services


def _recent_sample_lines(samples: list[dict[str, Any]], limit: int = 2) -> list[str]:
    return [_sample_text(sample) for sample in samples[:limit]]


def _clamp_confidence(value: float) -> float:
    return round(min(max(value, 0.35), 0.97), 2)


def _base_context(inference_request: InferenceRequest) -> dict[str, Any]:
    evidence = inference_request.evidence_bundle
    return {
        "topology": evidence.get("topology_context") or {},
        "history": evidence.get("historical_context") or {},
        "rule_context": evidence.get("rule_context") or {},
        "device": evidence.get("device_context") or {},
        "change": evidence.get("change_context") or {},
        "path": evidence.get("path_context") or {},
        "policy": evidence.get("policy_context") or {},
        "samples": evidence.get("sample_context") or {},
    }


def _build_deny_alert_payload(inference_request: InferenceRequest) -> dict[str, Any]:
    ctx = _base_context(inference_request)
    topology = ctx["topology"]
    history = ctx["history"]
    rule_context = ctx["rule_context"]
    device = ctx["device"]
    change = ctx["change"]
    path = ctx["path"]
    policy = ctx["policy"]
    samples = _string_list([])

    service = _text(topology.get("service"))
    device_key = _text(device.get("src_device_key"), _text(topology.get("src_device_key")))
    device_label = _device_label(device, device_key)
    policy_id = _text(policy.get("policyid"), "unknown")
    current_path = _path_signature(topology, path)
    deny_count = _int((rule_context.get("metrics") or {}).get("deny_count"))
    window_sec = _int((rule_context.get("metrics") or {}).get("window_sec"), 60)
    threshold = _int((rule_context.get("metrics") or {}).get("threshold"))
    recent_similar_1h = _int(history.get("recent_similar_1h"))
    known_service_mismatch = _known_service_mismatch(device, service)
    baseline = history.get("historical_baseline") or {}
    recent_samples = history.get("recent_alert_samples") or []
    sample_lines = _recent_sample_lines(recent_samples)
    change_refs = _string_list(change.get("change_refs"))

    summary = (
        f"{device_label} reached {deny_count}/{threshold} denies for {service} inside "
        f"{window_sec}s on {current_path}; policy={policy_id}; recent_similar_1h={recent_similar_1h}."
    )

    hypotheses = []
    if policy_id in {"0", "unknown"}:
        hypotheses.append(
            f"The repeated deny pattern is consistent with a policy miss or interface/zone mismatch on {current_path}."
        )
    else:
        hypotheses.append(
            f"Policy {policy_id} is repeatedly denying {service}; verify whether that rule still matches the intended posture for {device_label}."
        )
    if known_service_mismatch:
        hypotheses.append(
            f"{service} is not listed in the current known_services profile for {device_label}, so profile drift or a new workload should be verified."
        )
    if change.get("suspected_change"):
        hypotheses.append(
            "Recent change markers are attached to the alert, so the deny burst may be change-adjacent rather than purely stochastic."
        )
    if not hypotheses:
        hypotheses.append(
            "The deny burst is repeated enough to justify checking policy intent, path intent, and device profile together."
        )

    recommended_actions = []
    if policy_id in {"0", "unknown"}:
        recommended_actions.append(
            f"Verify whether an explicit allow policy should exist for {service} on {current_path}; confirm src={_text(topology.get('srcip'))}, dst={_text(topology.get('dstip'))}, srcintf={_text(path.get('srcintf'))}, dstintf={_text(path.get('dstintf'))} before changing policy."
        )
    else:
        recommended_actions.append(
            f"Review FortiGate policy {policy_id} hit conditions and rule order for {service} on {current_path}; confirm whether the current deny is intended for {device_label}."
        )
    if sample_lines:
        recommended_actions.append(
            "Replay the most recent deny samples first and compare tuple repetition before widening the investigation: "
            + " | ".join(sample_lines)
        )
    recommended_actions.append(
        f"Query the last 15 minutes in ClickHouse using rule_id={inference_request.rule_id}, service={service}, src_device_key={device_key}, and srcip={_text(topology.get('srcip'))} to confirm whether the same tuple, path, and policy repeat."
    )
    if known_service_mismatch:
        recommended_actions.append(
            f"Check whether {service} should be added to the device profile for {device_label}; if yes, update the baseline before tuning the correlator threshold."
        )
    if change_refs:
        recommended_actions.append(
            "Check the attached change markers before tuning rules: " + ", ".join(change_refs[:3])
        )

    confidence_score = 0.72 if inference_request.severity == "warning" else 0.82
    if recent_similar_1h > 10:
        confidence_score += 0.05
    if policy_id in {"0", "unknown"}:
        confidence_score += 0.03
    if change.get("suspected_change"):
        confidence_score += 0.03
    confidence_score = _clamp_confidence(confidence_score)

    projection_basis = _projection_basis(
        trigger=[
            _basis(
                "deny threshold",
                "rule_context",
                "metrics.deny_count",
                f"{deny_count}/{threshold} in {window_sec}s",
                "This is the deterministic condition that emitted the alert.",
            ),
            _basis(
                "service",
                "topology_context",
                "service",
                service,
                "The suggestion is scoped to the service carried by the alert evidence.",
            ),
        ],
        aggregate=[
            _basis(
                "recent similar",
                "historical_context",
                "recent_similar_1h",
                recent_similar_1h,
                "One-hour recurrence shows whether this is isolated or repeating.",
            ),
            _basis(
                "24h baseline",
                "historical_context",
                "historical_baseline",
                json.dumps(baseline, ensure_ascii=True, separators=(",", ":")),
                "Recent alert history is used as the closest available normal-range reference.",
            ),
        ],
        path=[
            _basis(
                "path",
                "path_context",
                "path_signature",
                current_path,
                "The path is used to decide whether the deny belongs to the expected interface pair.",
            ),
            _basis(
                "recent paths",
                "path_context",
                "recent_path_hits",
                json.dumps(path.get("recent_path_hits") or [], ensure_ascii=True, separators=(",", ":")),
                "Recent path hits show whether the same deny concentrates on one interface path.",
            ),
        ],
        device=[
            _basis(
                "device profile",
                "device_context",
                "device_role",
                f"{_text(device.get('device_role'), '')} / {_text(device.get('vendor'), '')} / {_text(device.get('family'), '')}",
                "Device role and vendor profile constrain which services and paths are expected.",
            ),
            _basis(
                "change markers",
                "change_context",
                "change_refs",
                ", ".join(change_refs[:3]) if change_refs else "none",
                "Change markers indicate whether the incident should be checked against recent rollout or policy changes.",
            ),
        ],
        inference=[
            _basis(
                "policy hit",
                "policy_context",
                "policyid",
                policy_id,
                "Policy hit state distinguishes likely policy miss from explicit deny intent.",
            ),
            _basis(
                "recent samples",
                "sample_context",
                "recent_alert_samples",
                " | ".join(sample_lines) if sample_lines else "none",
                "Recent concrete tuples anchor the diagnosis to repeated evidence instead of a generic story.",
            ),
        ],
        action=[
            _basis(
                "action target",
                "topology_context",
                "srcip,dstip,service",
                f"{_text(topology.get('srcip'))} -> {_text(topology.get('dstip'))} / {service}",
                "The first operator action should use the exact tuple that triggered the deterministic alert.",
            ),
            _basis(
                "policy review",
                "policy_context",
                "recent_policy_hits",
                json.dumps(policy.get("recent_policy_hits") or [], ensure_ascii=True, separators=(",", ":")),
                "Policy-hit history tells the operator whether to start from a missing policy or a stable explicit deny.",
            ),
        ],
    )

    return {
        "summary": summary,
        "hypotheses": hypotheses,
        "recommended_actions": recommended_actions,
        "confidence_score": confidence_score,
        "confidence_label": "high" if confidence_score >= 0.85 else "medium",
        "confidence_reason": (
            "Confidence uses deterministic threshold hit, recurrence, policy visibility, and change markers from the attached evidence bundle."
        ),
        "rule_context": rule_context,
        "projection_basis": projection_basis,
    }


def _build_bytes_alert_payload(inference_request: InferenceRequest) -> dict[str, Any]:
    ctx = _base_context(inference_request)
    topology = ctx["topology"]
    history = ctx["history"]
    rule_context = ctx["rule_context"]
    device = ctx["device"]
    change = ctx["change"]
    path = ctx["path"]
    samples = ctx["samples"]

    service = _text(topology.get("service"))
    device_key = _text(device.get("src_device_key"), _text(topology.get("src_device_key")))
    device_label = _device_label(device, device_key)
    current_path = _path_signature(topology, path)
    bytes_sum = _int((rule_context.get("metrics") or {}).get("bytes_sum"))
    window_sec = _int((rule_context.get("metrics") or {}).get("window_sec"), 300)
    threshold = _int((rule_context.get("metrics") or {}).get("threshold"))
    recent_similar_1h = _int(history.get("recent_similar_1h"))
    baseline = history.get("historical_baseline") or {}
    recent_samples = history.get("recent_alert_samples") or []
    sample_lines = _recent_sample_lines(recent_samples)
    change_refs = _string_list(change.get("change_refs"))
    ratio_to_max = _float(baseline.get("vs_recent_max_ratio"))
    known_service_mismatch = _known_service_mismatch(device, service)

    summary = (
        f"{device_label} accumulated {bytes_sum}/{threshold} bytes for {service} inside "
        f"{window_sec}s on {current_path}; src={_text(topology.get('srcip'))}, dst={_text(topology.get('dstip'))}, recent_similar_1h={recent_similar_1h}."
    )

    hypotheses = [
        f"The current traffic spike is concentrated on {current_path}, so the first check should stay on this source/path slice before tuning thresholds."
    ]
    if ratio_to_max >= 1.2:
        hypotheses.append(
            "The current aggregate exceeds the recent alert maximum, which points to a real intensity shift rather than normal burst variance."
        )
    if known_service_mismatch:
        hypotheses.append(
            f"{service} is outside the known device-service profile for {device_label}, so workload drift or misclassification should be checked."
        )
    if change.get("suspected_change"):
        hypotheses.append(
            "Attached change markers make a recent rollout or policy move a stronger candidate than random traffic noise."
        )

    recommended_actions = [
        f"Pull a 5-minute window around src={_text(topology.get('srcip'))}, dst={_text(topology.get('dstip'))}, service={service}, path={current_path} and confirm whether the spike is concentrated on one tuple or already widening across destinations.",
        f"Compare the current bytes_sum={bytes_sum} with the recent 24h alert baseline avg={baseline.get('avg_24h', 0)} max={baseline.get('max_24h', 0)} before increasing the correlator threshold.",
    ]
    if sample_lines:
        recommended_actions.append(
            "Replay the latest spike samples first to identify the dominant tuple and direction: "
            + " | ".join(sample_lines)
        )
    if change_refs:
        recommended_actions.append(
            "Check the attached change markers before treating the traffic burst as benign: "
            + ", ".join(change_refs[:3])
        )
    if known_service_mismatch:
        recommended_actions.append(
            f"Validate whether {service} is expected for {device_label}; if it is a new workload, update the device profile and baseline rather than only tuning the bytes threshold."
        )

    confidence_score = 0.8 if inference_request.severity == "critical" else 0.7
    if recent_similar_1h > 10:
        confidence_score += 0.04
    if ratio_to_max >= 1.2:
        confidence_score += 0.05
    if change.get("suspected_change"):
        confidence_score += 0.03
    confidence_score = _clamp_confidence(confidence_score)

    projection_basis = _projection_basis(
        trigger=[
            _basis(
                "bytes threshold",
                "rule_context",
                "metrics.bytes_sum",
                f"{bytes_sum}/{threshold} in {window_sec}s",
                "This is the deterministic aggregate that emitted the bytes_spike alert.",
            ),
            _basis(
                "service",
                "topology_context",
                "service",
                service,
                "The spike is evaluated on the same service slice as the alert evidence.",
            ),
        ],
        aggregate=[
            _basis(
                "recent similar",
                "historical_context",
                "recent_similar_1h",
                recent_similar_1h,
                "One-hour recurrence shows whether the spike is repeating.",
            ),
            _basis(
                "24h baseline",
                "historical_context",
                "historical_baseline",
                json.dumps(baseline, ensure_ascii=True, separators=(",", ":")),
                "Historical alert metrics provide the nearest available normal range for comparison.",
            ),
        ],
        path=[
            _basis(
                "path",
                "path_context",
                "path_signature",
                current_path,
                "The interface path is used to decide whether the traffic rise is localized.",
            ),
            _basis(
                "recent paths",
                "path_context",
                "recent_path_hits",
                json.dumps(path.get("recent_path_hits") or [], ensure_ascii=True, separators=(",", ":")),
                "Recent path hits show whether the spike stays on one route.",
            ),
        ],
        device=[
            _basis(
                "device profile",
                "device_context",
                "device_role",
                f"{_text(device.get('device_role'), '')} / {_text(device.get('vendor'), '')} / {_text(device.get('family'), '')}",
                "Device role and family constrain expected traffic posture.",
            ),
            _basis(
                "change markers",
                "change_context",
                "change_refs",
                ", ".join(change_refs[:3]) if change_refs else "none",
                "Change markers indicate whether the traffic rise aligns with a recent change window.",
            ),
        ],
        inference=[
            _basis(
                "sample tuples",
                "sample_context",
                "recent_alert_samples",
                " | ".join(sample_lines) if sample_lines else "none",
                "Recent tuples anchor the traffic explanation to concrete repeated samples.",
            ),
            _basis(
                "recent max ratio",
                "historical_context",
                "historical_baseline.vs_recent_max_ratio",
                baseline.get("vs_recent_max_ratio"),
                "The ratio to recent max helps separate baseline variance from a new spike.",
            ),
        ],
        action=[
            _basis(
                "tuple target",
                "topology_context",
                "srcip,dstip,service",
                f"{_text(topology.get('srcip'))} -> {_text(topology.get('dstip'))} / {service}",
                "The operator should start with the tuple that drove the aggregate.",
            ),
            _basis(
                "recent samples",
                "sample_context",
                "recent_alert_samples",
                " | ".join(sample_lines) if sample_lines else "none",
                "Recent repeated samples tell the operator which path to replay first.",
            ),
        ],
    )

    return {
        "summary": summary,
        "hypotheses": hypotheses,
        "recommended_actions": recommended_actions,
        "confidence_score": confidence_score,
        "confidence_label": "high" if confidence_score >= 0.85 else "medium",
        "confidence_reason": (
            "Confidence uses deterministic aggregate size, historical contrast, recurrence, and change markers from the attached evidence bundle."
        ),
        "rule_context": rule_context,
        "projection_basis": projection_basis,
    }


def _build_cluster_payload(inference_request: InferenceRequest) -> dict[str, Any]:
    ctx = _base_context(inference_request)
    topology = ctx["topology"]
    history = ctx["history"]
    rule_context = ctx["rule_context"]
    device = ctx["device"]
    change = ctx["change"]
    path = ctx["path"]
    policy = ctx["policy"]

    service = _text(topology.get("service"))
    device_key = _text(device.get("src_device_key"), _text(topology.get("src_device_key")))
    device_label = _device_label(device, device_key)
    cluster_size = _int(history.get("cluster_size"), 0)
    cluster_window_sec = _int(history.get("cluster_window_sec"), 0)
    recent_similar_1h = _int(history.get("recent_similar_1h"))
    current_path = _path_signature(topology, path)
    policy_id = _text(policy.get("policyid"), "unknown")
    change_refs = _string_list(change.get("change_refs"))
    baseline = history.get("historical_baseline") or {}

    summary = (
        f"{inference_request.rule_id} clustered {cluster_size} alerts inside {cluster_window_sec}s "
        f"for {service} on {device_label} ({current_path}); recent_similar_1h={recent_similar_1h}."
    )

    hypotheses = [
        "The same-key cluster indicates repeated behavior rather than a single-path transient.",
        f"The repeated pattern is concentrated on {current_path}, so the first review should stay on that service/path slice.",
    ]
    if change.get("suspected_change"):
        hypotheses.append(
            "Recent change markers make a rollout or posture shift a stronger candidate for the repeated pattern."
        )

    recommended_actions = [
        f"Review the last {cluster_window_sec}s cluster window for {service} on {current_path}; confirm whether the same source tuple, policy, or destination repeats across the sample alerts.",
        f"Use rule_id={inference_request.rule_id}, service={service}, src_device_key={device_key} in ClickHouse to compare cluster members before tuning thresholds or cooldowns.",
    ]
    if policy_id not in {"", "unknown"}:
        recommended_actions.append(
            f"Check whether policy {policy_id} is the common denial point across the clustered alerts before modifying the rule profile."
        )
    if change_refs:
        recommended_actions.append(
            "Correlate the cluster onset with attached change markers: " + ", ".join(change_refs[:3])
        )

    confidence_score = 0.78 if inference_request.severity == "warning" else 0.86
    if cluster_size >= 5:
        confidence_score += 0.04
    if recent_similar_1h > 20:
        confidence_score += 0.03
    confidence_score = _clamp_confidence(confidence_score)

    projection_basis = _projection_basis(
        trigger=[
            _basis(
                "cluster gate",
                "historical_context",
                "cluster_size,cluster_window_sec",
                f"{cluster_size}/{cluster_window_sec}s",
                "Cluster size and window define the repeated-pattern trigger.",
            ),
            _basis(
                "service",
                "topology_context",
                "service",
                service,
                "The cluster remains tied to one service slice.",
            ),
        ],
        aggregate=[
            _basis(
                "recent similar",
                "historical_context",
                "recent_similar_1h",
                recent_similar_1h,
                "One-hour recurrence adds historical weight to the cluster decision.",
            ),
            _basis(
                "24h baseline",
                "historical_context",
                "historical_baseline",
                json.dumps(baseline, ensure_ascii=True, separators=(",", ":")),
                "Recent alert metrics provide a simple baseline for how abnormal the cluster looks.",
            ),
        ],
        path=[
            _basis(
                "path",
                "path_context",
                "path_signature",
                current_path,
                "The repeated pattern is anchored to one interface path.",
            ),
            _basis(
                "recent paths",
                "path_context",
                "recent_path_hits",
                json.dumps(path.get("recent_path_hits") or [], ensure_ascii=True, separators=(",", ":")),
                "Recent path hits show whether the cluster is path-stable.",
            ),
        ],
        device=[
            _basis(
                "device profile",
                "device_context",
                "device_role",
                f"{_text(device.get('device_role'), '')} / {_text(device.get('vendor'), '')} / {_text(device.get('family'), '')}",
                "Device profile provides the expected service posture for the clustered alerts.",
            ),
            _basis(
                "change markers",
                "change_context",
                "change_refs",
                ", ".join(change_refs[:3]) if change_refs else "none",
                "Change markers help explain why the pattern may have started recently.",
            ),
        ],
        inference=[
            _basis(
                "policy hit",
                "policy_context",
                "policyid",
                policy_id,
                "Policy visibility helps distinguish repeated policy intent from broader pattern drift.",
            ),
            _basis(
                "cluster sample ids",
                "historical_context",
                "cluster_sample_alert_ids",
                ", ".join(_string_list(history.get("cluster_sample_alert_ids"))[:4]),
                "Cluster sample ids identify the repeated evidence set.",
            ),
        ],
        action=[
            _basis(
                "action target",
                "topology_context",
                "service,path",
                f"{service} / {current_path}",
                "The first operator action should stay on the same clustered service/path slice.",
            ),
            _basis(
                "change review",
                "change_context",
                "recent_change_records",
                json.dumps(history.get("recent_change_records") or [], ensure_ascii=True, separators=(",", ":")),
                "Recent change records tell the operator whether the cluster aligns with a change window.",
            ),
        ],
    )

    return {
        "summary": summary,
        "hypotheses": hypotheses,
        "recommended_actions": recommended_actions,
        "confidence_score": confidence_score,
        "confidence_label": "high" if confidence_score >= 0.85 else "medium",
        "confidence_reason": (
            "Confidence uses cluster size, recurrence, path concentration, and change markers from the attached evidence bundle."
        ),
        "rule_context": rule_context,
        "projection_basis": projection_basis,
    }


@dataclass(frozen=True)
class TemplateProvider:
    name: str = "template"
    kind: str = "builtin"

    def infer(self, inference_request: InferenceRequest) -> InferenceResult:
        if inference_request.suggestion_scope == "cluster":
            payload = _build_cluster_payload(inference_request)
            return inference_result_from_payload(inference_request.request_id, self.name, self.kind, payload)

        if inference_request.rule_id == "deny_burst_v1":
            payload = _build_deny_alert_payload(inference_request)
        elif inference_request.rule_id == "bytes_spike_v1":
            payload = _build_bytes_alert_payload(inference_request)
        else:
            payload = _build_cluster_payload(inference_request)

        return inference_result_from_payload(inference_request.request_id, self.name, self.kind, payload)


@dataclass(frozen=True)
class HTTPInferenceProvider:
    routing_config: AgentConfig
    endpoint_url: str
    api_key: str
    model: str
    timeout_sec: int
    compute_target: str
    max_parallelism: int
    name: str = "http"
    kind: str = "external_model_service"

    def infer(self, inference_request: InferenceRequest) -> InferenceResult:
        routing_hint = build_provider_routing_hint(self.routing_config, inference_request)
        if not bool(routing_hint.get("should_invoke_llm")):
            fallback = TemplateProvider(name=f"{self.name}:template_only").infer(inference_request)
            raw_response = dict(fallback.raw_response)
            raw_response["external_provider_skipped"] = True
            raw_response["external_provider_skip_reason"] = (
                "topology gate selected template_only budget tier"
            )
            raw_response["routing"] = routing_hint
            return replace(
                fallback,
                provider_name=self.name,
                provider_kind="topology_gate_template_fallback",
                raw_response=raw_response,
            )

        body = json.dumps(
            {
                "model": self.model,
                "input": inference_request.to_payload(),
                "routing": routing_hint,
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
    if provider in {"http", "gpu_http", "external_model_service"}:
        return HTTPInferenceProvider(
            routing_config=config,
            endpoint_url=config.provider_endpoint_url,
            api_key=config.provider_api_key,
            model=config.provider_model,
            timeout_sec=config.provider_timeout_sec,
            compute_target=config.provider_compute_target,
            max_parallelism=config.provider_max_parallelism,
            name=provider,
        )
    return TemplateProvider()
