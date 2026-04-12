from __future__ import annotations

import argparse
import json
import os
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class GpuState:
    index: int
    name: str
    memory_total_mb: int
    memory_used_mb: int
    utilization_percent: int

    @property
    def memory_free_mb(self) -> int:
        return max(self.memory_total_mb - self.memory_used_mb, 0)


def _parse_int(raw: str) -> int:
    try:
        return int(raw.strip())
    except ValueError:
        return 0


def read_gpus() -> list[GpuState]:
    output = subprocess.check_output(
        [
            "nvidia-smi",
            "--query-gpu=index,name,memory.total,memory.used,utilization.gpu",
            "--format=csv,noheader,nounits",
        ],
        text=True,
    )
    gpus: list[GpuState] = []
    for line in output.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != 5:
            continue
        gpus.append(
            GpuState(
                index=_parse_int(parts[0]),
                name=parts[1],
                memory_total_mb=_parse_int(parts[2]),
                memory_used_mb=_parse_int(parts[3]),
                utilization_percent=_parse_int(parts[4]),
            )
        )
    return gpus


def select_gpus(
    gpus: list[GpuState],
    *,
    count: int,
    min_free_mb: int,
    max_util_percent: int,
    allow_busy: bool,
) -> list[GpuState]:
    a6000 = [gpu for gpu in gpus if "A6000" in gpu.name]
    candidates = [
        gpu
        for gpu in a6000
        if gpu.memory_free_mb >= min_free_mb and gpu.utilization_percent <= max_util_percent
    ]
    if len(candidates) < count and allow_busy:
        candidates = a6000
    ranked = sorted(
        candidates,
        key=lambda gpu: (
            gpu.utilization_percent,
            -gpu.memory_free_mb,
            gpu.memory_used_mb,
            gpu.index,
        ),
    )
    return ranked[:count]


def write_lock(path: Path, selected: list[GpuState]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "locked_at": datetime.now(timezone.utc).isoformat(),
        "pid": os.getpid(),
        "selected_gpu_indices": [gpu.index for gpu in selected],
        "selected_gpus": [asdict(gpu) | {"memory_free_mb": gpu.memory_free_mb} for gpu in selected],
        "lock_type": "soft_reservation",
        "note": "This lock documents NetOps model-service ownership but does not prevent scheduler-level use by other users.",
    }
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Select low-utilization RTX A6000 GPUs for NetOps inference.")
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--min-free-mb", type=int, default=22_000)
    parser.add_argument("--max-util-percent", type=int, default=25)
    parser.add_argument("--allow-busy", action="store_true")
    parser.add_argument("--emit", choices={"json", "shell", "csv"}, default="json")
    parser.add_argument("--write-lock", default="")
    args = parser.parse_args()

    selected = select_gpus(
        read_gpus(),
        count=max(args.count, 1),
        min_free_mb=max(args.min_free_mb, 0),
        max_util_percent=max(args.max_util_percent, 0),
        allow_busy=args.allow_busy,
    )
    if not selected:
        raise SystemExit("no RTX A6000 GPU matched the requested inference reservation policy")

    if args.write_lock:
        write_lock(Path(args.write_lock), selected)

    indices = ",".join(str(gpu.index) for gpu in selected)
    if args.emit == "shell":
        print(f"export CUDA_VISIBLE_DEVICES={indices}")
    elif args.emit == "csv":
        print(indices)
    else:
        print(
            json.dumps(
                {
                    "cuda_visible_devices": indices,
                    "selected_gpus": [
                        asdict(gpu) | {"memory_free_mb": gpu.memory_free_mb}
                        for gpu in selected
                    ],
                },
                ensure_ascii=True,
                indent=2,
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()
