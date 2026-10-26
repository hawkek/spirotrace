"""Free-text layer: what the report's own words say, checked against each other.

The checks against derived values (report pattern against the computed pattern,
the bronchodilator statement against the computed response) run after derive
and are built in phase 2.
"""

from __future__ import annotations

from collections.abc import Iterator

from spirotrace.layouts import conditions as cond
from spirotrace.model import ColumnRole, Parameter, ValueState

from .context import RecordContext
from .flags import Flag, Severity
from .registry import rule

INTERPRETATION_PARAMETERS: tuple[Parameter, ...] = (
    Parameter.INTERPRETATION_SPIROMETRY,
    Parameter.INTERPRETATION_VOLUMES,
    Parameter.INTERPRETATION_GAS_TRANSFER,
)
NORMAL = "normal"


def _categories(text: str | None) -> list[str]:
    return [c.strip() for c in (text or "").split(";") if c.strip()]


@rule(
    "free_text.interpretation_not_read",
    "free_text",
    Severity.NOTE,
    "A test named in the interpretation with no finding recognised must not pass silently",
)
def interpretation_not_read(ctx: RecordContext) -> Iterator[Flag]:
    read = {
        p
        for p in INTERPRETATION_PARAMETERS
        for o in ctx.all(p, ColumnRole.MEASURED)
        if o.value_state is ValueState.VALUE
    }
    for c in ctx.conditions_of(cond.INTERPRETATION_FINDING_NOT_RECOGNISED):
        named = c.key.parameter if c.key is not None else _parameter_named(c.detail)
        if named is not None and named in read:
            continue  # the same test has a finding elsewhere in the record
        keys = (c.key,) if c.key is not None else ()
        yield ctx.flag(
            "free_text.interpretation_not_read",
            f"interpretation names a test but no finding was recognised: {c.detail}"
            if c.detail
            else "interpretation text with no finding recognised",
            keys,
            page=c.page,
        )


def _parameter_named(detail: str) -> Parameter | None:
    try:
        return Parameter(detail)
    except ValueError:
        return None


@rule(
    "free_text.interpretation_contradiction",
    "free_text",
    Severity.CHECK,
    "Text that calls the same test normal and abnormal needs a look before its pattern is used",
)
def interpretation_contradiction(ctx: RecordContext) -> Iterator[Flag]:
    for p in INTERPRETATION_PARAMETERS:
        obs = [
            o
            for o in ctx.all(p, ColumnRole.MEASURED)
            if o.value_state is ValueState.VALUE
        ]
        cats = {c for o in obs for c in _categories(o.parsed_text)}
        if NORMAL in cats and len(cats) > 1:
            yield ctx.flag(
                "free_text.interpretation_contradiction",
                f"interpretation says normal and {', '.join(sorted(cats - {NORMAL}))} "
                f"for {p.value.removeprefix('interpretation_').replace('_', ' ')}",
                obs,
            )
