import json
from argparse import Namespace
from pathlib import Path

from core.aiops_agent.alert_reasoning_runtime.incident_window import build_incident_window_index
from core.benchmark.provider_output_quality_runner import run as run_provider_output_quality
from core.benchmark.provider_failure_harness import run as run_provider_failure_harness
from core.benchmark.rcaeval_admission_stress import run as run_rcaeval_admission_stress
from core.benchmark.representative_sufficiency import run as run_representative_sufficiency
from core.benchmark.window_boundary_algorithm_benchmark import run as run_window_boundary_algorithm_benchmark
from core.benchmark.window_horizon_sensitivity import run as run_window_horizon_sensitivity
from core.benchmark.window_risk_ablation import run as run_window_risk_ablation
from core.benchmark.window_review_agreement import run as run_window_review_agreement


def _alert(alert_id: str, *, ts: str, device: str, scenario: str) -> dict:
    return {
        "alert_id": alert_id,
        "rule_id": "annotated_fault_v1",
        "severity": "warning",
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
            "path_signature": f"{device}|hop_core=2|hop_server=4|path_up=1",
            "hop_to_server": "4",
            "hop_to_core": "2",
            "downstream_dependents": "4",
            "path_up": "1",
        },
        "device_profile": {
            "src_device_key": device,
            "device_name": device,
            "device_role": "core_router",
        },
    }


def test_adaptive_session_splits_after_burst_when_fixed_session_would_overmerge() -> None:
    alerts = [
        _alert("a1", ts="2026-04-10T00:00:00+00:00", device="CORE-R2", scenario="transient_fault"),
        _alert("a2", ts="2026-04-10T00:01:00+00:00", device="CORE-R3", scenario="transient_fault"),
        _alert("a3", ts="2026-04-10T00:02:00+00:00", device="CORE-R4", scenario="transient_fault"),
        _alert("a4", ts="2026-04-10T00:07:00+00:00", device="CORE-R5", scenario="transient_fault"),
    ]

    session_windows, _ = build_incident_window_index(alerts, window_sec=600, window_mode="session", max_window_sec=900)
    adaptive_windows, _ = build_incident_window_index(alerts, window_sec=600, window_mode="adaptive", max_window_sec=900)

    assert len(session_windows) == 1
    assert len(adaptive_windows) == 2
    assert {window["window_mode"] for window in adaptive_windows} == {"adaptive_session"}
    assert all(int(window["group_idle_gap_sec"]) >= 60 for window in adaptive_windows)


def test_aics_topology_windowing_tracks_dynamic_frontier_without_fixed_bucket_fragmentation() -> None:
    alerts = [
        _alert("a1", ts="2026-04-10T00:00:00+00:00", device="CORE-R2", scenario="transient_fault"),
        _alert("a2", ts="2026-04-10T00:01:00+00:00", device="CORE-R3", scenario="transient_fault"),
        _alert("a3", ts="2026-04-10T00:02:00+00:00", device="CORE-R4", scenario="transient_fault"),
        _alert("a4", ts="2026-04-10T00:08:00+00:00", device="CORE-R5", scenario="induced_fault"),
    ]

    topology_windows, _ = build_incident_window_index(
        alerts,
        window_sec=500,
        window_mode="aics-topology",
        max_window_sec=1200,
    )

    assert len(topology_windows) == 2
    assert {window["window_mode"] for window in topology_windows} == {"aics_topology"}
    assert all(window["boundary_strategy"] == "topology" for window in topology_windows)


def test_window_horizon_sensitivity_reports_recommended_config(tmp_path: Path) -> None:
    alert_dir = tmp_path / "alerts"
    alert_dir.mkdir()
    records = [
        _alert("a1", ts="2026-04-10T00:00:00+00:00", device="CORE-R2", scenario="transient_fault"),
        _alert("a2", ts="2026-04-10T00:01:00+00:00", device="CORE-R3", scenario="transient_fault"),
        _alert("a3", ts="2026-04-10T00:02:00+00:00", device="CORE-R4", scenario="induced_fault"),
        _alert("a4", ts="2026-04-10T00:08:00+00:00", device="CORE-R5", scenario="transient_fault"),
        _alert("a5", ts="2026-04-10T00:09:00+00:00", device="CORE-R6", scenario="transient_fault"),
    ]
    with (alert_dir / "alerts-test.jsonl").open("w", encoding="utf-8") as fp:
        for record in records:
            fp.write(json.dumps(record, ensure_ascii=True) + "\n")

    output_json = tmp_path / "sensitivity.json"
    summary = run_window_horizon_sensitivity(
        Namespace(
            alert_dir=str(alert_dir),
            limit_files=0,
            max_alerts=0,
            recurrence_threshold=3,
            downstream_threshold=10,
            output_json=str(output_json),
            output_png="",
        )
    )

    assert summary["recommended_config"]["window_mode"] in {"fixed", "session", "adaptive"}
    assert any(row["window_mode"] == "adaptive" for row in summary["configs"])
    assert output_json.exists()


def test_window_boundary_algorithm_benchmark_reports_algorithm_recommendation(tmp_path: Path) -> None:
    alert_dir = tmp_path / "alerts"
    alert_dir.mkdir()
    records = [
        _alert("a1", ts="2026-04-10T00:00:00+00:00", device="CORE-R2", scenario="induced_fault"),
        _alert("a2", ts="2026-04-10T00:01:00+00:00", device="CORE-R3", scenario="transient_fault"),
        _alert("a3", ts="2026-04-10T00:07:00+00:00", device="CORE-R4", scenario="induced_fault"),
        _alert("a4", ts="2026-04-10T00:08:00+00:00", device="CORE-R5", scenario="transient_fault"),
    ]
    with (alert_dir / "alerts-test.jsonl").open("w", encoding="utf-8") as fp:
        for record in records:
            fp.write(json.dumps(record, ensure_ascii=True) + "\n")

    rcaeval_records = tmp_path / "rcaeval-records.jsonl"
    rcaeval_samples = [
        {
            "id": "r1",
            "dataset": "RE1-OB",
            "dataset_family": "RE1",
            "root_service": "svc-a",
            "service": "svc-a",
            "fault_type": "latency",
            "is_root_cause": True,
            "symptom_score": 10.0,
            "timestamp": "2026-04-10T00:00:00+00:00",
        },
        {
            "id": "r2",
            "dataset": "RE1-SS",
            "dataset_family": "RE1",
            "root_service": "svc-b",
            "service": "svc-b",
            "fault_type": "latency",
            "is_root_cause": True,
            "symptom_score": 9.0,
            "timestamp": "2026-04-10T00:01:00+00:00",
        },
        {
            "id": "r3",
            "dataset": "RE1-TT",
            "dataset_family": "RE1",
            "root_service": "svc-c",
            "service": "svc-c",
            "fault_type": "latency",
            "is_root_cause": True,
            "timestamp": "2026-04-10T00:02:00+00:00",
            "symptom_score": 8.0,
        },
    ]
    with rcaeval_records.open("w", encoding="utf-8") as fp:
        for record in rcaeval_samples:
            fp.write(json.dumps(record, ensure_ascii=True) + "\n")

    summary = run_window_boundary_algorithm_benchmark(
        Namespace(
            lcore_alert_dir=str(alert_dir),
            rcaeval_records_jsonl=str(rcaeval_records),
            limit_files=0,
            max_alerts=0,
            recurrence_threshold=3,
            downstream_threshold=10,
            output_json=str(tmp_path / "boundary-benchmark.json"),
            output_png="",
        )
    )

    assert summary["recommended_algorithm_config"]["window_mode"] in {"adaptive", "aics-topology", "aics-evidence", "aics"}
    assert any(row["window_mode"] == "aics-topology" for row in summary["configs"])


def test_provider_output_quality_runner_compares_real_output_fields(tmp_path: Path) -> None:
    run1 = tmp_path / "run1.jsonl"
    run2 = tmp_path / "run2.jsonl"
    event_good = {
        "attempted_external_call": True,
        "response_schema_valid": True,
        "latency_ms": 100.0,
        "response_quality": {
            "score": 1.0,
            "label": "strong",
            "checks": {
                "mentions_root_device": True,
                "mentions_path_or_topology": True,
                "human_gated": True,
            },
        },
        "raw_response": {
            "summary": "CORE-R2 on path CORE-R2|hop_core=2|hop_server=4|path_up=1 requires review.",
            "hypotheses": ["CORE-R2 is the bounded root candidate."],
            "recommended_actions": ["Human review should verify the selected path before any change."],
            "model_usage": {"prompt_tokens": 100, "total_tokens": 200},
        },
    }
    event_bad = {
        "attempted_external_call": True,
        "response_schema_valid": True,
        "latency_ms": 120.0,
        "response_quality": {
            "score": 0.5,
            "label": "weak",
            "checks": {
                "mentions_root_device": False,
                "mentions_path_or_topology": False,
                "human_gated": False,
            },
        },
        "raw_response": {
            "summary": "This definitely finds the root cause.",
            "hypotheses": ["No path evidence is needed."],
            "recommended_actions": ["Execute restart service immediately."],
            "model_usage": {"prompt_tokens": 110, "total_tokens": 210},
        },
    }
    run1.write_text(json.dumps(event_good) + "\n", encoding="utf-8")
    run2.write_text(json.dumps(event_bad) + "\n", encoding="utf-8")

    summary = run_provider_output_quality(
        Namespace(
            run=[f"good={run1}", f"bad={run2}"],
            external_only=True,
            output_json=str(tmp_path / "quality.json"),
            output_png="",
        )
    )

    assert summary["runs"][0]["avg_response_quality_score"] > summary["runs"][1]["avg_response_quality_score"]
    assert summary["runs"][1]["unsafe_action_rate"] == 1.0
    assert summary["runs"][1]["overclaim_rate"] == 1.0


def test_window_review_agreement_builds_adjudication_report(tmp_path: Path) -> None:
    review1 = tmp_path / "reviewer_a.jsonl"
    review2 = tmp_path / "reviewer_b.jsonl"
    base_record = {
        "window": {"window_id": "w1", "window_label": "external_induced_fault"},
        "weak_label": {"should_invoke_external": True},
    }
    records_a = [
        {
            **base_record,
            "expert_label": {
                "reviewer": "alice",
                "should_invoke_external": True,
                "representative_alert_sufficient": True,
                "selected_device_covered": True,
                "selected_path_covered": True,
                "timeline_sufficient": True,
                "false_skip_if_local": True,
            },
        }
    ]
    records_b = [
        {
            **base_record,
            "expert_label": {
                "reviewer": "bob",
                "should_invoke_external": False,
                "representative_alert_sufficient": True,
                "selected_device_covered": True,
                "selected_path_covered": True,
                "timeline_sufficient": True,
                "false_skip_if_local": False,
            },
        }
    ]
    review1.write_text("\n".join(json.dumps(record) for record in records_a) + "\n", encoding="utf-8")
    review2.write_text("\n".join(json.dumps(record) for record in records_b) + "\n", encoding="utf-8")

    report = run_window_review_agreement(
        Namespace(
            review_jsonl=[str(review1), str(review2)],
            output_json=str(tmp_path / "agreement.json"),
            output_adjudicated_jsonl=str(tmp_path / "adjudicated.jsonl"),
        )
    )

    assert report["windows_reviewed"] == 1
    assert report["fields"]["representative_alert_sufficient"]["pairwise_exact_agreement"] == 1.0
    assert report["windows_needing_adjudication"] == 1


def test_provider_failure_harness_falls_back_without_gate_drift(tmp_path: Path) -> None:
    alert_dir = tmp_path / "alerts"
    alert_dir.mkdir()
    records = [
        _alert("a1", ts="2026-04-10T00:00:00+00:00", device="CORE-R2", scenario="induced_fault"),
        _alert("a2", ts="2026-04-10T00:01:00+00:00", device="CORE-R3", scenario="transient_fault"),
    ]
    with (alert_dir / "alerts-test.jsonl").open("w", encoding="utf-8") as fp:
        for record in records:
            fp.write(json.dumps(record, ensure_ascii=True) + "\n")

    summary = run_provider_failure_harness(
        Namespace(
            alert_dir=str(alert_dir),
            limit_files=0,
            max_alerts=0,
            sample_per_scenario_device=0,
            failure_mode="exception",
            fail_every=1,
            extra_latency_ms=1,
            fallback_on_invalid_schema=True,
            output_json=str(tmp_path / "failure.json"),
            output_jsonl=str(tmp_path / "failure.jsonl"),
        )
    )

    assert summary["planned_external_calls"] >= 1
    assert summary["fallback_calls"] >= 1
    assert summary["gate_decision_drift"] == 0
    assert summary["response_schema_valid_rate"] == 1.0


def test_representative_sufficiency_reports_coverage_cost_tradeoff(tmp_path: Path) -> None:
    alert_dir = tmp_path / "alerts"
    alert_dir.mkdir()
    records = [
        _alert("a1", ts="2026-04-10T00:00:00+00:00", device="CORE-R2", scenario="induced_fault"),
        _alert("a2", ts="2026-04-10T00:01:00+00:00", device="CORE-R3", scenario="transient_fault"),
        _alert("a3", ts="2026-04-10T00:02:00+00:00", device="CORE-R4", scenario="transient_fault"),
    ]
    with (alert_dir / "alerts-test.jsonl").open("w", encoding="utf-8") as fp:
        for record in records:
            fp.write(json.dumps(record, ensure_ascii=True) + "\n")

    report = run_representative_sufficiency(
        Namespace(
            alert_dir=str(alert_dir),
            limit_files=0,
            max_alerts=0,
            window_sec=600,
            window_mode="session",
            max_window_sec=0,
            group_by_scenario=False,
            k_values="1,2,all",
            budget_fraction=0.2,
            target_sufficiency=0.5,
            output_json=str(tmp_path / "representative.json"),
            output_png="",
        )
    )

    by_label = {item["label"]: item for item in report["variants"]}
    assert by_label["all"]["avg_coverage_rate"] >= by_label["k=1"]["avg_coverage_rate"]
    assert by_label["all"]["invoke_all_external_calls"] >= by_label["k=1"]["invoke_all_external_calls"]
    assert report["recommended_variant"]["label"] in {"k=1", "k=2", "all"}


def test_window_risk_ablation_removes_requested_atom_family(tmp_path: Path) -> None:
    alert_dir = tmp_path / "alerts"
    alert_dir.mkdir()
    records = [
        _alert("a1", ts="2026-04-10T00:00:00+00:00", device="CORE-R2", scenario="induced_fault"),
        _alert("a2", ts="2026-04-10T00:01:00+00:00", device="CORE-R3", scenario="transient_fault"),
    ]
    with (alert_dir / "alerts-test.jsonl").open("w", encoding="utf-8") as fp:
        for record in records:
            fp.write(json.dumps(record, ensure_ascii=True) + "\n")

    report = run_window_risk_ablation(
        Namespace(
            alert_dir=str(alert_dir),
            limit_files=0,
            max_alerts=0,
            window_sec=600,
            window_mode="session",
            max_window_sec=0,
            group_by_scenario=False,
            ablation="full,no-mixed-fault",
            output_json=str(tmp_path / "ablation.json"),
            output_png="",
        )
    )

    by_name = {item["ablation"]: item for item in report["ablations"]}
    assert by_name["no-mixed-fault"]["removed_atom_instances"] > 0
    assert by_name["no-mixed-fault"]["avg_risk_score"] <= by_name["full"]["avg_risk_score"]


def test_rcaeval_admission_stress_keeps_datasets_isolated(tmp_path: Path) -> None:
    records_jsonl = tmp_path / "rcaeval-records.jsonl"
    records = [
        {
            "dataset": "REX-A",
            "id": "a-root",
            "alert_id": "a-root",
            "service": "svc-a",
            "root_service": "svc-a",
            "root_cause": "svc-a",
            "fault_type": "rcaeval_cpu_fault",
            "timestamp": "2026-04-10T00:00:00+00:00",
            "path_signature": "svc-a|path=1",
            "is_root_cause": True,
        },
        {
            "dataset": "REX-A",
            "id": "a-symptom",
            "alert_id": "a-symptom",
            "service": "svc-a",
            "root_service": "svc-a",
            "root_cause": "svc-a",
            "fault_type": "transient_fault",
            "timestamp": "2026-04-10T00:01:00+00:00",
            "path_signature": "svc-a|path=1",
            "is_root_cause": False,
        },
        {
            "dataset": "REX-B",
            "id": "b-root",
            "alert_id": "b-root",
            "service": "svc-a",
            "root_service": "svc-a",
            "root_cause": "svc-a",
            "fault_type": "rcaeval_cpu_fault",
            "timestamp": "2026-04-10T00:00:00+00:00",
            "path_signature": "svc-a|path=1",
            "is_root_cause": True,
        },
        {
            "dataset": "REX-B",
            "id": "b-symptom",
            "alert_id": "b-symptom",
            "service": "svc-a",
            "root_service": "svc-a",
            "root_cause": "svc-a",
            "fault_type": "transient_fault",
            "timestamp": "2026-04-10T00:01:00+00:00",
            "path_signature": "svc-a|path=1",
            "is_root_cause": False,
        },
    ]
    records_jsonl.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")

    report = run_rcaeval_admission_stress(
        Namespace(
            records_jsonl=str(records_jsonl),
            rcaeval_root="",
            window_sec=600,
            window_mode="session",
            max_window_sec=0,
            top_symptoms=5,
            min_symptom_score=1.0,
            output_json=str(tmp_path / "stress.json"),
            output_png="",
        )
    )

    assert report["combined"]["incident_windows"] == 2
    assert report["per_dataset"]["REX-A"]["incident_windows"] == 1
    assert report["per_dataset"]["REX-B"]["incident_windows"] == 1
