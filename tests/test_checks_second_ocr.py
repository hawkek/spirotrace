"""The second-reading rules: agreement confirms, disagreement checks (note at low
confidence), an unreadable or impossible first reading gets the suggestion, and
a failed record is noted once."""

from __future__ import annotations

from dataclasses import replace

from checks_helpers import FakeRecord, P, R, cells, flags_of, run

from spirotrace.layouts import Condition
from spirotrace.layouts import conditions as cond
from spirotrace.model import ColumnRole, Parameter


def with_second(
    rec: FakeRecord,
    parameter: Parameter,
    role: ColumnRole,
    reading: str,
    conf: float | None = 90.0,
) -> FakeRecord:
    key = next(
        k
        for k in rec.observations
        if k.parameter is parameter and k.column_role is role
    )
    rec.observations[key] = replace(
        rec.observations[key], second_reading_run=True, second_reading=reading
    )
    if conf is not None:
        rec.conditions.append(
            type(rec.conditions[0])(
                rec.record.record_id,
                1,
                key,
                cond.SECOND_READING_CONFIDENCE,
                f"{conf:.0f}",
            )
            if rec.conditions
            else _condition(rec, key, conf)
        )
    return rec


def _condition(rec: FakeRecord, key, conf: float):
    from spirotrace.layouts import ReadingCondition

    return ReadingCondition(
        rec.record.record_id, 1, key, cond.SECOND_READING_CONFIDENCE, f"{conf:.0f}"
    )


BASE = {(P.FEV1, R.PRE): "3.05", (P.FVC, R.PRE): "3.70", (P.FEV1_FVC, R.PRE): "0.824"}


def test_agreement_confirms() -> None:
    rec = with_second(cells(BASE), P.FEV1, R.PRE, "3.05")
    flags = run(rec)
    agree = flags_of(flags, "ocr.second_reading_agrees")
    assert len(agree) == 1 and agree[0].severity.value == "confirm"
    assert not flags_of(flags, "ocr.second_reading_disagrees")


def test_disagreement_is_a_check_or_a_note_by_confidence() -> None:
    high = run(with_second(cells(BASE), P.FEV1, R.PRE, "3.06", 80.0))
    f = flags_of(high, "ocr.second_reading_disagrees")
    assert len(f) == 1 and f[0].severity.value == "check"
    assert "3.06" in f[0].message and "3.05" in f[0].message and "80" in f[0].message
    low = run(with_second(cells(BASE), P.FEV1, R.PRE, "3.06", 30.0))
    assert flags_of(low, "ocr.second_reading_disagrees")[0].severity.value == "note"


def test_unreadable_first_reading_gets_a_suggestion_never_applied() -> None:
    rec = with_second(
        cells({**BASE, (P.FEV1, R.PRE): "x"}), P.FEV1, R.PRE, "3.05", 70.0
    )
    flags = run(rec)
    s = flags_of(flags, "ocr.second_reading_suggestion")
    assert len(s) == 1 and s[0].suggestion is not None
    assert s[0].suggestion.value == "3.05" and s[0].suggestion.source == "second OCR"
    assert not flags_of(flags, "ocr.second_reading_agrees")
    obs = rec.observations[s[0].keys[0]]
    assert obs.parsed_value is None  # the rule changed nothing


def test_out_of_range_first_reading_is_a_disagreement() -> None:
    # the range layer runs after the ocr layer, as validation ran after the old
    # script's second reading: a readable but impossible value gets the check, not
    # the suggestion
    rec = with_second(cells({**BASE, (P.FEV1, R.PRE): "30.5"}), P.FEV1, R.PRE, "3.05")
    flags = run(rec)
    assert flags_of(flags, "ocr.second_reading_disagrees")
    assert not flags_of(flags, "ocr.second_reading_suggestion")
    assert flags_of(flags, "range.outside_possible")


def test_ratio_second_reading_in_percent_compares_as_a_fraction() -> None:
    rec = with_second(cells(BASE), P.FEV1_FVC, R.PRE, "82.4")
    assert flags_of(run(rec), "ocr.second_reading_agrees")


def test_unparseable_second_reading_raises_nothing() -> None:
    rec = with_second(cells(BASE), P.FEV1, R.PRE, "-", None)
    flags = run(rec)
    for rid in (
        "ocr.second_reading_agrees",
        "ocr.second_reading_disagrees",
        "ocr.second_reading_suggestion",
    ):
        assert not flags_of(flags, rid)


def test_failed_record_is_noted_once() -> None:
    rec = cells(BASE)
    rec.note(cond.SECOND_READING_FAILED, "TesseractError", page=1)
    f = flags_of(run(rec), "ocr.second_reading_failed")
    assert len(f) == 1 and f[0].severity.value == "note" and f[0].record_level


def test_empty_second_reading_is_not_a_reading() -> None:
    rec = with_second(cells(BASE), P.FEV1, R.PRE, "", None)
    flags = run(rec)
    assert not flags_of(flags, "ocr.second_reading_agrees")
    assert not flags_of(flags, "ocr.second_reading_suggestion")
    _ = Condition  # the helpers module keeps the import list honest
