"""What a rule sees: one record's observations and reading conditions, indexed,
with the helpers the old validation used (usable values, rounding half-units).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from spirotrace.layouts import ReadingCondition, parse_number
from spirotrace.model import (
    ColumnRole,
    Observation,
    ObservationKey,
    Parameter,
    RatioForm,
    Record,
    ValueState,
)

from .flags import Flag, Severity, Suggestion
from .registry import RULES, check_flag


class RecordInput(Protocol):
    """What the runner needs from a read record (the private readers' RecordRead)."""

    @property
    def record(self) -> Record: ...
    @property
    def observations(self) -> Mapping[ObservationKey, Observation]: ...
    @property
    def conditions(self) -> Sequence[ReadingCondition]: ...


Slot = tuple[Parameter, ColumnRole, int]


def decimals_of(obs: Observation) -> int | None:
    """Printed decimal places of a numeric observation (as a fraction for a ratio
    printed as a percent: ``74`` percent is ``0.74``)."""
    if obs.value_state is not ValueState.VALUE or obs.parsed_value is None:
        return None
    d = parse_number(obs.raw_text).decimals
    if d is None:
        return None
    if obs.printed_form is RatioForm.PERCENT:
        d += 2
    return d


def half_unit(obs: Observation) -> float:
    """Half of the last printed digit: the rounding interval of the printed value."""
    d = decimals_of(obs)
    return 0.5 * 10 ** -(d if d is not None else 2)


@dataclass(slots=True)
class RecordContext:
    """One record for the per-record rules."""

    record: Record
    observations: dict[ObservationKey, Observation]
    conditions: tuple[ReadingCondition, ...]
    by_slot: dict[Slot, list[Observation]] = field(default_factory=dict)
    errors: set[ObservationKey] = field(default_factory=set)
    """Keys the ocr or range layer flagged as an error (not a number, outside the
    possible range): excluded from the cross-checks, as the old script's ``bad``
    values were. A cross-check error does not exclude a value from other
    cross-checks (the old script kept such values in play)."""
    error_keys: set[ObservationKey] = field(default_factory=set)
    """Keys of every error flag so far; the gli rules skip them all."""
    flags: list[Flag] = field(default_factory=list)
    empty_by_format: frozenset[Slot] = frozenset()
    """Slots the cohort found empty in nearly every record of this layout (the
    report's format, not an OCR drop); set by the runner before the rules."""
    blank_on_scan: frozenset[ObservationKey] = frozenset()
    """Keys of empty cells the image stage found blank on the scan (nothing was
    dropped); set by the runner when ``image.empty_cell_blank`` is enabled."""

    @classmethod
    def of(cls, rec: RecordInput) -> RecordContext:
        by_slot: dict[Slot, list[Observation]] = defaultdict(list)
        for k, o in rec.observations.items():
            by_slot[(k.parameter, k.column_role, k.display_position)].append(o)
        for lst in by_slot.values():
            lst.sort(key=lambda o: o.key.page)  # the first page's reading comes first
        return cls(
            rec.record,
            dict(rec.observations),
            tuple(rec.conditions),
            dict(by_slot),
        )

    @property
    def record_id(self) -> str:
        return self.record.record_id

    @property
    def layout(self) -> str:
        return self.record.layout

    # --- lookups --------------------------------------------------------------

    def all(
        self, parameter: Parameter, role: ColumnRole, position: int = 1
    ) -> list[Observation]:
        return self.by_slot.get((parameter, role, position), [])

    def get(
        self, parameter: Parameter, role: ColumnRole, position: int = 1
    ) -> Observation | None:
        """The first page's observation of a slot, or None."""
        lst = self.all(parameter, role, position)
        return lst[0] if lst else None

    def usable(
        self, parameter: Parameter, role: ColumnRole, position: int = 1
    ) -> Observation | None:
        """A numeric value not flagged as an error so far, else None."""
        o = self.get(parameter, role, position)
        return o if self.is_usable(o) else None

    def is_usable(self, o: Observation | None) -> bool:
        return (
            o is not None
            and o.value_state is ValueState.VALUE
            and o.parsed_value is not None
            and o.key not in self.errors
        )

    def usable_unflagged(
        self, parameter: Parameter, role: ColumnRole, position: int = 1
    ) -> Observation | None:
        """A usable value carrying no error flag of any layer (the gli inputs)."""
        o = self.usable(parameter, role, position)
        return None if o is None or o.key in self.error_keys else o

    def value(
        self, parameter: Parameter, role: ColumnRole, position: int = 1
    ) -> float | None:
        o = self.usable(parameter, role, position)
        return None if o is None else o.parsed_value

    def text(
        self, parameter: Parameter, role: ColumnRole, position: int = 1
    ) -> str | None:
        o = self.get(parameter, role, position)
        if o is None or o.value_state is not ValueState.VALUE:
            return None
        return o.parsed_text

    def positions(self, parameter: Parameter, role: ColumnRole) -> list[int]:
        return sorted(
            pos for (p, r, pos) in self.by_slot if p is parameter and r is role
        )

    def has_role(self, role: ColumnRole) -> bool:
        return any(r is role for (_, r, _) in self.by_slot)

    def conditions_of(self, code: str) -> list[ReadingCondition]:
        return [c for c in self.conditions if c.code == code]

    # --- flags ----------------------------------------------------------------

    def flag(
        self,
        rule_id: str,
        message: str,
        keys: Iterable[Observation | ObservationKey] = (),
        *,
        severity: Severity | None = None,
        page: int | None = None,
        suggestion: Suggestion | None = None,
    ) -> Flag:
        """Build a flag of ``rule_id`` on ``keys`` (observations or keys)."""
        r = RULES[rule_id]
        ks = tuple(k.key if isinstance(k, Observation) else k for k in keys)
        if page is None and ks:
            page = ks[0].page
        f = Flag(
            r.id,
            r.layer,
            r.severity if severity is None else severity,
            self.record_id,
            ks,
            page,
            message,
            suggestion,
        )
        return check_flag(f)

    def add(self, f: Flag) -> None:
        self.flags.append(f)
        if f.severity is Severity.ERROR:
            self.error_keys.update(f.keys)
            if f.layer in ("ocr", "range"):
                self.errors.update(f.keys)

    def flags_of(self, rule_id: str) -> list[Flag]:
        return [f for f in self.flags if f.rule_id == rule_id]
