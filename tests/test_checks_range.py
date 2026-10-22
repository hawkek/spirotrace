"""Range layer: possible and typical limits, lost decimals, dates, grades."""

from __future__ import annotations

import datetime as dt

from checks_helpers import P, R, cells, flags_of, record, run

from spirotrace.checks import Severity


def test_outside_possible_is_an_error_and_excludes_the_value_from_cross_checks() -> (
    None
):
    rec = cells({(P.FEV1, R.PRE): "38.0", (P.FVC, R.PRE): "4.50"})
    flags = run(rec)
    f = flags_of(flags, "range.outside_possible")
    assert (
        len(f) == 1
        and f[0].severity is Severity.ERROR
        and f[0].keys[0].parameter is P.FEV1
    )
    assert not flags_of(
        flags, "consistency.fev1_not_above_fvc"
    )  # 38 > 4.5 but excluded


def test_lost_decimal_carries_a_suggestion() -> None:
    rec = cells({(P.FEV1, R.PRE): "366"})
    f = flags_of(run(rec), "range.lost_decimal")
    assert len(f) == 1 and f[0].suggestion is not None
    assert f[0].suggestion.value == "3.66" and "3.66?" in f[0].message
    assert not flags_of(run(cells({(P.FEV1, R.PRE): "36.6"})), "range.lost_decimal")


def test_typical_limits_are_checks() -> None:
    rec = cells(
        {(P.FEV1, R.PRE): "0.30", (P.FVC, R.PRE): "4.50", (P.FEV1, R.PCTPRED): "160"}
    )
    f = flags_of(run(rec), "range.outside_typical")
    assert {k.parameter for fl in f for k in fl.keys} == {P.FEV1}
    assert len(f) == 2 and all(fl.severity is Severity.CHECK for fl in f)


def test_second_z_column_is_checked_against_z_limits_not_ratio_limits() -> None:
    # README 0.3.15: v0.3.14 checked spiro_*_z2 against the ratio's limits
    rec = cells({(P.FEV1_FVC, R.Z, 1): "-1.20", (P.FEV1_FVC, R.Z, 2): "-1.35"})
    flags = run(rec)
    assert not flags_of(flags, "range.outside_possible")
    assert not flags_of(flags, "range.outside_typical")


def test_ratios_are_limited_as_fractions_whatever_the_printed_form() -> None:
    assert not flags_of(
        run(cells({(P.FEV1_FVC, R.PRE): "74"})), "range.outside_possible"
    )
    assert flags_of(
        run(cells({(P.RV_TLC, R.MEASURED): "0.95"})), "range.outside_possible"
    )


def test_trend_values_are_not_range_checked() -> None:
    rec = cells({(P.FEV1, R.TREND, 1): "38.0"})
    assert not flags_of(run(rec), "range.outside_possible")


def test_dates_in_the_future_or_before_1990_are_checks() -> None:
    future = (dt.date.today() + dt.timedelta(days=400)).strftime("%d/%m/%Y")
    rec = record()
    rec.put(P.TEST_DATE, R.MEASURED, future)
    rec.put(P.TEST_DATE, R.MEASURED, "12/05/1985", page=2)
    f = flags_of(run(rec), "range.date_implausible")
    assert len(f) == 2
    ok = record()
    ok.put(P.TEST_DATE, R.MEASURED, "12/05/2024")
    assert not flags_of(run(ok), "range.date_implausible")


def test_grade_vocabulary() -> None:
    rec = record()
    rec.put(P.FEV1_GRADE, R.PRE, "A", parsed_text="A")
    rec.put(P.FVC_GRADE, R.PRE, "Q", parsed_text="Q")
    rec.put(
        P.FEV1_GRADE, R.FREE_TEXT, "Q", parsed_text="Q"
    )  # comments grades are not graded
    f = flags_of(run(rec), "range.grade_vocabulary")
    assert (
        len(f) == 1
        and f[0].keys[0].parameter is P.FVC_GRADE
        and f[0].severity is Severity.ERROR
    )
