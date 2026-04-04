import hashlib
from datetime import datetime, timezone
from typing import Any

from core.aiops_agent.cluster_aggregator import ClusterTrigger


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
    alert_id = str(alert.get("alert_id") or "")
    rule_id = str(alert.get("rule_id") or "unknown")
    severity = str(alert.get("severity") or "unknown").lower()
    service = str(excerpt.get("service") or topology.get("service") or "")
    src_device_key = str(excerpt.get("src_device_key") or device_profile.get("src_device_key") or "")
    history_support = history_support or {}

    seed = f"{alert_id}|{rule_id}|{service}|{src_device_key}|alert"
    bundle_id = hashlib.sha1(seed.encode("utf-8"), usedforsecurity=False).hexdigest()

    return {
        "schema_version": 1,
        "bundle_id": bundle_id,
        "bundle_ts": now.isoformat(),
        "bundle_scope": "alert",
        "alert_ref": {
            "alert_id": alert_id,
            "rule_id": rule_id,
            "severity": severity,
        },
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
    }


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
    history_support = history_support or {}

    seed = (
        f"{alert.get('alert_id','')}|{trigger.key.rule_id}|{trigger.key.service}|"
        f"{trigger.key.src_device_key}|{trigger.last_alert_ts}"
    )
    bundle_id = hashlib.sha1(seed.encode("utf-8"), usedforsecurity=False).hexdigest()

    return {
        "schema_version": 1,
        "bundle_id": bundle_id,
        "bundle_ts": now.isoformat(),
        "bundle_scope": "cluster",
        "alert_ref": {
            "alert_id": str(alert.get("alert_id") or ""),
            "rule_id": trigger.key.rule_id,
            "severity": trigger.key.severity,
        },
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
    }


def _topology_context(
    excerpt: dict[str, Any],
    topology: dict[str, Any],
    device_profile: dict[str, Any],
    service: str,
    src_device_key: str,
) -> dict[str, Any]:
    return {
        "service": service,
        "src_device_key": src_device_key,
        "srcip": str(excerpt.get("srcip") or topology.get("srcip") or ""),
        "dstip": str(excerpt.get("dstip") or topology.get("dstip") or ""),
        "srcport": str(excerpt.get("srcport") or ""),
        "dstport": str(excerpt.get("dstport") or ""),
        "srcintf": str(excerpt.get("srcintf") or topology.get("srcintf") or ""),
        "dstintf": str(excerpt.get("dstintf") or topology.get("dstintf") or ""),
        "srcintfrole": str(excerpt.get("srcintfrole") or topology.get("srcintfrole") or ""),
        "dstintfrole": str(excerpt.get("dstintfrole") or topology.get("dstintfrole") or ""),
        "site": str(topology.get("site") or device_profile.get("site") or ""),
        "zone": str(topology.get("zone") or ""),
        "path_signature": str(
            topology.get("path_signature")
            or f"{topology.get('srcintf') or excerpt.get('srcintf') or 'unknown'}->{topology.get('dstintf') or excerpt.get('dstintf') or 'unknown'}"
        ),
        "neighbor_refs": _normalize_str_list(topology.get("neighbor_refs")),
    }


def _path_context(
    excerpt: dict[str, Any],
    topology: dict[str, Any],
    history_support: dict[str, Any],
) -> dict[str, Any]:
    srcintf = str(excerpt.get("srcintf") or topology.get("srcintf") or "")
    dstintf = str(excerpt.get("dstintf") or topology.get("dstintf") or "")
    return {
        "srcintf": srcintf,
        "dstintf": dstintf,
        "srcintfrole": str(excerpt.get("srcintfrole") or topology.get("srcintfrole") or ""),
        "dstintfrole": str(excerpt.get("dstintfrole") or topology.get("dstintfrole") or ""),
        "path_signature": str(topology.get("path_signature") or f"{srcintf or 'unknown'}->{dstintf or 'unknown'}"),
        "recent_path_hits": history_support.get("recent_path_hits") or [],
    }


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
