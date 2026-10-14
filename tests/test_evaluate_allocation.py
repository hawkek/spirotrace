"""Coder allocation: overlap per pair, exclusions never violated, exact matching of singles."""

from collections import Counter

import pytest
from conftest import design, synthetic_frame

from spirotrace.evaluate import (
    Allocation,
    AllocationError,
    Assignment,
    EvaluateError,
    FrameRecord,
    SamplingFrame,
    allocate_coders,
    check_frame,
    draw_sample,
)
from spirotrace.evaluate.allocation import _match_singles


def allocation_holds(allocation: Allocation, d, exclusions) -> None:
    """The design and the exclusion lists are satisfied."""
    for coder in d.coders:
        mine = allocation.for_coder(coder)
        assert len(mine) == d.reports_per_coder[coder]
        assert sum(a.overlap for a in mine) == d.overlap_reports_for(coder)
        assert not {a.record_id for a in mine} & set(exclusions.get(coder, ()))
    for pair in d.pairs:
        shared = [a for a in allocation.assignments if a.coders == pair]
        assert len(shared) == d.overlap_per_pair
        if d.overlap_per_pair == len(allocation.layouts):
            assert sorted(a.layout for a in shared) == list(allocation.layouts)
    overlap = [a for a in allocation.assignments if a.overlap]
    assert len(overlap) == d.n_overlap
    assert len(allocation) == d.n_distinct
    assert all(len(a.coders) == (2 if a.overlap else 1) for a in allocation.assignments)


def test_three_coders_no_exclusions() -> None:
    frame = synthetic_frame()
    d = design(k=14, seed=1)
    sample = draw_sample(frame, d)
    allocation = allocate_coders(sample, d, {})
    allocation_holds(allocation, d, {})
    assert {a.record_id for a in allocation.assignments} == sample.record_ids
    assert allocation.coders == ("c1", "c2", "c3")
    assert allocation.layouts == ("layout_a", "layout_b")
    first = allocation.assignments[0]
    assert allocation[first.record_id] is first
    assert first.stratum == sample[first.record_id].stratum


def test_unequal_reports_per_coder() -> None:
    frame = synthetic_frame()
    d = design(k=(14, 10, 6), seed=2)
    allocation = allocate_coders(draw_sample(frame, d), d, {})
    allocation_holds(allocation, d, {})
    assert Counter(c for a in allocation.assignments for c in a.coders) == {
        "c1": 14,
        "c2": 10,
        "c3": 6,
    }


def test_excluded_coder_keeps_only_eligible_reports_in_overlap_and_singles() -> None:
    # the study case: one coder may not code the reports they corrected (a fixed list)
    frame = synthetic_frame()
    ids = sorted(frame.record_ids)
    corrected = frozenset(ids[::2])  # every second record, both layouts
    d = design(k=14, seed=3)
    sample = draw_sample(frame, d)
    allocation = allocate_coders(sample, d, {"c1": corrected})
    allocation_holds(allocation, d, {"c1": corrected})
    # the excluded coder sits in two pairs: both overlaps avoid the list and span the layouts
    for pair in (("c1", "c2"), ("c1", "c3")):
        shared = [a for a in allocation.assignments if a.coders == pair]
        assert len(shared) == 2
        assert sorted(a.layout for a in shared) == ["layout_a", "layout_b"]
        assert not {a.record_id for a in shared} & corrected
    singles = [a for a in allocation.for_coder("c1") if not a.overlap]
    assert len(singles) == 10 and not {a.record_id for a in singles} & corrected
    assert {a.record_id for a in allocation.assignments} == sample.record_ids


def test_matching_succeeds_where_greedy_would_fail() -> None:
    eligible = {"r1": ["c1", "c2"], "r2": ["c1", "c2"], "r3": ["c1"], "r4": ["c1"]}
    assigned = _match_singles(["r1", "r2", "r3", "r4"], eligible, {"c1": 2, "c2": 2})
    assert assigned == {"r1": "c2", "r2": "c2", "r3": "c1", "r4": "c1"}


def test_matching_leaves_unplaceable_reports_out() -> None:
    assigned = _match_singles(
        ["r1", "r2", "r3"], {"r1": ["c1"], "r2": ["c1"], "r3": []}, {"c1": 1}
    )
    assert len(assigned) == 1


def test_infeasible_frame_stops_before_drawing() -> None:
    frame = synthetic_frame()
    ids = sorted(frame.record_ids)
    with pytest.raises(AllocationError, match="eligible records in the frame"):
        check_frame(frame, design(k=14), {"c1": frozenset(ids[:95])})
    small = SamplingFrame(tuple(FrameRecord(str(i), "layout_a") for i in range(10)))
    with pytest.raises(AllocationError, match="holds 10 records"):
        check_frame(small, design(k=14), {})
    check_frame(frame, design(k=14), {})


def test_infeasible_sample_raises_with_counts_only() -> None:
    frame = synthetic_frame()
    d = design(k=14, seed=5)
    sample = draw_sample(frame, d)
    ids = sorted(sample.record_ids)
    # too few eligible reports in the sample for one coder
    with pytest.raises(AllocationError, match="eligible reports in the sample") as info:
        allocate_coders(sample, d, {"c2": frozenset(ids[:30])})
    assert not any(rid in str(info.value) for rid in ids)
    # one coder may not code any report of one layout: no overlap of that layout for their pairs
    layout_b = frozenset(r for r in ids if sample[r].layout == "layout_b")
    with pytest.raises(AllocationError, match="no report of layout") as info:
        allocate_coders(sample, d, {"c3": layout_b})
    assert not any(rid in str(info.value) for rid in ids)


def test_singles_infeasible_raises_with_counts_only() -> None:
    ids = [str(7000 + i) for i in range(6)]
    frame = SamplingFrame(tuple(FrameRecord(i, "layout_a") for i in ids))
    d = design(k=3, seed=1, coders=("c1", "c2"), overlap=0, floor=0)
    exclusions = {"c1": frozenset(ids[:3]), "c2": frozenset(ids[:2])}
    with pytest.raises(AllocationError, match="cannot be given to any coder") as info:
        allocate_coders(draw_sample(frame, d), d, exclusions)
    assert "2 of 6 single reports" in str(info.value)
    assert not any(rid in str(info.value) for rid in ids)


def test_unknown_coder_in_exclusions_refused() -> None:
    frame = synthetic_frame()
    d = design(k=14)
    with pytest.raises(EvaluateError, match="not in the design"):
        allocate_coders(draw_sample(frame, d), d, {"nobody": frozenset()})


def test_allocation_is_reproducible() -> None:
    frame = synthetic_frame()
    d = design(k=14, seed=9)
    sample = draw_sample(frame, d)
    assert allocate_coders(sample, d, {}) == allocate_coders(sample, d, {})
    other = design(k=14, seed=10)
    assert allocate_coders(sample, d, {}) != allocate_coders(sample, other, {})


def test_allocation_sorts_and_keeps_the_coder_order() -> None:
    assignments = (
        Assignment("5", "layout_a", "layout_a:none", ("z", "y"), True),
        Assignment("3", "layout_b", "layout_b:none", ("y",), False),
    )
    allocation = Allocation(("z", "y"), assignments)
    assert [a.record_id for a in allocation.assignments] == ["3", "5"]
    assert allocation.coders == ("z", "y")
    assert allocation.for_coder("z") == (allocation["5"],)
    with pytest.raises(EvaluateError, match="does not list"):
        Allocation(("z",), assignments)
    with pytest.raises(EvaluateError, match="does not list"):
        Allocation(("z", "y", "y"), assignments)
