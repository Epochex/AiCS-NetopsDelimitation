import logging
from typing import Any

LOGGER = logging.getLogger(__name__)


def recent_similar_count(client: Any, db: str, table: str, rule_id: str, service: str) -> int:
    if client is None:
        return 0
    try:
        result = client.query(
            f"""
            SELECT count()
            FROM {db}.{table}
            WHERE rule_id = %(rule_id)s
              AND service = %(service)s
              AND emit_ts >= now() - INTERVAL 1 HOUR
            """,
            parameters={"rule_id": rule_id, "service": service},
        )
        return int(result.first_item or 0)
    except Exception:
        LOGGER.exception("failed to query clickhouse context")
        return 0
