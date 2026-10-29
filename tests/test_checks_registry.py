"""The rule registry, the threshold table and the flag type."""

from __future__ import annotations

import pytest

from spirotrace.checks import (
    LAYERS,
    PARAMETER_LIMITS,
    ROLE_LIMITS,
    RULES,
    THRESHOLDS,
    Flag,
    Severity,
    enabled_rules,
    limits_for,
)
from spirotrace.checks import run as _run  # noqa: F401 - registers the rules
from spirotrace.checks.registry import check_flag
from spirotrace.model import ColumnRole, Parameter

P, R = Parameter, ColumnRole


def test_every_rule_declares_id_layer_severity_and_rationale() -> None:
    assert len(RULES) >= 80
    for rid, r in RULES.items():
        assert r.id == rid and r.layer in LAYERS and rid.startswith(r.layer + ".")
        assert r.severities and all(isinstance(s, Severity) for s in r.severities)
        assert len(r.why.split()) >= 5, rid
        assert r.scope in ("record", "cohort", "gli", "derived")


def test_curated_list_rules_are_registered() -> None:
    expected = {
        "input.page_blank",
        "input.stage_failed",
        "ocr.not_a_number",
        "ocr.decimal_places",
        "ocr.dash_variant",
        "range.outside_possible",
        "range.lost_decimal",
        "range.outside_typical",
        "range.grade_vocabulary",
        "layout.row_placed_by_template",
        "layout.cell_empty_in_filled_column",
        "layout.trial_number_repeated",
        "layout.post_fev1_row_clipped",
        "layout.core_field_not_extracted",
        "image.struck_number",
        "image.printed_in_empty_cell",
        "image.empty_cell_blank",
        "consistency.bmi",
        "consistency.header_across_pages",
        "consistency.ratio_matches_values",
        "consistency.lln_vs_z",
        "consistency.dlcoc_direction",
        "consistency.trend_page_portable",
        "consistency.trend_row_lab",
        "consistency.grade_vs_variability",
        "consistency.bev_acceptability",
        "gli.z_agrees",
        "gli.z_agrees_from_best_ratio",
        "gli.z_disagrees",
        "gli.second_z_identified",
        "cohort.robust_z",
        "cohort.column_empty_by_format",
        "free_text.interpretation_not_read",
        "free_text.interpretation_contradiction",
    }
    assert expected <= set(RULES)


def test_enabled_rules_honour_off_and_layers_off_in_layer_order() -> None:
    rules = enabled_rules()
    layers = [r.layer for r in rules]
    assert layers == sorted(layers, key=LAYERS.index)
    off = enabled_rules(off=["range.outside_typical"], layers_off=["gli"])
    ids = {r.id for r in off}
    assert "range.outside_typical" not in ids and not any(
        i.startswith("gli.") for i in ids
    )
    assert "range.outside_possible" in ids


def test_a_flag_with_an_undeclared_severity_is_refused() -> None:
    good = Flag("range.outside_possible", "range", Severity.ERROR, "11", (), None, "x")
    assert check_flag(good) is good
    with pytest.raises(ValueError, match="raised"):
        check_flag(
            Flag("range.outside_possible", "range", Severity.NOTE, "11", (), None, "x")
        )
    with pytest.raises(ValueError, match="unregistered"):
        check_flag(Flag("range.nope", "range", Severity.NOTE, "11", (), None, "x"))
    with pytest.raises(ValueError, match="layer"):
        check_flag(
            Flag("range.outside_possible", "ocr", Severity.ERROR, "11", (), None, "x")
        )


def test_every_threshold_and_limit_has_a_source() -> None:
    for name, t in THRESHOLDS.items():
        assert t.source.strip(), name
    for lims in [*PARAMETER_LIMITS.values(), *ROLE_LIMITS.values()]:
        assert (
            lims.hard_low < lims.typical_low <= lims.typical_high < lims.hard_high
            or (
                lims.hard_low <= lims.typical_low <= lims.typical_high <= lims.hard_high
            )
        )
        assert lims.source.strip()


def test_limits_follow_the_role_then_the_parameter() -> None:
    assert limits_for(P.FEV1, R.PRE) is PARAMETER_LIMITS[P.FEV1]
    assert limits_for(P.FEV1, R.Z) is ROLE_LIMITS[R.Z]
    assert limits_for(P.FEV1_FVC, R.Z) is ROLE_LIMITS[R.Z]  # a second z column too
    assert limits_for(P.FEV1, R.TREND) is None  # trend rows are not range-checked
    assert limits_for(P.TRIAL_NUMBER, R.TRIAL) is None
    assert limits_for(P.HAEMOGLOBIN, R.FREE_TEXT) is PARAMETER_LIMITS[P.HAEMOGLOBIN]
