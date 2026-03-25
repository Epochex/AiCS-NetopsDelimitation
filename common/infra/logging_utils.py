import logging
import os


def configure_logging(service_name: str) -> None:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format=(
            "%(asctime)sZ "
            "%(levelname)s "
            f"[{service_name}] "
            "%(message)s"
        ),
    )
