import json

from edge.lcore_streamer.main import main


def test_lcore_streamer_writes_checkpointed_canonical_events(tmp_path, monkeypatch) -> None:
    input_path = tmp_path / "sample.csv"
    input_path.write_text(
        "timestamp,Device_name,ICMP loss,class\n"
        "1760264160,CORE-R1,0,H\n"
        "1760264220,CORE-R1,100,F\n"
        "1760264280,CORE-R1,50,T\n",
        encoding="utf-8",
    )
    output_path = tmp_path / "output" / "events-lcore-d.jsonl"
    plan_path = tmp_path / "work" / "feature-plan.json"
    checkpoint_path = tmp_path / "work" / "checkpoint.json"

    monkeypatch.setattr(
        "sys.argv",
        [
            "lcore-streamer",
            "--input",
            str(input_path),
            "--output-jsonl",
            str(output_path),
            "--plan-json",
            str(plan_path),
            "--checkpoint-json",
            str(checkpoint_path),
            "--events-per-second",
            "0",
            "--run-id",
            "test-run-001",
            "--max-records",
            "2",
            "--reset-output",
        ],
    )

    main()

    events = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))

    assert len(events) == 2
    assert events[0]["fault_context"]["scenario"] == "healthy"
    assert events[1]["fault_context"]["scenario"] == "induced_fault"
    assert events[1]["subtype"] == "fault_annotation"
    assert events[1]["dataset_context"]["run_id"] == "test-run-001"
    assert checkpoint["run_id"] == "test-run-001"
    assert checkpoint["next_row_index"] == 2


def test_lcore_streamer_loop_uses_new_event_ids_per_loop(tmp_path, monkeypatch) -> None:
    input_path = tmp_path / "sample.csv"
    input_path.write_text(
        "timestamp,Device_name,ICMP loss,class\n"
        "1760264160,CORE-R1,0,H\n",
        encoding="utf-8",
    )
    output_path = tmp_path / "output" / "events-lcore-d.jsonl"
    plan_path = tmp_path / "work" / "feature-plan.json"
    checkpoint_path = tmp_path / "work" / "checkpoint.json"

    monkeypatch.setattr(
        "sys.argv",
        [
            "lcore-streamer",
            "--input",
            str(input_path),
            "--output-jsonl",
            str(output_path),
            "--plan-json",
            str(plan_path),
            "--checkpoint-json",
            str(checkpoint_path),
            "--events-per-second",
            "0",
            "--run-id",
            "loop-smoke",
            "--loop",
            "--max-loops",
            "2",
            "--loop-sleep-seconds",
            "0",
            "--reset-output",
        ],
    )

    main()

    events = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]
    assert len(events) == 2
    assert [event["dataset_context"]["run_id"] for event in events] == [
        "loop-smoke-loop-0000",
        "loop-smoke-loop-0001",
    ]
    assert events[0]["event_id"] != events[1]["event_id"]


def test_lcore_compact_class_labels_are_normalized() -> None:
    from common.data_features import AdaptiveFeatureExtractor, row_to_canonical_event

    rows = [
        {"timestamp": "1760264160", "Device_name": "CORE-R1", "class": "H", "ICMP loss": "0"},
        {"timestamp": "1760264220", "Device_name": "CORE-R1", "class": "F", "ICMP loss": "100"},
        {"timestamp": "1760264280", "Device_name": "CORE-R1", "class": "T", "ICMP loss": "50"},
        {"timestamp": "1760264340", "Device_name": "CORE-R1", "class": "TH", "ICMP loss": "0"},
    ]

    plan = AdaptiveFeatureExtractor(max_sample_rows=10).build_plan(rows)
    events = [row_to_canonical_event(row, plan, idx) for idx, row in enumerate(rows)]

    assert [event["fault_context"]["scenario"] for event in events] == [
        "healthy",
        "induced_fault",
        "transient_fault",
        "transient_healthy",
    ]
    assert [event["fault_context"]["is_fault"] for event in events] == [False, True, True, False]
