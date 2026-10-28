"""CSV and JSON files of the checkpoints: encoding rules and alongside-writes.

Files are UTF-8 without a byte-order mark and are read back tolerating one,
falling back to cp1252 for a file re-saved by Excel on Windows (reported to the
caller, never silently). A file is written fresh under its own name; when the
name is locked (open in Excel on a network drive) it is written alongside as
``<name>.<timestamp><suffix>`` and the caller is told. Nothing is ever renamed
over an existing file.
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

Row = dict[str, str]
Notice = Callable[[str], None]


class StoreError(ValueError):
    """A checkpoint file is missing, unreadable or has the wrong columns."""


def _no_notice(_: str) -> None:
    return None


def read_text(path: Path, notice: Notice = _no_notice) -> str:
    """The file's text, UTF-8 (BOM tolerated) or cp1252 with a notice."""
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        notice(f"{path.name}: not UTF-8 (saved by Excel?); read as Windows text")
        return raw.decode("cp1252", errors="replace")


def read_rows(
    path: Path, columns: Sequence[str] | None = None, notice: Notice = _no_notice
) -> list[Row]:
    """Rows of a checkpoint CSV as dicts of strings.

    With ``columns`` the header must hold every named column (extra columns
    are kept, so a later schema can add one); a missing column raises.
    """
    if not path.is_file():
        raise StoreError(f"{path}: not found")
    text = read_text(path, notice)
    reader = csv.DictReader(io.StringIO(text, newline=""))
    header = [h.strip().lstrip("﻿") for h in reader.fieldnames or []]
    if columns is not None:
        missing = [c for c in columns if c not in header]
        if missing:
            raise StoreError(f"{path.name}: missing columns {', '.join(missing)}")
    out: list[Row] = []
    for r in reader:
        out.append(
            {(k or "").strip(): (v if isinstance(v, str) else "") for k, v in r.items()}
        )
    return out


def _stamp_now() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def alongside(path: Path) -> Path:
    """The alongside name used when ``path`` is locked."""
    return path.with_name(f"{path.stem}.{_stamp_now()}{path.suffix}")


def write_rows(
    path: Path,
    columns: Sequence[str],
    rows: Iterable[Mapping[str, str]],
    notice: Notice = _no_notice,
) -> Path:
    """Write ``rows`` under ``columns``; returns the path written (alongside if locked)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = io.StringIO()
    w = csv.DictWriter(text, fieldnames=list(columns), lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow({c: r.get(c, "") for c in columns})
    return write_bytes(path, text.getvalue().encode("utf-8"), notice)


def write_bytes(path: Path, data: bytes, notice: Notice = _no_notice) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_bytes(data)
        return path
    except PermissionError:
        other = alongside(path)
        other.write_bytes(data)
        notice(f"{path.name} is locked (open elsewhere?); written as {other.name}")
        return other


def write_json(
    path: Path, payload: Mapping[str, Any], notice: Notice = _no_notice
) -> Path:
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    return write_bytes(path, text.encode("utf-8"), notice)


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise StoreError(f"{path}: not found")
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise StoreError(f"{path}: not valid JSON ({exc})") from exc
    if not isinstance(data, dict):
        raise StoreError(f"{path}: expected a JSON object")
    return data
