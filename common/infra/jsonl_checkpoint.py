import json
import logging
import os
import tempfile
from typing import Any

LOGGER = logging.getLogger(__name__)


def load_checkpoint(path: str) -> dict[str, Any]:
    if not os.path.exists(path):
        return {"file_offsets": {}}

    try:
        with open(path, "r", encoding="utf-8") as fp:
            data = json.load(fp)
    except Exception as exc:
        LOGGER.warning("failed to load checkpoint %s: %s", path, exc)
        return {"file_offsets": {}}

    if not isinstance(data, dict):
        return {"file_offsets": {}}
    if not isinstance(data.get("file_offsets"), dict):
        data["file_offsets"] = {}
    return data


def save_checkpoint(path: str, payload: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix="checkpoint-", suffix=".tmp", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            json.dump(payload, fp, ensure_ascii=True, sort_keys=True)
            fp.flush()
            os.fsync(fp.fileno())
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
