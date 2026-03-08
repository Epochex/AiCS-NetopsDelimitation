import glob
import hashlib
import json
import logging
import os
import time
from typing import Any

from kafka import KafkaProducer

from edge.edge_forwarder.infra.config import env_float, env_int, env_str
from edge.edge_forwarder.infra.jsonl_checkpoint import load_checkpoint, save_checkpoint
from edge.edge_forwarder.infra.logging_utils import configure_logging

LOGGER = logging.getLogger(__name__)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    v = raw.strip().lower()
    if v in {"1", "true", "yes", "y", "on"}:
        return True
    if v in {"0", "false", "no", "n", "off"}:
        return False
    return default


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


def _is_local_deny(payload: dict[str, Any]) -> bool:
    return (
        payload.get("type") == "traffic"
        and payload.get("subtype") == "local"
        and payload.get("action") == "deny"
    )


def _to_int(v: Any) -> int | None:
    if isinstance(v, int):
        return v
    if isinstance(v, str) and v.strip().isdigit():
        try:
            return int(v.strip())
        except ValueError:
            return None
    return None


def _is_broadcast_mdns_nbns(payload: dict[str, Any]) -> bool:
    dstip = str(payload.get("dstip") or "").lower()
    service = str(payload.get("service") or "").lower()
    app = str(payload.get("app") or "").lower()
    dstport = _to_int(payload.get("dstport"))

    if dstip in {"255.255.255.255", "224.0.0.251", "224.0.0.252", "ff02::fb", "ff02::1:3"}:
        return True

    if dstport in {5353, 137, 138}:
        return True

    broadcast_markers = ["mdns", "netbios", "nbns"]
    if any(m in service for m in broadcast_markers):
        return True
    if any(m in app for m in broadcast_markers):
        return True

    return False


def main() -> None:
    configure_logging("edge-forwarder")

    input_glob = env_str("FORWARDER_INPUT_GLOB", "/data/fortigate-runtime/output/parsed/events-*.jsonl")
    checkpoint_path = env_str("FORWARDER_CHECKPOINT_PATH", "/data/netops-runtime/forwarder/checkpoint.json")
    bootstrap_servers = env_str("KAFKA_BOOTSTRAP_SERVERS", "netops-kafka.netops-core.svc.cluster.local:9092")
    topic_raw = env_str("KAFKA_TOPIC_RAW", "netops.facts.raw.v1")
    scan_interval_sec = env_float("FORWARDER_SCAN_INTERVAL_SEC", 5.0)
    max_batch_lines = env_int("FORWARDER_MAX_BATCH_LINES", 1000)

    drop_local_deny = _env_bool("FORWARDER_FILTER_DROP_LOCAL_DENY", False)
    drop_broadcast_mdns_nbns = _env_bool("FORWARDER_FILTER_DROP_BROADCAST_MDNS_NBNS", False)

    checkpoint = load_checkpoint(checkpoint_path)
    file_offsets = checkpoint.setdefault("file_offsets", {})
    producer = _producer(bootstrap_servers)
    cumulative_sent = 0
    cumulative_bytes = 0
    cumulative_dropped = 0

    LOGGER.info(
        "forwarder started: glob=%s topic=%s drop_local_deny=%s drop_broadcast_mdns_nbns=%s",
        input_glob,
        topic_raw,
        drop_local_deny,
        drop_broadcast_mdns_nbns,
    )

    while True:
        files = _scan_files(input_glob)
        total_sent = 0
        total_bytes = 0
        dropped_local_deny = 0
        dropped_broadcast_mdns_nbns = 0
        scan_start = time.time()

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

                    if drop_local_deny and _is_local_deny(payload):
                        dropped_local_deny += 1
                        file_offsets[path] = fp.tell()
                        continue

                    if drop_broadcast_mdns_nbns and _is_broadcast_mdns_nbns(payload):
                        dropped_broadcast_mdns_nbns += 1
                        file_offsets[path] = fp.tell()
                        continue

                    key = _event_key(payload, line)
                    producer.send(topic_raw, key=key, value=line)

                    lines_sent += 1
                    total_sent += 1
                    total_bytes += len(raw)
                    file_offsets[path] = fp.tell()

                    if lines_sent % max_batch_lines == 0:
                        producer.flush()
                        save_checkpoint(checkpoint_path, checkpoint)

                producer.flush()
                file_offsets[path] = fp.tell()

            save_checkpoint(checkpoint_path, checkpoint)

        scan_elapsed = max(time.time() - scan_start, 1e-6)
        dropped_total = dropped_local_deny + dropped_broadcast_mdns_nbns
        cumulative_sent += total_sent
        cumulative_bytes += total_bytes
        cumulative_dropped += dropped_total

        eps = total_sent / scan_elapsed
        mbps = (total_bytes / (1024 * 1024)) / scan_elapsed
        LOGGER.info(
            (
                "scan complete: sent=%d bytes=%d eps=%.2f mbps=%.2f dropped=%d "
                "dropped_local_deny=%d dropped_broadcast_mdns_nbns=%d files=%d "
                "cumulative_sent=%d cumulative_bytes=%d cumulative_dropped=%d"
            ),
            total_sent,
            total_bytes,
            eps,
            mbps,
            dropped_total,
            dropped_local_deny,
            dropped_broadcast_mdns_nbns,
            len(files),
            cumulative_sent,
            cumulative_bytes,
            cumulative_dropped,
        )

        for known_path in list(file_offsets.keys()):
            if known_path not in files:
                del file_offsets[known_path]
                save_checkpoint(checkpoint_path, checkpoint)

        time.sleep(scan_interval_sec)


if __name__ == "__main__":
    main()
