"""Build model observations from raw cell text.

The value state, the parsed value and the report's marker all come from the
token grammar; ratios in value-like roles go through the model's ratio
parser so the stored value is a fraction with the printed form kept.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from spirotrace.ingest import BBox
from spirotrace.model import (
    RATIO_PARAMETERS,
    VALUE_ROLES,
    Observation,
    ObservationKey,
    ParameterKind,
    RatioForm,
    RatioParseError,
    ReadMethod,
    ValueState,
    kind_of,
    parse_ratio,
)

from . import conditions as cond
from .conditions import Condition
from .tokens import (
    FLAG_CHAR_FIX,
    FLAG_COMMA,
    FLAG_DASH,
    FLAG_MINUS_GUESS,
    FLAG_STAR,
    FLAG_UNPARSEABLE,
    parse_date,
    parse_number,
)

_TOKEN_CONDITIONS = (
    (FLAG_CHAR_FIX, cond.OCR_CHAR_SUBSTITUTION),
    (FLAG_COMMA, cond.DECIMAL_COMMA),
    (FLAG_MINUS_GUESS, cond.MINUS_GUESSED),
    (FLAG_UNPARSEABLE, cond.NOT_A_NUMBER),
)


@dataclass(frozen=True, slots=True)
class Built:
    """An observation and the conditions its reading raised."""

    observation: Observation
    conditions: tuple[Condition, ...] = field(default_factory=tuple)


def build_observation(
    key: ObservationKey,
    record_id: str,
    template_version: int,
    raw: str,
    bbox: BBox | None,
    read_method: ReadMethod = ReadMethod.TEXT_LAYER,
    *,
    unit: str | None = None,
    not_on_page: bool = False,
    parsed_text: str | None = None,
    parsed_value: float | None = None,
) -> Built:
    """Make an observation of ``key`` from the cell text ``raw``.

    Number parameters are parsed with the token grammar (a dash gives state
    ``dash``, blank text ``empty``, anything else unparseable ``unreadable``
    with the raw text kept). Category and text parameters take ``raw`` as
    their value unless ``parsed_text`` overrides it; date parameters are
    parsed day-first to ISO. ``parsed_value`` overrides the number parsed
    from ``raw`` (a printed trial number whose raw text is the header word).
    ``not_on_page`` records a cell the layout has but this report does not
    print.
    """
    kind = kind_of(key.parameter)
    conditions: list[Condition] = []
    if not_on_page:
        obs = _make(
            key,
            record_id,
            template_version,
            "",
            None,
            None,
            unit,
            None,
            False,
            read_method,
            ValueState.NOT_ON_PAGE,
            None,
        )
        return Built(obs)
    if kind is ParameterKind.NUMBER and parsed_value is not None:
        obs = _make(
            key,
            record_id,
            template_version,
            raw,
            parsed_value,
            None,
            unit,
            None,
            False,
            read_method,
            ValueState.VALUE,
            bbox,
        )
        return Built(obs)
    if kind is ParameterKind.NUMBER:
        np = parse_number(raw)
        marked = FLAG_STAR in np.flags
        for flag, code in _TOKEN_CONDITIONS:
            if flag in np.flags:
                conditions.append(Condition(code, raw))
        if raw.strip() == "":
            state, value, form = ValueState.EMPTY, None, None
        elif FLAG_DASH in np.flags:
            state, value, form = ValueState.DASH, None, None
        elif np.value is None:
            state, value, form = ValueState.UNREADABLE, None, None
        elif key.parameter in RATIO_PARAMETERS and key.column_role in VALUE_ROLES:
            try:
                value, form = parse_ratio(np.text)
                state = ValueState.VALUE
            except RatioParseError as exc:
                conditions.append(Condition(cond.RATIO_UNPARSEABLE, str(exc)))
                state, value, form = ValueState.UNREADABLE, None, None
        else:
            state, value, form = ValueState.VALUE, np.value, None
        obs = _make(
            key,
            record_id,
            template_version,
            raw,
            value,
            None,
            None if form else unit,
            form,
            marked,
            read_method,
            state,
            bbox,
        )
        return Built(obs, tuple(conditions))
    text = parsed_text if parsed_text is not None else raw.strip()
    if kind is ParameterKind.DATE:
        d = parse_date(text)
        if raw.strip() == "":
            state, text_value = ValueState.EMPTY, None
        elif d is None:
            conditions.append(Condition(cond.DATE_NOT_PARSED, raw))
            state, text_value = ValueState.UNREADABLE, None
        else:
            state, text_value = ValueState.VALUE, d.isoformat()
    elif text == "":
        state, text_value = ValueState.EMPTY, None
    else:
        state, text_value = ValueState.VALUE, text
    obs = _make(
        key,
        record_id,
        template_version,
        raw,
        None,
        text_value,
        None,
        None,
        False,
        read_method,
        state,
        bbox,
    )
    return Built(obs, tuple(conditions))


def _make(
    key: ObservationKey,
    record_id: str,
    template_version: int,
    raw: str,
    value: float | None,
    text: str | None,
    unit: str | None,
    form: RatioForm | None,
    marked: bool,
    read_method: ReadMethod,
    state: ValueState,
    bbox: BBox | None,
) -> Observation:
    return Observation(
        key=key,
        record_id=record_id,
        template_version=template_version,
        raw_text=raw,
        parsed_value=value,
        parsed_text=text,
        unit=unit,
        printed_form=form,
        marked=marked,
        struck=False,
        bbox=None if state is ValueState.NOT_ON_PAGE else bbox,
        read_method=read_method,
        ocr_confidence=None,
        second_reading_run=False,
        second_reading=None,
        value_state=state,
    )
