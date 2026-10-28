"""Review events (checkpoint 3): one append-only file per reviewer.

An event is one reviewer's answer on one observation key. Files are only ever
appended to, under a lock held for the append (``msvcrt.locking`` on Windows,
``fcntl.flock`` elsewhere); nothing edits a file of values in place. Session
rows record wall-clock start and end per review session, which the review-
minutes figure uses.
"""

from __future__ import annotations

import csv
import io
import os
import re
import sys
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import IO, ClassVar

from .csvio import Notice, Row, StoreError, read_rows

EVENT_SCHEMA_VERSION = 1
EVENT_FILE_RE = re.compile(r"^events_([A-Za-z0-9]{1,8})\.csv$")
SESSION_FILE_RE = re.compile(r"^sessions_([A-Za-z0-9]{1,8})\.csv$")
REVIEWER_RE = re.compile(r"^[A-Za-z0-9]{1,8}$")

ACTIONS: tuple[str, ...] = (
    "typed",
    "as_read",
    "not_readable",
    "empty",
    "dash",
    "struck",
    "exclude",
    "withdraw",
)
"""The eight actions approved at G2."""


def _no_notice(_: str) -> None:
    return None


@dataclass(frozen=True, slots=True)
class Event:
    """One reviewer answer; the columns of ``events_<initials>.csv``."""

    event_id: str
    sequence: int
    time: str
    reviewer: str
    record_id: str
    key: str
    action: str
    value: str = ""
    before_raw: str = ""
    before_value: str = ""
    note: str = ""
    open_rules: str = ""
    shown_at: str = ""
    elapsed_ms: int | None = None
    source: str = "app"
    source_fingerprint: str = ""
    tool_version: str = ""
    template_id: str = ""
    template_version: str = ""
    schema_version: int = EVENT_SCHEMA_VERSION

    COLUMNS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "event_id",
        "sequence",
        "time",
        "reviewer",
        "record_id",
        "key",
        "action",
        "value",
        "before_raw",
        "before_value",
        "note",
        "open_rules",
        "shown_at",
        "elapsed_ms",
        "source",
        "source_fingerprint",
        "tool_version",
        "template_id",
        "template_version",
    )

    def __post_init__(self) -> None:
        if self.action not in ACTIONS:
            raise StoreError(f"unknown event action {self.action!r}")
        if not REVIEWER_RE.match(self.reviewer):
            raise StoreError("reviewer must be 1 to 8 letters or digits")
        if self.action == "exclude" and not self.note.strip():
            raise StoreError("an exclude event needs a note")
        if self.sequence < 1:
            raise StoreError("sequence starts at 1")

    def to_row(self) -> Row:
        return {
            "schema_version": str(self.schema_version),
            "event_id": self.event_id,
            "sequence": str(self.sequence),
            "time": self.time,
            "reviewer": self.reviewer,
            "record_id": self.record_id,
            "key": self.key,
            "action": self.action,
            "value": self.value,
            "before_raw": self.before_raw,
            "before_value": self.before_value,
            "note": self.note,
            "open_rules": self.open_rules,
            "shown_at": self.shown_at,
            "elapsed_ms": "" if self.elapsed_ms is None else str(self.elapsed_ms),
            "source": self.source,
            "source_fingerprint": self.source_fingerprint,
            "tool_version": self.tool_version,
            "template_id": self.template_id,
            "template_version": self.template_version,
        }

    @classmethod
    def from_row(cls, r: Mapping[str, str]) -> Event:
        version = int(r["schema_version"])
        if version > EVENT_SCHEMA_VERSION:
            raise StoreError(f"event schema version {version} is newer than this code")
        return cls(
            event_id=r["event_id"],
            sequence=int(r["sequence"]),
            time=r["time"],
            reviewer=r["reviewer"],
            record_id=r["record_id"],
            key=r["key"],
            action=r["action"],
            value=r["value"],
            before_raw=r["before_raw"],
            before_value=r["before_value"],
            note=r["note"],
            open_rules=r["open_rules"],
            shown_at=r["shown_at"],
            elapsed_ms=int(r["elapsed_ms"]) if r["elapsed_ms"] else None,
            source=r["source"],
            source_fingerprint=r["source_fingerprint"],
            tool_version=r["tool_version"],
            template_id=r["template_id"],
            template_version=r["template_version"],
            schema_version=version,
        )


def new_event_id() -> str:
    return uuid.uuid4().hex


def events_path(review_dir: Path, reviewer: str) -> Path:
    return review_dir / f"events_{reviewer}.csv"


def sessions_path(review_dir: Path, reviewer: str) -> Path:
    return review_dir / f"sessions_{reviewer}.csv"


@contextmanager
def _locked(f: IO[bytes]) -> Iterator[None]:
    """Hold an exclusive lock on the open file for the duration."""
    if sys.platform == "win32":
        import msvcrt

        f.seek(0, os.SEEK_END)
        pos = f.tell()
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
        try:
            f.seek(pos)
            yield
        finally:
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def _append_row(path: Path, columns: tuple[str, ...], row: Row) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = io.StringIO()
    w = csv.DictWriter(text, fieldnames=list(columns), lineterminator="\n")
    with path.open("a+b") as f, _locked(f):
        f.seek(0, os.SEEK_END)
        if f.tell() == 0:
            w.writeheader()
        w.writerow({c: row.get(c, "") for c in columns})
        f.write(text.getvalue().encode("utf-8"))
        f.flush()


def next_sequence(review_dir: Path, reviewer: str) -> int:
    path = events_path(review_dir, reviewer)
    if not path.is_file():
        return 1
    rows = read_rows(path, Event.COLUMNS)
    return 1 + max((int(r["sequence"]) for r in rows), default=0)


def append_event(review_dir: Path, event: Event) -> None:
    """Append one event to the reviewer's file (header written on first use)."""
    _append_row(events_path(review_dir, event.reviewer), Event.COLUMNS, event.to_row())


SESSION_COLUMNS: tuple[str, ...] = (
    "session_id",
    "reviewer",
    "started",
    "ended",
    "answers",
)


def append_session(
    review_dir: Path,
    reviewer: str,
    session_id: str,
    started: str,
    ended: str,
    answers: int,
) -> None:
    if not REVIEWER_RE.match(reviewer):
        raise StoreError("reviewer must be 1 to 8 letters or digits")
    _append_row(
        sessions_path(review_dir, reviewer),
        SESSION_COLUMNS,
        {
            "session_id": session_id,
            "reviewer": reviewer,
            "started": started,
            "ended": ended,
            "answers": str(answers),
        },
    )


def read_events(review_dir: Path, notice: Notice = _no_notice) -> list[Event]:
    """Every event of every reviewer file in ``review_dir`` (missing folder: none)."""
    out: list[Event] = []
    if not review_dir.is_dir():
        return out
    for path in sorted(review_dir.iterdir()):
        m = EVENT_FILE_RE.match(path.name)
        if m is None:
            continue
        for r in read_rows(path, Event.COLUMNS, notice):
            e = Event.from_row(r)
            if e.reviewer != m.group(1):
                raise StoreError(f"{path.name}: event of reviewer {e.reviewer!r}")
            out.append(e)
    return out


def read_sessions(review_dir: Path, notice: Notice = _no_notice) -> list[Row]:
    out: list[Row] = []
    if not review_dir.is_dir():
        return out
    for path in sorted(review_dir.iterdir()):
        if SESSION_FILE_RE.match(path.name):
            out.extend(read_rows(path, SESSION_COLUMNS, notice))
    return out
