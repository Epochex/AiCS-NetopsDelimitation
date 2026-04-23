from __future__ import annotations

import argparse
import csv
import json
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from core.aiops_agent.alert_reasoning_runtime.budget_controller import select_windows_under_budget
from core.aiops_agent.alert_reasoning_runtime.incident_window import (
    build_incident_window_index,
    build_window_evidence_boundary,
)
from core.aiops_agent.alert_reasoning_runtime.window_labeling import build_weak_window_label
from core.benchmark.topology_subgraph_ablation import _iter_alerts


DEFAULT_ALERT_DIR = "/data/netops-runtime/LCORE-D/work/alerts-lcore-corepatched-full-20260412T152119Z"
DEFAULT_OUTPUT_DIR = "/data/netops-runtime/LCORE-D/work/window-dual-review-packet-v1"
DEFAULT_PER_STRATUM = 24

PRIMARY_STRATA = (
    "strict_budget_false_skip",
    "high_value_retained",
    "window_risk_tier_extra",
    "mixed_fault_and_transient",
    "pressure_self_healing",
    "local_single_transient",
    "topology_split_vs_adaptive_merge",
)


def run(args: argparse.Namespace) -> dict[str, Any]:
    rng = random.Random(args.seed)
    alerts = _iter_alerts(Path(args.alert_dir), args.limit_files)
    if args.max_alerts > 0:
        alerts = alerts[: args.max_alerts]
    if not alerts:
        raise ValueError("no alerts available for dual-review packet generation")

    session_windows = _build_windows(
        alerts,
        mode=str(args.window_mode),
        window_sec=args.window_sec,
        max_window_sec=args.max_window_sec,
    )
    adaptive_windows = _build_windows(
        alerts,
        mode=str(args.adaptive_window_mode),
        window_sec=args.adaptive_window_sec,
        max_window_sec=args.adaptive_max_window_sec,
    )
    topology_windows = _build_windows(
        alerts,
        mode=str(args.topology_window_mode),
        window_sec=args.topology_window_sec,
        max_window_sec=args.topology_max_window_sec,
    )

    strict_budget = select_windows_under_budget(
        session_windows,
        budget_fraction=args.budget_fraction,
        min_high_value=False,
    )
    risk_budget = select_windows_under_budget(
        session_windows,
        budget_fraction=args.budget_fraction,
        min_high_value=True,
    )
    strict_selected = set(strict_budget.get("selected_window_ids") or set())
    risk_selected = set(risk_budget.get("selected_window_ids") or set())

    session_by_id = {str(window.get("window_id") or ""): window for window in session_windows}
    session_overlap = _window_overlap_metadata(
        base_windows=session_windows,
        adaptive_windows=adaptive_windows,
        topology_windows=topology_windows,
    )
    stratum_to_windows = _build_strata(
        session_windows=session_windows,
        strict_selected=strict_selected,
        risk_selected=risk_selected,
        overlap=session_overlap,
    )
    sampled_window_ids = _sample_strata(
        session_by_id=session_by_id,
        stratum_to_windows=stratum_to_windows,
        per_stratum=args.per_stratum,
        max_windows=args.max_windows,
        rng=rng,
    )
    sampled_records = [
        _review_record(
            window=session_by_id[window_id],
            review_strata=_review_strata_for(window_id, stratum_to_windows),
            strict_selected=strict_selected,
            risk_selected=risk_selected,
            overlap=session_overlap.get(window_id) or {},
        )
        for window_id in sampled_window_ids
    ]
    sampled_records.sort(
        key=lambda record: (
            -int((record.get("window") or {}).get("high_value_count") or 0),
            -int((record.get("window") or {}).get("risk_score") or 0),
            str((record.get("window") or {}).get("window_label") or ""),
            str((record.get("window") or {}).get("window_id") or ""),
        )
    )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    master_jsonl = output_dir / "window_dual_review_master.jsonl"
    reviewer_a_jsonl = output_dir / "window_dual_review_reviewer_a.jsonl"
    reviewer_b_jsonl = output_dir / "window_dual_review_reviewer_b.jsonl"
    csv_path = output_dir / "window_dual_review_sheet.csv"
    summary_json = output_dir / "window_dual_review_summary.json"

    _write_jsonl(master_jsonl, sampled_records)
    _write_jsonl(reviewer_a_jsonl, [_reset_review(record, reviewer="reviewer_a") for record in sampled_records])
    _write_jsonl(reviewer_b_jsonl, [_reset_review(record, reviewer="reviewer_b") for record in sampled_records])
    _write_csv(csv_path, sampled_records)

    report = {
        "schema_version": 1,
        "alert_dir": args.alert_dir,
        "alerts_scanned": len(alerts),
        "session_windows": len(session_windows),
        "adaptive_windows": len(adaptive_windows),
        "topology_windows": len(topology_windows),
        "budget_fraction": args.budget_fraction,
        "strict_budget_selected_windows": len(strict_selected),
        "risk_budget_selected_windows": len(risk_selected),
        "strata_population": {
            name: len(items) for name, items in sorted(stratum_to_windows.items())
        },
        "windows_sampled": len(sampled_records),
        "sampled_strata_counts": dict(
            Counter(
                stratum
                for record in sampled_records
                for stratum in list(record.get("review_strata") or [])
            ).most_common()
        ),
        "output_master_jsonl": str(master_jsonl),
        "output_reviewer_a_jsonl": str(reviewer_a_jsonl),
        "output_reviewer_b_jsonl": str(reviewer_b_jsonl),
        "output_csv": str(csv_path),
        "review_protocol": {
            "goal": "independent dual review of window-level external-worthiness, representative sufficiency, and boundary quality",
            "notes": [
                "risk-budget and scenario-only select the same 348 high-value windows on the sessionized denominator",
                "strict-budget false skips are therefore the highest-priority disagreement bucket",
                "topology_split_vs_adaptive_merge marks windows whose alerts participate in an adaptive merge that topology-coupled AiCS splits",
            ],
        },
    }
    summary_json.write_text(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
    return report


def _build_windows(
    alerts: list[dict[str, Any]],
    *,
    mode: str,
    window_sec: int,
    max_window_sec: int,
) -> list[dict[str, Any]]:
    windows, _ = build_incident_window_index(
        alerts,
        window_sec=window_sec,
        window_mode=mode,
        max_window_sec=max_window_sec,
    )
    return windows


def _window_overlap_metadata(
    *,
    base_windows: list[dict[str, Any]],
    adaptive_windows: list[dict[str, Any]],
    topology_windows: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    adaptive_by_alert = _alert_to_window(adaptive_windows)
    topology_by_alert = _alert_to_window(topology_windows)
    adaptive_split_alerts: set[str] = set()
    for adaptive in adaptive_windows:
        topology_ids = {
            topology_by_alert.get(alert_id)
            for alert_id in list(adaptive.get("alert_ids") or [])
            if topology_by_alert.get(alert_id)
        }
        topology_ids.discard(None)
        if len(topology_ids) > 1:
            adaptive_split_alerts.update(str(alert_id) for alert_id in list(adaptive.get("alert_ids") or []))

    metadata: dict[str, dict[str, Any]] = {}
    for window in base_windows:
        alert_ids = [str(alert_id) for alert_id in list(window.get("alert_ids") or []) if str(alert_id)]
        adaptive_ids = sorted(
            {
                str(adaptive_by_alert.get(alert_id) or "")
                for alert_id in alert_ids
                if str(adaptive_by_alert.get(alert_id) or "")
            }
        )
        topology_ids = sorted(
            {
                str(topology_by_alert.get(alert_id) or "")
                for alert_id in alert_ids
                if str(topology_by_alert.get(alert_id) or "")
            }
        )
        metadata[str(window.get("window_id") or "")] = {
            "adaptive_window_ids": adaptive_ids,
            "adaptive_window_count": len(adaptive_ids),
            "topology_window_ids": topology_ids,
            "topology_window_count": len(topology_ids),
            "topology_split_vs_adaptive_merge": any(alert_id in adaptive_split_alerts for alert_id in alert_ids),
        }
    return metadata


def _alert_to_window(windows: list[dict[str, Any]]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for window in windows:
        window_id = str(window.get("window_id") or "")
        for alert_id in list(window.get("alert_ids") or []):
            alert_id = str(alert_id)
            if alert_id:
                mapping[alert_id] = window_id
    return mapping


def _build_strata(
    *,
    session_windows: list[dict[str, Any]],
    strict_selected: set[str],
    risk_selected: set[str],
    overlap: dict[str, dict[str, Any]],
) -> dict[str, list[str]]:
    strata: dict[str, list[str]] = defaultdict(list)
    for window in session_windows:
        window_id = str(window.get("window_id") or "")
        high_value = int(window.get("high_value_count") or 0) > 0
        label = str(window.get("window_label") or "")
        quality = str(window.get("quality_proxy_label") or "")
        recommended_action = str(window.get("recommended_action") or "local")
        review_overlap = overlap.get(window_id) or {}
        if high_value:
            strata["high_value_retained"].append(window_id)
        if high_value and window_id not in strict_selected:
            strata["strict_budget_false_skip"].append(window_id)
        if recommended_action == "external" and not high_value:
            strata["window_risk_tier_extra"].append(window_id)
        if label == "mixed_fault_and_transient":
            strata["mixed_fault_and_transient"].append(window_id)
        if quality == "pressure_self_healing_window":
            strata["pressure_self_healing"].append(window_id)
        if label == "local_single_transient":
            strata["local_single_transient"].append(window_id)
        if bool(review_overlap.get("topology_split_vs_adaptive_merge")):
            strata["topology_split_vs_adaptive_merge"].append(window_id)
        if window_id in risk_selected and window_id not in strict_selected:
            strata["risk_floor_rescued"].append(window_id)
    return {name: values for name, values in strata.items() if values}


def _sample_strata(
    *,
    session_by_id: dict[str, dict[str, Any]],
    stratum_to_windows: dict[str, list[str]],
    per_stratum: int,
    max_windows: int,
    rng: random.Random,
) -> list[str]:
    selected: list[str] = []
    seen: set[str] = set()
    ordered_strata = list(PRIMARY_STRATA) + [
        name for name in sorted(stratum_to_windows) if name not in PRIMARY_STRATA
    ]
    for stratum in ordered_strata:
        candidates = stratum_to_windows.get(stratum) or []
        ranked = sorted(
            candidates,
            key=lambda window_id: (
                -int((session_by_id.get(window_id) or {}).get("high_value_count") or 0),
                -int((session_by_id.get(window_id) or {}).get("risk_score") or 0),
                -int((session_by_id.get(window_id) or {}).get("alert_count") or 0),
                str(window_id),
            ),
        )
        head = ranked[: max(1, per_stratum // 2)]
        tail = ranked[max(1, per_stratum // 2):]
        rng.shuffle(tail)
        chosen = head + tail[: max(0, per_stratum - len(head))]
        for window_id in chosen:
            if max_windows and len(selected) >= max_windows:
                break
            if window_id in seen:
                continue
            selected.append(window_id)
            seen.add(window_id)
    return selected


def _review_strata_for(window_id: str, stratum_to_windows: dict[str, list[str]]) -> list[str]:
    return sorted(name for name, values in stratum_to_windows.items() if window_id in values)


def _review_record(
    *,
    window: dict[str, Any],
    review_strata: list[str],
    strict_selected: set[str],
    risk_selected: set[str],
    overlap: dict[str, Any],
) -> dict[str, Any]:
    boundary = build_window_evidence_boundary(window)
    window_id = str(window.get("window_id") or "")
    selected_surface = boundary.get("selected_surface") or {}
    excluded_surface = boundary.get("excluded_surface") or []
    missing_surface = boundary.get("missing_surface") or []
    review_context = {
        "window_id": window_id,
        "window_label": str(window.get("window_label") or ""),
        "quality_proxy_label": str(window.get("quality_proxy_label") or ""),
        "risk_tier": str(window.get("risk_tier") or ""),
        "risk_score": int(window.get("risk_score") or 0),
        "recommended_action": str(window.get("recommended_action") or "local"),
        "alert_count": int(window.get("alert_count") or 0),
        "high_value_count": int(window.get("high_value_count") or 0),
        "device_count": int(window.get("device_count") or 0),
        "path_count": int(window.get("path_count") or 0),
        "window_start": str(window.get("window_start") or ""),
        "window_end": str(window.get("window_end") or ""),
        "scenario_counts": window.get("scenario_counts") or {},
        "risk_reasons": list(window.get("risk_reasons") or [])[:8],
        "selected_devices": list(selected_surface.get("devices") or []),
        "selected_paths": list(selected_surface.get("path_signatures") or []),
        "selected_representatives": list(selected_surface.get("representative_alert_ids") or []),
        "excluded_surface": excluded_surface[:6],
        "missing_surface": missing_surface[:6],
        "timeline": list(window.get("timeline") or [])[:8],
        "policy_flags": {
            "risk_budget_20_selected": window_id in risk_selected,
            "strict_budget_20_selected": window_id in strict_selected,
            "strict_budget_false_skip": int(window.get("high_value_count") or 0) > 0 and window_id not in strict_selected,
            "topology_split_vs_adaptive_merge": bool(overlap.get("topology_split_vs_adaptive_merge")),
        },
        "boundary_overlap": overlap,
    }
    return {
        "window_id": window_id,
        "review_strata": review_strata,
        "window": window,
        "review_context": review_context,
        "weak_label": build_weak_window_label(window),
        "expert_label": _empty_expert_label(),
    }


def _empty_expert_label() -> dict[str, Any]:
    return {
        "should_invoke_external": None,
        "representative_alert_sufficient": None,
        "selected_device_covered": None,
        "selected_path_covered": None,
        "timeline_sufficient": None,
        "false_skip_if_local": None,
        "boundary_should_split_further": None,
        "boundary_should_merge_adjacent": None,
        "reviewer": "",
        "review_notes": "",
    }


def _reset_review(record: dict[str, Any], *, reviewer: str) -> dict[str, Any]:
    copied = json.loads(json.dumps(record))
    copied["expert_label"] = _empty_expert_label()
    copied["expert_label"]["reviewer"] = reviewer
    return copied


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as fp:
        for record in records:
            fp.write(json.dumps(record, ensure_ascii=True, sort_keys=True) + "\n")


def _write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    fieldnames = [
        "window_id",
        "review_strata",
        "window_label",
        "quality_proxy_label",
        "risk_tier",
        "risk_score",
        "recommended_action",
        "alert_count",
        "high_value_count",
        "device_count",
        "path_count",
        "window_start",
        "window_end",
        "policy_risk_budget_20_selected",
        "policy_strict_budget_20_selected",
        "policy_strict_budget_false_skip",
        "policy_topology_split_vs_adaptive_merge",
        "selected_devices",
        "selected_paths",
        "selected_representatives",
        "risk_reasons",
        "missing_surface",
        "timeline_excerpt",
        "should_invoke_external",
        "representative_alert_sufficient",
        "selected_device_covered",
        "selected_path_covered",
        "timeline_sufficient",
        "false_skip_if_local",
        "boundary_should_split_further",
        "boundary_should_merge_adjacent",
        "reviewer",
        "review_notes",
    ]
    with path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            context = record.get("review_context") or {}
            flags = context.get("policy_flags") or {}
            review = record.get("expert_label") or {}
            timeline_excerpt = []
            for item in list(context.get("timeline") or [])[:4]:
                timeline_excerpt.append(
                    f"{item.get('alert_ts')}|{item.get('device')}|{item.get('scenario')}"
                )
            writer.writerow(
                {
                    "window_id": record.get("window_id") or "",
                    "review_strata": ";".join(list(record.get("review_strata") or [])),
                    "window_label": context.get("window_label") or "",
                    "quality_proxy_label": context.get("quality_proxy_label") or "",
                    "risk_tier": context.get("risk_tier") or "",
                    "risk_score": context.get("risk_score") or 0,
                    "recommended_action": context.get("recommended_action") or "",
                    "alert_count": context.get("alert_count") or 0,
                    "high_value_count": context.get("high_value_count") or 0,
                    "device_count": context.get("device_count") or 0,
                    "path_count": context.get("path_count") or 0,
                    "window_start": context.get("window_start") or "",
                    "window_end": context.get("window_end") or "",
                    "policy_risk_budget_20_selected": flags.get("risk_budget_20_selected"),
                    "policy_strict_budget_20_selected": flags.get("strict_budget_20_selected"),
                    "policy_strict_budget_false_skip": flags.get("strict_budget_false_skip"),
                    "policy_topology_split_vs_adaptive_merge": flags.get("topology_split_vs_adaptive_merge"),
                    "selected_devices": ";".join(str(item) for item in list(context.get("selected_devices") or [])),
                    "selected_paths": ";".join(str(item) for item in list(context.get("selected_paths") or [])),
                    "selected_representatives": ";".join(str(item) for item in list(context.get("selected_representatives") or [])),
                    "risk_reasons": "; ".join(str(item) for item in list(context.get("risk_reasons") or [])),
                    "missing_surface": "; ".join(
                        str(item.get("field") or item) for item in list(context.get("missing_surface") or [])
                    ),
                    "timeline_excerpt": " || ".join(timeline_excerpt),
                    "should_invoke_external": review.get("should_invoke_external"),
                    "representative_alert_sufficient": review.get("representative_alert_sufficient"),
                    "selected_device_covered": review.get("selected_device_covered"),
                    "selected_path_covered": review.get("selected_path_covered"),
                    "timeline_sufficient": review.get("timeline_sufficient"),
                    "false_skip_if_local": review.get("false_skip_if_local"),
                    "boundary_should_split_further": review.get("boundary_should_split_further"),
                    "boundary_should_merge_adjacent": review.get("boundary_should_merge_adjacent"),
                    "reviewer": review.get("reviewer") or "",
                    "review_notes": review.get("review_notes") or "",
                }
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a dual-review packet for LCORE-D incident windows.")
    parser.add_argument("--alert-dir", default=DEFAULT_ALERT_DIR)
    parser.add_argument("--limit-files", type=int, default=0)
    parser.add_argument("--max-alerts", type=int, default=0)
    parser.add_argument("--window-mode", default="session", choices=("session", "fixed", "adaptive", "aics-topology", "aics-evidence", "aics"))
    parser.add_argument("--window-sec", type=int, default=600)
    parser.add_argument("--max-window-sec", type=int, default=600)
    parser.add_argument("--adaptive-window-mode", default="adaptive", choices=("adaptive", "session"))
    parser.add_argument("--adaptive-window-sec", type=int, default=600)
    parser.add_argument("--adaptive-max-window-sec", type=int, default=1800)
    parser.add_argument("--topology-window-mode", default="aics-topology", choices=("aics-topology", "aics-evidence", "aics"))
    parser.add_argument("--topology-window-sec", type=int, default=500)
    parser.add_argument("--topology-max-window-sec", type=int, default=1200)
    parser.add_argument("--budget-fraction", type=float, default=0.2)
    parser.add_argument("--per-stratum", type=int, default=DEFAULT_PER_STRATUM)
    parser.add_argument("--max-windows", type=int, default=0)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
