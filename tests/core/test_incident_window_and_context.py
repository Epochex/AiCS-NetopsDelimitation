import json
from argparse import Namespace
from pathlib import Path

from core.aiops_agent.alert_reasoning_runtime.context_views import build_context_views
from core.aiops_agent.alert_reasoning_runtime.incident_window import (
    build_window_evidence_boundary,
    build_incident_window_index,
)
from core.aiops_agent.alert_reasoning_runtime.prompt_contracts import build_prompt_contracts
from core.aiops_agent.alert_reasoning_runtime.budget_controller import select_windows_under_budget
from core.aiops_agent.alert_reasoning_runtime.representative_selection import select_representative_alerts
from core.aiops_agent.alert_reasoning_runtime.self_healing_policy import assess_self_healing_decision
from core.aiops_agent.alert_reasoning_runtime.window_labeling import build_weak_window_label
from core.aiops_agent.evidence_bundle import build_alert_evidence_bundle
from core.benchmark.quality_cost_policy_runner import run as run_quality_cost
from core.benchmark.window_expert_reviewer import review_window
from core.benchmark.external_validation_adapter import run as run_external_validation
from core.benchmark.rcaeval_re1_converter import run as run_rcaeval_converter
from core.benchmark.rcaeval_full_adapter import run as run_rcaeval_full_adapter
from core.benchmark.admission_baseline_runner import run as run_admission_baselines
from core.benchmark.prompt_quality_runner import run as run_prompt_quality


def _alert(
    alert_id: str,
    *,
    ts: str,
    device: str,
    scenario: str,
    severity: str = "warning",
    hop_core: str = "2",
    hop_server: str = "4",
    downstream: str = "4",
) -> dict:
    return {
        "alert_id": alert_id,
        "rule_id": "annotated_fault_v1",
        "severity": severity,
        "alert_ts": ts,
        "dimensions": {
            "src_device_key": device,
            "fault_scenario": scenario,
        },
        "metrics": {
            "label_value": scenario,
            "annotation_confidence": 1.0,
        },
        "event_excerpt": {
            "src_device_key": device,
            "service": "lcore-telemetry",
        },
        "topology_context": {
            "src_device_key": device,
            "service": "lcore-telemetry",
            "path_signature": f"{device}|hop_core={hop_core}|hop_server={hop_server}|path_up=1",
            "neighbor_refs": ["CORE-R1"],
            "hop_to_server": hop_server,
            "hop_to_core": hop_core,
            "downstream_dependents": downstream,
            "path_up": "1",
        },
        "device_profile": {
            "src_device_key": device,
            "device_name": device,
            "device_role": "core_router",
        },
    }


def test_incident_window_groups_path_shape_and_tracks_multi_device_pressure() -> None:
    alerts = [
        _alert("a1", ts="2026-04-10T00:00:00+00:00", device="CORE-R2", scenario="transient_fault"),
        _alert("a2", ts="2026-04-10T00:02:00+00:00", device="CORE-R3", scenario="transient_fault"),
        _alert("a3", ts="2026-04-10T00:04:00+00:00", device="CORE-R4", scenario="transient_fault"),
    ]

    windows, index = build_incident_window_index(alerts, window_sec=600)

    assert len(windows) == 1
    assert windows[0]["alert_count"] == 3
    assert windows[0]["multi_device_spread"] is True
    assert windows[0]["recurrence_pressure"] is True
    assert windows[0]["window_label"] == "external_multi_device_spread"
    assert windows[0]["recommended_action"] == "external"
    assert windows[0]["risk_tier"] == "high"
    assert {atom["key"] for atom in windows[0]["risk_atoms"]} >= {
        "spread:multi_device",
        "pressure:recurrence",
        "pressure:topology",
    }
    assert windows[0]["selected_evidence_targets"]["representative_alert_ids"]
    assert index["a2"]["device_count"] == 3


def test_incident_window_mixes_fault_and_transient_on_same_path_shape() -> None:
    alerts = [
        _alert("a1", ts="2026-04-10T00:00:00+00:00", device="CORE-R2", scenario="transient_fault"),
        _alert("a2", ts="2026-04-10T00:02:00+00:00", device="CORE-R3", scenario="induced_fault"),
    ]

    windows, index = build_incident_window_index(alerts, window_sec=600)
    boundary = build_window_evidence_boundary(windows[0])

    assert len(windows) == 1
    assert windows[0]["window_label"] == "mixed_fault_and_transient"
    assert windows[0]["high_value_count"] == 1
    assert windows[0]["self_healing_count"] == 1
    assert index["a1"]["recommended_action"] == "external"
    assert boundary["selected_surface"]["alert_ids"] == ["a2"]
    assert boundary["excluded_surface"][0]["kind"] == "transient_context_not_primary"
    assert boundary["risk_tier"] == "high"


def test_sessionized_window_merges_across_fixed_bucket_boundary() -> None:
    alerts = [
        _alert("a1", ts="2026-04-10T00:09:50+00:00", device="CORE-R2", scenario="transient_fault"),
        _alert("a2", ts="2026-04-10T00:10:05+00:00", device="CORE-R3", scenario="transient_fault"),
    ]

    session_windows, _ = build_incident_window_index(alerts, window_sec=600)
    fixed_windows, _ = build_incident_window_index(alerts, window_sec=600, window_mode="fixed")

    assert len(session_windows) == 1
    assert session_windows[0]["window_mode"] == "session"
    assert session_windows[0]["alert_count"] == 2
    assert len(fixed_windows) == 2
    assert {window["window_mode"] for window in fixed_windows} == {"fixed"}


def test_sessionized_window_closes_after_idle_gap() -> None:
    alerts = [
        _alert("a1", ts="2026-04-10T00:00:00+00:00", device="CORE-R2", scenario="transient_fault"),
        _alert("a2", ts="2026-04-10T00:10:01+00:00", device="CORE-R3", scenario="transient_fault"),
    ]

    windows, _ = build_incident_window_index(alerts, window_sec=600)

    assert len(windows) == 2
    assert [window["alert_count"] for window in windows] == [1, 1]


def test_representative_selection_and_budget_controller_keep_high_value_windows() -> None:
    alerts = [
        _alert("a1", ts="2026-04-10T00:00:00+00:00", device="CORE-R2", scenario="transient_fault"),
        _alert("a2", ts="2026-04-10T00:01:00+00:00", device="CORE-R3", scenario="transient_fault"),
        _alert("a3", ts="2026-04-10T00:02:00+00:00", device="CORE-R4", scenario="induced_fault"),
    ]
    windows, _ = build_incident_window_index(alerts, window_sec=600)
    selected = select_representative_alerts(alerts, max_items=2)
    admission = select_windows_under_budget(windows, budget_fraction=0.1)
    weak = build_weak_window_label(windows[0])

    assert "a3" in selected["representative_alert_ids"]
    assert admission["admission_strategy"] == "marginal_uncovered_risk_per_representative_cost"
    assert admission["selected_windows"] == 1
    assert "a3" in admission["representative_alert_ids"]
    assert weak["should_invoke_external"] is True
    assert weak["selected_device_covered"] is True
    assert any(atom["key"] == "value:high_fault" for atom in weak["risk_atoms"])


def test_budget_controller_prefers_uncovered_risk_atoms() -> None:
    windows = [
        {
            "window_id": "w1",
            "high_value_count": 1,
            "risk_score": 10,
            "risk_tier": "high",
            "risk_atoms": [{"key": "value:high_fault", "weight": 10}],
            "selected_evidence_targets": {"representative_alert_ids": ["a1"]},
        },
        {
            "window_id": "w2",
            "high_value_count": 1,
            "risk_score": 10,
            "risk_tier": "high",
            "risk_atoms": [{"key": "value:high_fault", "weight": 10}],
            "selected_evidence_targets": {"representative_alert_ids": ["a2"]},
        },
        {
            "window_id": "w3",
            "high_value_count": 0,
            "risk_score": 10,
            "risk_tier": "high",
            "risk_atoms": [
                {"key": "spread:multi_device", "weight": 6},
                {"key": "pressure:topology", "weight": 4},
            ],
            "selected_evidence_targets": {"representative_alert_ids": ["a3"]},
        },
    ]

    admission = select_windows_under_budget(windows, budget_fraction=0.67, min_high_value=False)

    assert admission["selected_window_ids"] == {"w1", "w3"}
    assert admission["covered_risk_atom_count"] == 3
    assert admission["used_external_calls"] == 2


def test_self_healing_decision_separates_single_pressure_and_repeated_transient() -> None:
    single = _alert(
        "a1",
        ts="2026-04-10T00:00:00+00:00",
        device="CORE-R2",
        scenario="transient_fault",
        downstream="12",
    )
    local = assess_self_healing_decision(alert=single, recent_similar_1h=0)
    repeated = assess_self_healing_decision(
        alert=single,
        recent_similar_1h=3,
        incident_window={"alert_count": 3, "device_count": 1, "recurrence_pressure": True},
    )

    assert local["decision"] == "local_transient_with_pressure"
    assert local["should_invoke_external"] is False
    assert repeated["decision"] == "external_repeated_transient"
    assert repeated["should_invoke_external"] is True


def test_context_views_and_prompt_contracts_expose_fixed_views() -> None:
    alert = _alert(
        "a1",
        ts="2026-04-10T00:00:00+00:00",
        device="CORE-R2",
        scenario="induced_fault",
    )
    evidence = build_alert_evidence_bundle(alert, recent_similar_1h=0)
    views = build_context_views(evidence)
    contracts = build_prompt_contracts(views)

    assert {"alert_view", "topology_view", "timeline_view", "history_view"}.issubset(views)
    assert "missing_evidence_view" in views
    assert "excluded_evidence_view" in views
    assert contracts["boundary_review"]["output_schema"]["boundary_status"]
    assert contracts["incident_interpretation"]["required_context_views"]
    assert evidence["context_views"]["topology_view"]["src_device_key"] == "CORE-R2"
    assert "window_boundary" in views["timeline_view"]
    assert evidence["prompt_contracts"]["output_review"]["output_schema"]["revision_required"] == "bool"


def test_quality_cost_policy_runner_reports_tradeoff_metrics(tmp_path: Path) -> None:
    alert_dir = tmp_path / "alerts"
    alert_dir.mkdir()
    records = [
        _alert("a1", ts="2026-04-10T00:00:00+00:00", device="CORE-R2", scenario="transient_fault"),
        _alert("a2", ts="2026-04-10T00:02:00+00:00", device="CORE-R3", scenario="transient_fault"),
        _alert("a3", ts="2026-04-10T00:04:00+00:00", device="CORE-R4", scenario="transient_fault"),
        _alert("a4", ts="2026-04-10T00:05:00+00:00", device="CORE-R4", scenario="induced_fault"),
    ]
    with (alert_dir / "alerts-test.jsonl").open("w", encoding="utf-8") as fp:
        for record in records:
            fp.write(json.dumps(record, ensure_ascii=True) + "\n")

    report = run_quality_cost(
        Namespace(
            alert_dir=str(alert_dir),
            limit_files=0,
            max_alerts=0,
            window_sec=600,
            recurrence_threshold=3,
            downstream_threshold=10,
            group_by_scenario=False,
            output_json="",
            output_windows_jsonl="",
            output_labels_jsonl="",
        )
    )

    assert report["incident_windows"] == 1
    assert report["window_labels"]["mixed_fault_and_transient"] == 1
    assert report["policies"]["invoke-all"]["calls"] == 4
    assert report["policies"]["scenario-only"]["calls"] == 1
    assert report["policies"]["topology+timeline"]["calls"] >= 2
    assert report["policies"]["window-risk-tier"]["calls"] >= 1
    assert report["policies"]["window-risk-tier"]["window_metrics"]["high_value_window_recall"] == 1.0
    assert report["policies"]["budget-risk-5"]["window_metrics"]["high_value_window_recall"] == 1.0
    assert report["budget_admissions"]["budget-risk-10"]["selected_windows"] >= 1
    assert report["window_risk_tiers"]["high"] == 1
    assert report["policies"]["topology+timeline"]["evidence_coverage_rate"] == 1.0


def test_expert_style_window_review_distinguishes_pressure_from_local_transient() -> None:
    high_value_window, _ = build_incident_window_index(
        [
            _alert("a1", ts="2026-04-10T00:00:00+00:00", device="CORE-R2", scenario="induced_fault"),
            _alert("a2", ts="2026-04-10T00:01:00+00:00", device="CORE-R3", scenario="transient_fault"),
        ],
        window_sec=600,
    )
    local_window, _ = build_incident_window_index(
        [
            _alert("b1", ts="2026-04-10T00:00:00+00:00", device="CORE-R2", scenario="transient_fault"),
        ],
        window_sec=600,
    )

    high_review = review_window(high_value_window[0])
    local_review = review_window(local_window[0])

    assert high_review["should_invoke_external"] is True
    assert high_review["false_skip_if_local"] is True
    assert high_review["representative_alert_sufficient"] is True
    assert local_review["should_invoke_external"] is False
    assert local_review["false_skip_if_local"] is False


def test_external_validation_adapter_reports_admission_metrics(tmp_path: Path) -> None:
    dataset = tmp_path / "external.jsonl"
    records = [
        {
            "id": "r1",
            "timestamp": "2026-04-10T00:00:00+00:00",
            "service": "checkout",
            "fault_type": "latency_fault",
            "trace_id": "trace-a",
        },
        {
            "id": "r2",
            "timestamp": "2026-04-10T00:01:00+00:00",
            "service": "payment",
            "fault_type": "latency_fault",
            "trace_id": "trace-a",
        },
        {
            "id": "r3",
            "timestamp": "2026-04-10T00:02:00+00:00",
            "service": "frontend",
            "fault_type": "transient_fault",
            "trace_id": "trace-b",
        },
    ]
    with dataset.open("w", encoding="utf-8") as fp:
        for record in records:
            fp.write(json.dumps(record, ensure_ascii=True) + "\n")

    report = run_external_validation(
        Namespace(
            dataset_jsonl=str(dataset),
            window_sec=600,
            output_json="",
        )
    )

    assert report["converted_alerts"] == 3
    assert report["incident_windows"] >= 2
    assert report["policies"]["invoke-all"]["high_value_window_recall"] == 1.0
    assert "budget-risk-20" in report["policies"]
    assert "budget-coverage-1" in report["policies"]
    assert report["policies"]["invoke-all"]["external_calls"] == 3


def test_rcaeval_re1_converter_preserves_root_and_metric_symptoms(tmp_path: Path) -> None:
    case_dir = tmp_path / "RE1-OB" / "checkoutservice_mem" / "1"
    case_dir.mkdir(parents=True)
    inject = 1_700_000_600
    (case_dir / "inject_time.txt").write_text(str(inject), encoding="utf-8")
    with (case_dir / "data.csv").open("w", encoding="utf-8") as fp:
        fp.write("time,checkoutservice_mem,paymentservice_latency,frontend_cpu\n")
        for ts in range(inject - 10, inject):
            fp.write(f"{ts},10,1.0,5.0\n")
        for ts in range(inject, inject + 10):
            fp.write(f"{ts},100,4.0,5.1\n")

    output = tmp_path / "rcaeval.jsonl"
    summary = run_rcaeval_converter(
        Namespace(
            re1_root=str(tmp_path),
            output_jsonl=str(output),
            output_summary_json="",
            top_symptoms=3,
            min_symptom_score=1.0,
        )
    )
    records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]

    assert summary["cases"] == 1
    assert records[0]["is_root_cause"] is True
    assert records[0]["service"] == "checkoutservice"
    assert records[0]["fault_type"] == "rcaeval_mem_fault"
    assert any(record["service"] == "paymentservice" for record in records[1:])


def test_rcaeval_full_adapter_exports_records_windows_and_dataset_summary(tmp_path: Path) -> None:
    case_dir = tmp_path / "data" / "RE1" / "RE1-OB" / "checkoutservice_cpu" / "1"
    case_dir.mkdir(parents=True)
    inject = 1_700_000_600
    (case_dir / "inject_time.txt").write_text(str(inject), encoding="utf-8")
    with (case_dir / "data.csv").open("w", encoding="utf-8") as fp:
        fp.write("time,checkoutservice_cpu,paymentservice_latency,frontend_cpu\n")
        for ts in range(inject - 10, inject):
            fp.write(f"{ts},10,1.0,5.0\n")
        for ts in range(inject, inject + 10):
            fp.write(f"{ts},100,9.0,5.1\n")

    output = tmp_path / "rcaeval_all.jsonl"
    windows = tmp_path / "rcaeval_windows.jsonl"
    summary = run_rcaeval_full_adapter(
        Namespace(
            rcaeval_root=str(tmp_path),
            output_jsonl=str(output),
            output_cases_jsonl="",
            output_windows_jsonl=str(windows),
            output_summary_json="",
            window_sec=600,
            top_symptoms=3,
            min_symptom_score=1.0,
        )
    )
    records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    window_records = [json.loads(line) for line in windows.read_text(encoding="utf-8").splitlines()]

    assert summary["cases"] == 1
    assert summary["per_dataset"]["RE1-OB"]["cases"] == 1
    assert records[0]["dataset"] == "RE1-OB"
    assert records[0]["dataset_family"] == "RE1"
    assert window_records


def test_unified_admission_baseline_runner_reports_required_policies(tmp_path: Path) -> None:
    dataset = tmp_path / "external.jsonl"
    records = [
        {
            "id": "r1",
            "timestamp": "2026-04-10T00:00:00+00:00",
            "service": "checkout",
            "fault_type": "latency_fault",
            "trace_id": "trace-a",
        },
        {
            "id": "r2",
            "timestamp": "2026-04-10T00:01:00+00:00",
            "service": "payment",
            "fault_type": "transient_fault",
            "trace_id": "trace-a",
        },
        {
            "id": "r3",
            "timestamp": "2026-04-10T00:02:00+00:00",
            "service": "frontend",
            "fault_type": "transient_fault",
            "trace_id": "trace-a",
        },
    ]
    with dataset.open("w", encoding="utf-8") as fp:
        for record in records:
            fp.write(json.dumps(record, ensure_ascii=True) + "\n")

    report = run_admission_baselines(
        Namespace(
            source="rcaeval",
            alert_dir="",
            dataset_jsonl=str(dataset),
            limit_files=0,
            max_alerts=0,
            window_sec=600,
            group_by_scenario=False,
            budgets="1,20",
            output_json="",
            output_windows_jsonl="",
        )
    )

    assert report["incident_windows"] >= 1
    assert {"invoke-all", "analyze-all-windows", "representative-only", "scenario-only"}.issubset(
        report["policies"]
    )
    assert "risk-score-20" in report["policies"]
    assert "risk-coverage-20" in report["policies"]
    assert report["policies"]["invoke-all"]["external_calls"] == 3
    assert report["policies"]["representative-only"]["external_calls"] <= 3


def test_prompt_quality_runner_scores_stage_specific_contracts(tmp_path: Path) -> None:
    alerts = [
        _alert("a1", ts="2026-04-10T00:00:00+00:00", device="CORE-R2", scenario="induced_fault"),
        _alert("a2", ts="2026-04-10T00:01:00+00:00", device="CORE-R3", scenario="transient_fault"),
    ]
    windows, _ = build_incident_window_index(alerts, window_sec=600)
    windows_jsonl = tmp_path / "windows.jsonl"
    with windows_jsonl.open("w", encoding="utf-8") as fp:
        for window in windows:
            fp.write(json.dumps(window, ensure_ascii=True) + "\n")

    raw = tmp_path / "prompt_raw.jsonl"
    scores = run_prompt_quality(
        Namespace(
            windows_jsonl=str(windows_jsonl),
            max_windows=0,
            output_raw_jsonl=str(raw),
            output_scores_json="",
        )
    )
    raw_records = [json.loads(line) for line in raw.read_text(encoding="utf-8").splitlines()]

    assert scores["strategies"]["full-contract"]["avg_quality_score"] >= scores["strategies"]["alert-only"]["avg_quality_score"]
    assert scores["strategies"]["full-contract"]["avg_stage_count"] == 3.0
    assert len(raw_records) == len(windows) * 5
    assert any(record["strategy"] == "boundary-then-interpretation" for record in raw_records)
