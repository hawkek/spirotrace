"""Cohort layer: what one record cannot know; needs every record of the run."""

from __future__ import annotations

import statistics
from collections import defaultdict
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field

from spirotrace.model import ColumnRole, Parameter, ValueState

from .context import RecordContext, Slot
from .flags import Flag, Severity
from .registry import rule
from .thresholds import T

EXCLUDED_ROLES: frozenset[ColumnRole] = frozenset({ColumnRole.FREE_TEXT})
EXCLUDED_PARAMETERS: frozenset[Parameter] = frozenset(
    {
        Parameter.SESSION_QUALITY,
        Parameter.FEV1_GRADE,
        Parameter.FVC_GRADE,
        Parameter.FEV1_VARIABILITY,
        Parameter.FVC_VARIABILITY,
        Parameter.FEV1_VARIABILITY_PCT,
        Parameter.FVC_VARIABILITY_PCT,
        Parameter.TRIAL_NUMBER,
    }
)
"""v0.3.14 left free-text and session-quality values out of the cohort statistics."""


@dataclass(slots=True)
class CohortStats:
    """Per-layout slot statistics computed once over all records."""

    empty_by_format: dict[str, frozenset[Slot]] = field(default_factory=dict)
    median_mad: dict[Slot, tuple[float, float]] = field(default_factory=dict)

    @classmethod
    def of(cls, contexts: Sequence[RecordContext]) -> CohortStats:
        # empty share per layout and slot
        counts: dict[tuple[str, Slot], list[int]] = defaultdict(lambda: [0, 0])
        records_per_layout: dict[str, int] = defaultdict(int)
        values: dict[Slot, list[float]] = defaultdict(list)
        for ctx in contexts:
            records_per_layout[ctx.layout] += 1
            for slot, obs in ctx.by_slot.items():
                o = obs[0]
                c = counts[(ctx.layout, slot)]
                c[1] += 1
                if o.value_state is ValueState.EMPTY:
                    c[0] += 1
                param, role, _ = slot
                if role in EXCLUDED_ROLES or param in EXCLUDED_PARAMETERS:
                    continue
                for ob in obs:
                    if ctx.is_usable(ob) and ob.parsed_value is not None:
                        values[slot].append(ob.parsed_value)
        empty: dict[str, set[Slot]] = defaultdict(set)
        for (layout, slot), (n_empty, n) in counts.items():
            if (
                records_per_layout[layout] >= T("column_empty_min_records")
                and n >= T("column_empty_min_records")
                and n_empty / n >= T("column_empty_share")
            ):
                empty[layout].add(slot)
        stats = cls(empty_by_format={k: frozenset(v) for k, v in empty.items()})
        for slot, xs in values.items():
            if len(xs) < T("cohort_min_values"):
                continue
            med = statistics.median(xs)
            mad = statistics.median(abs(x - med) for x in xs)
            if mad > 0:
                stats.median_mad[slot] = (med, mad)
        return stats


@rule(
    "cohort.robust_z",
    "cohort",
    Severity.CHECK,
    "A value far from the cohort on a robust scale is a shifted digit inside the plausible range",
    scope="cohort",
)
def robust_z(ctx: RecordContext, stats: CohortStats) -> Iterator[Flag]:
    thresh = T("cohort_robust_z")
    for slot, (med, mad) in sorted(stats.median_mad.items()):
        for o in ctx.by_slot.get(slot, []):
            if not ctx.is_usable(o) or o.parsed_value is None:
                continue
            rz = 0.6745 * (o.parsed_value - med) / mad
            if abs(rz) > thresh:
                yield ctx.flag(
                    "cohort.robust_z",
                    f"cohort outlier (robust z {rz:+.1f}; cohort median {med:g})",
                    [o],
                )
