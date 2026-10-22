"""Free-text and cohort layers."""

from __future__ import annotations

from checks_helpers import P, R, cells, flags_of, record, run

from spirotrace.checks import Severity
from spirotrace.layouts import Condition
from spirotrace.layouts import conditions as cond


def test_interpretation_contradiction() -> None:
    rec = record()
    rec.put(
        P.INTERPRETATION_SPIROMETRY,
        R.MEASURED,
        "Normal. Obstruction.",
        parsed_text="normal; obstructive",
    )
    rec.put(
        P.INTERPRETATION_VOLUMES, R.MEASURED, "Normal volumes.", parsed_text="normal"
    )
    f = flags_of(run(rec), "free_text.interpretation_contradiction")
    assert (
        len(f) == 1
        and f[0].severity is Severity.CHECK
        and "obstructive" in f[0].message
    )


def test_interpretation_contradiction_across_pages() -> None:
    rec = record()
    rec.put(
        P.INTERPRETATION_SPIROMETRY, R.MEASURED, "Normal.", parsed_text="normal", page=1
    )
    rec.put(
        P.INTERPRETATION_SPIROMETRY,
        R.MEASURED,
        "Reduced.",
        parsed_text="reduced",
        page=2,
    )
    assert len(flags_of(run(rec), "free_text.interpretation_contradiction")) == 1


def test_interpretation_not_read_is_a_note_unless_read_elsewhere() -> None:
    rec = record()
    rec.note(
        cond.INTERPRETATION_FINDING_NOT_RECOGNISED, P.INTERPRETATION_SPIROMETRY.value, 1
    )
    f = flags_of(run(rec), "free_text.interpretation_not_read")
    assert len(f) == 1 and f[0].severity is Severity.NOTE and f[0].page == 1
    rec.put(
        P.INTERPRETATION_SPIROMETRY, R.MEASURED, "Normal.", parsed_text="normal", page=2
    )
    assert not flags_of(run(rec), "free_text.interpretation_not_read")
    # an unreadable continuation paragraph carries the condition on its observation
    rec2 = record()
    rec2.put(
        P.INTERPRETATION_VOLUMES,
        R.MEASURED,
        "Lung volumes: odd.",
        page=2,
        unreadable=True,
        conditions=[Condition(cond.INTERPRETATION_FINDING_NOT_RECOGNISED)],
    )
    f = flags_of(run(rec2), "free_text.interpretation_not_read")
    assert len(f) == 1 and f[0].keys[0].parameter is P.INTERPRETATION_VOLUMES


def test_free_text_derived_is_a_condition_not_a_flag() -> None:
    rec = record()
    rec.put(
        P.FEV1_GRADE,
        R.FREE_TEXT,
        "A",
        parsed_text="A",
        conditions=[Condition(cond.FREE_TEXT_DERIVED)],
    )
    assert not run(rec)


def test_cohort_robust_z_needs_twenty_values() -> None:
    recs = [cells({(P.FEV1, R.PRE): "3.00"}, str(100 + i)) for i in range(19)]
    recs.append(cells({(P.FEV1, R.PRE): "4.20"}, "200"))  # shifted digit? median 3.00
    assert not flags_of(run(*recs[:19]), "cohort.robust_z")
    recs2 = [
        cells({(P.FEV1, R.PRE): f"{3.0 + 0.01 * (i % 7):.2f}"}, str(100 + i))
        for i in range(24)
    ]
    recs2.append(cells({(P.FEV1, R.PRE): "5.30"}, "200"))
    f = flags_of(run(*recs2), "cohort.robust_z")
    assert len(f) == 1 and f[0].record_id == "200" and f[0].severity is Severity.CHECK
