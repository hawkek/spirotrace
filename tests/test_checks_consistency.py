"""Consistency layer: fire and no-fire cases per rule, synthetic numbers only."""

from __future__ import annotations

from checks_helpers import P, R, cells, flags_of, record, run

from spirotrace.checks import Severity


def _only(flags, rule_id, n=1):
    f = flags_of(flags, rule_id)
    assert len(f) == n, [x.message for x in flags]
    return f[0]


def test_bmi() -> None:
    ok = cells(
        {
            (P.HEIGHT, R.MEASURED): "172.5",
            (P.WEIGHT, R.MEASURED): "70.0",
            (P.BMI, R.MEASURED): "23.5",
        }
    )
    assert not flags_of(run(ok), "consistency.bmi")
    bad = cells(
        {
            (P.HEIGHT, R.MEASURED): "172.5",
            (P.WEIGHT, R.MEASURED): "70.0",
            (P.BMI, R.MEASURED): "28.5",
        }
    )
    f = _only(run(bad), "consistency.bmi")
    assert f.severity is Severity.ERROR and len(f.keys) == 3


def test_header_across_pages_error_for_numbers_check_for_text() -> None:
    rec = record()
    rec.put(P.AGE, R.MEASURED, "54", page=1)
    rec.put(P.AGE, R.MEASURED, "45", page=2)
    rec.put(P.SEX, R.MEASURED, "Female", page=1)
    rec.put(P.SEX, R.MEASURED, "Male", page=2)
    rec.put(P.HEIGHT, R.MEASURED, "170", page=1)
    rec.put(P.HEIGHT, R.MEASURED, "170", page=2)
    rec.put(
        P.INTERPRETATION_SPIROMETRY,
        R.MEASURED,
        "Spirometry is normal.",
        page=1,
        parsed_text="normal",
    )
    rec.put(
        P.INTERPRETATION_SPIROMETRY,
        R.MEASURED,
        "Obstruction.",
        page=2,
        parsed_text="obstructive",
    )
    f = flags_of(run(rec), "consistency.header_across_pages")
    sev = {x.keys[0].parameter: x.severity for x in f}
    assert sev == {P.AGE: Severity.ERROR, P.SEX: Severity.CHECK}


def test_fev1_not_above_fvc_in_summary_and_trials() -> None:
    rec = cells(
        {
            (P.FEV1, R.PRE): "4.60",
            (P.FVC, R.PRE): "4.50",
            (P.FEV1, R.TRIAL, 2): "4.60",
            (P.FVC, R.TRIAL, 2): "4.50",
            (P.FEV1, R.TRIAL, 3): "3.60",
            (P.FVC, R.TRIAL, 3): "4.50",
        }
    )
    flags = run(rec)
    _only(flags, "consistency.fev1_not_above_fvc")
    _only(flags, "consistency.trial_fev1_not_above_fvc")


def test_volume_order_and_sums() -> None:
    rec = cells(
        {
            (P.TLC, R.MEASURED): "6.00",
            (P.RV, R.MEASURED): "2.00",
            (P.FRC, R.MEASURED): "3.00",
            (P.ERV, R.MEASURED): "1.00",
            (P.IC, R.MEASURED): "3.00",
            (P.VC_MAX, R.MEASURED): "4.00",
        }
    )
    flags = run(rec)
    assert not flags_of(flags, "consistency.volume_order")
    assert not flags_of(flags, "consistency.volume_sums")
    bad = cells(
        {
            (P.TLC, R.MEASURED): "6.00",
            (P.RV, R.MEASURED): "6.50",
            (P.IC, R.MEASURED): "3.50",
            (P.VC_MAX, R.MEASURED): "3.40",
        }
    )
    order = flags_of(run(bad), "consistency.volume_order")
    assert {f.severity for f in order} == {
        Severity.ERROR,
        Severity.CHECK,
    }  # RV above TLC; IC above its capacity
    sums = cells(
        {
            (P.TLC, R.MEASURED): "6.00",
            (P.FRC, R.MEASURED): "3.00",
            (P.IC, R.MEASURED): "3.50",
            (P.VC_MAX, R.MEASURED): "4.00",
        }
    )
    _only(run(sums), "consistency.volume_sums")  # FRC + IC = 6.5, not 6.0


def test_ratio_matches_values_error_for_fraction_check_for_percent() -> None:
    dev = cells(
        {(P.FEV1, R.PRE): "3.85", (P.FVC, R.PRE): "4.50", (P.FEV1_FVC, R.PRE): "0.756"}
    )
    f = _only(run(dev), "consistency.ratio_matches_values")
    assert f.severity is Severity.ERROR and len(f.keys) == 3
    lab = cells(
        {(P.FEV1, R.PRE): "3.85", (P.FVC, R.PRE): "4.50", (P.FEV1_FVC, R.PRE): "76"}
    )
    assert (
        _only(run(lab), "consistency.ratio_matches_values").severity is Severity.CHECK
    )
    ok = cells(
        {(P.FEV1, R.PRE): "3.85", (P.FVC, R.PRE): "4.50", (P.FEV1_FVC, R.PRE): "86"}
    )
    assert not flags_of(run(ok), "consistency.ratio_matches_values")


def test_volume_ratios_and_kco() -> None:
    ok = cells(
        {
            (P.RV, R.MEASURED): "2.00",
            (P.TLC, R.MEASURED): "6.00",
            (P.RV_TLC, R.MEASURED): "33",
            (P.DLCO, R.MEASURED): "25.0",
            (P.VA, R.MEASURED): "5.00",
            (P.KCO, R.MEASURED): "5.00",
        }
    )
    flags = run(ok)
    assert not flags_of(flags, "consistency.ratio_matches_values")
    assert not flags_of(flags, "consistency.kco_matches")
    bad = cells(
        {
            (P.RV, R.MEASURED): "2.00",
            (P.TLC, R.MEASURED): "6.00",
            (P.RV_TLC, R.MEASURED): "43",
            (P.DLCO, R.MEASURED): "25.0",
            (P.VA, R.MEASURED): "5.00",
            (P.KCO, R.MEASURED): "6.00",
        }
    )
    flags = run(bad)
    assert _only(flags, "consistency.ratio_matches_values").severity is Severity.ERROR
    _only(flags, "consistency.kco_matches")


def test_pctpred_pred_lln_uln_rules() -> None:
    rec = cells(
        {
            (P.TLC, R.MEASURED): "6.00",
            (P.TLC, R.PREDICTED): "6.00",
            (P.TLC, R.PCTPRED): "110",
            (P.TLC, R.LLN): "6.10",
            (P.TLC, R.ULN): "7.00",
            (P.TLC, R.Z): "-0.50",
        }
    )
    flags = run(rec)
    _only(flags, "consistency.pctpred_matches_pred")
    _only(flags, "consistency.lln_pred_uln_order")
    _only(flags, "consistency.pctpred_sign_vs_z")  # 110% with z -0.5
    assert not flags_of(flags, "consistency.pred_sign_vs_z")  # value == predicted


def test_lln_vs_z_and_pred_sign() -> None:
    rec = cells(
        {(P.FEV1, R.PRE): "2.00", (P.FEV1, R.LLN): "2.50", (P.FEV1, R.Z): "-1.00"}
    )
    f = _only(run(rec), "consistency.lln_vs_z")
    assert "below LLN" in f.message and f.severity is Severity.ERROR
    ok = cells(
        {(P.FEV1, R.PRE): "2.00", (P.FEV1, R.LLN): "2.50", (P.FEV1, R.Z): "-2.40"}
    )
    assert not flags_of(run(ok), "consistency.lln_vs_z")
    lab = cells(
        {(P.RV, R.MEASURED): "3.00", (P.RV, R.PREDICTED): "2.00", (P.RV, R.Z): "-1.00"}
    )
    _only(run(lab), "consistency.pred_sign_vs_z")


def test_post_pre_ratio_and_bdr_column() -> None:
    rec = cells(
        {
            (P.FEV1, R.PRE): "2.00",
            (P.FEV1, R.POST): "2.40",
            (P.FEV1, R.PCTPRED): "60",
            (P.FEV1, R.POST_PCTPRED): "72",
            (P.FEV1, R.BDR): "12",
        }
    )
    flags = run(rec)
    assert not flags_of(flags, "consistency.post_pre_ratio")
    assert not flags_of(flags, "consistency.bdr_column")  # 12 = change in %pred
    bad = cells(
        {
            (P.FEV1, R.PRE): "2.00",
            (P.FEV1, R.POST): "2.40",
            (P.FEV1, R.PCTPRED): "60",
            (P.FEV1, R.POST_PCTPRED): "90",
            (P.FEV1, R.BDR): "5",
        }
    )
    flags = run(bad)
    _only(flags, "consistency.post_pre_ratio")
    _only(flags, "consistency.bdr_column")


def test_best_among_trials_and_summary_equals_trial_best() -> None:
    rec = cells(
        {
            (P.FEV1, R.PRE): "3.85",
            (P.FEV1, R.TRIAL, 1): "3.80",
            (P.FEV1, R.TRIAL, 2): "3.70",
            (P.FEV1, R.TRIAL, 3): "3.60",
            (P.FVC, R.TRIAL, 1): "4.50",
            (P.FVC, R.TRIAL, 2): "4.50",
        }
    )
    flags = run(rec)
    _only(flags, "consistency.best_among_trials")  # 3.80 is no trial's value
    _only(flags, "consistency.summary_equals_trial_best")  # 3.85 vs 3.80


def test_session_quality_rules() -> None:
    rec = record()
    rec.put(P.FEV1_GRADE, R.PRE, "A", parsed_text="A")
    rec.put(P.FEV1_VARIABILITY, R.PRE, "0.180")
    rec.put(P.FEV1_VARIABILITY_PCT, R.PRE, "2.0")
    rec.put(P.FEV1, R.TRIAL, "3.60", 1)
    rec.put(P.FEV1_GRADE, R.FREE_TEXT, "B", parsed_text="B")
    rec.put(P.BEV, R.TRIAL, "0.20", 2)
    rec.put(P.FVC, R.TRIAL, "3.00", 2)
    flags = run(rec)
    _only(flags, "consistency.grade_vs_variability")
    _only(flags, "consistency.variability_pct")  # 0.18 / 3.6 = 5%, not 2%
    _only(flags, "consistency.grade_sources_disagree")
    assert _only(flags, "consistency.bev_acceptability").severity is Severity.NOTE


def test_dlcoc_band_and_direction() -> None:
    rec = record()
    rec.put(P.SEX, R.MEASURED, "Female")
    rec.put(P.HAEMOGLOBIN, R.MEASURED, "11.0")  # below 13.4: DLCOc should be above DLCO
    rec.put(P.DLCO, R.MEASURED, "25.0")
    rec.put(P.DLCOC, R.MEASURED, "23.0")
    flags = run(rec)
    _only(flags, "consistency.dlcoc_direction")
    assert not flags_of(flags, "consistency.dlcoc_band")
    rec2 = record()
    rec2.put(P.DLCO, R.MEASURED, "25.0")
    rec2.put(P.DLCOC, R.MEASURED, "15.0")
    flags = run(rec2)
    _only(flags, "consistency.dlcoc_band")
    assert not flags_of(flags, "consistency.dlcoc_direction")  # no Hb read: not run


def test_trend_page_portable_confirms_or_suggests() -> None:
    rec = record()
    rec.put(P.TEST_DATE, R.MEASURED, "12/05/2024")
    rec.put(P.TEST_DATE, R.TREND, "12/05/2024", 1, page=3)
    rec.put(P.TEST_DATE, R.TREND, "01/02/2023", 2, page=3)
    rec.put(P.FEV1, R.PRE, "3.85")
    rec.put(P.FEV1, R.TREND, "3.85", 1, page=3)
    rec.put(P.FEV1, R.TREND_Z, "-0.10", 1, page=3)
    rec.put(P.FEV1, R.Z, "-0.20")
    rec.put(P.FEV1, R.TREND, "3.50", 2, page=3)
    flags = flags_of(run(rec), "consistency.trend_page_portable")
    sev = {f.keys[0].column_role: f.severity for f in flags}
    assert sev == {R.PRE: Severity.CONFIRM, R.Z: Severity.CHECK}
    check = next(f for f in flags if f.severity is Severity.CHECK)
    assert check.suggestion is not None and check.suggestion.value == "-0.1"


def test_trend_row_lab_is_an_error() -> None:
    rec = record()
    rec.put(P.TEST_DATE, R.MEASURED, "12/05/2024")
    rec.put(P.TEST_DATE, R.TREND, "12/05/2024", 1, page=3)
    rec.put(P.TLC, R.MEASURED, "6.00")
    rec.put(P.TLC, R.TREND, "6.20", 1, page=3)
    rec.put(P.FEV1, R.PRE, "3.85")
    rec.put(P.FEV1, R.TREND, "3.85", 1, page=3)
    flags = run(rec)
    f = _only(flags, "consistency.trend_row_lab")
    assert f.severity is Severity.ERROR and f.keys[0].parameter is P.TLC
    assert not flags_of(flags, "consistency.trend_page_portable")
