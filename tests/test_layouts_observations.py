"""Raw cell text to model observations: states, ratios, markers, dates."""

import pytest

from spirotrace.layouts import build_observation
from spirotrace.layouts import conditions as cond
from spirotrace.model import (
    ColumnRole,
    ObservationKey,
    Parameter,
    RatioForm,
    ReadMethod,
    ValueState,
)

HASH = "cd" * 32
BBOX = (0.3, 0.2, 0.34, 0.21)


def key(
    param: Parameter, role: ColumnRole = ColumnRole.PRE, pos: int = 1
) -> ObservationKey:
    return ObservationKey(HASH, 1, "layout_x", param, role, pos)


def build(param: Parameter, raw: str, role: ColumnRole = ColumnRole.PRE, **kw):
    return build_observation(key(param, role), "11", 1, raw, BBOX, **kw)


def test_number_value_with_unit_and_bbox() -> None:
    b = build(Parameter.FEV1, "3.20", unit="L")
    o = b.observation
    assert o.value_state is ValueState.VALUE
    assert o.parsed_value == 3.2 and o.raw_text == "3.20" and o.unit == "L"
    assert o.bbox == BBOX and o.read_method is ReadMethod.TEXT_LAYER
    assert not o.marked and not o.struck and b.conditions == ()


@pytest.mark.parametrize(
    ("raw", "state"),
    [
        ("", ValueState.EMPTY),
        ("  ", ValueState.EMPTY),
        ("-", ValueState.DASH),
        ("–", ValueState.DASH),
    ],
)
def test_empty_and_dash_states(raw: str, state: ValueState) -> None:
    b = build(Parameter.FVC, raw, unit="L")
    o = b.observation
    assert o.value_state is state and o.parsed_value is None and o.raw_text == raw
    assert b.conditions == ()  # a printed dash is not flagged


@pytest.mark.parametrize("raw", ["~", "_", "=", "~~"])
def test_dash_read_by_ocr_as_a_variant_is_a_dash_with_a_condition(raw: str) -> None:
    b = build(Parameter.FVC, raw, unit="L")
    o = b.observation
    assert o.value_state is ValueState.DASH and o.raw_text == raw
    assert [c.code for c in b.conditions] == [cond.DASH_READ_AS_VARIANT]


def test_unparseable_number_is_unreadable_with_raw_kept() -> None:
    b = build(Parameter.FVC, "N/A", unit="L")
    assert b.observation.value_state is ValueState.UNREADABLE
    assert b.observation.raw_text == "N/A" and b.observation.parsed_value is None
    assert [c.code for c in b.conditions] == [cond.NOT_A_NUMBER]


def test_token_repairs_become_conditions() -> None:
    assert [c.code for c in build(Parameter.FEV1, "3.6B", unit="L").conditions] == [
        cond.OCR_CHAR_SUBSTITUTION
    ]
    assert [c.code for c in build(Parameter.FEV1, "2,98", unit="L").conditions] == [
        cond.DECIMAL_COMMA
    ]
    b = build(Parameter.FEV1, "~0.55", ColumnRole.Z)
    assert [c.code for c in b.conditions] == [
        cond.MINUS_GUESSED
    ] and b.observation.parsed_value == -0.55


def test_marker_sets_marked_and_keeps_the_star_in_raw() -> None:
    o = build(Parameter.FEV1, "2.98*", unit="L").observation
    assert o.marked and o.parsed_value == 2.98 and o.raw_text == "2.98*"


def test_ratio_in_a_value_role_is_a_fraction_with_printed_form() -> None:
    frac = build(Parameter.FEV1_FVC, "0.814").observation
    assert (
        frac.parsed_value == 0.814
        and frac.printed_form is RatioForm.FRACTION
        and frac.unit is None
    )
    pct = build(Parameter.RV_TLC, "35", ColumnRole.MEASURED).observation
    assert pct.parsed_value == 0.35 and pct.printed_form is RatioForm.PERCENT
    star = build(Parameter.FEV1_FVC, "74*").observation
    assert star.marked and star.parsed_value == 0.74


def test_ratio_pctpred_is_an_ordinary_number() -> None:
    o = build(Parameter.FEV1_FVC, "96", ColumnRole.PCTPRED).observation
    assert o.parsed_value == 96.0 and o.printed_form is None


def test_impossible_ratio_is_unreadable() -> None:
    b = build(Parameter.FEV1_FVC, "814")
    assert b.observation.value_state is ValueState.UNREADABLE
    assert [c.code for c in b.conditions] == [cond.RATIO_UNPARSEABLE]


def test_category_text_and_date_parameters() -> None:
    sex = build(Parameter.SEX, "Female", ColumnRole.MEASURED).observation
    assert sex.parsed_text == "Female" and sex.value_state is ValueState.VALUE
    assert (
        build(Parameter.SEX, "", ColumnRole.MEASURED).observation.value_state
        is ValueState.EMPTY
    )
    date = build(
        Parameter.TEST_DATE, "12/03/2025 10:20", ColumnRole.MEASURED
    ).observation
    assert date.parsed_text == "2025-03-12"
    bad = build(Parameter.TEST_DATE, "soon", ColumnRole.MEASURED)
    assert bad.observation.value_state is ValueState.UNREADABLE
    assert [c.code for c in bad.conditions] == [cond.DATE_NOT_PARSED]
    text = build(
        Parameter.TECHNICAL_COMMENTS,
        "  a comment ",
        ColumnRole.MEASURED,
        parsed_text="a comment",
    ).observation
    assert text.parsed_text == "a comment" and text.raw_text == "  a comment "


def test_not_on_page_has_no_text_and_no_bbox() -> None:
    o = build(Parameter.FEV1, "ignored", ColumnRole.POST, not_on_page=True).observation
    assert (
        o.value_state is ValueState.NOT_ON_PAGE and o.raw_text == "" and o.bbox is None
    )


def test_read_method_is_recorded() -> None:
    o = build(
        Parameter.FEV1, "3.20", unit="L", read_method=ReadMethod.POSITION_FALLBACK
    ).observation
    assert o.read_method is ReadMethod.POSITION_FALLBACK


def test_parsed_value_override_keeps_the_raw_header_text() -> None:
    o = build(
        Parameter.TRIAL_NUMBER, "Trial2", ColumnRole.TRIAL, parsed_value=2
    ).observation
    assert (
        o.raw_text == "Trial2"
        and o.parsed_value == 2.0
        and o.value_state is ValueState.VALUE
    )
