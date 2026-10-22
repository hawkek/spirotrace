"""Builders for the checks tests: a record from a dict of cell texts. Synthetic only."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from spirotrace.checks import Flag, RecordContext, check_records
from spirotrace.config import default_settings
from spirotrace.layouts import Condition, ReadingCondition, build_observation
from spirotrace.model import (
    ColumnRole,
    Observation,
    ObservationKey,
    Parameter,
    ReadMethod,
    Record,
)

HASH = "ab" * 32
LAYOUT = "layout_x"
P, R = Parameter, ColumnRole

Spec = (
    tuple[Parameter, ColumnRole]
    | tuple[Parameter, ColumnRole, int]
    | tuple[Parameter, ColumnRole, int, int]
)
"""(parameter, role[, position[, page]])."""


@dataclass
class FakeRecord:
    record: Record
    observations: dict[ObservationKey, Observation] = field(default_factory=dict)
    conditions: list[ReadingCondition] = field(default_factory=list)

    def put(
        self,
        parameter: Parameter,
        role: ColumnRole,
        raw: str,
        position: int = 1,
        page: int = 1,
        *,
        parsed_text: str | None = None,
        parsed_value: float | None = None,
        conditions: Iterable[Condition] = (),
        read_method: ReadMethod = ReadMethod.TEXT_LAYER,
        unreadable: bool = False,
    ) -> Observation:
        key = ObservationKey(HASH, page, LAYOUT, parameter, role, position)
        built = build_observation(
            key,
            self.record.record_id,
            1,
            raw,
            (0.1, 0.1, 0.2, 0.12),
            read_method,
            parsed_text=parsed_text,
            parsed_value=parsed_value,
            unreadable=unreadable,
        )
        self.observations[key] = built.observation
        for c in (*conditions, *built.conditions):
            self.conditions.append(
                ReadingCondition(self.record.record_id, page, key, c.code, c.detail)
            )
        return built.observation

    def note(self, code: str, detail: str = "", page: int | None = None) -> None:
        self.conditions.append(
            ReadingCondition(self.record.record_id, page, None, code, detail)
        )


def record(
    record_id: str = "11", layout: str = LAYOUT, pages: tuple[int, ...] = (1, 2)
) -> FakeRecord:
    return FakeRecord(Record(record_id, HASH, layout, record_id.rstrip("AB"), pages))


def cells(spec: Mapping[Spec, str], record_id: str = "11") -> FakeRecord:
    """A record holding the cells of ``spec`` (raw texts, numbers parsed by the grammar)."""
    rec = record(record_id)
    for k, raw in spec.items():
        param, role = k[0], k[1]
        pos = k[2] if len(k) > 2 else 1
        page = k[3] if len(k) > 3 else 1
        rec.put(param, role, raw, pos, page)
    return rec


def run(*recs: FakeRecord, off: Iterable[str] = (), gli_results=None) -> list[Flag]:
    s = default_settings()
    if off:
        s = type(s)(
            **{
                **{f: getattr(s, f) for f in s.__slots__},
                "rules": type(s.rules)(tuple(off), ()),
            }
        )
    return check_records(list(recs), s, gli_results=gli_results).flags


def flags_of(flags: Iterable[Flag], rule_id: str) -> list[Flag]:
    return [f for f in flags if f.rule_id == rule_id]


def rule_ids(flags: Iterable[Flag]) -> set[str]:
    return {f.rule_id for f in flags}


def context(rec: FakeRecord) -> RecordContext:
    return RecordContext.of(rec)
