from __future__ import annotations

import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib import error, request


HOST = os.environ.get("NETOPS_GATEWAY_HOST", "127.0.0.1")
PORT = int(os.environ.get("NETOPS_GATEWAY_PORT", "18080"))
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "http://127.0.0.1:8000/v1")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "glm-fast")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_TIMEOUT_SEC = int(os.environ.get("OPENAI_TIMEOUT_SEC", "90"))
MAX_TOKENS = int(os.environ.get("OPENAI_MAX_TOKENS", "1536"))
TEMPERATURE = float(os.environ.get("OPENAI_TEMPERATURE", "0.2"))
DRY_RUN = os.environ.get("NETOPS_GATEWAY_DRY_RUN", "").lower() in {"1", "true", "yes"}


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    raw = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(raw)))
    handler.end_headers()
    handler.wfile.write(raw)


def _compact_request(provider_body: dict[str, Any]) -> dict[str, Any]:
    input_payload = provider_body.get("input") if isinstance(provider_body.get("input"), dict) else {}
    bundle = input_payload.get("evidence_bundle") if isinstance(input_payload.get("evidence_bundle"), dict) else {}
    evidence_pack = bundle.get("evidence_pack_v2") if isinstance(bundle.get("evidence_pack_v2"), dict) else {}
    topology_subgraph = bundle.get("topology_subgraph") if isinstance(bundle.get("topology_subgraph"), dict) else {}
    gate = topology_subgraph.get("llm_invocation_gate") if isinstance(topology_subgraph.get("llm_invocation_gate"), dict) else {}
    return {
        "request_id": input_payload.get("request_id"),
        "request_kind": input_payload.get("request_kind"),
        "alert_id": input_payload.get("alert_id"),
        "rule_id": input_payload.get("rule_id"),
        "severity": input_payload.get("severity"),
        "expected_response_schema": input_payload.get("expected_response_schema"),
        "routing": provider_body.get("routing"),
        "topology_context": bundle.get("topology_context"),
        "historical_context": bundle.get("historical_context"),
        "rule_context": bundle.get("rule_context"),
        "path_context": bundle.get("path_context"),
        "device_context": bundle.get("device_context"),
        "topology_subgraph_summary": {
            "fault_scenario": topology_subgraph.get("fault_scenario"),
            "root_candidate_nodes": topology_subgraph.get("root_candidate_nodes"),
            "symptom_nodes": topology_subgraph.get("symptom_nodes"),
            "noise_nodes": topology_subgraph.get("noise_nodes"),
            "llm_invocation_gate": gate,
        },
        "direct_evidence": evidence_pack.get("direct_evidence"),
        "supporting_evidence": evidence_pack.get("supporting_evidence"),
        "contradictory_evidence": evidence_pack.get("contradictory_evidence"),
        "missing_evidence": evidence_pack.get("missing_evidence"),
    }


def _build_messages(provider_body: dict[str, Any]) -> list[dict[str, str]]:
    compact = _compact_request(provider_body)
    system = (
        "You are a bounded NetOps fault-localization assistant. "
        "Use only the supplied evidence. Distinguish root cause, symptom, and noise. "
        "Return strict JSON with keys summary, hypotheses, recommended_actions, "
        "confidence_score, confidence_label, confidence_reason."
    )
    user = (
        "Analyze this topology-gated alert evidence. Keep remediation human-gated. "
        "Do not invent devices, topology links, metrics, or commands outside the evidence.\n\n"
        + json.dumps(compact, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _fallback_payload(provider_body: dict[str, Any], reason: str) -> dict[str, Any]:
    compact = _compact_request(provider_body)
    topology = compact.get("topology_context") if isinstance(compact.get("topology_context"), dict) else {}
    subgraph = compact.get("topology_subgraph_summary") if isinstance(compact.get("topology_subgraph_summary"), dict) else {}
    scenario = str(subgraph.get("fault_scenario") or "unknown")
    device = str(topology.get("src_device_key") or "unknown")
    path = str(topology.get("path_signature") or "unknown")
    return {
        "summary": f"{device} produced a topology-gated {scenario} alert on {path}.",
        "hypotheses": [
            f"Primary root candidate is the seed device {device}; validate adjacent symptoms before action.",
            f"The observed path {path} should be checked against the LCORE topology evidence.",
        ],
        "recommended_actions": [
            "Review the selected root-candidate and symptom nodes before widening investigation scope.",
            "Check whether the same fault scenario recurs in the recent alert window.",
            "Keep remediation human-approved; do not execute changes from this model response.",
        ],
        "confidence_score": 0.62,
        "confidence_label": "medium",
        "confidence_reason": reason,
    }


def _normalize_model_payload(raw_text: str, provider_body: dict[str, Any]) -> dict[str, Any]:
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = _fallback_payload(provider_body, "model returned non-json text; response was wrapped")
        payload["summary"] = text[:800] or payload["summary"]
        return payload
    if not isinstance(payload, dict):
        return _fallback_payload(provider_body, "model returned non-object json")
    return payload


def call_openai_compatible(provider_body: dict[str, Any]) -> dict[str, Any]:
    if DRY_RUN:
        return _fallback_payload(provider_body, "dry-run gateway response")

    body = json.dumps(
        {
            "model": provider_body.get("model") or OPENAI_MODEL,
            "messages": _build_messages(provider_body),
            "temperature": TEMPERATURE,
            "max_tokens": MAX_TOKENS,
            "response_format": {"type": "json_object"},
        },
        ensure_ascii=False,
    ).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if OPENAI_API_KEY:
        headers["Authorization"] = f"Bearer {OPENAI_API_KEY}"

    req = request.Request(
        f"{OPENAI_BASE_URL.rstrip('/')}/chat/completions",
        data=body,
        headers=headers,
        method="POST",
    )
    with request.urlopen(req, timeout=OPENAI_TIMEOUT_SEC) as resp:
        raw = json.loads(resp.read().decode("utf-8"))
    choices = raw.get("choices") if isinstance(raw, dict) else []
    message = choices[0].get("message") if choices and isinstance(choices[0], dict) else {}
    content = str(message.get("content") or "")
    payload = _normalize_model_payload(content, provider_body)
    payload["model_usage"] = raw.get("usage") if isinstance(raw, dict) else {}
    return payload


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/healthz":
            _json_response(self, 200, {"status": "ok", "model": OPENAI_MODEL, "dry_run": DRY_RUN})
            return
        _json_response(self, 404, {"error": "not found"})

    def do_POST(self) -> None:
        started = time.perf_counter()
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            output = call_openai_compatible(body)
            output["provider_latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
            _json_response(self, 200, {"output": output})
        except error.URLError as exc:
            _json_response(self, 502, {"error": f"upstream model service failed: {exc}"})
        except Exception as exc:
            _json_response(self, 500, {"error": str(exc)})

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"{self.log_date_time_string()} {self.address_string()} {fmt % args}", flush=True)


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(
        json.dumps(
            {
                "event": "netops_llm_gateway_started",
                "host": HOST,
                "port": PORT,
                "openai_base_url": OPENAI_BASE_URL,
                "model": OPENAI_MODEL,
                "dry_run": DRY_RUN,
            },
            ensure_ascii=True,
            sort_keys=True,
        ),
        flush=True,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
