"""GLI layer against fixed recalculated ranges (no R needed), and the inputs built
for the bridge."""

from __future__ import annotations

from checks_helpers import P, R, context, flags_of, record, run

from spirotrace.checks import Severity
from spirotrace.checks.rules_gli import demographics, gli_inputs
from spirotrace.rspiro import GliRange


def subject(**extra):
    rec = record()
    rec.put(P.SEX, R.MEASURED, "Female")
    rec.put(P.AGE, R.MEASURED, "24")
    rec.put(P.HEIGHT, R.MEASURED, "172.5")
    rec.put(P.REFERENCE_SPIROMETRY, R.MEASURED, "GLI 2012 Ref. Caucasian")
    rec.put(P.FEV1, R.PRE, "3.85")
    rec.put(P.FVC, R.PRE, "4.50")
    rec.put(P.FEV1_FVC, R.PRE, "0.856")
    for (p, r, pos), raw in extra.items() if isinstance(extra, dict) else ():
        rec.put(p, r, raw, pos)
    return rec


def rng(z_min, z_max, **kw) -> GliRange:
    return GliRange(
        kw.get("pred_min", 3.73),
        kw.get("pred_max", 3.74),
        kw.get("lln_min", 3.00),
        kw.get("lln_max", 3.01),
        z_min,
        z_max,
        kw.get("zgl_min"),
        kw.get("zgl_max"),
        kw.get("zeth", (None,) * 5),
    )


def test_demographics_and_inputs() -> None:
    rec = subject()
    demo, why = demographics(context(rec))
    assert why == "" and demo is not None
    assert (demo.sex, demo.ethnicity) == (2, 1)
    assert (demo.age_lo, demo.age_hi) == (23.5, 24.999)
    assert (demo.height_lo, demo.height_hi) == (172.45, 172.55)
    inputs = gli_inputs(context(rec))
    ids = [s.id for s in inputs.subjects]
    assert ids == [
        "11|pre",
        "11|pre|best",
    ]  # the README's best FEV1 / best FVC candidate
    assert inputs.subjects[0].values["FEV1FVC"] == (0.856, 0.0005)


def test_inputs_skip_without_demographics_or_another_reference() -> None:
    rec = record()
    rec.put(P.FEV1, R.PRE, "3.85")
    rec.put(P.FEV1, R.Z, "-0.10")
    assert "missing" in gli_inputs(context(rec)).skipped
    f = flags_of(run(rec, gli_results={}), "gli.skipped")
    assert len(f) == 1 and f[0].severity is Severity.NOTE
    rec2 = subject()
    rec2.put(P.REFERENCE_SPIROMETRY, R.MEASURED, "NHANES III", page=2)
    assert gli_inputs(context(rec2)).skipped == ""  # the first page's reference is read
    rec3 = record()
    rec3.put(P.REFERENCE_SPIROMETRY, R.MEASURED, "ECCS 1993")
    assert "not GLI 2012" in gli_inputs(context(rec3)).skipped


def test_z_agrees_disagrees_rounding_and_trial_matches() -> None:
    rec = subject()
    rec.put(P.FEV1, R.Z, "0.25")
    rec.put(P.FVC, R.Z, "0.40")  # 0.14 off: a check
    rec.put(P.FEV1_FVC, R.Z, "-0.30")  # matches trial position 2
    rec.put(P.FEV1, R.TRIAL, "3.70", 2)
    rec.put(P.FVC, R.TRIAL, "4.60", 2)
    rec.put(P.FEV1_FVC, R.TRIAL, "0.804", 2)
    rec.put(P.FIVC, R.PRE, "4.70")
    results = {
        ("11|pre", "FEV1"): rng(0.24, 0.27),
        ("11|pre", "FVC"): rng(0.24, 0.26),
        ("11|pre", "FEV1FVC"): rng(-0.13, -0.11),
        ("11|pre|pos2", "FEV1FVC"): rng(-0.31, -0.29),
        ("11|pre|fivc", "FEV1FVC"): rng(-0.9, -0.8),
        ("11|pre|best", "FEV1FVC"): rng(-0.13, -0.11),
    }
    flags = run(rec, gli_results=results)
    assert [f.keys[1].parameter for f in flags_of(flags, "gli.z_agrees")] == [P.FEV1]
    dis = flags_of(flags, "gli.z_disagrees")
    assert (
        len(dis) == 1
        and dis[0].keys[0].parameter is P.FVC
        and dis[0].severity is Severity.CHECK
    )
    tm = flags_of(flags, "gli.z_matches_trial")
    assert (
        len(tm) == 1
        and "trial position 2" in tm[0].message
        and tm[0].severity is Severity.NOTE
    )
    assert not flags_of(flags, "gli.several_disagree")
    # within 0.03: a note, not a check
    rec2 = subject()
    rec2.put(P.FEV1, R.Z, "0.29")
    flags = run(rec2, gli_results={("11|pre", "FEV1"): rng(0.24, 0.27)})
    assert flags_of(flags, "gli.z_within_rounding") and not flags_of(
        flags, "gli.z_disagrees"
    )


def test_z_from_best_ratio_counts_as_agreement() -> None:
    rec = subject()
    rec.put(P.FEV1_FVC, R.Z, "-0.30")
    results = {
        ("11|pre", "FEV1FVC"): rng(-0.13, -0.11),
        ("11|pre|best", "FEV1FVC"): rng(-0.31, -0.29),
    }
    flags = run(rec, gli_results=results)
    f = flags_of(flags, "gli.z_agrees_from_best_ratio")
    assert len(f) == 1 and f[0].severity is Severity.CONFIRM
    assert not flags_of(flags, "gli.z_disagrees") and not flags_of(
        flags, "gli.z_matches_trial"
    )


def test_far_trial_match_is_a_check_and_several_disagreements_add_a_record_flag() -> (
    None
):
    rec = subject()
    rec.put(P.FEV1, R.Z, "-2.00")
    rec.put(P.FVC, R.Z, "-2.00")
    rec.put(P.FEV1_FVC, R.Z, "-2.00")
    rec.put(P.FEV1, R.TRIAL, "2.70", 2)
    results = {
        ("11|pre", "FEV1"): rng(0.24, 0.27),
        ("11|pre", "FVC"): rng(0.24, 0.26),
        ("11|pre", "FEV1FVC"): rng(-0.13, -0.11),
        ("11|pre|pos2", "FEV1"): rng(-2.05, -1.95),
    }
    flags = run(rec, gli_results=results)
    assert len(flags_of(flags, "gli.z_far_matches_trial")) == 1
    assert len(flags_of(flags, "gli.z_disagrees")) == 2
    assert len(flags_of(flags, "gli.several_disagree")) == 1


def test_lln_pctpred_pred_and_not_checked() -> None:
    rec = subject()
    rec.put(P.FEV1, R.LLN, "3.00")
    rec.put(P.FVC, R.LLN, "3.20")
    rec.put(P.FEV1, R.PCTPRED, "103")
    rec.put(P.FVC, R.PCTPRED, "90")
    rec.put(P.FVC, R.Z, "-0.25")
    results = {
        ("11|pre", "FEV1"): rng(
            0.24, 0.27, lln_min=3.003, lln_max=3.004, pred_min=3.736, pred_max=3.737
        ),
        ("11|pre", "FVC"): GliRange(4.36, 4.37, 3.48, 3.49, None, None),
    }
    flags = run(rec, gli_results=results)
    assert len(flags_of(flags, "gli.lln_agrees")) == 1
    assert flags_of(flags, "gli.lln_disagrees")[0].keys[0].parameter is P.FVC
    assert flags_of(flags, "gli.pctpred_agrees")[0].keys[0].parameter is P.FEV1
    assert flags_of(flags, "gli.pctpred_disagrees")[0].keys[1].parameter is P.FVC
    assert flags_of(flags, "gli.not_checked")[0].keys[0].parameter is P.FVC


def test_diffusion_rows_use_the_lab_predicted_column() -> None:
    rec = subject()
    rec.put(P.DLCO, R.MEASURED, "25.0")
    rec.put(P.DLCO, R.PREDICTED, "24.4")
    rec.put(P.DLCO, R.Z, "0.20")
    rec.put(P.KCO, R.MEASURED, "4.50")
    rec.put(P.KCO, R.PREDICTED, "5.00")
    inputs = gli_inputs(context(rec))
    diff = next(s for s in inputs.subjects if s.id == "11|diffusion")
    assert set(diff.values) == {"TLCO", "KCO"} and diff.si is False
    results = {
        ("11|diffusion", "TLCO"): rng(0.18, 0.21, pred_min=24.35, pred_max=24.36),
        ("11|diffusion", "KCO"): rng(-0.14, 0.02, pred_min=4.53, pred_max=4.54),
    }
    flags = run(rec, gli_results=results)
    assert flags_of(flags, "gli.pred_agrees")[0].keys[0].parameter is P.DLCO
    assert flags_of(flags, "gli.pred_disagrees")[0].keys[0].parameter is P.KCO
    assert flags_of(flags, "gli.z_agrees")[0].keys[0].parameter is P.DLCO


def test_second_z_column_is_identified() -> None:
    rec = subject()
    rec.put(P.FEV1, R.Z, "0.25")
    rec.put(P.FEV1, R.Z, "0.60", 2)
    results = {("11|pre", "FEV1"): rng(0.24, 0.27, zgl_min=0.58, zgl_max=0.61)}
    f = flags_of(run(rec, gli_results=results), "gli.second_z_identified")
    assert (
        len(f) == 1
        and "GLI global" in f[0].message
        and f[0].keys[0].display_position == 2
    )
    results = {("11|pre", "FEV1"): rng(0.24, 0.27, zgl_min=0.90, zgl_max=0.95)}
    f = flags_of(run(rec, gli_results=results), "gli.second_z_identified")
    assert "matches none" in f[0].message
