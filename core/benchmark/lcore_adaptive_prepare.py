from __future__ import annotations

import argparse
import json
from itertools import islice
from pathlib import Path
from typing import Iterable

from common.data_features import LCORE_D_SOURCE_URL, AdaptiveFeatureExtractor, iter_records_from_paths


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Profile LCORE-D or another tabular network-monitoring dataset and "
            "emit canonical NetOps fact JSONL for the existing core pipeline."
        )
    )
    parser.add_argument("--input", action="append", required=True, help="Input file, zip, or directory.")
    parser.add_argument("--output-jsonl", required=True, help="Canonical fact JSONL output path.")
    parser.add_argument("--plan-json", required=True, help="Feature discovery plan output path.")
    parser.add_argument("--dataset-id", default="lcore-d")
    parser.add_argument("--run-id", default="", help="Optional replay/run identifier included in dataset_context and event_id.")
    parser.add_argument("--source-uri", default=LCORE_D_SOURCE_URL)
    parser.add_argument("--sample-rows", type=int, default=5000)
    parser.add_argument("--max-records", type=int, default=0, help="0 means no conversion limit.")
    return parser.parse_args()


def _records(inputs: list[str]) -> Iterable[dict]:
    return iter_records_from_paths(inputs)


def main() -> None:
    args = _parse_args()
    extractor = AdaptiveFeatureExtractor(
        dataset_id=args.dataset_id,
        source_uri=args.source_uri,
        max_sample_rows=args.sample_rows,
    )

    plan = extractor.build_plan(_records(args.input))
    plan_path = Path(args.plan_json)
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(plan.to_dict(), ensure_ascii=True, indent=2, sort_keys=True) + "\n")

    output_path = Path(args.output_jsonl)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    row_iter = _records(args.input)
    if args.max_records > 0:
        row_iter = islice(row_iter, args.max_records)

    written = 0
    with output_path.open("w", encoding="utf-8") as fp:
        for event in extractor.transform(row_iter, plan, run_id=args.run_id):
            fp.write(json.dumps(event, ensure_ascii=True, separators=(",", ":")) + "\n")
            written += 1

    summary = {
        "dataset_id": args.dataset_id,
        "run_id": args.run_id,
        "source_uri": args.source_uri,
        "observed_rows_for_plan": plan.observed_rows,
        "total_columns": plan.total_columns,
        "metric_fields": len(plan.metric_fields),
        "label_fields": plan.label_fields,
        "entity_fields": plan.entity_fields,
        "topology_fields": plan.topology_fields,
        "scenario_values": plan.scenario_values,
        "events_written": written,
        "output_jsonl": str(output_path),
        "plan_json": str(plan_path),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
