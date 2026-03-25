from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from core.correlator.rules import RuleConfig
from common.infra.config import env_int, env_str

LOGGER = logging.getLogger(__name__)

_PROFILE_ENV_MAP = {
    "RULE_DENY_WINDOW_SEC": "deny_window_sec",
    "RULE_DENY_THRESHOLD": "deny_threshold",
    "RULE_BYTES_WINDOW_SEC": "bytes_window_sec",
    "RULE_BYTES_THRESHOLD": "bytes_threshold",
    "RULE_ALERT_COOLDOWN_SEC": "cooldown_sec",
}


def load_rule_config() -> RuleConfig:
    values = _defaults_from_env()
    profile_name = env_str("CORRELATOR_RULE_PROFILE", "")
    profile_path = env_str("CORRELATOR_RULE_PROFILE_PATH", "")

    source = "env_defaults"
    if profile_path:
        values.update(_load_profile_file(Path(profile_path)))
        source = f"path:{profile_path}"
    elif profile_name:
        filename = profile_name if profile_name.endswith(".json") else f"{profile_name}.json"
        local_path = Path(__file__).resolve().parent / "profiles" / filename
        values.update(_load_profile_file(local_path))
        source = f"profile:{filename}"

    _apply_env_overrides(values)
    cfg = RuleConfig(**values)
    LOGGER.info("rule profile loaded source=%s values=%s", source, json.dumps(values, sort_keys=True))
    return cfg


def _defaults_from_env() -> dict[str, int]:
    return {
        "deny_window_sec": env_int("RULE_DENY_WINDOW_SEC", 60),
        "deny_threshold": env_int("RULE_DENY_THRESHOLD", 30),
        "bytes_window_sec": env_int("RULE_BYTES_WINDOW_SEC", 300),
        "bytes_threshold": env_int("RULE_BYTES_THRESHOLD", 20_000_000),
        "cooldown_sec": env_int("RULE_ALERT_COOLDOWN_SEC", 60),
    }


def _load_profile_file(path: Path) -> dict[str, int]:
    if not path.exists():
        raise FileNotFoundError(f"rule profile not found: {path}")
    data: Any
    with open(path, "r", encoding="utf-8") as fp:
        data = json.load(fp)
    if not isinstance(data, dict):
        raise ValueError(f"invalid rule profile content (dict expected): {path}")

    values: dict[str, int] = {}
    for key in ("deny_window_sec", "deny_threshold", "bytes_window_sec", "bytes_threshold", "cooldown_sec"):
        if key in data:
            values[key] = int(data[key])
    return values


def _apply_env_overrides(values: dict[str, int]) -> None:
    for env_key, cfg_key in _PROFILE_ENV_MAP.items():
        raw = os.getenv(env_key)
        if raw is None:
            continue
        raw = raw.strip()
        if not raw:
            continue
        try:
            values[cfg_key] = int(raw)
        except ValueError:
            LOGGER.warning("ignore invalid env override %s=%s", env_key, raw)
