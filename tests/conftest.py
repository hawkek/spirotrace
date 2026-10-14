"""Shared synthetic inputs for the evaluate tests. No real record, value or layout."""

from __future__ import annotations

from collections.abc import Iterable

import pytest

from spirotrace.evaluate import FrameRecord, SampleDesign, SamplingFrame

FEATURES = ("hard", "post_bd", "volumes")
"""Neutral feature names used by the tests, in precedence order."""


def synthetic_frame(n_a: int = 58, n_b: int = 44) -> SamplingFrame:
    """A frame of two layouts with features spread deterministically.

    Layout ``layout_a`` gets ``post_bd`` on every third record and ``hard`` on
    every fifth; ``layout_b`` gets ``volumes`` on all but every seventh record
    and ``hard`` on every fourth. Record ids are plain numbers, with an ``A``
    and ``B`` pair for the first id so both record-id forms appear.
    """
    records = []
    for i in range(n_a):
        features = set()
        if i % 3 == 0:
            features.add("post_bd")
        if i % 5 == 0:
            features.add("hard")
        rid = "1A" if i == 0 else str(100 + i)
        records.append(FrameRecord(rid, "layout_a", frozenset(features)))
    for i in range(n_b):
        features = set()
        if i % 7 != 0:
            features.add("volumes")
        if i % 4 == 0:
            features.add("hard")
        rid = "1B" if i == 0 else str(200 + i)
        records.append(FrameRecord(rid, "layout_b", frozenset(features)))
    return SamplingFrame(tuple(records))


def design(
    k: int | Iterable[int] = 14,
    seed: int = 7,
    coders: tuple[str, ...] = ("c1", "c2", "c3"),
    overlap: int = 2,
    floor: int = 2,
) -> SampleDesign:
    ks = [k] * len(coders) if isinstance(k, int) else list(k)
    return SampleDesign(
        coders=coders,
        reports_per_coder=dict(zip(coders, ks, strict=True)),
        precedence=FEATURES,
        seed=seed,
        overlap_per_pair=overlap,
        min_per_stratum=floor,
    )


@pytest.fixture
def frame() -> SamplingFrame:
    return synthetic_frame()


@pytest.fixture
def make_design():
    return design
