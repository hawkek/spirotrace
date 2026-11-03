"""The review queue: one item per flagged cell, built from the store in memory.

An item is one (record, key) with at least one open error or check flag that
names the key. It carries every open flag's rule and message, the suggestion
if a rule offered one, the cell as read, the other cells of its table row for
context, the record-level open flags as notes, and the answers already given
(this reviewer's, which hides the item unless asked for, and the other
reviewers', which are shown). ``note`` and ``confirm`` flags are never queued.

Order: core fields first, then errors before checks, then record, page and
position on the page. The core-field list is the study's, declared by the
reader module as ``CORE_FIELDS`` (pairs of parameter and column role); the
package holds no study list.
"""

from __future__ import annotations

import importlib
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from spirotrace.checks import Flag, Severity
from spirotrace.checks.rules_gli import DIFFUSION, GLI_PARAM
from spirotrace.config import Settings
from spirotrace.model import (
    ColumnRole,
    Observation,
    ObservationKey,
    Parameter,
    RatioForm,
    kind_of,
)
from spirotrace.resolve import MergedEvents
from spirotrace.store import Event, RawStore, ReadRecord

CoreField = tuple[Parameter, ColumnRole]

QUEUED_SEVERITIES: frozenset[Severity] = frozenset({Severity.ERROR, Severity.CHECK})

_GLI_VALUE_ROLES: frozenset[ColumnRole] = frozenset(
    {
        ColumnRole.MEASURED,
        ColumnRole.PRE,
        ColumnRole.POST,
        ColumnRole.LLN,
        ColumnRole.POST_LLN,
        ColumnRole.PCTPRED,
        ColumnRole.POST_PCTPRED,
        ColumnRole.PREDICTED,
        ColumnRole.Z,
        ColumnRole.POST_Z,
    }
)
_GLI_PARAMETERS: frozenset[Parameter] = frozenset(
    {*GLI_PARAM, *(p for p, _ in DIFFUSION)}
)
_DEMOGRAPHICS: frozenset[Parameter] = frozenset(
    {
        Parameter.AGE,
        Parameter.HEIGHT,
        Parameter.SEX,
        Parameter.ETHNICITY,
        Parameter.REFERENCE_SPIROMETRY,
    }
)

_RECORD_ID = re.compile(r"^(f?)([0-9a-f]+)([AB]?)(?:-([0-9]+))?$")


def is_gli_input(key: ObservationKey) -> bool:
    """Whether an answer on ``key`` can change the GLI recalculation (G2 answer 7)."""
    if key.parameter in _DEMOGRAPHICS and key.column_role is ColumnRole.MEASURED:
        return True
    return key.parameter in _GLI_PARAMETERS and key.column_role in _GLI_VALUE_ROLES


def record_sort_key(record_id: str) -> tuple[int, int, str, int]:
    """Participant numbers in numeric order, hashed ids after them."""
    m = _RECORD_ID.match(record_id)
    if m is None:
        return (2, 0, record_id, 0)
    hashed, digits, suffix, part = m.groups()
    number = int(digits, 16) if hashed else int(digits)
    return (1 if hashed else 0, number, suffix, int(part or 1))


def core_fields_of(settings: Settings) -> tuple[CoreField, ...]:
    """The reader module's ``CORE_FIELDS``; empty when it declares none.

    The caller has run ``load_reader`` (which puts ``templates.dirs`` on the
    path); here only the module is looked up, so a missing or unnamed reader
    gives an empty list and ``--core-only`` is refused with a message.
    """
    module_name = settings.templates.reader.partition(":")[0]
    if not module_name:
        return ()
    try:
        module = importlib.import_module(module_name)
    except ImportError:
        return ()
    fields = getattr(module, "CORE_FIELDS", ())
    return tuple((Parameter(p), ColumnRole(r)) for p, r in fields)


def shown_value(obs: Observation) -> str:
    """The parsed value as the reviewer should see it (the printed form of a ratio)."""
    if obs.parsed_value is not None:
        if obs.printed_form is RatioForm.PERCENT:
            return f"{obs.parsed_value * 100:g}"
        return f"{obs.parsed_value:g}"
    return obs.parsed_text or ""


def _event_json(e: Event) -> dict[str, str]:
    return {
        "reviewer": e.reviewer,
        "action": e.action,
        "value": e.value,
        "note": e.note,
    }


@dataclass(slots=True)
class QueueItem:
    """One flagged cell as the page shows it."""

    record_id: str
    key: ObservationKey
    layout: str
    page: int
    raw_text: str
    value: str
    value_state: str
    unit: str
    struck: bool
    marked: bool
    read_method: str
    second_reading: str
    flags: list[dict[str, str]]
    suggestion: str
    row: list[dict[str, str]]
    record_notes: list[str]
    core: bool
    mine: dict[str, str] | None
    others: list[dict[str, str]]
    bbox: tuple[float, float, float, float] | None
    kind: str
    template_version: int = 1
    answered: bool = field(init=False)

    def __post_init__(self) -> None:
        self.answered = self.mine is not None

    @property
    def key_string(self) -> str:
        return self.key.to_string()

    @property
    def severity(self) -> str:
        if any(f["severity"] == "error" for f in self.flags):
            return "error"
        return "check" if self.flags else "settled"

    def sort_key(self) -> tuple[Any, ...]:
        y, x = (0.0, 0.0) if self.bbox is None else (self.bbox[1], self.bbox[0])
        return (
            0 if self.core else 1,
            {"error": 0, "check": 1}.get(self.severity, 2),
            record_sort_key(self.record_id),
            self.page,
            round(y, 3),
            round(x, 3),
            self.key.display_position,
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "key": self.key_string,
            "layout": self.layout,
            "page": self.page,
            "parameter": self.key.parameter.value,
            "role": self.key.column_role.value,
            "position": self.key.display_position,
            "raw_text": self.raw_text,
            "value": self.value,
            "value_state": self.value_state,
            "unit": self.unit,
            "struck": self.struck,
            "marked": self.marked,
            "read_method": self.read_method,
            "second_reading": self.second_reading,
            "severity": self.severity,
            "flags": self.flags,
            "suggestion": self.suggestion,
            "row": self.row,
            "record_notes": self.record_notes,
            "core": self.core,
            "kind": self.kind,
            "mine": self.mine,
            "others": self.others,
            "answered": self.answered,
            "has_image": self.bbox is not None,
        }


def _row_context(rec: ReadRecord, key: ObservationKey) -> list[dict[str, str]]:
    """The other cells printed on the same table row (same parameter and position)."""
    out = []
    for k, o in rec.observations.items():
        if k == key or k.page != key.page or k.parameter is not key.parameter:
            continue
        if k.display_position != key.display_position:
            continue
        out.append(
            {"role": k.column_role.value, "raw": o.raw_text, "value": shown_value(o)}
        )
    return out


def build_queue(
    store: RawStore,
    open_flags: Mapping[str, Sequence[Flag]],
    merged: MergedEvents,
    reviewer: str,
    core_fields: Iterable[CoreField] = (),
    *,
    core_only: bool = False,
) -> list[QueueItem]:
    """The queue in order; ``open_flags`` holds each record's open flags by record id."""
    core = frozenset(core_fields)
    items: list[QueueItem] = []
    for rec in store.records:
        flags = list(open_flags.get(rec.record_id, ()))
        notes = [
            f"{f.rule_id}: {f.message}"
            for f in flags
            if f.record_level and f.severity in QUEUED_SEVERITIES
        ]
        by_key: dict[ObservationKey, list[Flag]] = {}
        for f in flags:
            if f.severity not in QUEUED_SEVERITIES:
                continue
            for k in f.keys:
                by_key.setdefault(k, []).append(f)
        # a cell this reviewer answered stays listed (hidden by default) so the
        # answer can be seen and withdrawn after its flag cleared; it then shows
        # the raw run's flags, which the answer settled
        for key in rec.observations:
            if key in by_key:
                continue
            if reviewer in merged.latest.get(key.to_string(), {}):
                by_key[key] = [
                    f
                    for f in store.flags
                    if key in f.keys and f.severity in QUEUED_SEVERITIES
                ]
        for key, key_flags in by_key.items():
            obs = rec.observations.get(key)
            if obs is None:
                continue
            is_core = (key.parameter, key.column_role) in core
            if core_only and not is_core:
                continue
            ks = key.to_string()
            answers = merged.latest.get(ks, {})
            mine = answers.get(reviewer)
            suggestion = next(
                (f.suggestion.value for f in key_flags if f.suggestion is not None), ""
            )
            items.append(
                QueueItem(
                    record_id=rec.record_id,
                    key=key,
                    layout=rec.record.layout,
                    page=key.page,
                    raw_text=obs.raw_text,
                    value=shown_value(obs),
                    value_state=obs.value_state.value,
                    unit=obs.unit or "",
                    struck=obs.struck,
                    marked=obs.marked,
                    read_method=obs.read_method.value,
                    second_reading=obs.second_reading or "",
                    flags=[
                        {
                            "rule_id": f.rule_id,
                            "severity": f.severity.value,
                            "message": f.message,
                        }
                        for f in key_flags
                    ],
                    suggestion=suggestion,
                    row=_row_context(rec, key),
                    record_notes=notes,
                    core=is_core,
                    mine=None if mine is None else _event_json(mine),
                    others=[
                        _event_json(e)
                        for r, e in sorted(answers.items())
                        if r != reviewer
                    ],
                    bbox=obs.bbox,
                    kind=kind_of(key.parameter).value,
                    template_version=obs.template_version,
                )
            )
    items.sort(key=QueueItem.sort_key)
    return items


def raw_open_flags(store: RawStore) -> dict[str, list[Flag]]:
    """The raw run's flags by record: the queue before any event is applied."""
    out: dict[str, list[Flag]] = {}
    for f in store.flags:
        out.setdefault(f.record_id, []).append(f)
    return out
