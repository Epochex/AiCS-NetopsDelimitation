import hashlib
from datetime import datetime, timezone
from typing import Any

from core.aiops_agent.alert_reasoning_runtime import (
    build_alert_runtime_seed,
    build_cluster_runtime_seed,
)
from core.aiops_agent.alert_reasoning_runtime.context_views import build_context_views
from core.aiops_agent.alert_reasoning_runtime.prompt_contracts import build_prompt_contracts
from core.aiops_agent.cluster_aggregator import ClusterTrigger
from core.aiops_agent.evidence_pack_v2 import build_evidence_pack_v2


def build_alert_evidence_bundle(
    alert: dict[str, Any],
    recent_similar_1h: int,
    history_support: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    excerpt = alert.get("event_excerpt") or {}
    metrics = alert.get("metrics") or {}
    dimensions = alert.get("dimensions") or {}
    topology = alert.get("topology_context") or {}
    device_profile = alert.get("device_profile") or {}
    change_context = alert.get("change_context") or {}
    dataset_context = alert.get("dataset_context") or {}
    alert_id = str(alert.get("alert_id") or "")
    rule_id = str(alert.get("rule_id") or "unknown")
    severity = str(alert.get("severity") or "unknown").lower()
    service = str(excerpt.get("service") or topology.get("service") or "")
    src_device_key = str(excerpt.get("src_device_key") or device_profile.get("src_device_key") or "")
    history_support = history_support or {}

    seed = f"{alert_id}|{rule_id}|{service}|{src_device_key}|alert"
    bundle_id = hashlib.sha1(seed.encode("utf-8"), usedforsecurity=False).hexdigest()
    reasoning_runtime_seed = build_alert_runtime_seed(
        alert=alert,
        recent_similar_1h=max(0, int(recent_similar_1h)),
        history_support=history_support,
    )

    bundle = {
        "schema_version": 1,
        "bundle_id": bundle_id,
        "bundle_ts": now.isoformat(),
        "bundle_scope": "alert",
        "alert_ref": {
            "alert_id": alert_id,
            "rule_id": rule_id,
            "severity": severity,
        },
        "dataset_context": _dataset_context(dataset_context),
        "topology_context": _topology_context(excerpt, topology, device_profile, service, src_device_key),
        "historical_context": {
            "recent_similar_1h": max(0, int(recent_similar_1h)),
            "cluster_size": 1,
            "cluster_window_sec": 0,
            "cluster_first_alert_ts": str(alert.get("alert_ts") or ""),
            "cluster_last_alert_ts": str(alert.get("alert_ts") or ""),
            "cluster_sample_alert_ids": [alert_id] if alert_id else [],
            "recent_alert_samples": history_support.get("recent_alert_samples") or [],
            "historical_baseline": history_support.get("historical_baseline") or {},
            "recent_change_records": history_support.get("recent_change_records") or [],
        },
        "rule_context": {
            "rule_id": rule_id,
            "severity": severity,
            "metrics": metrics,
            "dimensions": dimensions,
            "rule_hits": [
                {
                    "rule_id": rule_id,
                    "severity": severity,
                    "cluster_size": 1,
                }
            ],
        },
        "path_context": _path_context(excerpt, topology, history_support),
        "policy_context": _policy_context(excerpt, topology, history_support),
        "sample_context": {
            "recent_alert_samples": history_support.get("recent_alert_samples") or [],
        },
        "window_context": {
            "cluster_size": 1,
            "window_sec": 0,
            "sample_alert_ids": [alert_id] if alert_id else [],
        },
        "device_context": _device_context(device_profile, src_device_key),
        "change_context": _change_context(change_context),
        "reasoning_runtime_seed": reasoning_runtime_seed,
        "topology_subgraph": reasoning_runtime_seed.get("topology_subgraph") or {},
    }
    bundle["context_views"] = build_context_views(bundle)
    bundle["prompt_contracts"] = build_prompt_contracts(bundle["context_views"])
    bundle["evidence_pack_v2"] = build_evidence_pack_v2(bundle)
    return bundle


def build_cluster_evidence_bundle(
    alert: dict[str, Any],
    trigger: ClusterTrigger,
    recent_similar_1h: int,
    history_support: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    excerpt = alert.get("event_excerpt") or {}
    metrics = alert.get("metrics") or {}
    dimensions = alert.get("dimensions") or {}
    topology = alert.get("topology_context") or {}
    device_profile = alert.get("device_profile") or {}
    change_context = alert.get("change_context") or {}
    dataset_context = alert.get("dataset_context") or {}
    history_support = history_support or {}

    seed = (
        f"{alert.get('alert_id','')}|{trigger.key.rule_id}|{trigger.key.service}|"
        f"{trigger.key.src_device_key}|{trigger.last_alert_ts}"
    )
    bundle_id = hashlib.sha1(seed.encode("utf-8"), usedforsecurity=False).hexdigest()
    reasoning_runtime_seed = build_cluster_runtime_seed(
        alert=alert,
        trigger=trigger,
        recent_similar_1h=max(0, int(recent_similar_1h)),
        history_support=history_support,
    )

    bundle = {
        "schema_version": 1,
        "bundle_id": bundle_id,
        "bundle_ts": now.isoformat(),
        "bundle_scope": "cluster",
        "alert_ref": {
            "alert_id": str(alert.get("alert_id") or ""),
            "rule_id": trigger.key.rule_id,
            "severity": trigger.key.severity,
        },
        "dataset_context": _dataset_context(dataset_context),
        "topology_context": _topology_context(
            excerpt,
            topology,
            device_profile,
            trigger.key.service,
            trigger.key.src_device_key,
        ),
        "historical_context": {
            "recent_similar_1h": max(0, int(recent_similar_1h)),
            "cluster_size": trigger.cluster_size,
            "cluster_window_sec": trigger.window_sec,
            "cluster_first_alert_ts": trigger.first_alert_ts,
            "cluster_last_alert_ts": trigger.last_alert_ts,
            "cluster_sample_alert_ids": trigger.sample_alert_ids,
            "recent_alert_samples": history_support.get("recent_alert_samples") or [],
            "historical_baseline": history_support.get("historical_baseline") or {},
            "recent_change_records": history_support.get("recent_change_records") or [],
        },
        "rule_context": {
            "rule_id": trigger.key.rule_id,
            "severity": trigger.key.severity,
            "metrics": metrics,
            "dimensions": dimensions,
            "rule_hits": [
                {
                    "rule_id": trigger.key.rule_id,
                    "severity": trigger.key.severity,
                    "cluster_size": trigger.cluster_size,
                }
            ],
        },
        "path_context": _path_context(excerpt, topology, history_support),
        "policy_context": _policy_context(excerpt, topology, history_support),
        "sample_context": {
            "recent_alert_samples": history_support.get("recent_alert_samples") or [],
        },
        "window_context": {
            "cluster_size": trigger.cluster_size,
            "window_sec": trigger.window_sec,
            "sample_alert_ids": trigger.sample_alert_ids,
        },
        "device_context": _device_context(device_profile, trigger.key.src_device_key),
        "change_context": _change_context(change_context),
        "reasoning_runtime_seed": reasoning_runtime_seed,
        "topology_subgraph": reasoning_runtime_seed.get("topology_subgraph") or {},
    }
    incident_window = {
        "schema_version": 1,
        "window_id": str(trigger.key),
        "window_sec": trigger.window_sec,
        "window_start": trigger.first_alert_ts,
        "window_end": trigger.last_alert_ts,
        "alert_count": trigger.cluster_size,
        "alert_ids": trigger.sample_alert_ids,
        "sample_alert_ids": trigger.sample_alert_ids,
        "devices": [trigger.key.src_device_key] if trigger.key.src_device_key else [],
        "device_count": 1 if trigger.key.src_device_key else 0,
        "path_signatures": [bundle["path_context"].get("path_signature") or ""],
        "path_count": 1,
        "path_shapes": [bundle["path_context"].get("path_signature") or ""],
        "path_shape_count": 1,
        "scenario_counts": {
            str((metrics.get("label_value") or dimensions.get("fault_scenario") or "unknown")).lower(): trigger.cluster_size
        },
        "recurrence_pressure": trigger.cluster_size >= 3,
        "topology_pressure": bool(bundle["topology_context"].get("neighbor_refs")),
        "multi_device_spread": False,
        "max_downstream_dependents": _safe_int(bundle["topology_context"].get("downstream_dependents")),
        "timeline": [
            {
                "alert_id": alert_id,
                "alert_ts": trigger.last_alert_ts,
                "device": trigger.key.src_device_key,
                "scenario": str((metrics.get("label_value") or dimensions.get("fault_scenario") or "unknown")).lower(),
                "path_signature": bundle["path_context"].get("path_signature") or "",
                "severity": trigger.key.severity,
            }
            for alert_id in trigger.sample_alert_ids[:12]
        ],
    }
    bundle["context_views"] = build_context_views(bundle, incident_window=incident_window)
    bundle["prompt_contracts"] = build_prompt_contracts(bundle["context_views"])
    bundle["evidence_pack_v2"] = build_evidence_pack_v2(bundle)
    return bundle


def _topology_context(
    excerpt: dict[str, Any],
    topology: dict[str, Any],
    device_profile: dict[str, Any],
    service: str,
    src_device_key: str,
) -> dict[str, Any]:
    srcintf = str(excerpt.get("srcintf") or topology.get("srcintf") or "")
    dstintf = str(excerpt.get("dstintf") or topology.get("dstintf") or "")
    if _is_low_semantic_interface(srcintf):
        srcintf = ""
    path_signature = _canonical_path_signature(topology, src_device_key, srcintf, dstintf)
    return {
        "service": service,
        "src_device_key": src_device_key,
        "srcip": str(excerpt.get("srcip") or topology.get("srcip") or ""),
        "dstip": str(excerpt.get("dstip") or topology.get("dstip") or ""),
        "srcport": str(excerpt.get("srcport") or ""),
        "dstport": str(excerpt.get("dstport") or ""),
        "srcintf": srcintf,
        "dstintf": dstintf,
        "srcintfrole": str(excerpt.get("srcintfrole") or topology.get("srcintfrole") or ""),
        "dstintfrole": str(excerpt.get("dstintfrole") or topology.get("dstintfrole") or ""),
        "site": str(topology.get("site") or device_profile.get("site") or ""),
        "zone": str(topology.get("zone") or ""),
        "path_signature": path_signature,
        "neighbor_refs": _normalize_str_list(topology.get("neighbor_refs")),
        "hop_to_server": str(topology.get("hop_to_server") or ""),
        "hop_to_core": str(topology.get("hop_to_core") or ""),
        "downstream_dependents": str(topology.get("downstream_dependents") or ""),
        "path_up": str(topology.get("path_up") or ""),
    }


def _safe_int(value: Any) -> int:
    try:
        return int(str(value or "0"))
    except ValueError:
        return 0


def _path_context(
    excerpt: dict[str, Any],
    topology: dict[str, Any],
    history_support: dict[str, Any],
) -> dict[str, Any]:
    srcintf = str(excerpt.get("srcintf") or topology.get("srcintf") or "")
    dstintf = str(excerpt.get("dstintf") or topology.get("dstintf") or "")
    if _is_low_semantic_interface(srcintf):
        srcintf = ""
    path_signature = _canonical_path_signature(
        topology,
        str(topology.get("src_device_key") or excerpt.get("src_device_key") or ""),
        srcintf,
        dstintf,
    )
    return {
        "srcintf": srcintf,
        "dstintf": dstintf,
        "srcintfrole": str(excerpt.get("srcintfrole") or topology.get("srcintfrole") or ""),
        "dstintfrole": str(excerpt.get("dstintfrole") or topology.get("dstintfrole") or ""),
        "path_signature": path_signature,
        "recent_path_hits": history_support.get("recent_path_hits") or [],
    }


def _canonical_path_signature(topology: dict[str, Any], src_device_key: str, srcintf: str, dstintf: str) -> str:
    current = str(topology.get("path_signature") or "").strip()
    if current and not _is_low_semantic_path_signature(current):
        return current
    hop_to_core = str(topology.get("hop_to_core") or "").strip()
    hop_to_server = str(topology.get("hop_to_server") or "").strip()
    path_up = str(topology.get("path_up") or "").strip()
    parts: list[str] = []
    if hop_to_core:
        parts.append(f"hop_core={hop_to_core}")
    if hop_to_server:
        parts.append(f"hop_server={hop_to_server}")
    if path_up:
        parts.append(f"path_up={path_up}")
    if src_device_key and parts:
        return f"{src_device_key}|" + "|".join(parts)
    return f"{srcintf or 'unknown'}->{dstintf or 'unknown'}"


def _is_low_semantic_path_signature(value: str) -> bool:
    text = value.strip()
    if not text or text in {"unknown", "unknown->unknown"}:
        return True
    if "/data/" in text or ".csv" in text:
        return True
    left, sep, right = text.partition("->")
    if sep and _is_low_semantic_interface(left) and right.strip().lower() == "unknown":
        return True
    return False


def _is_low_semantic_interface(value: str) -> bool:
    text = value.strip()
    return bool(text) and text.isdigit() and len(text) <= 2


def _policy_context(
    excerpt: dict[str, Any],
    topology: dict[str, Any],
    history_support: dict[str, Any],
) -> dict[str, Any]:
    return {
        "policyid": str(excerpt.get("policyid") or topology.get("policyid") or ""),
        "policytype": str(excerpt.get("policytype") or topology.get("policytype") or ""),
        "recent_policy_hits": history_support.get("recent_policy_hits") or [],
    }


def _dataset_context(dataset_context: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(dataset_context, dict):
        return {}
    keys = [
        "dataset_id",
        "run_id",
        "row_index",
        "source_uri",
        "source_file",
        "timestamp_source",
        "primary_time_field",
    ]
    return {key: dataset_context.get(key) for key in keys if key in dataset_context}


def _device_context(device_profile: dict[str, Any], src_device_key: str) -> dict[str, Any]:
    return {
        "src_device_key": src_device_key,
        "device_role": str(device_profile.get("device_role") or ""),
        "site": str(device_profile.get("site") or ""),
        "vendor": str(device_profile.get("vendor") or ""),
        "device_name": str(device_profile.get("device_name") or ""),
        "osname": str(device_profile.get("osname") or ""),
        "family": str(device_profile.get("family") or ""),
        "srcmac": str(device_profile.get("srcmac") or ""),
        "model": str(device_profile.get("model") or ""),
        "version": str(device_profile.get("version") or ""),
        "asset_tags": _normalize_str_list(device_profile.get("asset_tags")),
        "known_services": _normalize_str_list(device_profile.get("known_services")),
    }


def _change_context(change_context: dict[str, Any]) -> dict[str, Any]:
    return {
        "suspected_change": bool(change_context.get("suspected_change")),
        "change_window_min": int(change_context.get("change_window_min") or 0),
        "change_refs": _normalize_str_list(change_context.get("change_refs")),
        "score": change_context.get("score"),
        "action": str(change_context.get("action") or ""),
        "level": str(change_context.get("level") or ""),
    }


def _normalize_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    items = []
    for item in value:
        text = str(item).strip()
        if text:
            items.append(text)
    return items
