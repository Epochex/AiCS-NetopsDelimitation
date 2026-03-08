import gzip
import os
import re
import time
from typing import Dict, Generator, List, Optional, Tuple

DIR = "/data/fortigate-runtime/input"
ACTIVE_PATH = "/data/fortigate-runtime/input/fortigate.log"

ROTATED_RE = re.compile(r"^fortigate\.log-(\d{8}-\d{6})(?:\.gz)?$")


def list_rotated_files() -> List[str]:
    files: List[str] = []
    # Avoid consuming rotated files that may still be being generated/compressed.
    min_age_sec_raw = os.getenv("ROTATED_MIN_AGE_SEC", "120")
    try:
        min_age_sec = max(0, int(min_age_sec_raw))
    except ValueError:
        min_age_sec = 120
    now = time.time()

    try:
        for name in os.listdir(DIR):
            if ROTATED_RE.match(name):
                path = os.path.join(DIR, name)
                if min_age_sec > 0:
                    try:
                        st = os.stat(path)
                    except FileNotFoundError:
                        continue
                    if (now - st.st_mtime) < min_age_sec:
                        continue
                files.append(path)
    except FileNotFoundError:
        return []

    def key_fn(p: str) -> str:
        m = ROTATED_RE.match(os.path.basename(p))
        return m.group(1) if m else "99999999-999999"

    files.sort(key=key_fn)
    return files


def stat_file(path: str) -> Tuple[int, int, int]:
    st = os.stat(path)
    return (st.st_ino, st.st_size, int(st.st_mtime))


def read_whole_file_lines(path: str) -> Generator[Tuple[str, Dict], None, None]:
    inode, size, mtime = stat_file(path)
    is_gz = path.endswith(".gz")
    if is_gz:
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as f:
            for line in f:
                yield line, {"path": path, "inode": inode, "offset": None, "size": size, "mtime": mtime}
    else:
        offset = 0
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                yield line, {"path": path, "inode": inode, "offset": offset, "size": size, "mtime": mtime}
                offset += len(line.encode("utf-8", errors="replace"))


def follow_active_binary(offset: int, max_wait_sec: float = 0.5) -> Generator[Tuple[str, int], None, None]:
    """
    Tail ACTIVE_PATH from byte offset. Yield (line, new_offset).
    IMPORTANT: This generator will return if no new bytes arrive within max_wait_sec.
    This allows the caller (main loop) to keep control (rotate scan, checkpoint flush, metrics emit).
    """
    start_wait = time.time()

    with open(ACTIVE_PATH, "rb") as f:
        f.seek(offset, os.SEEK_SET)
        buf = b""
        while True:
            chunk = f.read(8192)
            if not chunk:
                if (time.time() - start_wait) >= max_wait_sec:
                    return
                time.sleep(0.05)
                continue

            start_wait = time.time()
            buf += chunk

            while True:
                nl = buf.find(b"\n")
                if nl == -1:
                    break

                line_bytes = buf[:nl + 1]
                buf = buf[nl + 1:]
                offset += len(line_bytes)
                line = line_bytes.decode("utf-8", errors="replace")
                yield line, offset


def active_inode() -> Optional[int]:
    try:
        return os.stat(ACTIVE_PATH).st_ino
    except FileNotFoundError:
        return None


def active_size() -> Optional[int]:
    try:
        return os.stat(ACTIVE_PATH).st_size
    except FileNotFoundError:
        return None
