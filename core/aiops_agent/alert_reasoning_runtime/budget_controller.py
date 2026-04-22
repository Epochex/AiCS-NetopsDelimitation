from __future__ import annotations

from typing import Any


def select_windows_under_budget(
    windows: list[dict[str, Any]],
    *,
    budget_fraction: float,
    min_high_value: bool = True,
) -> dict[str, Any]:
    """Select windows by marginal uncovered risk per representative-call cost.

    ``budget_fraction`` is expressed against the number of windows and converted
    into an external-call budget. When ``min_high_value`` is enabled, high-value
    windows form a safety floor and may exceed the nominal budget; the returned
    summary reports that overflow explicitly.
    """

    budget_fraction = max(0.0, min(float(budget_fraction), 1.0))
    total = len(windows)
    budget_calls = int(round(total * budget_fraction))
    if budget_fraction > 0 and budget_calls == 0 and total > 0:
        budget_calls = 1

    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    covered_atoms: set[str] = set()
    used_calls = 0

    if min_high_value:
        for window in _rank_windows_by_score(windows):
            if int(window.get("high_value_count") or 0) <= 0:
                continue
            selected.append(window)
            selected_ids.add(str(window.get("window_id") or ""))
            covered_atoms |= _atom_keys(window)
            used_calls += _representative_cost(window)

    remaining = [
        window for window in windows
        if str(window.get("window_id") or "") not in selected_ids
    ]
    while remaining:
        if used_calls >= budget_calls:
            break
        best = max(
            remaining,
            key=lambda window: _priority(window, covered_atoms),
        )
        gain = _marginal_gain(best, covered_atoms)
        cost = _representative_cost(best)
        if gain <= 0:
            break
        if used_calls + cost > budget_calls and used_calls > 0:
            break
        window_id = str(best.get("window_id") or "")
        selected.append(best)
        selected_ids.add(window_id)
        covered_atoms |= _atom_keys(best)
        used_calls += cost
        remaining = [
            window for window in remaining
            if str(window.get("window_id") or "") != window_id
        ]

    representative_alert_ids: set[str] = set()
    selected_window_ids: set[str] = set()
    for window in selected:
        window_id = str(window.get("window_id") or "")
        if window_id:
            selected_window_ids.add(window_id)
        representative_alert_ids.update(_representative_ids(window))

    return {
        "schema_version": 1,
        "admission_strategy": "marginal_uncovered_risk_per_representative_cost",
        "objective": {
            "maximize": "unique_risk_atom_weight_under_representative_call_budget",
            "safety_floor": "all_high_value_windows" if min_high_value else "none",
        },
        "budget_fraction": budget_fraction,
        "budget_windows": budget_calls,
        "budget_external_calls": budget_calls,
        "used_external_calls": len(representative_alert_ids),
        "safety_floor_extra_calls": max(0, len(representative_alert_ids) - budget_calls),
        "windows_total": total,
        "selected_window_ids": selected_window_ids,
        "representative_alert_ids": representative_alert_ids,
        "selected_windows": len(selected_window_ids),
        "selected_representative_alerts": len(representative_alert_ids),
        "covered_risk_atoms": sorted(covered_atoms),
        "covered_risk_atom_count": len(covered_atoms),
        "selected_risk_weight": _selected_risk_weight(selected),
    }


def _rank_windows_by_score(windows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        windows,
        key=lambda window: (
            _tier_rank(str(window.get("risk_tier") or "")),
            int(window.get("risk_score") or 0),
            int(window.get("high_value_count") or 0),
            int(window.get("pressure_score") or 0),
            int(window.get("alert_count") or 0),
        ),
        reverse=True,
    )


def _tier_rank(tier: str) -> int:
    return {"high": 3, "medium": 2, "low": 1}.get(tier, 0)


def _representative_ids(window: dict[str, Any]) -> set[str]:
    targets = window.get("selected_evidence_targets") or {}
    values = targets.get("representative_alert_ids") or targets.get("alert_ids") or []
    return {str(value) for value in values if str(value)}


def _representative_cost(window: dict[str, Any]) -> int:
    return max(1, len(_representative_ids(window)))


def _atom_keys(window: dict[str, Any]) -> set[str]:
    atoms = window.get("risk_atoms") or []
    return {
        str(atom.get("key") or "")
        for atom in atoms
        if isinstance(atom, dict) and str(atom.get("key") or "")
    }


def _atom_weight(atom: dict[str, Any]) -> int:
    try:
        return int(atom.get("weight") or 0)
    except (TypeError, ValueError):
        return 0


def _marginal_gain(window: dict[str, Any], covered_atoms: set[str]) -> int:
    gain = 0
    for atom in window.get("risk_atoms") or []:
        if not isinstance(atom, dict):
            continue
        key = str(atom.get("key") or "")
        if key and key not in covered_atoms:
            gain += max(_atom_weight(atom), 0)
    return gain


def _priority(window: dict[str, Any], covered_atoms: set[str]) -> tuple[float, int, int, int]:
    cost = _representative_cost(window)
    gain = _marginal_gain(window, covered_atoms)
    return (
        gain / max(cost, 1),
        int(window.get("risk_score") or 0),
        int(window.get("high_value_count") or 0),
        int(window.get("alert_count") or 0),
    )


def _selected_risk_weight(windows: list[dict[str, Any]]) -> int:
    total = 0
    for window in windows:
        for atom in window.get("risk_atoms") or []:
            if isinstance(atom, dict):
                total += max(_atom_weight(atom), 0)
    return total
