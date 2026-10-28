"""derive: the ATS/ERS 2022 pattern, PRISm, severity, BDR, the report's pattern,
grades, the GLI point recalculation on a fixture, and the post-derive rules.
Synthetic records; hand-calculated expectations."""

from __future__ import annotations

import pytest
from checks_helpers import P, R, cells, run

from spirotrace.config import default_settings
from spirotrace.derive import (
    derive_records,
    pattern_from_flags,
    pattern_from_text,
    severity_of,
)
from spirotrace.model import ObservationKey
from spirotrace.resolve import merge_events, resolve_records
from spirotrace.rspiro import GliRange
from spirotrace.store import Event, RawStore, ReadRecord

HASH = "ab" * 32


def derive(spec: dict, events: list[Event] = (), gli_results=None, record_id="11"):
    rec = cells(spec, record_id)
    store = RawStore(
        records=[ReadRecord(rec.record, dict(rec.observations), list(rec.conditions))],
        flags=run(rec),
    )
    res = resolve_records(store, merge_events(list(events)), default_settings())
    return derive_records(res, default_settings(), gli_results=gli_results), res


def by_name(run_):
    return {r.name: r for r in run_.rows}


# --- the flowchart ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("obs", "fvc", "tlc", "expected"),
    [
        (False, False, None, "normal"),
        (True, False, None, "obstruction"),
        (True, True, None, "obstruction, possible mixed"),
        (False, True, None, "possible restriction"),
        (True, True, True, "mixed"),
        (True, False, False, "obstruction"),
        (False, True, False, "non-specific"),
        (False, False, True, "restriction"),
        (False, True, True, "restriction"),
        (None, False, None, None),
        (False, None, None, None),
        (True, None, True, "mixed"),
        (True, None, False, "obstruction"),
        (False, None, True, "restriction"),
        (False, None, False, None),
    ],
)
def test_pattern_from_flags(obs, fvc, tlc, expected) -> None:
    assert pattern_from_flags(obs, fvc, tlc) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (None, None),
        ("", None),
        ("mixed obstructive and restrictive", "mixed"),
        ("obstructive", "obstructive"),
        ("restrictive", "restrictive"),
        ("non-specific", "nonspecific"),
        ("preserved ratio impaired spirometry", "nonspecific"),
        ("normal", "normal"),
        ("unusual", "other"),
    ],
)
def test_pattern_from_text(text, expected) -> None:
    assert pattern_from_text(text) == expected


@pytest.mark.parametrize(
    ("z", "expected"),
    [
        (None, None),
        (0.2, "within normal limits"),
        (-1.645, "within normal limits"),
        (-1.65, "mild"),
        (-2.5, "mild"),
        (-2.51, "moderate"),
        (-4.0, "moderate"),
        (-4.01, "severe"),
    ],
)
def test_severity_bands(z, expected) -> None:
    assert severity_of(z) == expected


# --- rows from a record ------------------------------------------------------------

NORMAL = {
    (P.FEV1, R.PRE): "3.05",
    (P.FVC, R.PRE): "3.70",
    (P.FEV1_FVC, R.PRE): "0.824",
    (P.FEV1, R.Z): "-0.50",
    (P.FVC, R.Z): "-0.30",
    (P.FEV1_FVC, R.Z): "-0.10",
}


def test_normal_record_from_z() -> None:
    d = by_name(derive(NORMAL)[0])
    assert d["pattern"].value == "normal" and d["pattern"].basis == "ratio:z fvc:z tlc:"
    assert d["prism"].value == "no"
    assert d["fev1_severity"].value == "within normal limits"
    assert d["ratio_below_lln"].value == "no" and d["ratio_below_lln"].basis == "z"
    assert d["pattern"].status == "computed"
    assert {k.parameter for k in d["pattern"].inputs} == {P.FEV1_FVC, P.FVC}
    assert all(s == "accepted_unflagged" for s in d["pattern"].input_statuses)
    assert "tlc_below_lln" not in d  # no TLC on this layout
    assert "bdr_positive_2022" not in d  # no post values


def test_lln_used_when_z_missing_and_prism() -> None:
    spec = {
        (P.FEV1, R.PRE): "2.00",
        (P.FEV1, R.LLN): "2.60",
        (P.FVC, R.PRE): "3.70",
        (P.FVC, R.LLN): "3.00",
        (P.FEV1_FVC, R.PRE): "0.54",
        (P.FEV1_FVC, R.LLN): "0.70",
    }
    d = by_name(derive(spec)[0])
    assert d["ratio_below_lln"].value == "yes" and d["ratio_below_lln"].basis == "lln"
    assert d["pattern"].value == "obstruction"
    spec2 = {
        **spec,
        (P.FVC, R.PRE): "2.50",
        (P.FVC, R.LLN): "2.40",
        (P.FEV1_FVC, R.PRE): "0.80",
    }
    d2 = by_name(derive(spec2)[0])
    assert d2["pattern"].value == "normal" and d2["prism"].value == "yes"


def test_lab_record_uses_tlc() -> None:
    spec = {
        **NORMAL,
        (P.FVC, R.Z): "-2.0",
        (P.TLC, R.MEASURED): "4.0",
        (P.TLC, R.Z): "-2.1",
    }
    d = by_name(derive(spec)[0])
    assert d["tlc_below_lln"].value == "yes"
    assert d["pattern"].value == "restriction"
    assert d["pattern"].basis == "ratio:z fvc:z tlc:z"


def test_pattern_not_computed_when_inputs_flagged() -> None:
    spec = {**NORMAL, (P.FEV1_FVC, R.Z): "x"}  # not a number: an open error
    run_, _ = derive(spec)
    d = by_name(run_)
    assert d["pattern"].value == "" and d["pattern"].status == "not computed"
    assert any(f.rule_id == "derived.pattern_not_computed" for f in run_.flags)


def test_derive_skips_unreadable_excluded_and_disputed_inputs() -> None:
    k = ObservationKey(HASH, 1, "layout_x", P.FEV1_FVC, R.Z, 1)

    def ev(seq, action, value="", reviewer="KH"):
        return Event(
            f"{seq:032x}",
            seq,
            f"2026-11-02T10:{seq:02d}:00+13:00",
            reviewer,
            "11",
            k.to_string(),
            action,
            value,
            note="n" if action == "exclude" else "",
        )

    for events in (
        [ev(1, "not_readable")],
        [ev(1, "exclude")],
        [ev(1, "typed", "-0.1"), ev(2, "typed", "-2.5", reviewer="AB")],
    ):
        d = by_name(derive(NORMAL, events)[0])
        assert d["pattern"].value == ""


def test_open_checks_pass_and_are_recorded() -> None:
    # an FVC z outside the typical range is a check on the z, a pattern input
    spec = {**NORMAL, (P.FVC, R.Z): "3.5"}
    d = by_name(derive(spec)[0])
    assert d["pattern"].value == "normal"
    assert "check" in d["pattern"].input_open_severities


# --- BDR ---------------------------------------------------------------------------

POST = {
    **NORMAL,
    (P.FEV1, R.PCTPRED): "80",
    (P.FEV1, R.POST): "3.40",
    (P.FEV1, R.POST_PCTPRED): "89",
    (P.FVC, R.PCTPRED): "85",
    (P.FVC, R.POST): "3.80",
    (P.FVC, R.POST_PCTPRED): "87",
}


def test_bdr_from_pctpred_change() -> None:
    d = by_name(derive(POST)[0])
    assert d["bdr_fev1_pct_pred"].value == "9" and d["bdr_fvc_pct_pred"].value == "2"
    assert d["bdr_positive_2022"].value == "no"
    # 3.05 -> 3.40 is +0.35 L and +11.5 %: 2005 needs >= 12 %
    assert d["bdr_positive_2005"].value == "no"


def test_bdr_column_used_when_it_is_pct_pred_and_threshold_note() -> None:
    spec = {**POST, (P.FEV1, R.POST_PCTPRED): "90", (P.FEV1, R.BDR): "10"}
    run_, _ = derive(spec)
    d = by_name(run_)
    assert d["bdr_fev1_pct_pred"].value == "10"
    assert d["bdr_fev1_pct_pred"].basis == "BDR column (% of predicted)"
    assert d["bdr_positive_2022"].value == "yes"
    assert any(f.rule_id == "derived.bdr_exactly_threshold" for f in run_.flags)


def test_bdr_column_that_is_change_from_baseline_is_noted() -> None:
    spec = {**POST, (P.FEV1, R.BDR): "11.5"}  # 100 * 0.35 / 3.05
    run_, _ = derive(spec)
    d = by_name(run_)
    assert d["bdr_fev1_pct_pred"].value == "9"
    assert any(f.rule_id == "derived.bdr_column_not_pct_pred" for f in run_.flags)


def test_bdr_statement_vs_computed() -> None:
    spec = {**POST, (P.BDR_SIGNIFICANT, R.FREE_TEXT): "yes"}
    run_, _ = derive(spec)
    assert any(f.rule_id == "free_text.bdr_statement_vs_computed" for f in run_.flags)
    spec_ok = {**POST, (P.BDR_SIGNIFICANT, R.FREE_TEXT): "no"}
    assert not any(
        f.rule_id == "free_text.bdr_statement_vs_computed"
        for f in derive(spec_ok)[0].flags
    )


# --- the report's pattern ----------------------------------------------------------


def test_report_pattern_from_phrase_and_check() -> None:
    spec = {**NORMAL, (P.INTERPRETATION_PATTERN, R.FREE_TEXT): "obstructive"}
    run_, _ = derive(spec)
    d = by_name(run_)
    assert d["report_pattern"].value == "obstructive"
    f = [f for f in run_.flags if f.rule_id == "free_text.report_pattern_vs_computed"]
    assert len(f) == 1 and f[0].severity.value == "check"


def test_report_pattern_near_miss_is_a_note() -> None:
    spec = {
        **NORMAL,
        (P.FVC, R.Z): "-2.0",
        (P.TLC, R.MEASURED): "5.0",
        (P.TLC, R.Z): "-0.5",
        (P.INTERPRETATION_PATTERN, R.FREE_TEXT): "restrictive",
    }
    run_, _ = derive(spec)
    assert by_name(run_)["pattern"].value == "non-specific"
    f = [f for f in run_.flags if f.rule_id == "free_text.report_pattern_vs_computed"]
    assert len(f) == 1 and f[0].severity.value == "note"


def test_report_pattern_from_per_test_findings() -> None:
    spec = {
        **NORMAL,
        (P.INTERPRETATION_SPIROMETRY, R.MEASURED): "restrictive",
        (P.INTERPRETATION_VOLUMES, R.MEASURED): "normal",
    }
    d = by_name(derive(spec)[0])
    assert d["report_pattern"].value == "nonspecific"
    assert d["report_pattern"].basis == "per-test findings"
    spec2 = {**spec, (P.INTERPRETATION_VOLUMES, R.MEASURED): "reduced"}
    assert by_name(derive(spec2)[0])["report_pattern"].value == "restrictive"


def test_report_pattern_from_whole_text() -> None:
    spec = {
        **NORMAL,
        (P.TECHNICAL_COMMENTS, R.MEASURED): "Spirometry is within normal limits.",
    }
    d = by_name(derive(spec)[0])
    assert (
        d["report_pattern"].value == "normal"
        and d["report_pattern"].basis == "whole text"
    )


def test_grades_prefer_the_session_quality_line() -> None:
    spec = {
        **NORMAL,
        (P.FEV1_GRADE, R.PRE): "A",
        (P.FEV1_GRADE, R.FREE_TEXT): "B",
        (P.SPIROMETRY_GRADE, R.FREE_TEXT): "C",
    }
    d = by_name(derive(spec)[0])
    assert d["grade_fev1"].value == "A" and d["grade_fev1"].basis == "session quality"
    assert d["grade_fvc"].value == "C" and d["grade_fvc"].basis == "comments"


# --- GLI point values ---------------------------------------------------------------

DEMO = {
    (P.AGE, R.MEASURED): "40",
    (P.HEIGHT, R.MEASURED): "170",
    (P.SEX, R.MEASURED): "Female",
    (P.REFERENCE_SPIROMETRY, R.MEASURED): "GLI 2012 Caucasian",
}


def test_gli_rows_from_fixture_results_and_pattern_gli() -> None:
    results = {
        ("11|pre", "FEV1"): GliRange(3.2, 3.2, 2.5, 2.5, -0.4, -0.4),
        ("11|pre", "FVC"): GliRange(4.0, 4.0, 3.2, 3.2, -0.8, -0.8),
        ("11|pre", "FEV1FVC"): GliRange(0.80, 0.80, 0.70, 0.70, 0.6, 0.6),
    }
    run_, _ = derive({**NORMAL, **DEMO}, gli_results=results)
    d = by_name(run_)
    assert (
        d["gli_FEV1_pre_z"].value == "-0.40" and d["gli_FEV1_pre_pred"].value == "3.200"
    )
    assert d["gli_FEV1_pre_pctpred"].value == "95.3"  # 100 * 3.05 / 3.2
    assert d["gli_FEV1_pre_lln"].value == "2.500"
    assert {k.parameter for k in d["gli_FEV1_pre_z"].inputs} == {
        P.FEV1,
        P.AGE,
        P.HEIGHT,
        P.SEX,
    }
    assert d["pattern_gli"].value == "normal" and d["pattern"].value == "normal"
    assert run_.rspiro_version == "fixture"


def test_without_rspiro_only_gli_and_pattern_gli_are_blank() -> None:
    run_, _ = derive({**NORMAL, **DEMO})
    d = by_name(run_)
    assert d["pattern"].value == "normal"
    assert (
        d["gli_FEV1_pre_z"].value == ""
        and d["gli_FEV1_pre_z"].status == "not computed: rspiro absent"
    )
    assert d["pattern_gli"].status == "not computed: rspiro absent"
    assert run_.not_computed >= 13


def test_derived_row_columns() -> None:
    run_, _ = derive(NORMAL)
    row = run_.rows[0].to_row()
    assert tuple(row) == type(run_.rows[0]).COLUMNS
