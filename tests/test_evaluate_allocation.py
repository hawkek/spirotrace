"""Coder allocation: overlap per pair, exclusions never violated, exact matching of singles."""

import random
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


def test_exclusions_never_violated_over_many_seeds() -> None:
    frame = synthetic_frame()
    ids = sorted(frame.record_ids)
    feasible = infeasible = 0
    for seed in range(200):
        rng = random.Random(seed)
        exclusions = {
            c: frozenset(rng.sample(ids, rng.randint(0, 45)))
            for c in ("c1", "c2", "c3")
        }
        d = design(k=14, seed=seed)
        try:
            allocation = allocate_coders(draw_sample(frame, d), d, exclusions)
        except AllocationError as e:
            infeasible += 1
            assert not any(rid in str(e) for rid in ids)
            continue
        feasible += 1
        allocation_holds(allocation, d, exclusions)
    assert feasible > 50
    assert infeasible > 0


def test_one_constrained_coder_is_always_allocated_when_feasible() -> None:
    # the realistic case: one coder may not code the reports they corrected
    frame = synthetic_frame()
    ids = sorted(frame.record_ids)
    for seed in range(100):
        corrected = frozenset(random.Random(seed).sample(ids, 50))
        d = design(k=14, seed=seed)
        sample = draw_sample(frame, d)
        eligible = sample.record_ids - corrected
        per_layout = Counter(sample[r].layout for r in eligible)
        if len(eligible) < 14 or min(per_layout.values(), default=0) < 2:
            continue  # the sample itself cannot satisfy the design
        allocation = allocate_coders(sample, d, {"c1": corrected})
        allocation_holds(allocation, d, {"c1": corrected})


def test_matching_succeeds_where_greedy_would_fail() -> None:
    eligible = {"r1": ["c1", "c2"], "r2": ["c1", "c2"], "r3": ["c1"], "r4": ["c1"]}
    assigned = _match_singles(["r1", "r2", "r3", "r4"], eligible, {"c1": 2, "c2": 2})
    assert assigned == {"r1": "c2", "r2": "c2", "r3": "c1", "r4": "c1"}
    # the same structure through the public function, for every seed
    frame = SamplingFrame(tuple(FrameRecord(str(i), "layout_a") for i in range(1, 5)))
    exclusions = {"c2": frozenset({"3", "4"})}
    for seed in range(30):
        d = design(k=2, seed=seed, coders=("c1", "c2"), overlap=0, floor=0)
        allocation = allocate_coders(draw_sample(frame, d), d, exclusions)
        allocation_holds(allocation, d, exclusions)


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
