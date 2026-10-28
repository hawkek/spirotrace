"""Checkpoint 4, the part export's first half writes: resolved values, the
post-review flags, reviewer disagreements and derived values, with a stamp.
The dataset views, data dictionary and QC report are written by the export
step (A5).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from spirotrace.derive import DeriveRun
from spirotrace.resolve import Resolved

from .csvio import Notice, Row, write_rows
from .events import Event
from .stamps import make_stamp, write_stamp

RESOLVED_FILE = "resolved_CONTAINS_DATA.csv"
FLAGS_RESOLVED_FILE = "flags_resolved_CONTAINS_DATA.csv"
DISAGREEMENTS_FILE = "disagreements_CONTAINS_DATA.csv"
DERIVED_FILE = "derived_CONTAINS_DATA.csv"
DERIVED_FLAGS_FILE = "flags_derived_CONTAINS_DATA.csv"

DISAGREEMENT_COLUMNS: tuple[str, ...] = (
    "key",
    "record_id",
    "reviewer",
    "action",
    "value",
    "event_id",
)


def _no_notice(_: str) -> None:
    return None


def outputs_stamp_fields(
    raw_stamp: Mapping[str, Any], events: Iterable[Event], rspiro_version: str
) -> dict[str, Any]:
    """The raw stamp's fields plus what the events and R contribute."""
    evs = list(events)
    last_by_reviewer: dict[str, str] = {}
    for e in sorted(evs, key=lambda e: (e.reviewer, e.time, e.sequence)):
        last_by_reviewer[e.reviewer] = e.event_id
    return {
        **{
            k: v
            for k, v in raw_stamp.items()
            if k not in ("written_at", "store_schema_version", "code_version")
        },
        "events_count": len(evs),
        "last_event_ids": dict(sorted(last_by_reviewer.items())),
        "rspiro_version": rspiro_version,
    }


def disagreement_rows(resolved: Resolved) -> list[Row]:
    rows: list[Row] = []
    for key, by_reviewer in sorted(resolved.disagreements.items()):
        for reviewer, e in sorted(by_reviewer.items()):
            rows.append(
                {
                    "key": key,
                    "record_id": e.record_id,
                    "reviewer": reviewer,
                    "action": e.action,
                    "value": e.value,
                    "event_id": e.event_id,
                }
            )
    return rows


def write_outputs(
    folder: Path,
    resolved: Resolved,
    derived: DeriveRun,
    stamp_fields: Mapping[str, Any],
    notice: Notice = _no_notice,
    code: str | None = None,
) -> dict[str, Any]:
    from spirotrace.checks import Flag
    from spirotrace.derive import DerivedRow
    from spirotrace.resolve import ResolvedFlag, ResolvedValue

    folder.mkdir(parents=True, exist_ok=True)
    write_rows(
        folder / RESOLVED_FILE,
        ResolvedValue.COLUMNS,
        (v.to_row() for v in resolved.values.values()),
        notice,
    )
    write_rows(
        folder / FLAGS_RESOLVED_FILE,
        ResolvedFlag.COLUMNS,
        (f.to_row() for f in resolved.flags_resolved),
        notice,
    )
    write_rows(
        folder / DISAGREEMENTS_FILE,
        DISAGREEMENT_COLUMNS,
        disagreement_rows(resolved),
        notice,
    )
    write_rows(
        folder / DERIVED_FILE,
        DerivedRow.COLUMNS,
        (r.to_row() for r in derived.rows),
        notice,
    )
    write_rows(
        folder / DERIVED_FLAGS_FILE,
        Flag.COLUMNS,
        (f.to_row() for f in derived.flags),
        notice,
    )
    stamp = make_stamp(stamp_fields, code)
    write_stamp(folder, stamp, notice)
    return stamp
