"""parse_ratio: printed FEV1/FVC, RV/TLC and FRC/TLC to a fraction with the form kept."""

import pytest

from spirotrace.model import RatioForm, RatioParseError, parse_ratio

PERCENT = RatioForm.PERCENT
FRACTION = RatioForm.FRACTION


@pytest.mark.parametrize(
    ("text", "fraction", "form"),
    [
        # the cases in the work package
        ("78", 0.78, PERCENT),
        ("78%", 0.78, PERCENT),
        ("0.78", 0.78, FRACTION),
        ("78.0", 0.78, PERCENT),
        # ambiguous inputs, decided 14 Oct: 1 is a fraction, 100 is a percent
        ("1", 1.0, FRACTION),
        ("100", 1.0, PERCENT),
        ("0.5", 0.5, FRACTION),
        ("1.0", 1.0, FRACTION),
        ("0", 0.0, FRACTION),
        # an explicit percent sign always wins, with or without a space
        ("78 %", 0.78, PERCENT),
        ("100%", 1.0, PERCENT),
        ("1%", 0.01, PERCENT),
        ("0.5%", 0.005, PERCENT),
        # magnitude rule: anything above 1 is a percent, even when implausible
        ("1.5", 0.015, PERCENT),
        ("12.3", 0.123, PERCENT),
        # surrounding whitespace is ignored
        ("  78  ", 0.78, PERCENT),
        ("\t0.78\n", 0.78, FRACTION),
    ],
)
def test_ratio_to_fraction_and_form(
    text: str, fraction: float, form: RatioForm
) -> None:
    assert parse_ratio(text) == (fraction, form)


@pytest.mark.parametrize(
    "text",
    [
        "101",
        "100.1",
        "150%",
        "-78",
        "-0.5",
        "",
        "   ",
        "abc",
        "78,5",
        "7 8",
        "78%%",
        "%",
        "1e2",
    ],
)
def test_implausible_or_non_numeric_refused(text: str) -> None:
    with pytest.raises(RatioParseError):
        parse_ratio(text)


@pytest.mark.parametrize(
    ("text", "printed"),
    [
        ("78", "0.78"),
        ("78.5", "0.785"),
        ("0.78", "0.78"),
        ("7", "0.07"),
        ("63.2", "0.632"),
    ],
)
def test_fraction_is_exactly_the_written_decimal(text: str, printed: str) -> None:
    fraction, _ = parse_ratio(text)
    assert repr(fraction) == printed
    assert fraction == float(printed)
