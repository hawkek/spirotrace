"""Merging review events (seam 4): latest wins within one reviewer only; a
disagreement between reviewers is listed, never settled silently.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field

from spirotrace.store import Event


def _order(e: Event) -> tuple[str, int]:
    return (e.time, e.sequence)


def _same_answer(a: Event, b: Event) -> bool:
    return a.action == b.action and a.value.strip() == b.value.strip()


@dataclass(slots=True)
class MergedEvents:
    """Each key's latest event per reviewer, and the keys the reviewers disagree on."""

    latest: dict[str, dict[str, Event]] = field(default_factory=dict)
    disagreements: dict[str, dict[str, Event]] = field(default_factory=dict)
    count: int = 0
    reviewers: frozenset[str] = frozenset()

    def settled(self, key: str) -> Event | None:
        """The one answer every reviewer with an event on ``key`` agrees on, else None."""
        if key in self.disagreements:
            return None
        by_reviewer = self.latest.get(key)
        if not by_reviewer:
            return None
        return max(by_reviewer.values(), key=_order)

    def reviewers_of(self, key: str) -> tuple[str, ...]:
        return tuple(sorted(self.latest.get(key, {})))


def merge_events(events: Iterable[Event]) -> MergedEvents:
    """Keep the latest event per (key, reviewer); a ``withdraw`` retracts that
    reviewer's answer on the key; list keys whose reviewers' answers differ."""
    latest: dict[str, dict[str, Event]] = defaultdict(dict)
    reviewers: set[str] = set()
    count = 0
    for e in sorted(events, key=lambda e: (e.reviewer, e.key, _order(e))):
        count += 1
        reviewers.add(e.reviewer)
        if e.action == "withdraw":
            latest[e.key].pop(e.reviewer, None)
        else:
            latest[e.key][e.reviewer] = e
    merged = MergedEvents(count=count, reviewers=frozenset(reviewers))
    for key, by_reviewer in latest.items():
        if not by_reviewer:
            continue
        merged.latest[key] = dict(by_reviewer)
        answers = list(by_reviewer.values())
        if any(not _same_answer(answers[0], a) for a in answers[1:]):
            merged.disagreements[key] = dict(by_reviewer)
    return merged
