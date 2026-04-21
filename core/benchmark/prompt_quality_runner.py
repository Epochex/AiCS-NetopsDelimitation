from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from core.aiops_agent.alert_reasoning_runtime.incident_window import build_window_evidence_boundary
from core.aiops_agent.alert_reasoning_runtime.prompt_contracts import build_prompt_contracts


PROMPT_STRATEGIES = (
    "alert-only",
    "single-interpretation",
    "context-views",
    "boundary-then-interpretation",
    "full-contract",
)
UNSAFE_TERMS = ("reboot now", "delete service", "shutdown service", "apply command", "execute command")
OVERCLAIM_TERMS = ("guarantee", "proved", "definitely root", "root-cause accuracy")


def run(args: argparse.Namespace) -> dict[str, Any]:
    windows = _read_jsonl(Path(args.windows_jsonl))
    if args.max_windows > 0:
        windows = windows[: args.max_windows]

    raw_records: list[dict[str, Any]] = []
    score_rows: list[dict[str, Any]] = []
    for window in windows:
        views = _context_views_from_window(window)
        contracts = build_prompt_contracts(views)
        for strategy in PROMPT_STRATEGIES:
            response = _template_response(strategy=strategy, window=window, views=views, contracts=contracts)
            score = _score_response(strategy=strategy, window=window, views=views, response=response)
            raw_records.append(
                {
                    "window_id": str(window.get("window_id") or ""),
                    "strategy": strategy,
                    "prompt_contract": _contract_names(strategy),
                    "context_summary": contracts.get("context_view_summary") or {},
                    "raw_response": response,
                    "score": score,
                }
            )
            score_rows.append({"strategy": strategy, **score})

    summary = {
        "schema_version": 1,
        "windows": len(windows),
        "provider": "template",
        "strategies": _summarize_scores(score_rows),
        "quality_scope": (
            "prompt-contract and context-shape evaluation with deterministic template responses; "
            "external-model quality must be measured separately with saved provider outputs"
        ),
    }
    if args.output_raw_jsonl:
        _write_jsonl(Path(args.output_raw_jsonl), raw_records)
    if args.output_scores_json:
        path = Path(args.output_scores_json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(summary, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=True, indent=2, sort_keys=True))
    return summary


def _context_views_from_window(window: dict[str, Any]) -> dict[str, Any]:
    boundary = build_window_evidence_boundary(window)
    selected = boundary.get("selected_surface") or {}
    devices = [str(item) for item in selected.get("devices") or window.get("devices") or [] if str(item)]
    paths = [str(item) for item in selected.get("path_signatures") or window.get("path_signatures") or [] if str(item)]
    representative = [str(item) for item in selected.get("representative_alert_ids") or [] if str(item)]
    return {
        "alert_view": {
            "window_id": str(window.get("window_id") or ""),
            "window_label": str(window.get("window_label") or ""),
            "recommended_action": str(window.get("recommended_action") or "local"),
            "representative_alert_ids": representative,
            "scenario_counts": window.get("scenario_counts") or {},
        },
        "topology_view": {
            "src_device_key": devices[0] if devices else "",
            "devices": devices,
            "path_signature": paths[0] if paths else "",
            "path_signatures": paths,
            "device_count": int(window.get("device_count") or 0),
            "path_count": int(window.get("path_count") or 0),
        },
        "timeline_view": {
            "incident_window": {
                "window_start": str(window.get("window_start") or ""),
                "window_end": str(window.get("window_end") or ""),
                "alert_count": int(window.get("alert_count") or 0),
                "timeline": window.get("timeline") or [],
            },
            "window_boundary": {
                "timeline_required": bool(selected.get("timeline_required")),
            },
        },
        "history_view": {
            "recurrence_pressure": bool(window.get("recurrence_pressure")),
            "risk_reasons": window.get("risk_reasons") or [],
        },
        "missing_evidence_view": boundary.get("missing_surface") or [],
        "excluded_evidence_view": boundary.get("excluded_surface") or [],
        "serving_view": {
            "risk_tier": str(window.get("risk_tier") or "low"),
            "risk_score": int(window.get("risk_score") or 0),
            "decision_reason": str(window.get("decision_reason") or ""),
        },
    }


def _template_response(
    *,
    strategy: str,
    window: dict[str, Any],
    views: dict[str, Any],
    contracts: dict[str, Any],
) -> dict[str, Any]:
    topology = views["topology_view"]
    timeline = views["timeline_view"]["incident_window"]
    missing = views["missing_evidence_view"]
    excluded = views["excluded_evidence_view"]
    device = str(topology.get("src_device_key") or "the alerted device")
    path = str(topology.get("path_signature") or "the observed path")
    alert_count = int(timeline.get("alert_count") or 0)

    if strategy == "alert-only":
        return {
            "summary": f"Window {window.get('window_label', 'unknown')} should be reviewed.",
            "hypotheses": ["Use the alert label as the main signal."],
            "recommended_actions": ["Keep remediation human-reviewed."],
            "confidence_label": "low",
        }
    if strategy == "single-interpretation":
        return {
            "summary": f"{device} has bounded evidence on {path}.",
            "hypotheses": [f"Evidence points to {device} within the selected path context."],
            "recommended_actions": ["Review metrics and topology before action."],
            "confidence_label": "medium",
        }
    if strategy == "context-views":
        return {
            "summary": f"{device} on {path} appears in a {alert_count}-alert window.",
            "hypotheses": [f"Selected devices and paths define the model-visible context for {device}."],
            "missing_evidence": [str(item.get("field") or item) for item in missing if isinstance(item, dict)],
            "recommended_actions": ["Check the selected path and timeline; do not execute remediation automatically."],
            "confidence_label": "medium",
        }
    if strategy == "boundary-then-interpretation":
        return {
            "boundary_review": {
                "boundary_status": "accepted" if not missing else "needs_more_evidence",
                "missing_evidence": [str(item.get("field") or item) for item in missing if isinstance(item, dict)],
                "excluded_evidence_issues": [],
                "external_reasoning_needed": str(window.get("recommended_action") or "") == "external",
            },
            "interpretation": {
                "summary": f"Selected evidence covers {device}, {path}, and {alert_count} timeline events.",
                "hypotheses": ["The boundary is sufficient for advisory interpretation when selected evidence is present."],
                "recommended_actions": ["Use advisory checks only."],
            },
        }
    return {
        "boundary_review": {
            "boundary_status": "accepted" if not missing else "needs_more_evidence",
            "missing_evidence": [str(item.get("field") or item) for item in missing if isinstance(item, dict)],
            "selected_evidence_issues": [],
            "excluded_evidence_issues": [str(item.get("kind") or item) for item in excluded if isinstance(item, dict)],
            "topology_consistency": "consistent" if topology.get("path_signature") else "weak",
            "timeline_consistency": "consistent" if alert_count > 1 else "weak",
            "external_reasoning_needed": str(window.get("recommended_action") or "") == "external",
        },
        "incident_interpretation": {
            "summary": f"{device} on {path} is represented by bounded selected evidence from a {alert_count}-alert window.",
            "hypotheses": ["Treat selected evidence as the incident context and excluded evidence as non-primary context."],
            "recommended_actions": ["Check device, path, timeline, and missing evidence before any operator action."],
            "confidence_label": "medium",
        },
        "output_review": {
            "output_status": "accepted",
            "evidence_reference_issues": [],
            "overclaim_issues": [],
            "unsafe_action_issues": [],
            "root_symptom_confusion": False,
            "revision_required": False,
        },
        "contracts": {
            "stages": [
                contracts["boundary_review"]["stage"],
                contracts["incident_interpretation"]["stage"],
                contracts["output_review"]["stage"],
            ]
        },
    }


def _score_response(
    *,
    strategy: str,
    window: dict[str, Any],
    views: dict[str, Any],
    response: dict[str, Any],
) -> dict[str, Any]:
    text = json.dumps(response, ensure_ascii=True).lower()
    topology = views["topology_view"]
    timeline = views["timeline_view"]["incident_window"]
    missing = views["missing_evidence_view"]
    excluded = views["excluded_evidence_view"]
    device_values = [str(item).lower() for item in topology.get("devices") or [] if str(item)]
    path_values = [str(item).lower() for item in topology.get("path_signatures") or [] if str(item)]

    schema_valid = int(isinstance(response, dict) and bool(response))
    device_reference = int(not device_values or any(value in text for value in device_values[:3]))
    path_reference = int(not path_values or any(value in text for value in path_values[:3]))
    timeline_reference = int(int(timeline.get("alert_count") or 0) <= 1 or "timeline" in text or "window" in text)
    missing_ack = int(not missing or "missing" in text or "needs_more_evidence" in text)
    excluded_ack = int(not excluded or "excluded" in text or "non-primary" in text)
    unsafe_action = int(any(term in text for term in UNSAFE_TERMS))
    overclaim = int(any(term in text for term in OVERCLAIM_TERMS))
    stage_count = _stage_count(strategy)
    total = (
        schema_valid
        + device_reference
        + path_reference
        + timeline_reference
        + missing_ack
        + excluded_ack
        + int(not unsafe_action)
        + int(not overclaim)
    )
    return {
        "schema_valid": schema_valid,
        "device_reference": device_reference,
        "path_reference": path_reference,
        "timeline_reference": timeline_reference,
        "missing_evidence_ack": missing_ack,
        "excluded_evidence_ack": excluded_ack,
        "unsafe_action": unsafe_action,
        "overclaim": overclaim,
        "stage_count": stage_count,
        "quality_score": round(total / 8.0, 6),
    }


def _stage_count(strategy: str) -> int:
    if strategy == "full-contract":
        return 3
    if strategy == "boundary-then-interpretation":
        return 2
    return 1


def _contract_names(strategy: str) -> list[str]:
    if strategy == "full-contract":
        return ["boundary_review", "incident_interpretation", "output_review"]
    if strategy == "boundary-then-interpretation":
        return ["boundary_review", "incident_interpretation"]
    if strategy in {"single-interpretation", "context-views", "alert-only"}:
        return ["incident_interpretation"]
    return []


def _summarize_scores(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["strategy"]), []).append(row)
    summary: dict[str, dict[str, Any]] = {}
    for strategy, values in sorted(grouped.items()):
        summary[strategy] = {
            "windows": len(values),
            "avg_quality_score": _avg(values, "quality_score"),
            "schema_valid_rate": _avg(values, "schema_valid"),
            "device_reference_rate": _avg(values, "device_reference"),
            "path_reference_rate": _avg(values, "path_reference"),
            "timeline_reference_rate": _avg(values, "timeline_reference"),
            "missing_evidence_ack_rate": _avg(values, "missing_evidence_ack"),
            "excluded_evidence_ack_rate": _avg(values, "excluded_evidence_ack"),
            "unsafe_action_rate": _avg(values, "unsafe_action"),
            "overclaim_rate": _avg(values, "overclaim"),
            "avg_stage_count": _avg(values, "stage_count"),
        }
    return summary


def _avg(values: list[dict[str, Any]], key: str) -> float:
    if not values:
        return 0.0
    return round(sum(float(item.get(key) or 0.0) for item in values) / len(values), 6)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fp:
        for record in records:
            fp.write(json.dumps(record, ensure_ascii=True, sort_keys=True) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate prompt contracts over incident-window evidence boundaries.")
    parser.add_argument("--windows-jsonl", required=True)
    parser.add_argument("--max-windows", type=int, default=0)
    parser.add_argument("--output-raw-jsonl", default="")
    parser.add_argument("--output-scores-json", default="")
    run(parser.parse_args())


if __name__ == "__main__":
    main()
