from __future__ import annotations

from typing import Any


def build_weak_window_label(window: dict[str, Any]) -> dict[str, Any]:
    """Create a reviewable weak label for window-level admission evaluation."""

    label = str(window.get("window_label") or "")
    risk_tier = str(window.get("risk_tier") or "low")
    high_value = int(window.get("high_value_count") or 0) > 0
    pressure = bool(
        window.get("topology_pressure")
        or window.get("recurrence_pressure")
        or window.get("multi_device_spread")
    )
    representative_ids = _representative_ids(window)
    selected_devices = (window.get("selected_evidence_targets") or {}).get("devices") or []
    selected_paths = (window.get("selected_evidence_targets") or {}).get("path_signatures") or []
    should_invoke = high_value or label in {
        "external_induced_fault",
        "mixed_fault_and_transient",
        "external_multi_device_spread",
        "external_repeated_transient",
        "external_unknown_with_pressure",
    }
    local_sufficient = not should_invoke and risk_tier == "low"
    safe_skip = not should_invoke and label != "local_transient_with_pressure"
    needs_review = bool(
        label in {"local_transient_with_pressure", "external_unknown_with_pressure"}
        or (pressure and not should_invoke)
        or not representative_ids
    )
    return {
        "schema_version": 1,
        "window_id": str(window.get("window_id") or ""),
        "window_label": label,
        "risk_tier": risk_tier,
        "risk_score": int(window.get("risk_score") or 0),
        "risk_atoms": window.get("risk_atoms") or [],
        "quality_proxy_label": str(window.get("quality_proxy_label") or ""),
        "should_invoke_external": bool(should_invoke),
        "local_sufficient": bool(local_sufficient),
        "safe_skip": bool(safe_skip),
        "representative_alert_sufficient": bool(representative_ids),
        "selected_device_covered": bool(selected_devices),
        "selected_path_covered": bool(selected_paths),
        "timeline_sufficient": int(window.get("alert_count") or 0) > 1,
        "needs_review": needs_review,
        "reason": _reason(
            label=label,
            high_value=high_value,
            pressure=pressure,
            representative_ids=representative_ids,
            risk_tier=risk_tier,
        ),
    }


def _representative_ids(window: dict[str, Any]) -> list[str]:
    targets = window.get("selected_evidence_targets") or {}
    values = targets.get("representative_alert_ids") or targets.get("alert_ids") or []
    return [str(value) for value in values if str(value)]


def _reason(
    *,
    label: str,
    high_value: bool,
    pressure: bool,
    representative_ids: list[str],
    risk_tier: str,
) -> str:
    if high_value:
        return "window contains high-value fault evidence and should remain eligible for external reasoning."
    if label == "mixed_fault_and_transient":
        return "window mixes transient and high-value evidence; external reasoning should preserve the fault context."
    if label in {"external_multi_device_spread", "external_repeated_transient"}:
        return "transient-looking window has spread or recurrence pressure."
    if label == "local_transient_with_pressure":
        return "window stays local by default but should be reviewed because pressure is present."
    if not representative_ids:
        return "no representative alert was selected; manual review is needed."
    if pressure:
        return f"{risk_tier} risk window has pressure but no external trigger."
    return "low-risk transient or low-evidence window is suitable for local handling."
