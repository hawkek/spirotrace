"""Flags: what a rule says about a record or some of its observations.

A flag is raised by one rule and names the observations it rests on (none for
a record-level finding). Its severity is one the rule declared. ``confirm``
records agreement (a recalculation or a second reading that matches); it fills
``machine_confirmed_by`` on resolved values later and never sets a reviewer's
status. A suggestion is shown to the reviewer and never applied without an
event. The stored form (one CSV row per flag) follows the phase 2 plan:
``flag_key`` names a flag across the raw run and the post-review rerun, whose
messages differ once a value changes.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar, Self

from spirotrace.model import ModelError, ObservationKey


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

    COLUMNS: ClassVar[tuple[str, ...]] = (
        "flag_key",
        "record_id",
        "rule_id",
        "layer",
        "severity",
        "page",
        "keys",
        "message",
        "suggestion_value",
        "suggestion_source",
    )

    @property
    def record_level(self) -> bool:
        return not self.keys

    @property
    def flag_key(self) -> str:
        """``rule|record|keys``: the flag's identity across reruns."""
        return f"{self.rule_id}|{self.record_id}|{self.keys_string}"

    @property
    def keys_string(self) -> str:
        return " ".join(k.to_string() for k in self.keys)

    def to_row(self) -> dict[str, str]:
        return {
            "flag_key": self.flag_key,
            "record_id": self.record_id,
            "rule_id": self.rule_id,
            "layer": self.layer,
            "severity": self.severity.value,
            "page": "" if self.page is None else str(self.page),
            "keys": self.keys_string,
            "message": self.message,
            "suggestion_value": ""
            if self.suggestion is None
            else self.suggestion.value,
            "suggestion_source": ""
            if self.suggestion is None
            else self.suggestion.source,
        }

    @classmethod
    def from_row(cls, row: Mapping[str, str]) -> Self:
        missing = [c for c in cls.COLUMNS if c not in row]
        if missing:
            raise ModelError(f"Flag row lacks columns: {', '.join(missing)}")
        keys = tuple(ObservationKey.from_string(k) for k in row["keys"].split())
        sv, ss = row["suggestion_value"], row["suggestion_source"]
        return cls(
            rule_id=row["rule_id"],
            layer=row["layer"],
            severity=Severity(row["severity"]),
            record_id=row["record_id"],
            keys=keys,
            page=int(row["page"]) if row["page"] else None,
            message=row["message"],
            suggestion=Suggestion(sv, ss) if sv or ss else None,
        )
