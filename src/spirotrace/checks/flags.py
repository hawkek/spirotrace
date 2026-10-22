"""Flags: what a rule says about a record or some of its observations.

A flag is raised by one rule and names the observations it rests on (none for
a record-level finding). Its severity is one the rule declared. ``confirm``
records agreement (a recalculation or a second reading that matches); it fills
``machine_confirmed_by`` on resolved values later and never sets a reviewer's
status. A suggestion is shown to the reviewer and never applied without an
event. The stored form of flags is settled in the phase 2 plan; this is the
in-memory form the rules produce.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from spirotrace.model import ObservationKey


class Severity(StrEnum):
    ERROR = "error"
    CHECK = "check"
    NOTE = "note"
    CONFIRM = "confirm"


LAYERS: tuple[str, ...] = (
    "input",
    "ocr",
    "range",
    "layout",
    "image",
    "consistency",
    "gli",
    "cohort",
    "free_text",
    "derived",
)
"""Rule layers in the order the ablation adds them."""


@dataclass(frozen=True, slots=True)
class Suggestion:
    """A value a rule offers the reviewer (never applied by the rule)."""

    value: str
    source: str


@dataclass(frozen=True, slots=True)
class Flag:
    rule_id: str
    layer: str
    severity: Severity
    record_id: str
    keys: tuple[ObservationKey, ...]
    page: int | None
    message: str
    suggestion: Suggestion | None = None

    @property
    def record_level(self) -> bool:
        return not self.keys
