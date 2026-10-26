"""The runner: layer order, switches, counts, and gli rules not run without R."""

from __future__ import annotations

from checks_helpers import P, R, cells

from spirotrace.checks import check_records
from spirotrace.config import default_settings


def settings_with(off=(), layers_off=()):
    s = default_settings()
    return type(s)(
        **{
            **{f: getattr(s, f) for f in s.__slots__},
            "rules": type(s.rules)(tuple(off), tuple(layers_off)),
        }
    )


def test_gli_rules_are_reported_not_run_without_a_bridge() -> None:
    rec = cells({(P.FEV1, R.PRE): "3.85", (P.FEV1, R.Z): "0.25"})
    run = check_records([rec], default_settings())
    assert run.rules_not_run and all(r.startswith("gli.") for r in run.rules_not_run)
    assert "Rscript" in run.not_run_reason
    assert not any(f.rule_id.startswith("gli.") for f in run.flags)


def test_rules_off_and_layers_off_are_honoured_and_counts_are_by_layer_and_severity() -> (
    None
):
    rec = cells({(P.FEV1, R.PRE): "38.0", (P.FVC, R.PRE): "0.30"})
    run = check_records([rec], default_settings())
    assert run.counts()[("range", "error")] == 1
    assert run.counts()[("range", "check")] == 1
    run = check_records([rec], settings_with(off=["range.outside_typical"]))
    assert ("range", "check") not in run.counts()
    run = check_records(
        [rec], settings_with(layers_off=["range", "gli", "consistency"])
    )
    assert not run.flags and not run.rules_not_run
    assert run.by_rule() == {}


def test_an_error_in_an_earlier_layer_excludes_the_value_from_later_rules() -> None:
    rec = cells(
        {(P.FEV1, R.PRE): "3.8a", (P.FVC, R.PRE): "3.00", (P.FEV1_FVC, R.PRE): "0.900"}
    )
    run = check_records([rec], default_settings())
    ids = {f.rule_id for f in run.flags}
    assert "ocr.not_a_number" in ids and "consistency.ratio_matches_values" not in ids
