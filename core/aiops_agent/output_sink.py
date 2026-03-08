import os
from datetime import datetime, timezone


def hourly_file_path(base_dir: str) -> str:
    now = datetime.now(timezone.utc)
    return os.path.join(base_dir, f"suggestions-{now.strftime('%Y%m%d-%H')}.jsonl")


def append_jsonl_line(path: str, payload: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as fp:
        fp.write(payload)
        fp.write("\n")
