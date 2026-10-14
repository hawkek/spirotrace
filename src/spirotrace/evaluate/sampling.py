"""Stratified draw of the reference sample.

The design fixes the coders, how many reports each codes, the overlap per
coder pair, the feature precedence that defines strata, and the seed. The
number of distinct reports follows: every coder's count, less the reports
each pair shares.

Allocation across strata is proportional to stratum size with a floor per
stratum (so every stratum is represented) and a cap at the stratum size,
rounded by largest remainder. The per-stratum sampling fraction is recorded
with every sampled record for weighting back to the cohort.
"""

from __future__ import annotations

import itertools
import random
import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from .frame import EvaluateError, FrameRecord, SamplingFrame, check_precedence

CODER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
"""Coder labels name output files, so they are limited to file-name-safe characters."""


def stage_rng(seed: int, stage: str) -> random.Random:
    """A generator for one stage (draw, allocation, sheet order), seeded from the design seed.

    String seeds are hashed the same way on every Python 3 version, so each
    stage's draws are reproducible and independent of the other stages.
    """
    return random.Random(f"{seed}:{stage}")


@dataclass(frozen=True)
class SampleDesign:
    """The reference-sample design.

    Parameters
    ----------
    coders
        Coder labels in a fixed order; pairs and output files follow it.
    reports_per_coder
        How many reports each coder codes, by coder label.
    precedence
        Feature names in precedence order; a record's stratum is its layout
        and the first of these features it has.
    seed
        Integer seed recorded with the sample.
    overlap_per_pair
        Reports shared by every pair of coders, for coder agreement.
    min_per_stratum
        Floor on the number sampled from each stratum (capped at its size).
    """

    coders: tuple[str, ...]
    reports_per_coder: Mapping[str, int]
    precedence: tuple[str, ...]
    seed: int
    overlap_per_pair: int = 2
    min_per_stratum: int = 2

    def __post_init__(self) -> None:
        coders = tuple(self.coders)
        if len(coders) < 2:
            raise EvaluateError("a design needs at least two coders")
        if len(set(coders)) != len(coders):
            raise EvaluateError("coder labels must be distinct")
        for coder in coders:
            if not CODER_RE.match(coder):
                raise EvaluateError(
                    f"coder label {coder!r} must be letters, digits, '_' or '-'"
                )
        per_coder = dict(self.reports_per_coder)
        if set(per_coder) != set(coders):
            raise EvaluateError(
                "reports_per_coder must name exactly the design's coders"
            )
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise EvaluateError("seed must be an integer")
        if self.overlap_per_pair < 0:
            raise EvaluateError("overlap_per_pair must be 0 or more")
        if self.min_per_stratum < 0:
            raise EvaluateError("min_per_stratum must be 0 or more")
        object.__setattr__(self, "coders", coders)
        object.__setattr__(self, "reports_per_coder", per_coder)
        object.__setattr__(self, "precedence", check_precedence(self.precedence))
        for coder in coders:
            k = per_coder[coder]
            if (
                isinstance(k, bool)
                or not isinstance(k, int)
                or k < self.overlap_reports_for(coder)
            ):
                raise EvaluateError(
                    f"coder {coder!r} codes {k!r} reports but shares "
                    f"{self.overlap_reports_for(coder)} overlap reports with the other coders"
                )

    @property
    def pairs(self) -> tuple[tuple[str, str], ...]:
        """Every pair of coders, in coder order."""
        return tuple(itertools.combinations(self.coders, 2))

    def overlap_reports_for(self, coder: str) -> int:
        """Overlap reports one coder codes: the overlap with each other coder."""
        return self.overlap_per_pair * (len(self.coders) - 1)

    def singles_for(self, coder: str) -> int:
        """Reports this coder codes alone."""
        return self.reports_per_coder[coder] - self.overlap_reports_for(coder)

    @property
    def n_overlap(self) -> int:
        """Distinct reports coded by two coders."""
        return self.overlap_per_pair * len(self.pairs)

    @property
    def n_distinct(self) -> int:
        """Distinct reports in the sample: all codings less the shared ones."""
        return sum(self.reports_per_coder.values()) - self.n_overlap


@dataclass(frozen=True)
class SampledRecord:
    """One sampled record with the figures needed to weight it back."""

    record_id: str
    layout: str
    stratum: str
    stratum_size: int
    sampled_in_stratum: int

    @property
    def sampling_fraction(self) -> float:
        return self.sampled_in_stratum / self.stratum_size


@dataclass(frozen=True)
class StratumCount:
    """How many records a stratum holds and how many were sampled from it."""

    stratum: str
    layout: str
    size: int
    sampled: int

    @property
    def sampling_fraction(self) -> float:
        return self.sampled / self.size


@dataclass(frozen=True)
class Sample:
    """The drawn sample: records sorted by id, plus the stratum table and the seed."""

    records: tuple[SampledRecord, ...]
    strata: tuple[StratumCount, ...]
    seed: int
    _by_id: dict[str, SampledRecord] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        records = tuple(sorted(self.records, key=lambda r: r.record_id))
        object.__setattr__(self, "records", records)
        object.__setattr__(self, "_by_id", {r.record_id: r for r in records})

    def __len__(self) -> int:
        return len(self.records)

    def __getitem__(self, record_id: str) -> SampledRecord:
        return self._by_id[record_id]

    @property
    def record_ids(self) -> frozenset[str]:
        return frozenset(self._by_id)

    @property
    def layouts(self) -> tuple[str, ...]:
        return tuple(sorted({r.layout for r in self.records}))


def allocate_across_strata(
    sizes: Mapping[str, int], n: int, floor: int
) -> dict[str, int]:
    """Proportional allocation of ``n`` draws across strata with a floor and a cap.

    Each stratum gets at least ``min(floor, size)`` and at most its size; the
    rest is proportional to size, rounded by largest remainder (ties broken by
    stratum name). Strata pinned at their floor or cap are removed and the
    remainder re-allocated until the allocation is stable.
    """
    if n < 0:
        raise EvaluateError("the number to sample must be 0 or more")
    total = sum(sizes.values())
    if n > total:
        raise EvaluateError(f"cannot sample {n} records from a frame of {total}")
    floors = {h: min(floor, size) for h, size in sizes.items()}
    if sum(floors.values()) > n:
        raise EvaluateError(
            f"the floor of {floor} per stratum over {len(sizes)} strata needs "
            f"{sum(floors.values())} records but the sample holds {n}"
        )
    pinned: dict[str, int] = {}
    while True:
        free = [h for h in sizes if h not in pinned]
        n_free = n - sum(pinned.values())
        size_free = sum(sizes[h] for h in free)
        quotas = {
            h: (n_free * sizes[h] / size_free if size_free else 0.0) for h in free
        }
        changed = False
        for h in free:
            if quotas[h] < floors[h]:
                pinned[h] = floors[h]
                changed = True
            elif quotas[h] > sizes[h]:
                pinned[h] = sizes[h]
                changed = True
        if not changed:
            break
    counts = dict(pinned)
    free = [h for h in sizes if h not in pinned]
    whole = {h: int(quotas[h]) for h in free}
    short = (n - sum(pinned.values())) - sum(whole.values())
    by_remainder = sorted(free, key=lambda h: (-(quotas[h] - whole[h]), h))
    for h in free:
        counts[h] = whole[h]
    for h in by_remainder[:short]:
        counts[h] += 1
    return {h: counts[h] for h in sizes}


def draw_sample(frame: SamplingFrame, design: SampleDesign) -> Sample:
    """Draw the stratified sample the design asks for from the frame."""
    groups = frame.strata(design.precedence)
    sizes = {stratum: len(records) for stratum, records in groups.items()}
    counts = allocate_across_strata(sizes, design.n_distinct, design.min_per_stratum)
    rng = stage_rng(design.seed, "draw")
    sampled: list[SampledRecord] = []
    strata: list[StratumCount] = []
    for stratum, records in groups.items():
        chosen: list[FrameRecord] = rng.sample(list(records), counts[stratum])
        sampled.extend(
            SampledRecord(
                r.record_id, r.layout, stratum, sizes[stratum], counts[stratum]
            )
            for r in chosen
        )
        strata.append(
            StratumCount(stratum, records[0].layout, sizes[stratum], counts[stratum])
        )
    return Sample(tuple(sampled), tuple(strata), design.seed)
