"""The token grammar: numbers, dashes, markers, OCR repairs, units and dates."""

import datetime as dt

import pytest

from spirotrace.layouts import (
    DASH_OCR_VARIANTS,
    DASHES,
    is_numericish,
    is_unit,
    parse_date,
    parse_number,
)


@pytest.mark.parametrize(
    ("raw", "value", "flags", "decimals"),
    [
        ("3.20", 3.2, set(), 2),
        ("97", 97.0, set(), 0),
        ("-0.21", -0.21, set(), 2),
        ("+2", 2.0, set(), 0),
        ("~0.55", -0.55, {"minus_guess"}, 2),  # minus read as ~
        ("_0.55", -0.55, {"minus_guess"}, 2),  # minus read as _
        ("−0.55", -0.55, set(), 2),  # true minus sign
        ("–0.55", -0.55, set(), 2),  # en dash as minus
        ("O.55", 0.55, {"char_fix"}, 2),  # letter O for zero
        ("3.6B", 3.68, {"char_fix"}, 2),
        ("l.05", 1.05, {"char_fix"}, 2),
        ("2,98", 2.98, {"comma"}, 2),  # decimal comma
        ("0.81*", 0.81, {"star"}, 2),  # marker attached
        ("0.81•", 0.81, {"star"}, 2),  # marker as OCR bullet
        ("78%", 78.0, set(), 0),
        ("[3.2]", 3.2, set(), 1),
        ("3.2(cid:12)", 3.2, set(), 1),  # unmapped glyph after the number
    ],
)
def test_parse_number_values(
    raw: str, value: float, flags: set[str], decimals: int
) -> None:
    np = parse_number(raw)
    assert np.value == pytest.approx(value)
    assert set(np.flags) == flags
    assert np.decimals == decimals
    assert np.text and float(np.text) == pytest.approx(value)


@pytest.mark.parametrize(
    ("raw", "flags"),
    [
        ("", {"empty"}),
        ("   ", {"empty"}),
        ("-", {"dash"}),
        ("–", {"dash"}),  # en dash
        ("—", {"dash"}),  # em dash
        ("−", {"dash"}),  # minus sign
        ("--", {"dash"}),
        ("~", {"dash", "dash_variant"}),  # OCR readings of a printed dash
        ("_", {"dash", "dash_variant"}),
        ("=", {"dash", "dash_variant"}),
        (" == ", {"dash", "dash_variant"}),
        ("6.805.60", {"unparseable"}),  # two numbers merged into one token
        ("N/A", {"unparseable"}),
        ("abc", {"unparseable"}),
    ],
)
def test_parse_number_states(raw: str, flags: set[str]) -> None:
    np = parse_number(raw)
    assert np.value is None
    assert set(np.flags) == flags
    assert np.text == ""


def test_marker_on_a_dash_is_still_a_dash() -> None:
    np = parse_number("-*")
    assert np.value is None
    assert set(np.flags) == {"dash", "star"}


def test_dash_set_covers_printed_and_ocr_forms() -> None:
    assert {"-", "–", "—", "−"} <= DASHES
    assert DASH_OCR_VARIANTS == {"~", "_", "="}


def test_dash_variant_before_digits_is_still_a_minus_sign() -> None:
    np = parse_number("~0.55")
    assert np.value == -0.55 and set(np.flags) == {"minus_guess"}
    assert parse_number("_1.2").value == -1.2


def test_marker_on_a_dash_variant() -> None:
    assert set(parse_number("~*").flags) == {"dash", "dash_variant", "star"}


@pytest.mark.parametrize(
    ("tok", "expected"),
    [
        ("3.20", True),
        ("-", True),
        ("–", True),
        ("O.55", True),
        ("~0.07", True),
        ("~", True),  # a printed dash OCR read as ~, _ or =
        ("=", True),
        ("_", True),
        ("3.6B", True),
        ("97%", True),
        ("Pre", False),
        ("[L]", False),
        ("B", False),
        ("1/3", False),
    ],
)
def test_is_numericish(tok: str, expected: bool) -> None:
    assert is_numericish(tok) is expected


@pytest.mark.parametrize(
    ("tok", "expected"),
    [
        ("[L]", True),
        ("(L]", True),
        ("[%]", True),
        (
            "[ml/(min*mmHg)]",
            False,
        ),  # inner parentheses: longer than the unit grammar allows
        ("[1]", True),  # OCR of [L]
        ("sec]", True),
        ("[3.2]", False),  # bracketed decimal is a number
        ("3.20", False),
        ("Pre", False),
    ],
)
def test_is_unit(tok: str, expected: bool) -> None:
    assert is_unit(tok) is expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("12/03/2025 10:20 AM", dt.date(2025, 3, 12)),
        ("1.2.26", dt.date(2026, 2, 1)),
        ("2025-03-12", dt.date(2025, 3, 12)),
        ("31/02/2025", None),
        ("", None),
        ("no date", None),
    ],
)
def test_parse_date_day_first(text: str, expected: dt.date | None) -> None:
    assert parse_date(text) == expected
