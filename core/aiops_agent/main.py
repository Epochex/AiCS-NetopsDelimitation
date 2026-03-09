import logging
from core.aiops_agent.app_config import load_config
from core.aiops_agent.runtime_io import build_clickhouse_client, build_consumer, build_producer
from core.aiops_agent.service import run_agent_loop
from core.infra.logging_utils import configure_logging

LOGGER = logging.getLogger(__name__)


def main() -> None:
    configure_logging("core-aiops-agent")
    config = load_config()
    consumer = build_consumer(config)
    producer = build_producer(config)
    clickhouse_client = build_clickhouse_client(config)
    run_agent_loop(config, consumer, producer, clickhouse_client)


if __name__ == "__main__":
    main()
