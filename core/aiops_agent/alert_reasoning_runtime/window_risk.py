from __future__ import annotations

import hashlib
from typing import Any


HIGH_RISK_LABELS = {
    "external_induced_fault",
    "mixed_fault_and_transient",
    "external_multi_device_spread",
}
MEDIUM_RISK_LABELS = {
    "external_repeated_transient",
    "external_unknown_with_pressure",
    "local_transient_with_pressure",
}

DEFAULT_RISK_WEIGHTS = {
    "value:high_fault": 10,
    "context:mixed_fault_transient": 7,
    "spread:multi_device": 6,
    "pressure:recurrence": 4,
    "pressure:topology": 4,
    "scope:multi_path": 2,
    "impact:downstream_fanout": 2,
    "missing:device": 2,
    "missing:path": 2,
    "missing:timeline": 1,
    "scope:device": 1,
    "scope:path": 1,
    "occurrence:high": 3,
    "occurrence:pressure": 1,
    "mitigation:self_healing_dominant": -2,
}


def score_window_risk(window: dict[str, Any] | None) -> dict[str, Any]:
    """Extract risk atoms and derive a deterministic admission tier.

    The atoms are the primary output. The score and tier are deterministic
    summaries used by legacy policies and reports. They are not diagnosis
    scores; they estimate the risk of keeping the window away from external
    model reasoning.
    """

    if not window:
        return {
            "schema_version": 1,
            "risk_atoms": [],
            "risk_offsets": [],
            "risk_weights": dict(DEFAULT_RISK_WEIGHTS),
            "risk_score": 0,
            "risk_tier": "low",
            "risk_reasons": ["no incident window"],
        }

    atoms = extract_window_risk_atoms(window)
    offsets = _risk_offsets(window)
    score = max(
        sum(int(atom.get("weight") or 0) for atom in atoms)
        + sum(int(offset.get("weight") or 0) for offset in offsets),
        0,
    )
    label = str(window.get("window_label") or "")
    tier = _tier_for(score=score, label=label)
    return {
        "schema_version": 1,
        "risk_atoms": atoms,
        "risk_offsets": offsets,
        "risk_weights": dict(DEFAULT_RISK_WEIGHTS),
        "risk_score": score,
        "risk_tier": tier,
        "risk_reasons": _risk_reasons(atoms, offsets),
    }


def extract_window_risk_atoms(window: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Return positive risk atoms used by budgeted coverage admission."""

    if not window:
        return []

    atoms: list[dict[str, Any]] = []
    label = str(window.get("window_label") or "")
    high_value_count = int(window.get("high_value_count") or 0)
    device_count = int(window.get("device_count") or 0)
    path_count = int(window.get("path_count") or 0)
    alert_count = int(window.get("alert_count") or 0)
    max_downstream = int(window.get("max_downstream_dependents") or 0)

    if high_value_count > 0:
        atoms.append(_atom("value:high_fault", "contains high-value fault evidence"))
    if label == "mixed_fault_and_transient":
        atoms.append(_atom("context:mixed_fault_transient", "mixes high-value and transient evidence"))
    if bool(window.get("multi_device_spread")) or device_count >= 2:
        atoms.append(_atom("spread:multi_device", "spans multiple devices"))
    if bool(window.get("recurrence_pressure")) or alert_count >= 3:
        atoms.append(_atom("pressure:recurrence", "has recurrence pressure"))
    if bool(window.get("topology_pressure")):
        atoms.append(_atom("pressure:topology", "has topology pressure"))
    if path_count >= 2:
        atoms.append(_atom("scope:multi_path", "spans multiple paths"))
    if max_downstream >= 10:
        atoms.append(_atom("impact:downstream_fanout", "has high downstream fanout"))
    if device_count == 0:
        atoms.append(_atom("missing:device", "device evidence is missing"))
    if path_count == 0:
        atoms.append(_atom("missing:path", "path evidence is missing"))
    if alert_count <= 1:
        atoms.append(_atom("missing:timeline", "single-alert window has no temporal ordering"))

    for device in list(window.get("devices") or [])[:4]:
        if str(device).strip():
            atoms.append(_atom(f"scope:device:{_stable_short(str(device))}", "covers a device-specific risk scope"))
    for path in list(window.get("path_shapes") or window.get("path_signatures") or [])[:4]:
        if str(path).strip():
            atoms.append(_atom(f"scope:path:{_stable_short(str(path))}", "covers a path-specific risk scope"))

    window_id = str(window.get("window_id") or _stable_short(str(window)))
    if high_value_count > 0 or label in HIGH_RISK_LABELS:
        atoms.append(_atom(f"occurrence:high:{_stable_short(window_id)}", "covers one high-risk window occurrence"))
    elif bool(window.get("recurrence_pressure")) or bool(window.get("topology_pressure")):
        atoms.append(_atom(f"occurrence:pressure:{_stable_short(window_id)}", "covers one pressure-window occurrence"))

    return atoms


def _risk_offsets(window: dict[str, Any]) -> list[dict[str, Any]]:
    if bool(window.get("self_healing_dominant")) and int(window.get("high_value_count") or 0) == 0:
        return [
            {
                "key": "mitigation:self_healing_dominant",
                "weight": DEFAULT_RISK_WEIGHTS["mitigation:self_healing_dominant"],
                "reason": "self-healing dominated",
            }
        ]
    return []


def _atom(key: str, reason: str) -> dict[str, Any]:
    weight_key = key
    if key.startswith("scope:device:"):
        weight_key = "scope:device"
    elif key.startswith("scope:path:"):
        weight_key = "scope:path"
    elif key.startswith("occurrence:high:"):
        weight_key = "occurrence:high"
    elif key.startswith("occurrence:pressure:"):
        weight_key = "occurrence:pressure"
    return {
        "key": key,
        "weight": DEFAULT_RISK_WEIGHTS[weight_key],
        "reason": reason,
    }


def _risk_reasons(atoms: list[dict[str, Any]], offsets: list[dict[str, Any]]) -> list[str]:
    reasons: list[str] = []
    for item in [*atoms, *offsets]:
        reason = str(item.get("reason") or "")
        if reason and reason not in reasons:
            reasons.append(reason)
    return reasons or ["low evidence risk"]


def _stable_short(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]


def _tier_for(*, score: int, label: str) -> str:
    if label in HIGH_RISK_LABELS or score >= 12:
        return "high"
    if label in MEDIUM_RISK_LABELS or score >= 3:
        return "medium"
    return "low"
