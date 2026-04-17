from __future__ import annotations

import hashlib
import re
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


@dataclass
class RuleConfig:
    deny_window_sec: int = 60
    deny_threshold: int = 30
    bytes_window_sec: int = 300
    bytes_threshold: int = 20_000_000
    cooldown_sec: int = 60


class RuleEngine:
    def __init__(self, config: RuleConfig):
        self.config = config
        self._deny_windows: dict[str, deque[datetime]] = defaultdict(deque)
        self._bytes_windows: dict[str, deque[tuple[datetime, int]]] = defaultdict(deque)
        self._last_alert_at: dict[str, datetime] = {}
        self._annotated_fault_states: dict[str, str] = {}

    def process(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        event_ts = _parse_event_ts(event)
        if event_ts is None:
            return []

        alerts = []

        annotated_fault_alert = self._rule_annotated_fault(event, event_ts)
        if annotated_fault_alert:
            alerts.append(annotated_fault_alert)

        deny_alert = self._rule_deny_burst(event, event_ts)
        if deny_alert:
            alerts.append(deny_alert)

        bytes_alert = self._rule_bytes_spike(event, event_ts)
        if bytes_alert:
            alerts.append(bytes_alert)

        return alerts

    def _rule_annotated_fault(self, event: dict[str, Any], now: datetime) -> dict[str, Any] | None:
        annotation = _fault_annotation(event)
        if annotation is None:
            return None

        entity_key = _event_entity_key(event)
        scenario = annotation["scenario"]
        state_key = entity_key or "unknown"

        if not annotation["is_fault"]:
            self._annotated_fault_states[state_key] = "healthy"
            return None

        if self._annotated_fault_states.get(state_key) == scenario:
            return None
        self._annotated_fault_states[state_key] = scenario

        alert_key = f"annotated_fault::{state_key}::{scenario}"
        if not self._cooldown_ok(alert_key, now):
            return None

        return _make_alert(
            rule_id="annotated_fault_v1",
            severity=_fault_severity(scenario),
            event=event,
            event_ts=now,
            dimensions={
                "src_device_key": entity_key,
                "fault_scenario": scenario,
            },
            metrics={
                "annotation_confidence": annotation["confidence"],
                "label_field": annotation["label_field"],
                "label_value": annotation["label_value"],
            },
        )

    def _rule_deny_burst(self, event: dict[str, Any], now: datetime) -> dict[str, Any] | None:
        action = str(event.get("action") or "").lower()
        if action != "deny":
            return None

        key = str(event.get("src_device_key") or event.get("srcip") or "unknown")
        bucket = self._deny_windows[key]
        cutoff = now - timedelta(seconds=self.config.deny_window_sec)

        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        bucket.append(now)

        if len(bucket) < self.config.deny_threshold:
            return None

        alert_key = f"deny_burst::{key}"
        if not self._cooldown_ok(alert_key, now):
            return None

        return _make_alert(
            rule_id="deny_burst_v1",
            severity="warning",
            event=event,
            event_ts=now,
            dimensions={"src_device_key": key},
            metrics={
                "deny_count": len(bucket),
                "window_sec": self.config.deny_window_sec,
                "threshold": self.config.deny_threshold,
            },
        )

    def _rule_bytes_spike(self, event: dict[str, Any], now: datetime) -> dict[str, Any] | None:
        srcip = str(event.get("srcip") or "unknown")
        try:
            bytes_total = int(event.get("bytes_total") or 0)
        except (TypeError, ValueError):
            bytes_total = 0

        if bytes_total <= 0:
            return None

        bucket = self._bytes_windows[srcip]
        cutoff = now - timedelta(seconds=self.config.bytes_window_sec)

        while bucket and bucket[0][0] < cutoff:
            bucket.popleft()
        bucket.append((now, bytes_total))

        aggregate = sum(x[1] for x in bucket)
        if aggregate < self.config.bytes_threshold:
            return None

        alert_key = f"bytes_spike::{srcip}"
        if not self._cooldown_ok(alert_key, now):
            return None

        return _make_alert(
            rule_id="bytes_spike_v1",
            severity="critical",
            event=event,
            event_ts=now,
            dimensions={"srcip": srcip},
            metrics={
                "bytes_sum": aggregate,
                "window_sec": self.config.bytes_window_sec,
                "threshold": self.config.bytes_threshold,
            },
        )

    def _cooldown_ok(self, alert_key: str, now: datetime) -> bool:
        last = self._last_alert_at.get(alert_key)
        if last is not None and (now - last).total_seconds() < self.config.cooldown_sec:
            return False
        self._last_alert_at[alert_key] = now
        return True


def _parse_event_ts(event: dict[str, Any]) -> datetime | None:
    raw_ts = event.get("event_ts")
    if not isinstance(raw_ts, str) or not raw_ts:
        return None

    text = raw_ts.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _make_alert(
    rule_id: str,
    severity: str,
    event: dict[str, Any],
    event_ts: datetime,
    dimensions: dict[str, Any],
    metrics: dict[str, Any],
) -> dict[str, Any]:
    source_event_id = str(event.get("event_id") or "")
    seed = f"{rule_id}|{source_event_id}|{int(event_ts.timestamp())}"
    alert_id = hashlib.sha1(seed.encode("utf-8"), usedforsecurity=False).hexdigest()
    src_device_key = str(dimensions.get("src_device_key") or _event_entity_key(event) or "unknown")

    return {
        "schema_version": 1,
        "alert_id": alert_id,
        "alert_ts": event_ts.isoformat(),
        "rule_id": rule_id,
        "severity": severity,
        "src_device_key": src_device_key,
        "source_event_id": source_event_id,
        "dimensions": dimensions,
        "metrics": metrics,
        "dataset_context": _build_dataset_context(event),
        "event_excerpt": {
            "event_id": event.get("event_id"),
            "event_ts": event.get("event_ts"),
            "type": event.get("type"),
            "subtype": event.get("subtype"),
            "action": event.get("action"),
            "policyid": event.get("policyid"),
            "policytype": event.get("policytype"),
            "sessionid": event.get("sessionid"),
            "proto": event.get("proto"),
            "srcip": event.get("srcip"),
            "srcport": event.get("srcport"),
            "srcintf": event.get("srcintf"),
            "srcintfrole": event.get("srcintfrole"),
            "dstip": event.get("dstip"),
            "dstport": event.get("dstport"),
            "dstintf": event.get("dstintf"),
            "dstintfrole": event.get("dstintfrole"),
            "service": event.get("service"),
            "src_device_key": src_device_key,
            "srcmac": event.get("srcmac") or event.get("mastersrcmac"),
            "devname": event.get("devname"),
            "srcname": event.get("srcname"),
            "devtype": event.get("devtype"),
            "vendor": event.get("srchwvendor"),
            "family": event.get("srcfamily"),
            "version": event.get("srchwversion"),
            "appcat": event.get("appcat"),
            "bytes_total": event.get("bytes_total"),
            "pkts_total": event.get("pkts_total"),
            "source_path": (event.get("source") or {}).get("path") if isinstance(event.get("source"), dict) else "",
            "source_inode": (event.get("source") or {}).get("inode") if isinstance(event.get("source"), dict) else None,
        },
        "topology_context": _build_topology_context(event),
        "device_profile": _build_device_profile(event),
        "change_context": _build_change_context(event),
    }


def _fault_annotation(event: dict[str, Any]) -> dict[str, Any] | None:
    context = event.get("fault_context")
    if isinstance(context, dict):
        if "is_fault" not in context and "scenario" not in context and "label_value" not in context:
            return None
        scenario = _normalize_scenario(context.get("scenario") or context.get("label_value"))
        return {
            "is_fault": bool(context.get("is_fault")),
            "scenario": scenario,
            "confidence": _to_float(context.get("confidence")) or 1.0,
            "label_field": str(context.get("label_field") or ""),
            "label_value": str(context.get("label_value") or context.get("scenario") or ""),
        }

    for field_name in ["fault_label", "fault_type", "scenario", "label", "class", "status", "state"]:
        if field_name not in event:
            continue
        raw_value = event.get(field_name)
        scenario = _normalize_scenario(raw_value)
        return {
            "is_fault": _is_fault_label(raw_value),
            "scenario": scenario,
            "confidence": 1.0,
            "label_field": field_name,
            "label_value": str(raw_value or ""),
        }

    return None


def _event_entity_key(event: dict[str, Any]) -> str:
    topology = event.get("topology_context")
    if not isinstance(topology, dict):
        topology = {}
    profile = event.get("device_profile")
    if not isinstance(profile, dict):
        profile = {}
    for value in [
        profile.get("device_name"),
        profile.get("src_device_key"),
        event.get("src_device_key"),
        event.get("node_id"),
        event.get("device_id"),
        event.get("router"),
        topology.get("srcip"),
        topology.get("path_signature"),
        topology.get("srcintf"),
        event.get("srcip"),
    ]:
        text = str(value or "").strip()
        if text and not _is_low_semantic_entity_key(text):
            return text
    return "unknown"


def _is_low_semantic_entity_key(value: str) -> bool:
    text = value.strip()
    if not text:
        return True
    if text.isdigit() and len(text) <= 2:
        return True
    return False


def _fault_severity(scenario: str) -> str:
    text = scenario.lower()
    if any(
        marker in text
        for marker in [
            "multiple_nodes",
            "node_failure",
            "single_node",
            "multiple_link",
            "routing_misconfiguration",
            "line_card",
        ]
    ):
        return "critical"
    return "warning"


def _normalize_scenario(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    if text in {"", "0", "false", "normal", "healthy", "ok", "up", "benign", "none", "no_fault"}:
        return "healthy"
    if "icmp" in text and ("block" in text or "firewall" in text):
        return "icmp_blocked_firewall"
    if "snmp" in text and "agent" in text:
        return "snmp_agent_failure"
    if "multiple" in text and "link" in text:
        return "multiple_link_failure"
    if "single" in text and "link" in text:
        return "single_link_failure"
    if "multiple" in text and "node" in text:
        return "multiple_nodes_failures"
    if "single" in text and "node" in text:
        return "single_node_failure"
    if "link" in text and any(marker in text for marker in ["fault", "failure", "down"]):
        return "link_failure"
    if "node" in text and any(marker in text for marker in ["fault", "failure", "down"]):
        return "node_failure"
    if "routing" in text and any(marker in text for marker in ["misconfig", "fault", "failure"]):
        return "routing_misconfiguration"
    if "misconfig" in text or text == "misconfiguration":
        return "misconfiguration"
    if "line" in text and "card" in text:
        return "line_card_failure"
    if "transient" in text:
        return "transient_fault"
    if text in {"1", "true", "yes"}:
        return "annotated_fault"
    return text or "unknown_fault"


def _is_fault_label(value: Any) -> bool:
    text = _normalize_scenario(value)
    return text not in {"healthy"}


def _to_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _build_topology_context(event: dict[str, Any]) -> dict[str, Any]:
    base = event.get("topology_context")
    topology = dict(base) if isinstance(base, dict) else {}

    neighbor_refs = topology.get("neighbor_refs")
    if not isinstance(neighbor_refs, list):
        neighbor_refs = []

    topology["service"] = str(topology.get("service") or event.get("service") or "")
    topology["src_device_key"] = _event_entity_key(event)
    topology["srcip"] = str(topology.get("srcip") or event.get("srcip") or "")
    topology["dstip"] = str(topology.get("dstip") or event.get("dstip") or "")
    srcintf = str(topology.get("srcintf") or event.get("srcintf") or "")
    interface_type = str(topology.get("interface_type") or event.get("interface_type") or "")
    if _is_low_semantic_entity_key(srcintf):
        interface_type = interface_type or srcintf
        srcintf = ""
    topology["srcintf"] = srcintf
    topology["dstintf"] = str(topology.get("dstintf") or event.get("dstintf") or "")
    topology["srcintfrole"] = str(topology.get("srcintfrole") or event.get("srcintfrole") or "")
    topology["dstintfrole"] = str(topology.get("dstintfrole") or event.get("dstintfrole") or "")
    topology["site"] = str(topology.get("site") or event.get("site") or "")
    topology["zone"] = str(topology.get("zone") or event.get("srcintfrole") or event.get("dstintfrole") or "")
    topology["path_signature"] = _canonical_path_signature(event, topology)
    topology["policyid"] = str(topology.get("policyid") or event.get("policyid") or "")
    topology["policytype"] = str(topology.get("policytype") or event.get("policytype") or "")
    topology["neighbor_refs"] = [str(item).strip() for item in neighbor_refs if str(item).strip()]
    topology["hop_to_server"] = str(topology.get("hop_to_server") or event.get("hop_to_server") or "")
    topology["hop_to_core"] = str(topology.get("hop_to_core") or event.get("hop_to_core") or "")
    topology["downstream_dependents"] = str(
        topology.get("downstream_dependents") or event.get("downstream_dependents") or ""
    )
    topology["path_up"] = str(topology.get("path_up") or event.get("path_up") or "")
    topology["interface_type"] = interface_type
    return topology


def _canonical_path_signature(event: dict[str, Any], topology: dict[str, Any]) -> str:
    current = str(topology.get("path_signature") or "").strip()
    if current and not _is_low_semantic_path_signature(current):
        return current

    device = _event_entity_key(event)
    hop_to_core = str(topology.get("hop_to_core") or event.get("hop_to_core") or "").strip()
    hop_to_server = str(topology.get("hop_to_server") or event.get("hop_to_server") or "").strip()
    path_up = str(topology.get("path_up") or event.get("path_up") or "").strip()
    parts: list[str] = []
    if hop_to_core:
        parts.append(f"hop_core={hop_to_core}")
    if hop_to_server:
        parts.append(f"hop_server={hop_to_server}")
    if path_up:
        parts.append(f"path_up={path_up}")
    if device and device != "unknown" and parts:
        return f"{device}|" + "|".join(parts)

    srcintf = str(topology.get("srcintf") or event.get("srcintf") or "").strip()
    dstintf = str(topology.get("dstintf") or event.get("dstintf") or "").strip()
    return f"{srcintf or 'unknown'}->{dstintf or 'unknown'}"


def _is_low_semantic_path_signature(value: str) -> bool:
    text = value.strip()
    if not text or text in {"unknown", "unknown->unknown"}:
        return True
    if "/data/" in text or ".csv" in text:
        return True
    left, sep, right = text.partition("->")
    if sep and _is_low_semantic_entity_key(left) and right.strip().lower() == "unknown":
        return True
    return False


def _build_device_profile(event: dict[str, Any]) -> dict[str, Any]:
    base = event.get("device_profile")
    profile = dict(base) if isinstance(base, dict) else {}

    asset_tags = _normalize_str_list(profile.get("asset_tags"))
    if not asset_tags:
        asset_tags = _normalize_str_list([event.get("devtype"), event.get("srcfamily")])

    known_services = _normalize_str_list(profile.get("known_services"))
    if not known_services and event.get("service"):
        known_services = [str(event.get("service"))]

    profile["src_device_key"] = str(profile.get("src_device_key") or event.get("src_device_key") or "")
    profile["device_role"] = str(profile.get("device_role") or event.get("devtype") or "")
    profile["site"] = str(profile.get("site") or event.get("site") or "")
    profile["vendor"] = str(profile.get("vendor") or event.get("srchwvendor") or "")
    profile["device_name"] = str(profile.get("device_name") or event.get("srcname") or "")
    profile["osname"] = str(profile.get("osname") or event.get("osname") or "")
    profile["family"] = str(profile.get("family") or event.get("srcfamily") or "")
    profile["srcmac"] = str(profile.get("srcmac") or event.get("srcmac") or event.get("mastersrcmac") or "")
    profile["model"] = str(profile.get("model") or event.get("srchwmodel") or "")
    profile["version"] = str(profile.get("version") or event.get("srchwversion") or "")
    profile["asset_tags"] = asset_tags
    profile["known_services"] = known_services
    return profile


def _build_dataset_context(event: dict[str, Any]) -> dict[str, Any]:
    base = event.get("dataset_context")
    if not isinstance(base, dict):
        return {}
    keys = [
        "dataset_id",
        "run_id",
        "row_index",
        "source_uri",
        "source_file",
        "timestamp_source",
        "primary_time_field",
        "label_fields",
        "entity_fields",
        "topology_fields",
        "metric_field_count",
        "original_column_count",
    ]
    return {key: base.get(key) for key in keys if key in base}


def _build_change_context(event: dict[str, Any]) -> dict[str, Any]:
    base = event.get("change_context")
    context = dict(base) if isinstance(base, dict) else {}

    score = _to_int(event.get("crscore"))
    action = str(event.get("craction") or "")
    level = str(event.get("crlevel") or "")
    change_refs = _normalize_str_list(context.get("change_refs"))
    if not change_refs:
        derived_refs: list[str] = []
        if score is not None:
            derived_refs.append(f"crscore:{score}")
        if action:
            derived_refs.append(f"craction:{action}")
        if level:
            derived_refs.append(f"crlevel:{level}")
        change_refs = derived_refs

    context["suspected_change"] = bool(context.get("suspected_change")) or score is not None or bool(action) or bool(level)
    context["change_window_min"] = _to_int(context.get("change_window_min")) or 0
    context["change_refs"] = change_refs
    context["score"] = score
    context["action"] = action
    context["level"] = level
    return context


def _normalize_str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        raw_items = value
    else:
        raw_items = []
    items: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        text = str(item).strip()
        if text and text not in seen:
            seen.add(text)
            items.append(text)
    return items


def _to_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            return None
    return None
