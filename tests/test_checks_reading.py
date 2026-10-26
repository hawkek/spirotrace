"""Reading conditions become flags of the input, ocr and layout layers."""

from __future__ import annotations

from checks_helpers import P, R, cells, flags_of, record, rule_ids, run

from spirotrace.checks import Severity
from spirotrace.layouts import Condition
from spirotrace.layouts import conditions as cond


def test_record_level_conditions_become_record_level_flags() -> None:
    rec = record()
    rec.note(cond.PAGE_BLANK, "", 3)
    rec.note(cond.PARSER_CRASHED, "trials: boom", 2)
    rec.note(cond.SUBJECT_ID_MISSING, "scan")
    flags = run(rec)
    blank = flags_of(flags, "input.page_blank")[0]
    assert blank.record_level and blank.page == 3 and blank.severity is Severity.NOTE
    failed = flags_of(flags, "input.stage_failed")[0]
    assert failed.severity is Severity.ERROR and "boom" in failed.message
    assert flags_of(flags, "input.subject_id_missing")[0].severity is Severity.ERROR


def test_token_conditions_flag_their_observation() -> None:
    rec = cells(
        {(P.FEV1, R.PRE): "3.8a", (P.FVC, R.PRE): "O.55", (P.FET, R.PRE): "6,1"}
    )
    flags = run(rec)
    nan = flags_of(flags, "ocr.not_a_number")[0]
    assert nan.severity is Severity.ERROR and nan.keys[0].parameter is P.FEV1
    sub = flags_of(flags, "ocr.char_substitution")[0]
    assert sub.severity is Severity.CHECK and sub.keys[0].parameter is P.FVC
    comma = flags_of(flags, "ocr.decimal_comma")[0]
    assert comma.severity is Severity.NOTE and comma.keys[0].parameter is P.FET


def test_dash_variant_is_a_note_and_a_printed_dash_is_silent() -> None:
    rec = cells({(P.FEV1, R.POST): "~", (P.FVC, R.POST): "-"})
    flags = run(rec)
    assert [f.keys[0].parameter for f in flags_of(flags, "ocr.dash_variant")] == [
        P.FEV1
    ]
    assert not any(f.keys and f.keys[0].parameter is P.FVC for f in flags)


def test_table_not_found_severity_follows_the_table() -> None:
    rec = record()
    rec.note(cond.TABLE_NOT_FOUND, "spirometry", 1)
    rec.note(cond.TABLE_NOT_FOUND, "lung volumes", 1)
    rec.note(cond.TABLE_NOT_FOUND, "trend", 3)
    sevs = {f.message: f.severity for f in flags_of(run(rec), "layout.table_not_found")}
    assert sevs == {
        "table not found: spirometry": Severity.ERROR,
        "table not found: lung volumes": Severity.CHECK,
        "table not found: trend": Severity.NOTE,
    }


def test_row_placed_by_template_fires_once_per_table() -> None:
    rec = record()
    for p in (P.FEV1, P.FVC, P.FIVC):
        for role in (R.PRE, R.LLN, R.PCTPRED, R.Z):
            rec.put(p, role, "1.0", conditions=[Condition(cond.ROW_PLACED_BY_TEMPLATE)])
    for p in (P.TLC, P.RV):
        rec.put(
            p, R.MEASURED, "1.0", conditions=[Condition(cond.ROW_PLACED_BY_TEMPLATE)]
        )
    flags = flags_of(run(rec), "layout.row_placed_by_template")
    assert len(flags) == 2  # spirometry table, volumes table: not 14 cells
    assert {len(f.keys) for f in flags} == {12, 2}
    assert all(f.severity is Severity.NOTE for f in flags)


def test_cell_empty_in_filled_column_is_a_check_without_a_cohort() -> None:
    rec = record()
    rec.put(P.FEV1, R.LLN, "", conditions=[Condition(cond.CELL_EMPTY_IN_FILLED_COLUMN)])
    flags = run(rec)
    assert (
        flags_of(flags, "layout.cell_empty_in_filled_column")[0].severity
        is Severity.CHECK
    )
    assert not flags_of(flags, "cohort.column_empty_by_format")


def test_cell_empty_in_nearly_every_record_of_a_layout_is_a_note() -> None:
    recs = []
    for i in range(12):
        rec = record(str(100 + i))
        rec.put(P.FEV1, R.PRE, "3.00")
        if i < 11:  # 11 of 12 empty: the format
            rec.put(
                P.FEV1,
                R.LLN,
                "",
                conditions=[Condition(cond.CELL_EMPTY_IN_FILLED_COLUMN)],
            )
        else:
            rec.put(P.FEV1, R.LLN, "2.50")
        recs.append(rec)
    flags = run(*recs)
    assert len(flags_of(flags, "cohort.column_empty_by_format")) == 11
    assert not flags_of(flags, "layout.cell_empty_in_filled_column")
    # switching the cohort rule off restores the checks
    flags = run(*recs, off=["cohort.column_empty_by_format"])
    assert len(flags_of(flags, "layout.cell_empty_in_filled_column")) == 11


def test_trial_number_repeated() -> None:
    rec = record()
    for pos, n in ((2, 5), (3, 5), (4, 1)):
        rec.put(P.TRIAL_NUMBER, R.TRIAL, f"Trial {n}", pos, parsed_value=n)
    f = flags_of(run(rec), "layout.trial_number_repeated")
    assert len(f) == 1 and len(f[0].keys) == 2 and "5" in f[0].message
    rec2 = record()
    for pos, n in ((2, 2), (3, 1), (4, 3)):
        rec2.put(P.TRIAL_NUMBER, R.TRIAL, f"Trial {n}", pos, parsed_value=n)
    assert not flags_of(run(rec2), "layout.trial_number_repeated")


def test_decimal_places_only_on_layouts_with_a_trials_table() -> None:
    lab = cells({(P.FEV1, R.PRE): "3.8", (P.FEV1, R.Z): "-1.1"})
    assert not flags_of(run(lab), "ocr.decimal_places")
    dev = cells(
        {
            (P.FEV1, R.PRE): "3.8",
            (P.FEV1, R.Z): "-1.1",
            (P.FVC, R.PRE): "4.50",
            (P.FEV1_FVC, R.PRE): "0.856",
            (P.FEV1, R.TRIAL, 2): "3.80",
        }
    )
    flags = flags_of(run(dev), "ocr.decimal_places")
    assert {(f.keys[0].parameter, f.keys[0].column_role) for f in flags} == {
        (P.FEV1, R.PRE),
        (P.FEV1, R.Z),
    }


def test_session_quality_field_not_found_has_its_own_rule() -> None:
    rec = record()
    rec.put(
        P.FVC_VARIABILITY,
        R.PRE,
        "",
        conditions=[Condition(cond.FIELD_NOT_LOCATED, "fvc_var_l")],
    )
    rec.note(cond.FIELD_NOT_LOCATED, "age", 1)
    flags = run(rec)
    assert len(flags_of(flags, "layout.session_quality_field_not_found")) == 1
    assert len(flags_of(flags, "layout.field_not_located")) == 1


def test_clipped_post_row_and_core_field_not_extracted() -> None:
    rec = record()
    rec.put(
        P.FEV1, R.POST_TRIAL, "3.1", 2, conditions=[Condition(cond.POST_ROW_CLIPPED)]
    )
    rec.note(cond.CORE_FIELD_NOT_EXTRACTED, "FEV1 lln", 1)
    ids = rule_ids(run(rec))
    assert {"layout.post_fev1_row_clipped", "layout.core_field_not_extracted"} <= ids
