"""Range layer: possible and typical limits, lost decimal points, dates, grades."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator

from spirotrace.model import ColumnRole, Parameter, ValueState

from .context import RecordContext, decimals_of
from .flags import Flag, Severity, Suggestion
from .registry import rule
from .thresholds import GRADES, T, limits_for

E, C = Severity.ERROR, Severity.CHECK


@rule(
    "range.outside_possible",
    "range",
    E,
    "A value the device or physiology cannot produce is a misread",
)
def outside_possible(ctx: RecordContext) -> Iterator[Flag]:
    for (param, role, _pos), obs in sorted(ctx.by_slot.items(), key=lambda kv: kv[0]):
        lims = limits_for(param, role)
        if lims is None:
            continue
        for o in obs:
            if o.value_state is not ValueState.VALUE or o.parsed_value is None:
                continue
            x = o.parsed_value
            if not lims.hard_low <= x <= lims.hard_high:
                yield ctx.flag(
                    "range.outside_possible",
                    f"outside possible range {lims.hard_low:g} to {lims.hard_high:g}",
                    [o],
                )


@rule(
    "range.lost_decimal",
    "range",
    E,
    "A whole number outside the possible range that fits after dividing by a power of ten lost its decimal point",
)
def lost_decimal(ctx: RecordContext) -> Iterator[Flag]:
    for f in ctx.flags_of("range.outside_possible"):
        for key in f.keys:
            o = ctx.observations[key]
            if decimals_of(o) != 0 or o.parsed_value is None:
                continue
            lims = limits_for(key.parameter, key.column_role)
            if lims is None:
                continue
            for div in (10, 100, 1000):
                cand = o.parsed_value / div
                if lims.hard_low <= cand <= lims.hard_high:
                    yield ctx.flag(
                        "range.lost_decimal",
                        f"possible lost decimal point: {cand:g}?",
                        [o],
                        suggestion=Suggestion(f"{cand:g}", "lost decimal point"),
                    )
                    break


@rule(
    "range.outside_typical",
    "range",
    C,
    "A value outside adult clinical plausibility may be a shifted digit inside the hard range",
)
def outside_typical(ctx: RecordContext) -> Iterator[Flag]:
    for (param, role, _pos), obs in sorted(ctx.by_slot.items(), key=lambda kv: kv[0]):
        lims = limits_for(param, role)
        if lims is None:
            continue
        for o in obs:
            if not ctx.is_usable(o) or o.parsed_value is None:
                continue
            x = o.parsed_value
            if not lims.typical_low <= x <= lims.typical_high:
                yield ctx.flag(
                    "range.outside_typical",
                    f"unusual value (typical {lims.typical_low:g} to {lims.typical_high:g}); "
                    "double-check against scan",
                    [o],
                )


@rule(
    "range.date_implausible",
    "range",
    C,
    "A test date in the future or before the earliest plausible year is misread",
)
def date_implausible(ctx: RecordContext) -> Iterator[Flag]:
    today = dt.date.today()  # the report's local date is meant
    for o in ctx.all(Parameter.TEST_DATE, ColumnRole.MEASURED):
        if o.value_state is not ValueState.VALUE or not o.parsed_text:
            continue
        try:
            d = dt.date.fromisoformat(o.parsed_text)
        except ValueError:
            continue
        if d > today or d.year < int(T("date_earliest_year")):
            yield ctx.flag(
                "range.date_implausible",
                f"implausible date {d.isoformat()} (read day-first): check it",
                [o],
            )


@rule(
    "range.grade_vocabulary",
    "range",
    E,
    "A session-quality grade must be one of the device's grades A to F or U",
)
def grade_vocabulary(ctx: RecordContext) -> Iterator[Flag]:
    for param in (Parameter.FEV1_GRADE, Parameter.FVC_GRADE):
        for role in (ColumnRole.PRE, ColumnRole.POST):
            for o in ctx.all(param, role):
                if o.value_state is ValueState.VALUE and o.parsed_text not in GRADES:
                    yield ctx.flag(
                        "range.grade_vocabulary",
                        "not a valid quality grade (A-F or U)",
                        [o],
                    )
