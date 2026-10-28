"""resolve: event merge (seam 4), applying events, statuses, the rerun and
flags_resolved. Synthetic records from checks_helpers."""

from __future__ import annotations

import pytest
from checks_helpers import P, R, cells, run

from spirotrace.config import default_settings
from spirotrace.model import ObservationKey, ReadMethod, ValueState
from spirotrace.resolve import (
    STATUSES,
    apply_event,
    merge_events,
    resolve_records,
)
from spirotrace.rspiro import GliRange
from spirotrace.store import Event, RawStore, ReadRecord

HASH = "ab" * 32
LAYOUT = "layout_x"


def key(p=P.FEV1, r=R.PRE, pos=1, page=1) -> ObservationKey:
    return ObservationKey(HASH, page, LAYOUT, p, r, pos)


def ev(
    seq: int,
    action: str,
    value: str = "",
    reviewer: str = "KH",
    k: ObservationKey | None = None,
    time: str | None = None,
) -> Event:
    return Event(
        f"{seq:032x}",
        seq,
        time or f"2026-11-02T10:{seq:02d}:00+13:00",
        reviewer,
        "11",
        (k or key()).to_string(),
        action,
        value,
        note="not this test" if action == "exclude" else "",
    )


def store_of(spec: dict) -> RawStore:
    rec = cells(spec)
    flags = run(rec)
    return RawStore(
        records=[ReadRecord(rec.record, dict(rec.observations), list(rec.conditions))],
        flags=flags,
        file_names={HASH: "11.pdf"},
    )


DEMO = {
    (P.AGE, R.MEASURED): "40",
    (P.HEIGHT, R.MEASURED): "170",
    (P.SEX, R.MEASURED): "Female",
    (P.REFERENCE_SPIROMETRY, R.MEASURED): "GLI 2012 Caucasian",
}
CONSISTENT = {
    (P.FEV1, R.PRE): "3.05",
    (P.FVC, R.PRE): "3.70",
    (P.FEV1_FVC, R.PRE): "0.824",
    (P.FEV1, R.Z): "-0.50",
    (P.FEV1, R.LLN): "2.60",
}


# --- merge ------------------------------------------------------------------------


def test_latest_wins_within_one_reviewer() -> None:
    m = merge_events([ev(1, "typed", "3.00"), ev(2, "typed", "3.05")])
    assert m.settled(key().to_string()).value == "3.05"
    assert m.count == 2 and not m.disagreements


def test_same_time_breaks_the_tie_by_sequence() -> None:
    t = "2026-11-02T10:00:00+13:00"
    m = merge_events([ev(2, "typed", "3.05", time=t), ev(1, "typed", "3.00", time=t)])
    assert m.settled(key().to_string()).value == "3.05"


def test_withdraw_retracts_only_that_reviewers_answer() -> None:
    m = merge_events(
        [ev(1, "typed", "3.05"), ev(2, "as_read", "", reviewer="AB"), ev(3, "withdraw")]
    )
    assert m.settled(key().to_string()).reviewer == "AB"
    assert m.reviewers_of(key().to_string()) == ("AB",)
    assert (
        merge_events([ev(1, "typed", "3.05"), ev(2, "withdraw")]).settled(
            key().to_string()
        )
        is None
    )


def test_reviewers_disagreeing_are_listed_not_settled() -> None:
    m = merge_events([ev(1, "typed", "3.05"), ev(2, "typed", "3.50", reviewer="AB")])
    assert key().to_string() in m.disagreements
    assert m.settled(key().to_string()) is None
    agree = merge_events(
        [ev(1, "typed", "3.05"), ev(2, "typed", " 3.05", reviewer="AB")]
    )
    assert not agree.disagreements


# --- apply -------------------------------------------------------------------------


def obs(spec: dict | None = None):
    rec = cells(spec or {(P.FEV1, R.PRE): "3.05"})
    return rec.observations[key()]


@pytest.mark.parametrize(
    ("action", "value", "state", "status", "parsed"),
    [
        ("as_read", "", ValueState.VALUE, "confirmed", 3.05),
        ("typed", "3.50", ValueState.VALUE, "corrected", 3.5),
        ("typed", "3.05", ValueState.VALUE, "confirmed", 3.05),
        ("typed", "3,05", ValueState.VALUE, "confirmed", 3.05),
        ("typed", "-", ValueState.DASH, "corrected", None),
        ("not_readable", "", ValueState.UNREADABLE, "unreadable", None),
        ("empty", "", ValueState.EMPTY, "corrected", None),
        ("dash", "", ValueState.DASH, "corrected", None),
        ("exclude", "", ValueState.VALUE, "excluded", 3.05),
    ],
)
def test_apply_event(action, value, state, status, parsed) -> None:
    new, st = apply_event(obs(), ev(1, action, value))
    assert (new.value_state, st, new.parsed_value) == (state, status, parsed)
    if action not in ("as_read", "exclude"):
        assert new.read_method is ReadMethod.MANUAL
    assert new.key == key() and new.bbox == obs().bbox


def test_typed_ratio_is_stored_as_a_fraction() -> None:
    o = cells({(P.FEV1_FVC, R.PRE): "0.82"}).observations[key(P.FEV1_FVC)]
    new, st = apply_event(o, ev(1, "typed", "78%", k=key(P.FEV1_FVC)))
    assert (new.parsed_value, st, new.printed_form.value) == (
        0.78,
        "corrected",
        "percent",
    )


def test_struck_keeps_the_value_and_sets_the_flag() -> None:
    new, st = apply_event(obs(), ev(1, "struck", ""))
    assert new.struck and new.parsed_value == 3.05 and st == "corrected"
    new2, _ = apply_event(obs(), ev(1, "struck", "2.98"))
    assert new2.struck and new2.parsed_value == 2.98


def test_withdraw_cannot_be_applied() -> None:
    with pytest.raises(ValueError, match="withdraw"):
        apply_event(obs(), ev(1, "withdraw"))


# --- resolve ------------------------------------------------------------------------


def test_statuses_without_events() -> None:
    store = store_of({**CONSISTENT, (P.FVC, R.Z): "x"})
    res = resolve_records(store, merge_events([]), default_settings())
    assert res.values[key()].status == "accepted_unflagged"
    assert res.values[key(P.FVC, R.Z)].status == "open_flag"
    assert res.values[key(P.FVC, R.Z)].open_severity == "error"
    assert all(f.change == "unchanged" for f in res.flags_resolved)
    assert {v.status for v in res.values.values()} <= set(STATUSES)


def test_correction_clears_a_flag_and_the_change_is_recorded() -> None:
    store = store_of({**CONSISTENT, (P.FVC, R.Z): "x"})
    res = resolve_records(
        store,
        merge_events([ev(1, "typed", "-0.9", k=key(P.FVC, R.Z))]),
        default_settings(),
    )
    v = res.values[key(P.FVC, R.Z)]
    assert (
        v.status == "corrected"
        and v.open_severity == ""
        and v.last_event_id == f"{1:032x}"
    )
    cleared = [f for f in res.flags_resolved if f.change == "cleared"]
    assert cleared and all(f.flag.rule_id == "ocr.not_a_number" for f in cleared)
    assert all(f.flag.record_id == "11" for f in cleared)
    assert any(f.rule_id == "ocr.not_a_number" for f in store.flags)  # raw untouched


def test_correction_can_raise_a_new_flag() -> None:
    store = store_of(CONSISTENT)
    res = resolve_records(
        store, merge_events([ev(1, "typed", "9.5")]), default_settings()
    )
    new = [f for f in res.flags_resolved if f.change == "new"]
    assert any(f.flag.rule_id.startswith("range.") for f in new)
    assert res.values[key()].status == "corrected"
    assert res.values[key()].open_severity in ("error", "check")


def test_disagreement_is_a_status_and_listed() -> None:
    store = store_of(CONSISTENT)
    res = resolve_records(
        store,
        merge_events([ev(1, "typed", "3.05"), ev(2, "typed", "3.50", reviewer="AB")]),
        default_settings(),
    )
    v = res.values[key()]
    assert v.status == "reviewer_disagreement" and v.resolved.parsed_value == 3.05
    assert not v.usable and v.reviewers == ("AB", "KH")
    assert key().to_string() in res.disagreements


def test_orphan_events_are_listed_never_dropped() -> None:
    store = store_of(CONSISTENT)
    gone = key(P.PEF)
    res = resolve_records(
        store, merge_events([ev(1, "typed", "5", k=gone)]), default_settings()
    )
    assert len(res.orphans) == 1 and res.orphans[0].key == gone.to_string()


def test_confirm_rules_fill_machine_confirmed_by() -> None:
    store = store_of({**CONSISTENT, **DEMO})
    results = {("11|pre", "FEV1"): GliRange(3.2, 3.2, 2.5, 2.7, -0.6, -0.4)}
    res = resolve_records(
        store, merge_events([]), default_settings(), gli_results=results
    )
    v = res.values[key(P.FEV1, R.Z)]
    assert "gli.z_agrees" in v.machine_confirmed_by
    assert v.status == "accepted_unflagged"  # machine evidence never sets the status


def test_resolved_row_round_trip_columns() -> None:
    store = store_of(CONSISTENT)
    res = resolve_records(store, merge_events([ev(1, "exclude")]), default_settings())
    row = res.values[key()].to_row()
    assert row["status"] == "excluded" and row["resolved_value"] == "3.05"
    assert set(row) == set(type(res.values[key()]).COLUMNS)
