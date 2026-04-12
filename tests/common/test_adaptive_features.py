from common.data_features import AdaptiveFeatureExtractor, iter_records_from_paths, row_to_canonical_event


def test_adaptive_feature_plan_detects_lcore_style_fields() -> None:
    rows = [
        {
            "Timestamp": "2026-01-01T00:00:00Z",
            "Source_Node": "r1",
            "Destination_Node": "r2",
            "Interface": "ge-0/0/0",
            "Throughput_Bytes": "100",
            "Packet_Count": "10",
            "Fault_Type": "Normal",
        },
        {
            "Timestamp": "2026-01-01T00:00:01Z",
            "Source_Node": "r1",
            "Destination_Node": "r2",
            "Interface": "ge-0/0/0",
            "Throughput_Bytes": "1000",
            "Packet_Count": "100",
            "Fault_Type": "Single Link Failure",
        },
    ]

    extractor = AdaptiveFeatureExtractor(max_sample_rows=10)
    plan = extractor.build_plan(rows)

    assert plan.primary_time_field == "Timestamp"
    assert "Fault_Type" in plan.label_fields
    assert "Source_Node" in plan.entity_fields
    assert "Throughput_Bytes" in plan.metric_fields
    assert "single_link_failure" in plan.scenario_values

    event = row_to_canonical_event(rows[1], plan, row_index=1)
    assert event["event_ts"] == "2026-01-01T00:00:01+00:00"
    assert event["subtype"] == "fault_annotation"
    assert event["fault_context"]["scenario"] == "single_link_failure"
    assert event["bytes_total"] == 1000
    assert event["pkts_total"] == 100
    assert event["topology_context"]["path_signature"] == "r1->r2"


def test_iter_records_from_paths_reads_csv(tmp_path) -> None:
    path = tmp_path / "sample.csv"
    path.write_text(
        "Timestamp,Node,Metric,Fault_Label\n"
        "2026-01-01T00:00:00Z,r1,1,healthy\n"
        "2026-01-01T00:00:01Z,r2,2,node failure\n",
        encoding="utf-8",
    )

    rows = list(iter_records_from_paths([path]))

    assert len(rows) == 2
    assert rows[0]["Node"] == "r1"
    assert rows[0]["_source_file"] == str(path)


def test_lcore_d_fault_labels_preserve_ten_scenarios() -> None:
    labels = [
        "Single link failure",
        "Multiple Link Failure",
        "Misconfiguration",
        "Routing Misconfiguration",
        "Line card Failure",
        "ICMP Blocked (Firewall)",
        "Node failure",
        "Multiple nodes failures",
        "Single Node Failure",
        "SNMP agent failure",
    ]
    rows = [
        {
            "Timestamp": f"2026-01-01T00:00:{idx:02d}Z",
            "Source_Node": f"r{idx}",
            "Metric": idx + 1,
            "Fault_Type": label,
        }
        for idx, label in enumerate(labels)
    ]

    plan = AdaptiveFeatureExtractor(max_sample_rows=20).build_plan(rows)
    scenarios = {row_to_canonical_event(row, plan, idx)["fault_context"]["scenario"] for idx, row in enumerate(rows)}

    assert scenarios == {
        "single_link_failure",
        "multiple_link_failure",
        "misconfiguration",
        "routing_misconfiguration",
        "line_card_failure",
        "icmp_blocked_firewall",
        "node_failure",
        "multiple_nodes_failures",
        "single_node_failure",
        "snmp_agent_failure",
    }


def test_lcore_d_compact_class_wins_over_device_status_fields() -> None:
    rows = [
        {
            "timestamp": "1760264160",
            "ICMP loss": "0",
            "U_ Duplex_ status": "2",
            "U_ Operational_ status": "1",
            "class": "H",
            "Device_name": "CORE-R1",
        },
        {
            "timestamp": "1760264220",
            "ICMP loss": "100",
            "U_ Duplex_ status": "2",
            "U_ Operational_ status": "1",
            "class": "F",
            "Device_name": "CORE-R1",
        },
    ]

    plan = AdaptiveFeatureExtractor(max_sample_rows=10).build_plan(rows)
    event = row_to_canonical_event(rows[1], plan, 1)

    assert plan.label_fields[0] == "class"
    assert event["fault_context"]["label_value"] == "F"
    assert event["fault_context"]["scenario"] == "induced_fault"


def test_lcore_d_topology_contract_uses_stable_device_identity() -> None:
    rows = [
        {
            "timestamp": "1760264160",
            "ICMP loss": "100",
            "B8_ Interface_ type": "6",
            "B8_Operational_ status": "1",
            "class": "H",
            "router_name": "CORE-R4",
            "hop_to_server": "5",
            "hop_to_core": "3",
            "downstream_dependents": "4",
            "path_up": "1",
            "_source_file": "/data/netops-runtime/LCORE-D/raw/LCORE-D R4.csv",
        },
        {
            "timestamp": "1760266680",
            "ICMP loss": "100",
            "B8_ Interface_ type": "6",
            "B8_Operational_ status": "1",
            "class": "F",
            "router_name": "CORE-R4",
            "hop_to_server": "5",
            "hop_to_core": "3",
            "downstream_dependents": "4",
            "path_up": "0",
            "_source_file": "/data/netops-runtime/LCORE-D/raw/LCORE-D R4.csv",
        },
    ]

    plan = AdaptiveFeatureExtractor(max_sample_rows=10).build_plan(rows)
    event = row_to_canonical_event(rows[1], plan, 1)
    topology = event["topology_context"]

    assert event["src_device_key"] == "CORE-R4"
    assert event["device_profile"]["device_name"] == "CORE-R4"
    assert event["device_profile"]["src_device_key"] == "CORE-R4"
    assert topology["path_signature"] == "CORE-R4|hop_core=3|hop_server=5|path_up=0"
    assert "/data/" not in topology["path_signature"]
    assert topology["hop_to_core"] == "3"
    assert topology["hop_to_server"] == "5"
    assert topology["downstream_dependents"] == "4"
    assert topology["path_up"] == "0"
    assert topology["srcintf"] == ""
    assert topology["interface_type"] == "6"
    assert event["fault_context"]["scenario"] == "induced_fault"


def test_run_id_is_part_of_canonical_event_identity() -> None:
    row = {
        "timestamp": "1760264160",
        "Device_name": "CORE-R1",
        "class": "F",
        "ICMP loss": "100",
    }
    plan = AdaptiveFeatureExtractor(max_sample_rows=10).build_plan([row])

    first = row_to_canonical_event(row, plan, 0, run_id="run-a")
    second = row_to_canonical_event(row, plan, 0, run_id="run-b")
    repeated = row_to_canonical_event(row, plan, 0, run_id="run-a")

    assert first["dataset_context"]["run_id"] == "run-a"
    assert second["dataset_context"]["run_id"] == "run-b"
    assert first["event_id"] != second["event_id"]
    assert first["event_id"] == repeated["event_id"]
