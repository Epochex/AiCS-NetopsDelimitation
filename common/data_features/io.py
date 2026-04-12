from __future__ import annotations

import csv
import json
import zipfile
from pathlib import Path
from typing import Any, Iterable, Mapping

_SUPPORTED_SUFFIXES = {".csv", ".jsonl", ".ndjson", ".json"}


def iter_records_from_paths(paths: Iterable[str | Path]) -> Iterable[dict[str, Any]]:
    for raw_path in paths:
        path = Path(raw_path)
        if path.is_dir():
            yield from iter_records_from_paths(_discover_files(path))
            continue
        if path.suffix.lower() == ".zip":
            yield from _iter_zip(path)
            continue
        yield from _iter_file(path)


def _discover_files(directory: Path) -> list[Path]:
    files = [
        path
        for path in directory.rglob("*")
        if path.is_file() and (path.suffix.lower() in _SUPPORTED_SUFFIXES or path.suffix.lower() == ".zip")
    ]
    files.sort()
    return files


def _iter_zip(path: Path) -> Iterable[dict[str, Any]]:
    with zipfile.ZipFile(path) as archive:
        for member in sorted(archive.namelist()):
            suffix = Path(member).suffix.lower()
            if suffix not in _SUPPORTED_SUFFIXES:
                continue
            with archive.open(member) as fp:
                text = (line.decode("utf-8", "replace") for line in fp)
                yield from _iter_lines(member, suffix, text)


def _iter_file(path: Path) -> Iterable[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix not in _SUPPORTED_SUFFIXES:
        return
    with path.open("r", encoding="utf-8", errors="replace", newline="") as fp:
        yield from _iter_lines(str(path), suffix, fp)


def _iter_lines(source_name: str, suffix: str, lines: Iterable[str]) -> Iterable[dict[str, Any]]:
    if suffix == ".csv":
        reader = csv.DictReader(lines)
        for row in reader:
            yield _with_source(row, source_name)
        return

    if suffix in {".jsonl", ".ndjson"}:
        for line_no, line in enumerate(lines, start=1):
            text = line.strip()
            if not text:
                continue
            obj = json.loads(text)
            if isinstance(obj, dict):
                yield _with_source(obj, source_name, line_no)
        return

    text = "".join(lines)
    if not text.strip():
        return
    obj = json.loads(text)
    if isinstance(obj, list):
        for line_no, item in enumerate(obj, start=1):
            if isinstance(item, dict):
                yield _with_source(item, source_name, line_no)
    elif isinstance(obj, dict):
        rows = obj.get("records") or obj.get("rows") or obj.get("data")
        if isinstance(rows, list):
            for line_no, item in enumerate(rows, start=1):
                if isinstance(item, dict):
                    yield _with_source(item, source_name, line_no)
        else:
            yield _with_source(obj, source_name)


def _with_source(row: Mapping[str, Any], source_name: str, line_no: int | None = None) -> dict[str, Any]:
    out = dict(row)
    out.setdefault("_source_file", source_name)
    if line_no is not None:
        out.setdefault("_source_line", line_no)
    return out
