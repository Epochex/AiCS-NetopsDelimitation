import glob
import hashlib
import json
import logging
import os
import time
from typing import Any

from kafka import KafkaProducer

from core.infra.config import env_float, env_int, env_str
from core.infra.jsonl_checkpoint import load_checkpoint, save_checkpoint
from core.infra.logging_utils import configure_logging

LOGGER = logging.getLogger(__name__)


def _event_key(payload: dict[str, Any], raw_line: str) -> bytes:
    event_id = payload.get("event_id")
    if isinstance(event_id, str) and event_id:
        return event_id.encode("utf-8")
    return hashlib.md5(raw_line.encode("utf-8"), usedforsecurity=False).hexdigest().encode("utf-8")


def _producer(bootstrap_servers: str) -> KafkaProducer:
    return KafkaProducer(
        bootstrap_servers=[x.strip() for x in bootstrap_servers.split(",") if x.strip()],
        retries=10,
        acks="all",
        linger_ms=200,
        compression_type="gzip",
        value_serializer=lambda x: x.encode("utf-8"),
    )


def _scan_files(input_glob: str) -> list[str]:
    files = [p for p in glob.glob(input_glob) if os.path.isfile(p)]
    files.sort()
    return files


def main() -> None:
    configure_logging("edge-forwarder")

    input_glob = env_str("FORWARDER_INPUT_GLOB", "/data/fortigate-runtime/output/parsed/events-*.jsonl")
    checkpoint_path = env_str("FORWARDER_CHECKPOINT_PATH", "/data/netops-runtime/forwarder/checkpoint.json")
    bootstrap_servers = env_str("KAFKA_BOOTSTRAP_SERVERS", "netops-kafka.netops-core.svc.cluster.local:9092")
    topic_raw = env_str("KAFKA_TOPIC_RAW", "netops.facts.raw.v1")
    scan_interval_sec = env_float("FORWARDER_SCAN_INTERVAL_SEC", 5.0)
    max_batch_lines = env_int("FORWARDER_MAX_BATCH_LINES", 1000)

    checkpoint = load_checkpoint(checkpoint_path)
    file_offsets = checkpoint.setdefault("file_offsets", {})
    producer = _producer(bootstrap_servers)

    LOGGER.info("forwarder started: glob=%s topic=%s", input_glob, topic_raw)

    while True:
        files = _scan_files(input_glob)
        total_sent = 0

        for path in files:
            offset = int(file_offsets.get(path, 0))
            file_size = os.path.getsize(path)
            if offset > file_size:
                LOGGER.warning("offset beyond file size, reset path=%s offset=%d size=%d", path, offset, file_size)
                offset = 0

            if offset == file_size:
                continue

            with open(path, "rb") as fp:
                fp.seek(offset)
                lines_sent = 0

                for raw in fp:
                    try:
                        line = raw.decode("utf-8").strip()
                    except UnicodeDecodeError:
                        LOGGER.warning("skip non-utf8 line path=%s offset=%d", path, fp.tell())
                        continue

                    if not line:
                        continue

                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        LOGGER.warning("skip invalid json path=%s offset=%d", path, fp.tell())
                        continue

                    key = _event_key(payload, line)
                    producer.send(topic_raw, key=key, value=line)

                    lines_sent += 1
                    total_sent += 1
                    file_offsets[path] = fp.tell()

                    if lines_sent % max_batch_lines == 0:
                        producer.flush()
                        save_checkpoint(checkpoint_path, checkpoint)

                producer.flush()
                file_offsets[path] = fp.tell()

            save_checkpoint(checkpoint_path, checkpoint)

        if total_sent:
            LOGGER.info("scan complete: sent=%d files=%d", total_sent, len(files))

        for known_path in list(file_offsets.keys()):
            if known_path not in files:
                del file_offsets[known_path]
                save_checkpoint(checkpoint_path, checkpoint)

        time.sleep(scan_interval_sec)


if __name__ == "__main__":
    main()
