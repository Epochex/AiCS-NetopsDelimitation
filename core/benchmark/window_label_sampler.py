from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Any

from core.aiops_agent.alert_reasoning_runtime.window_labeling import build_weak_window_label


DEFAULT_PER_LABEL = 25


def run(args: argparse.Namespace) -> dict[str, Any]:
    windows = _read_jsonl(Path(args.windows_jsonl))
    rng = random.Random(args.seed)
    by_label: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for window in windows:
        by_label[str(window.get("window_label") or "unknown")].append(window)

    sampled: list[dict[str, Any]] = []
    for label, items in sorted(by_label.items()):
        ordered = sorted(items, key=lambda item: (-int(item.get("risk_score") or 0), str(item.get("window_id") or "")))
        if len(ordered) > args.per_label:
            head = ordered[: max(1, args.per_label // 2)]
            tail = ordered[max(1, args.per_label // 2):]
            rng.shuffle(tail)
            chosen = head + tail[: args.per_label - len(head)]
        else:
            chosen = ordered
        sampled.extend(chosen)

    sampled = sorted(sampled, key=lambda item: (str(item.get("window_label") or ""), -int(item.get("risk_score") or 0)))
    output_records = [
        {
            "window": window,
            "weak_label": build_weak_window_label(window),
        }
        for window in sampled[: args.max_windows or None]
    ]
    if args.output_jsonl:
        path = Path(args.output_jsonl)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fp:
            for record in output_records:
                fp.write(json.dumps(record, ensure_ascii=True, sort_keys=True) + "\n")

    report = {
        "windows_input": len(windows),
        "windows_sampled": len(output_records),
        "labels": {label: len(items) for label, items in sorted(by_label.items())},
        "output_jsonl": args.output_jsonl,
    }
    print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
    return report


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records = []
    with path.open("r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description="Sample reviewable incident-window labels.")
    parser.add_argument("--windows-jsonl", required=True)
    parser.add_argument("--output-jsonl", default="")
    parser.add_argument("--per-label", type=int, default=DEFAULT_PER_LABEL)
    parser.add_argument("--max-windows", type=int, default=0)
    parser.add_argument("--seed", type=int, default=7)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
