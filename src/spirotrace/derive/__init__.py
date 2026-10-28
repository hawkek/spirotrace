"""Derive (stage 8): variables computed from resolved values only.

Pattern (ATS/ERS 2022 flowchart), PRISm and severity rest on the printed,
resolved z and LLN as the old script's did (G2 answer 5); the recalculated GLI
values are their own ``gli_*`` rows, and ``pattern_gli`` applies the same
flowchart to the recalculated z. A row records the keys of its inputs, their
statuses and open flag severities. An input is usable when its status is not
unreadable, excluded or reviewer disagreement and it carries no open error;
open checks pass and are recorded. The rules of scope ``derived`` run here on
each record's rows. Nothing prints.
"""

from .derive import (
    DERIVED_NAMES,
    PATTERNS,
    DerivedRow,
    DeriveRun,
    derive_records,
    pattern_from_flags,
    pattern_from_text,
    severity_of,
)

__all__ = [
    "DERIVED_NAMES",
    "PATTERNS",
    "DeriveRun",
    "DerivedRow",
    "derive_records",
    "pattern_from_flags",
    "pattern_from_text",
    "severity_of",
]
