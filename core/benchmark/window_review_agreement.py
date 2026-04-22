from __future__ import annotations

import argparse
import itertools
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


REVIEW_FIELDS = (
    "should_invoke_external",
    "representative_alert_sufficient",
    "selected_device_covered",
    "selected_path_covered",
    "timeline_sufficient",
    "false_skip_if_local",
)


def run(args: argparse.Namespace) -> dict[str, Any]:
    review_sets = [_load_review_file(Path(path)) for path in args.review_jsonl]
    merged = _merge_reviews(review_sets)
    field_summary = {field: _field_agreement(merged, field) for field in REVIEW_FIELDS}
    adjudicated = [_adjudicate(record) for record in merged.values()]
    report = {
        "schema_version": 1,
        "review_files": list(args.review_jsonl),
        "reviewers": sorted({review["reviewer"] for record in merged.values() for review in record["reviews"] if review["reviewer"]}),
        "windows_reviewed": len(merged),
        "fields": field_summary,
        "windows_needing_adjudication": sum(1 for record in adjudicated if bool(record["needs_adjudication"])),
    }
    if args.output_json:
        path = Path(args.output_json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.output_adjudicated_jsonl:
        path = Path(args.output_adjudicated_jsonl)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fp:
            for record in adjudicated:
                fp.write(json.dumps(record, ensure_ascii=True, sort_keys=True) + "\n")
    print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
    return report


def _load_review_file(path: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            window = record.get("window") or {}
            expert_label = record.get("expert_label") or {}
            window_id = str(window.get("window_id") or record.get("window_id") or "")
            if not window_id:
                continue
            reviewer = str(expert_label.get("reviewer") or record.get("reviewer") or path.stem)
            records[window_id] = {
                "window_id": window_id,
                "window": window,
                "weak_label": record.get("weak_label") or {},
                "reviewer": reviewer,
                "expert_label": expert_label,
            }
    return records


def _merge_reviews(review_sets: list[dict[str, dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for review_set in review_sets:
        for window_id, record in review_set.items():
            if window_id not in merged:
                merged[window_id] = {
                    "window_id": window_id,
                    "window": record.get("window") or {},
                    "weak_label": record.get("weak_label") or {},
                    "reviews": [],
                }
            merged[window_id]["reviews"].append(
                {
                    "reviewer": record["reviewer"],
                    "expert_label": record.get("expert_label") or {},
                }
            )
    return merged


def _field_agreement(merged: dict[str, dict[str, Any]], field: str) -> dict[str, Any]:
    pair_values: list[tuple[bool, bool]] = []
    exact = 0
    comparable = 0
    label_counts: Counter[str] = Counter()
    for record in merged.values():
        values = [
            review["expert_label"].get(field)
            for review in record["reviews"]
            if review["expert_label"].get(field) is not None
        ]
        for value in values:
            label_counts[str(value)] += 1
        for left, right in itertools.combinations(values, 2):
            comparable += 1
            pair_values.append((bool(left), bool(right)))
            if bool(left) == bool(right):
                exact += 1
    agreement_rate = exact / comparable if comparable else 0.0
    return {
        "pairwise_exact_agreement": round(agreement_rate, 6),
        "pairwise_comparisons": comparable,
        "cohen_kappa": round(_cohen_kappa(pair_values), 6) if comparable else 0.0,
        "label_counts": dict(label_counts),
    }


def _cohen_kappa(values: list[tuple[bool, bool]]) -> float:
    if not values:
        return 0.0
    total = len(values)
    observed = sum(1 for left, right in values if left == right) / total
    left_counts = Counter(left for left, _ in values)
    right_counts = Counter(right for _, right in values)
    expected = sum((left_counts[value] / total) * (right_counts[value] / total) for value in {False, True})
    if expected >= 1.0:
        return 1.0
    return (observed - expected) / max(1e-9, 1.0 - expected)


def _adjudicate(record: dict[str, Any]) -> dict[str, Any]:
    adjudicated: dict[str, Any] = {}
    disagreements: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for field in REVIEW_FIELDS:
        votes = []
        for review in record["reviews"]:
            value = review["expert_label"].get(field)
            if value is None:
                continue
            votes.append((review["reviewer"], bool(value)))
        if not votes:
            adjudicated[field] = None
            continue
        counts = Counter(value for _, value in votes)
        if len(counts) > 1 and counts.most_common(1)[0][1] == counts.most_common()[-1][1]:
            adjudicated[field] = None
            disagreements[field] = [{"reviewer": reviewer, "value": value} for reviewer, value in votes]
            continue
        adjudicated[field] = counts.most_common(1)[0][0]
        if len(counts) > 1:
            disagreements[field] = [{"reviewer": reviewer, "value": value} for reviewer, value in votes]
    return {
        "window_id": record["window_id"],
        "window": record.get("window") or {},
        "weak_label": record.get("weak_label") or {},
        "reviews": record["reviews"],
        "adjudicated_label": adjudicated,
        "needs_adjudication": bool(disagreements),
        "disagreements": disagreements,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure reviewer agreement and build adjudicated window labels.")
    parser.add_argument("--review-jsonl", action="append", required=True)
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-adjudicated-jsonl", default="")
    run(parser.parse_args())


if __name__ == "__main__":
    main()
