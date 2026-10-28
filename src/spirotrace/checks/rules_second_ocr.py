"""The second reading against the first (ocr layer, A4): agreement confirms,
disagreement is a check (a note at low Tesseract confidence), a reading where
the first was unreadable or an error is offered as a suggestion, and a failed
Tesseract call is said once per record. Nothing here changes a value.
"""

from __future__ import annotations

from collections.abc import Iterator

from spirotrace.layouts import conditions as cond
from spirotrace.layouts import parse_number
from spirotrace.model import (
    RATIO_PARAMETERS,
    VALUE_ROLES,
    Observation,
    ObservationKey,
    RatioParseError,
    ValueState,
    parse_ratio,
)

from .context import RecordContext
from .flags import Flag, Severity, Suggestion
from .registry import rule
from .thresholds import T

C, N, CONFIRM = Severity.CHECK, Severity.NOTE, Severity.CONFIRM
SOURCE = "second OCR"


def second_value(obs: Observation) -> float | None:
    """The second reading as a number (a fraction for a ratio in a value role)."""
    if not obs.second_reading_run or not obs.second_reading:
        return None
    np = parse_number(obs.second_reading)
    if np.value is None:
        return None
    if obs.key.parameter in RATIO_PARAMETERS and obs.key.column_role in VALUE_ROLES:
        try:
            return parse_ratio(np.text)[0]
        except RatioParseError:
            return None
    return np.value


def _with_second(ctx: RecordContext) -> Iterator[tuple[Observation, float]]:
    for o in ctx.observations.values():
        v2 = second_value(o)
        if v2 is not None:
            yield o, v2


def _confidence(ctx: RecordContext, key: ObservationKey) -> float | None:
    for c in ctx.conditions_of(cond.SECOND_READING_CONFIDENCE):
        if c.key == key:
            try:
                return float(c.detail)
            except ValueError:
                return None
    return None


def _agrees(o: Observation, v2: float) -> bool:
    return (
        o.value_state is ValueState.VALUE
        and o.parsed_value is not None
        and abs(o.parsed_value - v2) < 1e-9
    )


@rule(
    "ocr.second_reading_agrees",
    "ocr",
    CONFIRM,
    "Two independent readings of one cell that agree back the value",
)
def second_reading_agrees(ctx: RecordContext) -> Iterator[Flag]:
    for o, v2 in _with_second(ctx):
        if _agrees(o, v2):
            yield ctx.flag(
                "ocr.second_reading_agrees", "second OCR reads the same value", [o]
            )


@rule(
    "ocr.second_reading_suggestion",
    "ocr",
    C,
    "When the first reading was unreadable or empty, the second reading is offered, never applied",
)
def second_reading_suggestion(ctx: RecordContext) -> Iterator[Flag]:
    # the ocr layer runs before the range layer, so an out-of-range first reading is a
    # disagreement here, as in the old script, where the second reading preceded validation
    for o, _v2 in _with_second(ctx):
        if o.value_state is not ValueState.VALUE:
            assert o.second_reading is not None
            conf = _confidence(ctx, o.key)
            tail = "" if conf is None else f" (confidence {conf:.0f})"
            yield ctx.flag(
                "ocr.second_reading_suggestion",
                f"second OCR reads {o.second_reading}{tail}",
                [o],
                suggestion=Suggestion(o.second_reading, SOURCE),
            )


@rule(
    "ocr.second_reading_disagrees",
    "ocr",
    (C, N),
    "Two engines disagreeing on a cell means one of them misread it",
)
def second_reading_disagrees(ctx: RecordContext) -> Iterator[Flag]:
    for o, v2 in _with_second(ctx):
        if o.value_state is not ValueState.VALUE or _agrees(o, v2):
            continue
        conf = _confidence(ctx, o.key)
        low = conf is not None and conf < T("second_reading_confidence")
        tail = "" if conf is None else f" (confidence {conf:.0f})"
        yield ctx.flag(
            "ocr.second_reading_disagrees",
            f"second OCR reads {o.second_reading}{tail}, the first reading was {o.raw_text}",
            [o],
            severity=N if low else C,
        )


@rule(
    "ocr.second_reading_failed",
    "ocr",
    N,
    "A record whose second reading failed had nothing confirmed by it",
)
def second_reading_failed(ctx: RecordContext) -> Iterator[Flag]:
    for c in ctx.conditions_of(cond.SECOND_READING_FAILED):
        yield ctx.flag(
            "ocr.second_reading_failed",
            f"second OCR failed on this record ({c.detail}); its cells were not re-read"
            if c.detail
            else "second OCR failed on this record; its cells were not re-read",
            page=c.page,
        )
