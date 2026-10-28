"""Checkpoint stamps: what wrote a checkpoint, so a stale one is rebuilt, never reused.

A stamp is a JSON object with ``store_schema_version``, ``code_version``,
``written_at`` and the fields of the staleness table in the phase 2 plan. A
stage compares every field but ``written_at`` with what it would write now.
"""

from __future__ import annotations

import subprocess
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from spirotrace import __version__

from .csvio import Notice, StoreError, read_json, write_json

STORE_SCHEMA_VERSION = 1
"""Bumped whenever a checkpoint file gains, loses or renames a column."""

STAMP_FILE = "stamp.json"


def code_version(package_dir: Path | None = None) -> str:
    """The package version, plus the short git commit when run from a checkout.

    A development run is then distinguishable from a release; the git call is
    best effort and never fails the run.
    """
    here = package_dir or Path(__file__).resolve().parent
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=here,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return __version__
    sha = r.stdout.strip()
    return f"{__version__}+g{sha}" if r.returncode == 0 and sha else __version__


def now_iso() -> str:
    """Local wall-clock time with offset, to the second."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def make_stamp(fields: Mapping[str, Any], code: str | None = None) -> dict[str, Any]:
    return {
        "store_schema_version": STORE_SCHEMA_VERSION,
        "code_version": code if code is not None else code_version(),
        "written_at": now_iso(),
        **fields,
    }


def stamp_matches(stored: Mapping[str, Any] | None, current: Mapping[str, Any]) -> bool:
    """True when every field but ``written_at`` is equal."""
    if stored is None:
        return False
    a = {k: v for k, v in stored.items() if k != "written_at"}
    b = {k: v for k, v in current.items() if k != "written_at"}
    return a == b


def read_stamp(folder: Path) -> dict[str, Any] | None:
    path = folder / STAMP_FILE
    if not path.is_file():
        return None
    try:
        return read_json(path)
    except StoreError:
        return None


def write_stamp(
    folder: Path, stamp: Mapping[str, Any], notice: Notice | None = None
) -> Path:
    return write_json(folder / STAMP_FILE, stamp, notice or (lambda _m: None))
