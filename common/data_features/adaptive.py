from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping

LCORE_D_SOURCE_URL = "https://data.mendeley.com/datasets/77sztrg5ks/2"

_TOKEN_RE = re.compile(r"[^a-z0-9]+")
_GENERATED_START_TS = datetime(1970, 1, 1, tzinfo=timezone.utc)

_TIME_MARKERS = {
    "time",
    "timestamp",
    "datetime",
    "date",
    "eventtime",
    "event_ts",
    "ts",
}
_LABEL_MARKERS = {
    "label",
    "class",
    "target",
    "fault",
    "failure",
    "scenario",
    "anomaly",
    "abnormal",
    "state",
    "status",
    "incident",
    "ground_truth",
}
_ENTITY_MARKERS = {
    "node",
    "router",
    "device",
    "host",
    "hostname",
    "interface",
    "ifname",
    "link",
    "src",
    "source",
    "dst",
    "dest",
    "destination",
    "target",
    "peer",
    "neighbor",
}
_TOPOLOGY_MARKERS = _ENTITY_MARKERS | {
    "path",
    "hop",
    "asn",
    "pop",
    "site",
    "zone",
    "from",
    "to",
    "next_hop",
}
_METRIC_EXCLUDE_MARKERS = _TIME_MARKERS | _LABEL_MARKERS | _ENTITY_MARKERS | {
    "id",
    "uuid",
    "name",
}
_SERVICE_MARKERS = {"service", "protocol", "proto", "app", "application"}
_BYTES_MARKERS = {"byte", "bytes", "octet", "octets", "traffic", "bandwidth", "throughput", "bps"}
_PKT_MARKERS = {"packet", "packets", "pkt", "pkts", "pps"}
_HEALTHY_VALUES = {
    "",
    "0",
    "false",
    "f",
    "h",
    "no",
    "n",
    "normal",
    "healthy",
    "ok",
    "up",
    "benign",
    "none",
    "no_fault",
    "nofault",
    "non_fault",
    "nominal",
}
_FAULT_MARKERS = {
    "fault",
    "failure",
    "failed",
    "down",
    "misconfig",
    "misconfiguration",
    "abnormal",
    "anomaly",
    "transient",
    "flap",
    "card",
}
LCORE_D_SCENARIO_ALIASES = {
    "h": "healthy",
    "f": "induced_fault",
    "t": "transient_fault",
    "th": "transient_healthy",
    "single_link_failure": "single_link_failure",
    "multiple_link_failure": "multiple_link_failure",
    "misconfiguration": "misconfiguration",
    "routing_misconfiguration": "routing_misconfiguration",
    "line_card_failure": "line_card_failure",
    "icmp_blocked_firewall": "icmp_blocked_firewall",
    "node_failure": "node_failure",
    "multiple_nodes_failures": "multiple_nodes_failures",
    "single_node_failure": "single_node_failure",
    "snmp_agent_failure": "snmp_agent_failure",
}


@dataclass
class ColumnProfile:
    name: str
    observed_rows: int = 0
    non_null_rows: int = 0
    numeric_rows: int = 0
    timestamp_rows: int = 0
    boolean_rows: int = 0
    distinct_values: set[str] = field(default_factory=set)
    examples: list[str] = field(default_factory=list)
    min_number: float | None = None
    max_number: float | None = None

    def observe(self, value: Any, max_distinct: int = 128) -> None:
        self.observed_rows += 1
        text = _clean_text(value)
        if text == "":
            return

        self.non_null_rows += 1
        if len(self.examples) < 5 and text not in self.examples:
            self.examples.append(text)
        if len(self.distinct_values) < max_distinct:
            self.distinct_values.add(text)

        number = _coerce_number(value)
        if number is not None:
            self.numeric_rows += 1
            self.min_number = number if self.min_number is None else min(self.min_number, number)
            self.max_number = number if self.max_number is None else max(self.max_number, number)

        if _parse_timestamp(value) is not None:
            self.timestamp_rows += 1

        if _parse_bool(value) is not None:
            self.boolean_rows += 1

    @property
    def normalized_name(self) -> str:
        return _normalize_name(self.name)

    @property
    def numeric_ratio(self) -> float:
        return self.numeric_rows / max(self.non_null_rows, 1)

    @property
    def timestamp_ratio(self) -> float:
        return self.timestamp_rows / max(self.non_null_rows, 1)

    @property
    def distinct_count(self) -> int:
        return len(self.distinct_values)

    @property
    def range_width(self) -> float:
        if self.min_number is None or self.max_number is None:
            return 0.0
        return abs(self.max_number - self.min_number)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["distinct_values"] = sorted(self.distinct_values)[:20]
        data["numeric_ratio"] = round(self.numeric_ratio, 4)
        data["timestamp_ratio"] = round(self.timestamp_ratio, 4)
        data["range_width"] = self.range_width
        return data


@dataclass
class FeaturePlan:
    dataset_id: str
    source_uri: str
    observed_rows: int
    total_columns: int
    primary_time_field: str | None
    label_fields: list[str]
    entity_fields: list[str]
    topology_fields: list[str]
    metric_fields: list[str]
    categorical_fields: list[str]
    ignored_fields: list[str]
    scenario_values: list[str]
    generated_timestamp_start: str = _GENERATED_START_TS.isoformat()
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AdaptiveFeatureExtractor:
    def __init__(
        self,
        dataset_id: str = "lcore-d",
        source_uri: str = LCORE_D_SOURCE_URL,
        max_sample_rows: int = 5000,
        max_metric_fields: int = 64,
    ) -> None:
        self.dataset_id = dataset_id
        self.source_uri = source_uri
        self.max_sample_rows = max_sample_rows
        self.max_metric_fields = max_metric_fields

    def build_plan(self, rows: Iterable[Mapping[str, Any]]) -> FeaturePlan:
        return build_feature_plan(
            rows,
            dataset_id=self.dataset_id,
            source_uri=self.source_uri,
            max_sample_rows=self.max_sample_rows,
            max_metric_fields=self.max_metric_fields,
        )

    def transform(
        self,
        rows: Iterable[Mapping[str, Any]],
        plan: FeaturePlan,
        start_index: int = 0,
        run_id: str = "",
    ) -> Iterable[dict[str, Any]]:
        for offset, row in enumerate(rows, start=start_index):
            yield row_to_canonical_event(row, plan, offset, run_id=run_id)


def build_feature_plan(
    rows: Iterable[Mapping[str, Any]],
    dataset_id: str = "lcore-d",
    source_uri: str = LCORE_D_SOURCE_URL,
    max_sample_rows: int = 5000,
    max_metric_fields: int = 64,
) -> FeaturePlan:
    profiles: dict[str, ColumnProfile] = {}
    observed_rows = 0

    for row in rows:
        observed_rows += 1
        for key, value in row.items():
            profiles.setdefault(str(key), ColumnProfile(str(key))).observe(value)
        if observed_rows >= max_sample_rows:
            break

    ordered_profiles = list(profiles.values())
    time_fields = _rank_time_fields(ordered_profiles)
    label_fields = _rank_label_fields(ordered_profiles)
    entity_fields = _rank_marker_fields(ordered_profiles, _ENTITY_MARKERS, require_name_match=True)
    topology_fields = _rank_marker_fields(ordered_profiles, _TOPOLOGY_MARKERS, require_name_match=True)
    metric_fields = _rank_metric_fields(
        ordered_profiles,
        excluded=set(time_fields + label_fields + entity_fields),
    )[:max_metric_fields]
    categorical_fields = _rank_categorical_fields(
        ordered_profiles,
        excluded=set(time_fields + label_fields + entity_fields + topology_fields + metric_fields),
    )

    selected = set(time_fields + label_fields + entity_fields + topology_fields + metric_fields + categorical_fields)
    ignored_fields = [profile.name for profile in ordered_profiles if profile.name not in selected]

    return FeaturePlan(
        dataset_id=dataset_id,
        source_uri=source_uri,
        observed_rows=observed_rows,
        total_columns=len(ordered_profiles),
        primary_time_field=time_fields[0] if time_fields else None,
        label_fields=label_fields,
        entity_fields=entity_fields,
        topology_fields=topology_fields,
        metric_fields=metric_fields,
        categorical_fields=categorical_fields,
        ignored_fields=ignored_fields,
        scenario_values=_scenario_values(ordered_profiles, label_fields),
    )


def row_to_canonical_event(
    row: Mapping[str, Any],
    plan: FeaturePlan,
    row_index: int = 0,
    run_id: str = "",
) -> dict[str, Any]:
    event_ts, timestamp_source = _event_timestamp(row, plan, row_index)
    fault_state = infer_fault_state(row, plan)
    entity_key = _entity_key(row, plan)
    topology_context = _build_topology_context(row, plan, entity_key)
    service = _first_by_markers(row, _SERVICE_MARKERS)
    feature_vector = _feature_vector(row, plan.metric_fields)
    categorical_context = {
        field: _clean_text(row.get(field))
        for field in plan.categorical_fields
        if _clean_text(row.get(field)) != ""
    }

    bytes_total = _select_metric_value(row, plan.metric_fields, _BYTES_MARKERS)
    pkts_total = _select_metric_value(row, plan.metric_fields, _PKT_MARKERS)

    return {
        "schema_version": 1,
        "event_id": _stable_event_id(plan.dataset_id, row_index, row, run_id=run_id),
        "host": plan.dataset_id,
        "event_ts": event_ts,
        "type": "telemetry",
        "subtype": "fault_annotation" if fault_state["is_fault"] else "monitoring",
        "level": "warning" if fault_state["is_fault"] else "info",
        "action": "fault" if fault_state["is_fault"] else "observe",
        "service": service,
        "src_device_key": entity_key,
        "srcip": _first_by_name(row, ["srcip", "src_ip", "source_ip"]),
        "dstip": _first_by_name(row, ["dstip", "dst_ip", "dest_ip", "destination_ip"]),
        "bytes_total": bytes_total,
        "pkts_total": pkts_total,
        "parse_status": "ok",
        "topology_context": topology_context,
        "device_profile": _build_device_profile(row, plan, entity_key),
        "change_context": _build_change_context(fault_state),
        "fault_context": fault_state,
        "dataset_context": {
            "dataset_id": plan.dataset_id,
            "run_id": run_id,
            "source_uri": plan.source_uri,
            "row_index": row_index,
            "timestamp_source": timestamp_source,
            "primary_time_field": plan.primary_time_field,
            "label_fields": plan.label_fields,
            "entity_fields": plan.entity_fields,
            "topology_fields": plan.topology_fields,
            "metric_field_count": len(plan.metric_fields),
            "original_column_count": plan.total_columns,
        },
        "feature_vector": feature_vector,
        "categorical_context": categorical_context,
    }


def infer_fault_state(row: Mapping[str, Any], plan: FeaturePlan) -> dict[str, Any]:
    label_field = None
    label_value = ""
    for field_name in plan.label_fields:
        text = _clean_text(row.get(field_name))
        if text != "":
            label_field = field_name
            label_value = text
            break

    scenario = _normalize_scenario(label_value)
    is_fault = _is_fault_label(label_value)
    confidence = 1.0 if label_field else 0.0

    return {
        "is_fault": is_fault,
        "scenario": scenario,
        "label_field": label_field or "",
        "label_value": label_value,
        "confidence": confidence,
    }


def _rank_time_fields(profiles: list[ColumnProfile]) -> list[str]:
    scored: list[tuple[float, str]] = []
    for profile in profiles:
        if profile.name.startswith("_"):
            continue
        name_score = 2.0 if _has_marker(profile.normalized_name, _TIME_MARKERS) else 0.0
        score = name_score + profile.timestamp_ratio
        if score >= 1.0 and profile.non_null_rows > 0:
            scored.append((score, profile.name))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [name for _, name in scored]


def _rank_marker_fields(
    profiles: list[ColumnProfile],
    markers: set[str],
    require_name_match: bool,
) -> list[str]:
    scored: list[tuple[float, float, str]] = []
    for profile in profiles:
        if profile.name.startswith("_"):
            continue
        name_match = _has_marker(profile.normalized_name, markers)
        if require_name_match and not name_match:
            continue
        density = profile.non_null_rows / max(profile.observed_rows, 1)
        score = (2.0 if name_match else 0.0) + density
        scored.append((score, _name_preference(profile.normalized_name), profile.name))
    scored.sort(key=lambda item: (-item[0], -item[1], item[2]))
    return [name for _, _, name in scored]


def _rank_label_fields(profiles: list[ColumnProfile]) -> list[str]:
    scored: list[tuple[float, float, str]] = []
    for profile in profiles:
        if profile.name.startswith("_"):
            continue
        normalized = profile.normalized_name
        if not _has_marker(normalized, _LABEL_MARKERS):
            continue

        density = profile.non_null_rows / max(profile.observed_rows, 1)
        direct_label = normalized in {
            "class",
            "label",
            "target",
            "fault",
            "fault_type",
            "fault_label",
            "failure_type",
            "scenario",
            "state",
            "ground_truth",
        }
        telemetry_status = any(marker in normalized for marker in ("operational_status", "duplex_status", "interface_type"))
        if telemetry_status and not direct_label:
            continue
        score = 2.0 + density
        if direct_label:
            score += 5.0
        scored.append((score, _name_preference(normalized), profile.name))
    scored.sort(key=lambda item: (-item[0], -item[1], item[2]))
    return [name for _, _, name in scored]


def _rank_metric_fields(profiles: list[ColumnProfile], excluded: set[str]) -> list[str]:
    scored: list[tuple[float, str]] = []
    for profile in profiles:
        if profile.name.startswith("_"):
            continue
        if profile.name in excluded:
            continue
        if _has_marker(profile.normalized_name, _METRIC_EXCLUDE_MARKERS):
            continue
        if profile.numeric_ratio < 0.8 or profile.distinct_count <= 1:
            continue
        range_score = math.log10(profile.range_width + 1.0) if profile.range_width > 0 else 0.0
        density = profile.non_null_rows / max(profile.observed_rows, 1)
        scored.append((profile.numeric_ratio + range_score + density, profile.name))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [name for _, name in scored]


def _rank_categorical_fields(profiles: list[ColumnProfile], excluded: set[str]) -> list[str]:
    fields: list[str] = []
    for profile in profiles:
        if profile.name.startswith("_"):
            continue
        if profile.name in excluded:
            continue
        if profile.numeric_ratio >= 0.8:
            continue
        if 1 < profile.distinct_count <= min(100, max(profile.non_null_rows // 2, 20)):
            fields.append(profile.name)
    return fields


def _scenario_values(profiles: list[ColumnProfile], label_fields: list[str]) -> list[str]:
    by_name = {profile.name: profile for profile in profiles}
    values: set[str] = set()
    for field_name in label_fields:
        profile = by_name.get(field_name)
        if not profile:
            continue
        for value in profile.distinct_values:
            scenario = _normalize_scenario(value)
            if scenario != "healthy":
                values.add(scenario)
    return sorted(values)


def _event_timestamp(row: Mapping[str, Any], plan: FeaturePlan, row_index: int) -> tuple[str, str]:
    if plan.primary_time_field:
        parsed = _parse_timestamp(row.get(plan.primary_time_field))
        if parsed is not None:
            return parsed.astimezone(timezone.utc).isoformat(), "source"
    generated = _GENERATED_START_TS + timedelta(seconds=row_index)
    return generated.isoformat(), "generated"


def _build_topology_context(row: Mapping[str, Any], plan: FeaturePlan, entity_key: str) -> dict[str, Any]:
    src = _first_by_name(row, ["src", "source", "source_node", "from", "from_node", "src_node"])
    dst = _first_by_name(row, ["dst", "dest", "destination", "target", "to", "to_node", "dst_node"])
    link = _first_by_name(row, ["link", "link_id", "edge", "circuit"])
    interface = _first_interface_name(row)
    interface_type = _first_interface_type(row)
    site = _first_by_name(row, ["site", "pop", "location"])
    zone = _first_by_name(row, ["zone", "area", "domain"])
    neighbor = _first_by_name(row, ["neighbor", "peer", "next_hop"])
    hop_to_server = _first_by_name(row, ["hop_to_server", "hop server", "server_hop"])
    hop_to_core = _first_by_name(row, ["hop_to_core", "hop core", "core_hop"])
    downstream_dependents = _first_by_name(row, ["downstream_dependents", "downstream"])
    path_up = _first_by_name(row, ["path_up", "path status", "path_state"])

    path_signature = _path_signature(
        entity_key=entity_key,
        src=src,
        dst=dst,
        link=link,
        hop_to_core=hop_to_core,
        hop_to_server=hop_to_server,
        path_up=path_up,
    )
    topology = {
        "service": _first_by_markers(row, _SERVICE_MARKERS),
        "srcip": _first_by_name(row, ["srcip", "src_ip", "source_ip"]),
        "dstip": _first_by_name(row, ["dstip", "dst_ip", "dest_ip", "destination_ip"]),
        "srcintf": interface,
        "dstintf": _first_by_name(row, ["dstintf", "dst_interface", "destination_interface"]),
        "srcintfrole": "",
        "dstintfrole": "",
        "site": site,
        "zone": zone,
        "path_signature": path_signature,
        "policyid": "",
        "policytype": "",
        "neighbor_refs": [neighbor] if neighbor else [],
        "hop_to_server": hop_to_server,
        "hop_to_core": hop_to_core,
        "downstream_dependents": downstream_dependents,
        "path_up": path_up,
        "interface_type": interface_type,
        "topology_feature_fields": plan.topology_fields,
    }
    return topology


def _build_device_profile(row: Mapping[str, Any], plan: FeaturePlan, entity_key: str) -> dict[str, Any]:
    role = _first_by_name(row, ["role", "device_role", "node_type", "router_type"])
    name = _first_by_name(row, ["name", "device_name", "node_name", "hostname", "router"])
    site = _first_by_name(row, ["site", "pop", "location"])
    device_name = name or entity_key
    return {
        "src_device_key": entity_key,
        "device_role": role,
        "site": site,
        "vendor": "",
        "device_name": device_name,
        "osname": "",
        "family": "lcore-d",
        "srcmac": "",
        "model": "",
        "version": "",
        "asset_tags": [value for value in [role, site, plan.dataset_id] if value],
        "known_services": [_first_by_markers(row, _SERVICE_MARKERS)] if _first_by_markers(row, _SERVICE_MARKERS) else [],
    }


def _build_change_context(fault_state: Mapping[str, Any]) -> dict[str, Any]:
    scenario = str(fault_state.get("scenario") or "")
    suspected_change = scenario in {"misconfiguration", "routing_misconfiguration", "line_card_failure"} or "misconfig" in scenario
    return {
        "suspected_change": suspected_change,
        "change_window_min": 0,
        "change_refs": [f"fault_scenario:{scenario}"] if suspected_change else [],
        "score": None,
        "action": "fault_annotation" if suspected_change else "",
        "level": "warning" if suspected_change else "",
    }


def _feature_vector(row: Mapping[str, Any], metric_fields: list[str]) -> dict[str, float]:
    features: dict[str, float] = {}
    for field_name in metric_fields:
        number = _coerce_number(row.get(field_name))
        if number is not None:
            features[field_name] = number
    return features


def _select_metric_value(row: Mapping[str, Any], metric_fields: list[str], markers: set[str]) -> int | None:
    values = []
    for field_name in metric_fields:
        if not _has_marker(_normalize_name(field_name), markers):
            continue
        number = _coerce_number(row.get(field_name))
        if number is not None:
            values.append(number)
    if not values:
        return None
    return int(sum(values))


def _entity_key(row: Mapping[str, Any], plan: FeaturePlan) -> str:
    explicit = _first_by_name(
        row,
        [
            "device_name",
            "router_name",
            "node_name",
            "hostname",
            "router",
            "node",
            "source_node",
            "src_node",
        ],
    )
    if explicit and not _looks_like_low_semantic_entity("entity", explicit):
        return explicit

    entity = _first_non_empty(row, plan.entity_fields)
    if entity:
        return entity

    topology_entity = _first_non_empty(row, plan.topology_fields)
    if topology_entity:
        return topology_entity

    return "unknown"


def _path_signature(
    entity_key: str,
    src: str,
    dst: str,
    link: str,
    hop_to_core: str,
    hop_to_server: str,
    path_up: str,
) -> str:
    path_parts = [item for item in [src or entity_key, link, dst] if item and not _looks_like_local_path(item)]
    if len(path_parts) > 1:
        return "->".join(path_parts)

    topology_state = []
    if hop_to_core:
        topology_state.append(f"hop_core={hop_to_core}")
    if hop_to_server:
        topology_state.append(f"hop_server={hop_to_server}")
    if path_up:
        topology_state.append(f"path_up={path_up}")

    if topology_state:
        return f"{entity_key}|" + "|".join(topology_state)
    return entity_key


def _first_interface_name(row: Mapping[str, Any]) -> str:
    names = {
        "interface",
        "ifname",
        "port",
        "srcintf",
        "src_interface",
        "source_interface",
    }
    for key, value in row.items():
        if str(key).startswith("_"):
            continue
        normalized = _normalize_name(str(key))
        if "interface_type" in normalized:
            continue
        if normalized in names or normalized.endswith("_ifname") or normalized.endswith("_interface"):
            text = _clean_text(value)
            if text and not text.isdigit():
                return text
    return ""


def _first_interface_type(row: Mapping[str, Any]) -> str:
    for key, value in row.items():
        if str(key).startswith("_"):
            continue
        normalized = _normalize_name(str(key))
        if "interface_type" in normalized:
            text = _clean_text(value)
            if text:
                return text
    return ""


def _first_non_empty(row: Mapping[str, Any], fields: list[str]) -> str:
    for field_name in fields:
        if str(field_name).startswith("_"):
            continue
        text = _clean_text(row.get(field_name))
        if text and not _looks_like_low_semantic_entity(field_name, text):
            return text
    return ""


def _first_by_name(row: Mapping[str, Any], names: list[str]) -> str:
    wanted = {_normalize_name(name) for name in names}
    for key, value in row.items():
        if str(key).startswith("_"):
            continue
        normalized = _normalize_name(str(key))
        if normalized in wanted or any(_normalized_name_matches(normalized, wanted_name) for wanted_name in wanted):
            text = _clean_text(value)
            if text:
                return text
    return ""


def _first_by_markers(row: Mapping[str, Any], markers: set[str]) -> str:
    for key, value in row.items():
        if _has_marker(_normalize_name(str(key)), markers):
            text = _clean_text(value)
            if text:
                return text
    return ""


def _looks_like_local_path(value: str) -> bool:
    text = _clean_text(value)
    return text.startswith("/") or "/data/" in text or "\\" in text


def _normalized_name_matches(normalized: str, wanted_name: str) -> bool:
    if normalized == wanted_name:
        return True
    if normalized.startswith(f"{wanted_name}_") or normalized.endswith(f"_{wanted_name}"):
        return True
    tokens = normalized.split("_")
    if wanted_name in {"src", "dst", "to", "from", "source", "dest", "destination", "target"}:
        return tokens[0] == wanted_name or tokens[-1] == wanted_name
    if wanted_name == "name":
        return tokens[-1] == "name"
    return False


def _looks_like_low_semantic_entity(field_name: str, value: str) -> bool:
    text = _clean_text(value)
    normalized = _normalize_name(str(field_name))
    if _looks_like_local_path(text):
        return True
    if text.isdigit():
        return True
    low_semantic_markers = {
        "interface_type",
        "duplex_status",
        "operational_status",
        "hop_to_core",
        "hop_to_server",
        "path_up",
        "downstream_dependents",
    }
    return any(marker in normalized for marker in low_semantic_markers)


def _is_fault_label(value: Any) -> bool:
    text = _normalize_name(_clean_text(value))
    if text in {"f", "t"}:
        return True
    if text in _HEALTHY_VALUES:
        return False
    if text in {"1", "true", "yes", "y"}:
        return True
    return any(marker in text for marker in _FAULT_MARKERS)


def _normalize_scenario(value: Any) -> str:
    text = _normalize_name(_clean_text(value))
    if text in LCORE_D_SCENARIO_ALIASES:
        return LCORE_D_SCENARIO_ALIASES[text]
    if text in _HEALTHY_VALUES:
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
    if "link" in text and ("fault" in text or "failure" in text or "down" in text):
        return "link_failure"
    if "node" in text and ("fault" in text or "failure" in text or "down" in text):
        return "node_failure"
    if "routing" in text and ("misconfig" in text or "fault" in text or "failure" in text):
        return "routing_misconfiguration"
    if "misconfig" in text or text == "misconfiguration":
        return "misconfiguration"
    if "line" in text and "card" in text:
        return "line_card_failure"
    if "transient" in text:
        return "transient_fault"
    if text in {"1", "true", "yes", "y"}:
        return "annotated_fault"
    return text or "unknown_fault"


def _stable_event_id(dataset_id: str, row_index: int, row: Mapping[str, Any], run_id: str = "") -> str:
    raw = json.dumps(row, sort_keys=True, ensure_ascii=True, default=str)
    seed = f"{dataset_id}|{run_id}|{row_index}|{raw}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]


def _normalize_name(name: str) -> str:
    return _TOKEN_RE.sub("_", name.strip().lower()).strip("_")


def _name_preference(name: str) -> float:
    if name.startswith(("src_", "source_", "from_")) or name in {"src", "source", "from"}:
        return 3.0
    if "source" in name or "src" in name:
        return 2.0
    if "node" in name or "router" in name or "device" in name:
        return 1.0
    return 0.0


def _has_marker(name: str, markers: set[str]) -> bool:
    tokens = set(name.split("_"))
    return bool(tokens & markers) or any(marker in name for marker in markers)


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _coerce_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        return number if math.isfinite(number) else None
    text = _clean_text(value)
    if text == "":
        return None
    text = text.replace(",", "")
    try:
        number = float(text)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _parse_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    text = _normalize_name(_clean_text(value))
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return None


def _parse_timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = _clean_text(value)
        if text == "":
            return None
        if text.isdigit() and len(text) in {10, 13}:
            try:
                number = int(text)
                if len(text) == 13:
                    number = number / 1000
                return datetime.fromtimestamp(number, tz=timezone.utc)
            except (OverflowError, ValueError, OSError):
                return None
        normalized = text.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y %H:%M:%S"):
                try:
                    parsed = datetime.strptime(text, fmt)
                    break
                except ValueError:
                    parsed = None
            if parsed is None:
                return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed
