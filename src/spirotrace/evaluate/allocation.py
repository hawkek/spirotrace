"""Allocate the sampled reports to coders.

Every pair of coders shares ``overlap_per_pair`` reports, spread over the
layouts in the sample (two per pair over two layouts gives one of each); the
rest are coded once. A coder's exclusion list is never violated: a report is
eligible for a coder only if it is not on that coder's list, and a shared
report must be eligible for both coders of the pair.

Overlap reports are chosen pair by pair, the pair with the most constrained
coder first. The single reports are then matched to coder slots exactly
(augmenting paths), so a feasible assignment of singles is always found when
one exists. When no assignment exists the allocation stops with counts only;
nothing is redrawn.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field

from .frame import EvaluateError, SamplingFrame
from .sampling import Sample, SampleDesign, stage_rng


class AllocationError(EvaluateError):
    """No allocation satisfies the design and the exclusion lists."""


@dataclass(frozen=True)
class Assignment:
    """One sampled report and who codes it."""

    record_id: str
    layout: str
    stratum: str
    coders: tuple[str, ...]
    overlap: bool


@dataclass(frozen=True)
class Allocation:
    """Every sampled report with its coder or coders, sorted by record id.

    ``coders`` keeps the design's coder order, which fixes the order of the
    workbooks and the per-coder sheet shuffles.
    """

    coders: tuple[str, ...]
    assignments: tuple[Assignment, ...]
    _by_id: dict[str, Assignment] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        assignments = tuple(sorted(self.assignments, key=lambda a: a.record_id))
        named = {c for a in assignments for c in a.coders}
        if not named <= set(self.coders) or len(set(self.coders)) != len(self.coders):
            raise EvaluateError(
                "an assignment names a coder the allocation does not list"
            )
        object.__setattr__(self, "coders", tuple(self.coders))
        object.__setattr__(self, "assignments", assignments)
        object.__setattr__(self, "_by_id", {a.record_id: a for a in assignments})

    def __len__(self) -> int:
        return len(self.assignments)

    def __getitem__(self, record_id: str) -> Assignment:
        return self._by_id[record_id]

    @property
    def layouts(self) -> tuple[str, ...]:
        return tuple(sorted({a.layout for a in self.assignments}))

    def for_coder(self, coder: str) -> tuple[Assignment, ...]:
        return tuple(a for a in self.assignments if coder in a.coders)


def _exclusions(
    design: SampleDesign, exclusions: Mapping[str, Collection[str]]
) -> dict[str, frozenset[str]]:
    unknown = set(exclusions) - set(design.coders)
    if unknown:
        raise EvaluateError(
            f"exclusion lists name coders not in the design: {sorted(unknown)}"
        )
    return {c: frozenset(exclusions.get(c, ())) for c in design.coders}


def check_frame(
    frame: SamplingFrame,
    design: SampleDesign,
    exclusions: Mapping[str, Collection[str]],
) -> None:
    """Stop before drawing if the frame cannot satisfy the design at all.

    The frame must hold at least ``n_distinct`` records, and each coder must
    have at least as many eligible records in it as they are to code.
    """
    excluded = _exclusions(design, exclusions)
    if len(frame) < design.n_distinct:
        raise AllocationError(
            f"the frame holds {len(frame)} records but the design needs {design.n_distinct}"
        )
    for coder in design.coders:
        eligible = len(frame.record_ids - excluded[coder])
        if eligible < design.reports_per_coder[coder]:
            raise AllocationError(
                f"coder {coder!r} has {eligible} eligible records in the frame "
                f"but is to code {design.reports_per_coder[coder]}"
            )


def _match_singles(
    reports: list[str],
    eligible_coders: Mapping[str, list[str]],
    capacity: Mapping[str, int],
) -> dict[str, str]:
    """Assign every report to one eligible coder within capacities, or as many as possible.

    Kuhn's augmenting-path matching with coder capacities: when a coder is
    full, one of their reports is re-routed to another eligible coder if that
    frees a slot. Returns ``{record_id: coder}``.
    """
    assigned: dict[str, str] = {}
    held: dict[str, list[str]] = {c: [] for c in capacity}

    def place(report: str, visited: set[str]) -> bool:
        for coder in eligible_coders[report]:
            if coder in visited:
                continue
            visited.add(coder)
            if len(held[coder]) < capacity[coder]:
                assigned[report] = coder
                held[coder].append(report)
                return True
            for other in list(held[coder]):
                if place(other, visited):  # moved to another coder, freeing a slot here
                    held[coder].remove(other)
                    assigned[report] = coder
                    held[coder].append(report)
                    return True
        return False

    for report in reports:
        place(report, set())
    return assigned


def allocate_coders(
    sample: Sample, design: SampleDesign, exclusions: Mapping[str, Collection[str]]
) -> Allocation:
    """Allocate every sampled report to one coder, or to a pair for the overlap."""
    excluded = _exclusions(design, exclusions)
    eligible = {c: sample.record_ids - excluded[c] for c in design.coders}
    for coder in design.coders:
        if len(eligible[coder]) < design.reports_per_coder[coder]:
            raise AllocationError(
                f"coder {coder!r} has {len(eligible[coder])} eligible reports in the sample "
                f"but is to code {design.reports_per_coder[coder]}; draw again with another "
                "seed (recorded) or change the design"
            )
    rng = stage_rng(design.seed, "allocate")
    layouts = list(sample.layouts)
    overlap: dict[str, tuple[str, str]] = {}
    # the pair whose coders have the fewest eligible reports chooses first
    pairs = sorted(
        design.pairs, key=lambda p: (min(len(eligible[p[0]]), len(eligible[p[1]])),)
    )
    for pair in pairs:
        rng.shuffle(layouts)
        both = eligible[pair[0]] & eligible[pair[1]]
        others = [c for c in design.coders if c not in pair]
        for slot in range(design.overlap_per_pair):
            layout = layouts[slot % len(layouts)]
            # prefer reports the other coders may not code, so a constrained coder
            # keeps the reports only they can take
            by_demand = sorted(
                (sum(r in eligible[c] for c in others), r)
                for r in both
                if r not in overlap and sample[r].layout == layout
            )
            candidates = [r for demand, r in by_demand if demand == by_demand[0][0]]
            if not candidates:
                raise AllocationError(
                    f"no report of layout {layout!r} is left that both coders of pair "
                    f"{pair[0]!r} and {pair[1]!r} may code (overlap report {slot + 1} of "
                    f"{design.overlap_per_pair}); draw again with another seed (recorded) "
                    "or change the design"
                )
            overlap[rng.choice(candidates)] = pair
    singles = sorted(sample.record_ids - set(overlap))
    rng.shuffle(singles)
    coder_order = list(design.coders)
    eligible_coders: dict[str, list[str]] = {}
    for report in singles:
        rng.shuffle(coder_order)
        eligible_coders[report] = [c for c in coder_order if report in eligible[c]]
    capacity = {c: design.singles_for(c) for c in design.coders}
    assigned = _match_singles(singles, eligible_coders, capacity)
    if len(assigned) < len(singles):
        counts = ", ".join(
            f"{c!r}: {sum(1 for r in singles if r in eligible[c])} eligible for "
            f"{capacity[c]} single reports"
            for c in design.coders
        )
        raise AllocationError(
            f"{len(singles) - len(assigned)} of {len(singles)} single reports cannot be given "
            f"to any coder within the exclusion lists ({counts}); draw again with another "
            "seed (recorded) or change the design"
        )
    assignments = [
        Assignment(r, sample[r].layout, sample[r].stratum, pair, True)
        for r, pair in overlap.items()
    ] + [
        Assignment(r, sample[r].layout, sample[r].stratum, (coder,), False)
        for r, coder in assigned.items()
    ]
    allocation = Allocation(design.coders, tuple(assignments))
    _check_allocation(allocation, design, excluded)
    return allocation


def _check_allocation(
    allocation: Allocation, design: SampleDesign, excluded: Mapping[str, frozenset[str]]
) -> None:
    """Assert the design and the exclusion lists hold; a failure here is a bug, not an input."""
    for coder in design.coders:
        mine = allocation.for_coder(coder)
        if len(mine) != design.reports_per_coder[coder]:
            raise AllocationError(
                f"internal error: coder {coder!r} was given {len(mine)} reports"
            )
        if any(a.record_id in excluded[coder] for a in mine):
            raise AllocationError(
                f"internal error: coder {coder!r} was given an excluded report"
            )
    for pair in design.pairs:
        shared = sum(1 for a in allocation.assignments if a.coders == pair)
        if shared != design.overlap_per_pair:
            raise AllocationError(
                f"internal error: pair {pair!r} shares {shared} reports"
            )
