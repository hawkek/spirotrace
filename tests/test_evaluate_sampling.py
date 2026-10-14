"""Stratified draw: design arithmetic, allocation across strata, reproducibility."""

from collections import Counter

import pytest
from conftest import FEATURES, design, synthetic_frame

from spirotrace.evaluate import (
    EvaluateError,
    FrameRecord,
    SampleDesign,
    SamplingFrame,
    draw_sample,
)
from spirotrace.evaluate.sampling import allocate_across_strata, stage_rng

# --- design ------------------------------------------------------------------


def test_three_coders_two_per_pair_gives_3k_minus_6() -> None:
    d = design(k=14)
    assert d.pairs == (("c1", "c2"), ("c1", "c3"), ("c2", "c3"))
    assert d.n_overlap == 6
    assert d.overlap_reports_for("c1") == 4
    assert d.singles_for("c1") == 10
    assert d.n_distinct == 36
    assert design(k=17).n_distinct == 45


def test_unequal_reports_per_coder() -> None:
    d = design(k=(14, 10, 6))
    assert d.n_distinct == 30 - 6
    assert d.singles_for("c3") == 2
    with pytest.raises(EvaluateError, match="shares 4 overlap"):
        design(k=(14, 10, 3))


def test_two_coders_and_no_overlap() -> None:
    d = design(k=5, coders=("x", "y"), overlap=0)
    assert d.pairs == (("x", "y"),)
    assert d.n_overlap == 0
    assert d.n_distinct == 10


def test_design_validation() -> None:
    with pytest.raises(EvaluateError, match="two coders"):
        design(coders=("solo",))
    with pytest.raises(EvaluateError, match="distinct"):
        design(coders=("a", "a", "b"))
    with pytest.raises(EvaluateError, match="letters, digits"):
        design(coders=("a b", "c", "d"))
    with pytest.raises(EvaluateError, match="exactly the design's coders"):
        SampleDesign(("a", "b"), {"a": 5, "c": 5}, FEATURES, seed=1)
    with pytest.raises(EvaluateError, match="integer"):
        SampleDesign(("a", "b"), {"a": 5, "b": 5}, FEATURES, seed="7")  # type: ignore[arg-type]
    with pytest.raises(EvaluateError, match="integer"):
        SampleDesign(("a", "b"), {"a": 5, "b": 5}, FEATURES, seed=True)
    with pytest.raises(EvaluateError, match="overlap_per_pair"):
        design(overlap=-1)
    with pytest.raises(EvaluateError, match="min_per_stratum"):
        design(floor=-1)
    with pytest.raises(EvaluateError, match="codes 4.5"):
        SampleDesign(("a", "b"), {"a": 4.5, "b": 5}, FEATURES, seed=1)  # type: ignore[dict-item]
    with pytest.raises(EvaluateError, match="twice"):
        SampleDesign(("a", "b"), {"a": 5, "b": 5}, ("f", "f"), seed=1)


# --- allocation across strata -------------------------------------------------


def test_proportional_with_floor_and_cap() -> None:
    sizes = {"a:none": 40, "a:hard": 10, "b:none": 48, "b:hard": 2}
    counts = allocate_across_strata(sizes, 36, floor=2)
    assert sum(counts.values()) == 36
    assert counts["b:hard"] == 2  # capped at its size (and at the floor)
    # the other 34 go proportionally over 98 records: 13.9, 3.5, 16.7
    assert counts == {"a:none": 14, "a:hard": 3, "b:none": 17, "b:hard": 2}


def test_floor_lifts_a_small_stratum() -> None:
    sizes = {"big": 97, "tiny": 3}
    assert allocate_across_strata(sizes, 20, floor=2) == {"big": 18, "tiny": 2}
    assert allocate_across_strata(sizes, 20, floor=0) == {"big": 19, "tiny": 1}
    # a stratum smaller than the floor is taken whole
    assert allocate_across_strata({"big": 97, "one": 1}, 20, floor=2) == {
        "big": 19,
        "one": 1,
    }


def test_largest_remainder_ties_break_by_name() -> None:
    assert allocate_across_strata({"x": 10, "y": 10, "z": 10}, 4, floor=0) == {
        "x": 2,
        "y": 1,
        "z": 1,
    }


def test_allocation_refusals() -> None:
    with pytest.raises(EvaluateError, match="cannot sample 11"):
        allocate_across_strata({"a": 5, "b": 5}, 11, floor=0)
    with pytest.raises(EvaluateError, match="floor of 2"):
        allocate_across_strata({"a": 5, "b": 5, "c": 5}, 5, floor=2)
    with pytest.raises(EvaluateError, match="0 or more"):
        allocate_across_strata({"a": 5}, -1, floor=0)
    assert allocate_across_strata({"a": 5}, 0, floor=0) == {"a": 0}


# --- draw ---------------------------------------------------------------------


def test_draw_matches_allocation_and_records_fractions() -> None:
    frame = synthetic_frame()
    d = design(k=14, seed=3)
    sample = draw_sample(frame, d)
    sizes = {s: len(r) for s, r in frame.strata(FEATURES).items()}
    expected = allocate_across_strata(sizes, 36, 2)
    assert len(sample) == 36
    assert Counter(r.stratum for r in sample.records) == expected
    assert {s.stratum: s.sampled for s in sample.strata} == expected
    for record in sample.records:
        assert record.stratum_size == sizes[record.stratum]
        assert record.sampled_in_stratum == expected[record.stratum]
        assert (
            record.sampling_fraction == expected[record.stratum] / sizes[record.stratum]
        )
        assert record.record_id in frame.record_ids
        assert sample[record.record_id] is record
    assert sample.seed == 3
    assert sample.layouts == ("layout_a", "layout_b")
    assert sum(s.sampling_fraction * s.size for s in sample.strata) == pytest.approx(36)


def test_same_seed_same_sample_regardless_of_input_order() -> None:
    frame = synthetic_frame()
    shuffled = SamplingFrame(tuple(reversed(frame.records)))
    first = draw_sample(frame, design(seed=11))
    assert first == draw_sample(frame, design(seed=11))
    assert first == draw_sample(shuffled, design(seed=11))
    assert first.record_ids != draw_sample(frame, design(seed=12)).record_ids


def test_stage_generators_are_reproducible_and_independent() -> None:
    assert stage_rng(5, "draw").random() == stage_rng(5, "draw").random()
    assert stage_rng(5, "draw").random() != stage_rng(5, "allocate").random()
    assert stage_rng(5, "draw").random() != stage_rng(6, "draw").random()


def test_draw_refuses_more_than_the_frame_holds() -> None:
    small = SamplingFrame(tuple(FrameRecord(str(i), "layout_a") for i in range(10)))
    with pytest.raises(EvaluateError, match="cannot sample 36"):
        draw_sample(small, design(k=14))
