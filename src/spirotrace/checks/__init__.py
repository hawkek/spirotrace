"""Rule registry and the rules (stage 5 and the cohort pass).

Every check is a named rule with an id, a layer (input, ocr, range, layout,
image, consistency, gli, cohort, free_text, derived), the severities it may
raise and a one-sentence rationale; ``rules.off`` and ``rules.layers_off``
switch rules off by id or layer. Thresholds live in one table with their
sources. Reading conditions become flags here, never inside reading code.
The curated list these rules implement was approved on 22 October 2026.
"""

from .context import RecordContext, RecordInput, decimals_of, half_unit
from .flags import LAYERS, Flag, Severity, Suggestion
from .registry import RULES, Rule, enabled_rules, rule
from .run import CheckRun, check_records
from .thresholds import (
    PARAMETER_LIMITS,
    ROLE_LIMITS,
    THRESHOLDS,
    Limits,
    Threshold,
    limits_for,
)

__all__ = [
    "LAYERS",
    "PARAMETER_LIMITS",
    "ROLE_LIMITS",
    "RULES",
    "THRESHOLDS",
    "CheckRun",
    "Flag",
    "Limits",
    "RecordContext",
    "RecordInput",
    "Rule",
    "Severity",
    "Suggestion",
    "Threshold",
    "check_records",
    "decimals_of",
    "enabled_rules",
    "half_unit",
    "limits_for",
    "rule",
]
