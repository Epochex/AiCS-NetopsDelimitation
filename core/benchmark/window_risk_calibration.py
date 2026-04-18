from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


TARGET_FALSE_SKIP_RATES = (0.01, 0.05, 0.10)


def run(args: argparse.Namespace) -> dict[str, Any]:
    records = _read_jsonl(Path(args.labels_jsonl))
    examples = [_to_example(record, allow_weak=args.allow_weak_labels) for record in records]
    examples = [example for example in examples if example is not None]
    if not examples:
        raise ValueError("no usable labels; provide expert labels or pass --allow-weak-labels for a smoke run")

    weights = _calibrate_atom_weights(examples)
    scored = [
        {
            **example,
            "calibrated_score": _score_atoms(example["atoms"], weights),
        }
        for example in examples
    ]
    thresholds = {
        str(rate): _threshold_for_false_skip(scored, rate)
        for rate in TARGET_FALSE_SKIP_RATES
    }
    label_sources = Counter(str(item.get("label_source") or "unknown") for item in scored)
    report = {
        "schema_version": 1,
        "labels_jsonl": args.labels_jsonl,
        "label_source": "weak" if args.allow_weak_labels else _dominant_source(label_sources),
        "label_sources": dict(label_sources.most_common()),
        "examples": len(scored),
        "positive_examples": sum(1 for item in scored if item["target"]),
        "negative_examples": sum(1 for item in scored if not item["target"]),
        "calibration_warnings": _calibration_warnings(scored),
        "calibrated_weights": weights,
        "thresholds": thresholds,
    }
    if args.output_json:
        path = Path(args.output_json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
    return report


def _to_example(record: dict[str, Any], *, allow_weak: bool) -> dict[str, Any] | None:
    window = record.get("window") if isinstance(record.get("window"), dict) else record
    expert = record.get("expert_label") if isinstance(record.get("expert_label"), dict) else {}
    weak = record.get("weak_label") if isinstance(record.get("weak_label"), dict) else record
    expert_target = expert.get("should_invoke_external")
    if expert_target is None:
        if not allow_weak:
            return None
        target = bool(weak.get("should_invoke_external"))
        label_source = "weak"
    else:
        target = bool(expert_target)
        label_source = str(expert.get("label_source") or "expert")
    atoms = window.get("risk_atoms") or weak.get("risk_atoms") or []
    return {
        "window_id": str(window.get("window_id") or weak.get("window_id") or ""),
        "target": target,
        "label_source": label_source,
        "atoms": [
            _base_atom_key(str(atom.get("key") or ""))
            for atom in atoms
            if isinstance(atom, dict) and str(atom.get("key") or "")
        ],
    }


def _calibrate_atom_weights(examples: list[dict[str, Any]]) -> dict[str, int]:
    pos_total = sum(1 for item in examples if item["target"])
    neg_total = max(len(examples) - pos_total, 1)
    pos_total = max(pos_total, 1)
    present_pos: Counter[str] = Counter()
    present_neg: Counter[str] = Counter()
    for item in examples:
        atoms = set(item["atoms"])
        if item["target"]:
            present_pos.update(atoms)
        else:
            present_neg.update(atoms)

    keys = sorted(set(present_pos) | set(present_neg))
    weights: dict[str, int] = {}
    for key in keys:
        pos_rate = (present_pos[key] + 1) / (pos_total + 2)
        neg_rate = (present_neg[key] + 1) / (neg_total + 2)
        log_odds = math.log(pos_rate / neg_rate)
        weights[key] = max(0, min(20, int(round(5 + 4 * log_odds))))
    return weights


def _threshold_for_false_skip(examples: list[dict[str, Any]], target_rate: float) -> dict[str, Any]:
    positives = [item for item in examples if item["target"]]
    if not positives:
        return {"threshold": 0, "false_skip_rate": 0.0, "selected_rate": 0.0}
    scores = sorted({int(item["calibrated_score"]) for item in examples})
    best = {"threshold": 0, "false_skip_rate": 1.0, "selected_rate": 1.0}
    for threshold in scores:
        false_skips = sum(1 for item in positives if int(item["calibrated_score"]) < threshold)
        selected = sum(1 for item in examples if int(item["calibrated_score"]) >= threshold)
        false_skip_rate = false_skips / max(len(positives), 1)
        if false_skip_rate <= target_rate:
            best = {
                "threshold": threshold,
                "false_skip_rate": round(false_skip_rate, 6),
                "selected_rate": round(selected / max(len(examples), 1), 6),
            }
    return best


def _score_atoms(atoms: list[str], weights: dict[str, int]) -> int:
    return sum(int(weights.get(atom, 0)) for atom in set(atoms))


def _base_atom_key(key: str) -> str:
    if key.startswith("scope:device:"):
        return "scope:device"
    if key.startswith("scope:path:"):
        return "scope:path"
    if key.startswith("occurrence:high:"):
        return "occurrence:high"
    if key.startswith("occurrence:pressure:"):
        return "occurrence:pressure"
    return key


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _dominant_source(sources: Counter[str]) -> str:
    if not sources:
        return "expert"
    return sources.most_common(1)[0][0]


def _calibration_warnings(examples: list[dict[str, Any]]) -> list[str]:
    positives = sum(1 for item in examples if item["target"])
    negatives = len(examples) - positives
    warnings: list[str] = []
    if positives == 0:
        warnings.append("no positive examples; false-skip calibration is not meaningful")
    if negatives == 0:
        warnings.append("no negative examples; selectivity and false-positive tradeoffs cannot be calibrated")
    return warnings


def main() -> None:
    parser = argparse.ArgumentParser(description="Calibrate window risk weights from reviewed labels.")
    parser.add_argument("--labels-jsonl", required=True)
    parser.add_argument("--output-json", default="")
    parser.add_argument(
        "--allow-weak-labels",
        action="store_true",
        help="Use weak labels when expert labels are absent. Use for smoke tests, not final claims.",
    )
    run(parser.parse_args())


if __name__ == "__main__":
    main()
