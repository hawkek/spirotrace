"""The extraction store (checkpoint 2): the raw run under ``outputs/raw/``.

Five CSV files and a stamp. Records, observations, conditions and flags hold
record ids (participant numbers), raw text or values, so their names carry
``_CONTAINS_DATA``; the pages file holds file hashes and page types only. The
raw run is written once by ``spirotrace run`` and never changed by review.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from spirotrace.checks import Flag
from spirotrace.layouts import ReadingCondition
from spirotrace.model import Observation, ObservationKey, Page, Record

from .csvio import Notice, Row, StoreError, read_rows, write_rows
from .stamps import make_stamp, read_stamp, write_stamp

RAW_DIR = "raw"
RECORDS_FILE = "records_CONTAINS_DATA.csv"
PAGES_FILE = "pages.csv"
OBSERVATIONS_FILE = "observations_CONTAINS_DATA.csv"
CONDITIONS_FILE = "conditions_CONTAINS_DATA.csv"
FLAGS_FILE = "flags_CONTAINS_DATA.csv"

RECORD_COLUMNS: tuple[str, ...] = (*Record.COLUMNS, "file_name")
CONDITION_COLUMNS: tuple[str, ...] = ("record_id", "page", "key", "code", "detail")


def _no_notice(_: str) -> None:
    return None


@dataclass(slots=True)
class ReadRecord:
    """One record as the rules see it (the public form of a read record)."""

    record: Record
    observations: dict[ObservationKey, Observation] = field(default_factory=dict)
    conditions: list[ReadingCondition] = field(default_factory=list)

    @property
    def record_id(self) -> str:
        return self.record.record_id


@dataclass(slots=True)
class RawStore:
    """Everything the raw run produced, in memory."""

    records: list[ReadRecord] = field(default_factory=list)
    pages: list[Page] = field(default_factory=list)
    flags: list[Flag] = field(default_factory=list)
    file_names: dict[str, str] = field(default_factory=dict)
    """file hash -> file name (participant numbers live in file names)."""
    stamp: dict[str, Any] = field(default_factory=dict)

    def by_id(self) -> dict[str, ReadRecord]:
        return {r.record_id: r for r in self.records}

    def observations(self) -> dict[ObservationKey, Observation]:
        return {k: o for r in self.records for k, o in r.observations.items()}


def condition_row(c: ReadingCondition) -> Row:
    return {
        "record_id": c.record_id,
        "page": "" if c.page is None else str(c.page),
        "key": "" if c.key is None else c.key.to_string(),
        "code": c.code,
        "detail": c.detail,
    }


def condition_from_row(r: Mapping[str, str]) -> ReadingCondition:
    return ReadingCondition(
        r["record_id"],
        int(r["page"]) if r["page"] else None,
        ObservationKey.from_string(r["key"]) if r["key"] else None,
        r["code"],
        r["detail"],
    )


def raw_stamp_fields(
    settings_hash: str,
    reader: str,
    templates: Mapping[str, int],
    file_hashes: Iterable[str],
    *,
    tesseract_version: str = "",
    second_ocr: bool = False,
    missing_pages: bool = False,
) -> dict[str, Any]:
    """The staleness fields of the raw store (phase 2 plan, section 10)."""
    return {
        "settings_hash": settings_hash,
        "reader": reader,
        "templates": dict(sorted(templates.items())),
        "tesseract_version": tesseract_version,
        "second_ocr": second_ocr,
        "missing_pages": missing_pages,
        "file_hashes": sorted(set(file_hashes)),
    }


def write_raw(
    folder: Path,
    store: RawStore,
    stamp_fields: Mapping[str, Any],
    notice: Notice = _no_notice,
    code: str | None = None,
) -> dict[str, Any]:
    """Write the five files and the stamp into ``folder``; returns the stamp."""
    folder.mkdir(parents=True, exist_ok=True)
    write_rows(
        folder / RECORDS_FILE,
        RECORD_COLUMNS,
        (
            {
                **r.record.to_row(),
                "file_name": store.file_names.get(r.record.file_hash, ""),
            }
            for r in store.records
        ),
        notice,
    )
    write_rows(
        folder / PAGES_FILE, Page.COLUMNS, (p.to_row() for p in store.pages), notice
    )
    write_rows(
        folder / OBSERVATIONS_FILE,
        Observation.COLUMNS,
        (o.to_row() for r in store.records for o in r.observations.values()),
        notice,
    )
    write_rows(
        folder / CONDITIONS_FILE,
        CONDITION_COLUMNS,
        (condition_row(c) for r in store.records for c in r.conditions),
        notice,
    )
    write_rows(
        folder / FLAGS_FILE, Flag.COLUMNS, (f.to_row() for f in store.flags), notice
    )
    stamp = make_stamp(stamp_fields, code)
    write_stamp(folder, stamp, notice)
    store.stamp = stamp
    return stamp


def read_raw(folder: Path, notice: Notice = _no_notice) -> RawStore:
    """Read the raw store back; raises :class:`StoreError` when a file is missing."""
    store = RawStore()
    by_id: dict[str, ReadRecord] = {}
    for r in read_rows(folder / RECORDS_FILE, RECORD_COLUMNS, notice):
        record = Record.from_row({c: r[c] for c in Record.COLUMNS})
        by_id[record.record_id] = ReadRecord(record)
        store.records.append(by_id[record.record_id])
        if r["file_name"]:
            store.file_names[record.file_hash] = r["file_name"]
    store.pages = [
        Page.from_row({c: r[c] for c in Page.COLUMNS})
        for r in read_rows(folder / PAGES_FILE, Page.COLUMNS, notice)
    ]
    for r in read_rows(folder / OBSERVATIONS_FILE, Observation.COLUMNS, notice):
        o = Observation.from_row({c: r[c] for c in Observation.COLUMNS})
        rec = by_id.get(o.record_id)
        if rec is None:
            raise StoreError(f"observation of unknown record in {OBSERVATIONS_FILE}")
        rec.observations[o.key] = o
    for r in read_rows(folder / CONDITIONS_FILE, CONDITION_COLUMNS, notice):
        c = condition_from_row(r)
        rec = by_id.get(c.record_id)
        if rec is None:
            raise StoreError(f"condition of unknown record in {CONDITIONS_FILE}")
        rec.conditions.append(c)
    store.flags = [
        Flag.from_row(r) for r in read_rows(folder / FLAGS_FILE, Flag.COLUMNS, notice)
    ]
    store.stamp = read_stamp(folder) or {}
    return store


def records_as_inputs(store: RawStore) -> Sequence[ReadRecord]:
    return store.records
