"""Resolve (stage 7): the only place observations and events are combined.

``review`` calls it for one record at a time; ``derive`` and ``evaluate`` read
its output; nothing here imports ``review``.
"""

from .events import MergedEvents, merge_events
from .values import (
    STATUSES,
    UNUSABLE_STATUSES,
    Resolved,
    ResolvedFlag,
    ResolvedValue,
    apply_event,
    highest,
    resolve_records,
)

__all__ = [
    "STATUSES",
    "UNUSABLE_STATUSES",
    "MergedEvents",
    "Resolved",
    "ResolvedFlag",
    "ResolvedValue",
    "apply_event",
    "highest",
    "merge_events",
    "resolve_records",
]
