"""Sampling frame: validation, precedence and strata. All records synthetic."""

import pytest

from spirotrace.evaluate import EvaluateError, FrameRecord, SamplingFrame
from spirotrace.evaluate.frame import NO_FEATURE, check_precedence, stratum_id


def test_record_validates_id_layout_and_features() -> None:
    record = FrameRecord("12A-2", "layout_a", frozenset({"post_bd"}))
    assert record.features == frozenset({"post_bd"})
    with pytest.raises(EvaluateError, match="record id"):
        FrameRecord("12C", "layout_a")
    with pytest.raises(EvaluateError, match="template id"):
        FrameRecord("12", "Layout A")
    with pytest.raises(EvaluateError, match="feature name"):
        FrameRecord("12", "layout_a", frozenset({"Post BD"}))
    with pytest.raises(EvaluateError, match="reserved"):
        FrameRecord("12", "layout_a", frozenset({NO_FEATURE}))


def test_features_accept_any_iterable_and_freeze() -> None:
    record = FrameRecord("3", "layout_a", ["hard", "hard"])  # type: ignore[arg-type]
    assert record.features == frozenset({"hard"})


def test_frame_refuses_duplicates_and_empty() -> None:
    with pytest.raises(EvaluateError, match="more than once"):
        SamplingFrame((FrameRecord("1", "layout_a"), FrameRecord("1", "layout_b")))
    with pytest.raises(EvaluateError, match="empty"):
        SamplingFrame(())


def test_frame_sorts_records_so_input_order_does_not_matter() -> None:
    a, b, c = (
        FrameRecord("3", "layout_a"),
        FrameRecord("1", "layout_b"),
        FrameRecord("2", "layout_a"),
    )
    assert (
        SamplingFrame((a, b, c)).records
        == SamplingFrame((c, a, b)).records
        == (b, c, a)
    )
    assert SamplingFrame((a, b)).layouts == ("layout_a", "layout_b")
    assert SamplingFrame((a, b)).record_ids == {"3", "1"}
    assert len(SamplingFrame((a, b))) == 2


def test_stratum_follows_precedence_then_none() -> None:
    frame = SamplingFrame(
        (
            FrameRecord("1", "layout_a", frozenset({"post_bd", "hard"})),
            FrameRecord("2", "layout_a", frozenset({"post_bd"})),
            FrameRecord("3", "layout_b"),
        )
    )
    first, second, third = frame.records
    assert frame.stratum_of(first, ("hard", "post_bd")) == "layout_a:hard"
    assert frame.stratum_of(first, ("post_bd", "hard")) == "layout_a:post_bd"
    assert frame.stratum_of(second, ("hard", "post_bd")) == "layout_a:post_bd"
    assert frame.stratum_of(third, ("hard", "post_bd")) == stratum_id(
        "layout_b", NO_FEATURE
    )
    # a feature outside the precedence list is ignored
    assert frame.stratum_of(second, ("hard",)) == "layout_a:none"


def test_strata_groups_sorted() -> None:
    frame = SamplingFrame(
        (
            FrameRecord("2", "layout_b", frozenset({"hard"})),
            FrameRecord("1", "layout_a"),
            FrameRecord("3", "layout_a", frozenset({"hard"})),
        )
    )
    groups = frame.strata(("hard",))
    assert list(groups) == ["layout_a:hard", "layout_a:none", "layout_b:hard"]
    assert [r.record_id for r in groups["layout_a:hard"]] == ["3"]


def test_precedence_validation() -> None:
    assert check_precedence(["a", "b"]) == ("a", "b")
    with pytest.raises(EvaluateError, match="twice"):
        check_precedence(("a", "a"))
    with pytest.raises(EvaluateError, match="invalid feature"):
        check_precedence(("a", "none"))
    with pytest.raises(EvaluateError, match="invalid feature"):
        check_precedence(("A",))
