"""Sampling frame: the records a reference sample is drawn from.

A frame record carries only a record id, a layout label and the names of the
stratum features the record has. It holds no value, raw text or page, so
nothing extracted can reach a coding workbook through the frame.

A stratum is one layout crossed with one feature. A record with several
features goes to the first feature in the design's precedence list that it
has; a record with none of them goes to the layout's ``none`` stratum.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from ..model import RECORD_ID_RE, TEMPLATE_ID_RE

FEATURE_RE = re.compile(r"^[a-z][a-z0-9_]*$")

NO_FEATURE = "none"
"""Feature name of the stratum for records with none of the precedence features."""


class EvaluateError(ValueError):
    """An evaluation input or design is invalid."""


def stratum_id(layout: str, feature: str) -> str:
    """The stratum label used in manifests and counts: ``<layout>:<feature>``."""
    return f"{layout}:{feature}"


@dataclass(frozen=True)
class FrameRecord:
    """One record of the sampling frame.

    Parameters
    ----------
    record_id
        Record id as in the extraction store (see ``RECORD_ID_RE``).
    layout
        Neutral layout label (a template id).
    features
        Names of the stratum features this record has.
    """

    record_id: str
    layout: str
    features: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not RECORD_ID_RE.match(self.record_id):
            raise EvaluateError(
                f"record id {self.record_id!r} is not a valid record id"
            )
        if not TEMPLATE_ID_RE.match(self.layout):
            raise EvaluateError(f"layout {self.layout!r} is not a template id")
        object.__setattr__(self, "features", frozenset(self.features))
        for feature in self.features:
            if not FEATURE_RE.match(feature):
                raise EvaluateError(
                    f"feature name {feature!r} is not of the form [a-z][a-z0-9_]*"
                )
            if feature == NO_FEATURE:
                raise EvaluateError(
                    f"feature name {NO_FEATURE!r} is reserved for records with no feature"
                )


def check_precedence(precedence: Iterable[str]) -> tuple[str, ...]:
    """Validate a feature precedence list and return it as a tuple."""
    order = tuple(precedence)
    for feature in order:
        if not FEATURE_RE.match(feature) or feature == NO_FEATURE:
            raise EvaluateError(f"precedence holds an invalid feature name {feature!r}")
    if len(set(order)) != len(order):
        raise EvaluateError("precedence lists a feature twice")
    return order


@dataclass(frozen=True)
class SamplingFrame:
    """All records a sample can be drawn from, sorted by record id.

    Record ids are unique. The order records are given in does not matter:
    they are sorted on construction so that a seeded draw is reproducible.
    """

    records: tuple[FrameRecord, ...]

    def __post_init__(self) -> None:
        records = tuple(sorted(self.records, key=lambda r: r.record_id))
        if not records:
            raise EvaluateError("the sampling frame is empty")
        ids = [r.record_id for r in records]
        if len(set(ids)) != len(ids):
            raise EvaluateError("the sampling frame holds a record id more than once")
        object.__setattr__(self, "records", records)

    def __len__(self) -> int:
        return len(self.records)

    @property
    def layouts(self) -> tuple[str, ...]:
        """Layout labels present, sorted."""
        return tuple(sorted({r.layout for r in self.records}))

    @property
    def record_ids(self) -> frozenset[str]:
        return frozenset(r.record_id for r in self.records)

    def stratum_of(self, record: FrameRecord, precedence: Iterable[str]) -> str:
        """The stratum of ``record``: its layout and the first precedence feature it has."""
        for feature in check_precedence(precedence):
            if feature in record.features:
                return stratum_id(record.layout, feature)
        return stratum_id(record.layout, NO_FEATURE)

    def strata(self, precedence: Iterable[str]) -> dict[str, tuple[FrameRecord, ...]]:
        """Records grouped by stratum, strata and records both sorted."""
        order = check_precedence(precedence)
        groups: dict[str, list[FrameRecord]] = {}
        for record in self.records:
            groups.setdefault(self.stratum_of(record, order), []).append(record)
        return {stratum: tuple(groups[stratum]) for stratum in sorted(groups)}
