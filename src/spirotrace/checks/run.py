"""Running the rules over read records (stage 5 and the cohort pass).

Per-record rules run in layer order, each seeing the flags the earlier layers
raised on the record. The gli rules need the bridge: without one they are
reported as not run, never as passed. The cohort rules run last, over all
records. Console output from any caller is counts only.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field

from spirotrace.config import Settings
from spirotrace.rspiro import GliResults, RspiroBridge, RspiroError

from . import (  # noqa: F401 - importing registers the rules
    rules_cohort,
    rules_consistency,
    rules_derived,
    rules_free_text,
    rules_gli,
    rules_image,
    rules_range,
    rules_reading,
    rules_second_ocr,
)
from .context import RecordContext, RecordInput
from .flags import Flag
from .registry import Rule, enabled_rules
from .rules_cohort import CohortStats
from .rules_gli import gli_inputs


@dataclass(slots=True)
class CheckRun:
    """The flags of one run and what did not run."""

    flags: list[Flag] = field(default_factory=list)
    rules_not_run: tuple[str, ...] = ()
    not_run_reason: str = ""
    gli_subjects: int = 0

    def counts(self) -> dict[tuple[str, str], int]:
        """Flag counts by (layer, severity): the console summary."""
        return dict(Counter((f.layer, f.severity.value) for f in self.flags))

    def by_rule(self) -> dict[str, int]:
        return dict(Counter(f.rule_id for f in self.flags))


def _run_rule(ctx: RecordContext, r: Rule, *extra: object) -> None:
    for f in r.fn(ctx, *extra):
        ctx.add(f)


def check_records(
    records: Sequence[RecordInput],
    settings: Settings,
    bridge: RspiroBridge | None = None,
    gli_results: GliResults | None = None,
) -> CheckRun:
    """Run every enabled rule over ``records``.

    ``bridge`` recalculates the GLI ranges; ``gli_results`` supplies them
    instead (tests, or a cached recalculation). With neither, the gli rules
    are listed in ``rules_not_run``.
    """
    rules = enabled_rules(settings.rules.off, settings.rules.layers_off)
    record_rules = [r for r in rules if r.scope == "record"]
    gli_rules = [r for r in rules if r.scope == "gli"]
    cohort_rules = [r for r in rules if r.scope == "cohort"]
    contexts = [RecordContext.of(rec) for rec in records]
    stats = CohortStats.of(contexts)
    run = CheckRun()
    # gli: one bridge call for the whole run
    results = gli_results
    if results is None and gli_rules and bridge is not None:
        subjects = [s for ctx in contexts for s in gli_inputs(ctx).subjects]
        run.gli_subjects = len(subjects)
        try:
            results = bridge.compute(subjects)
        except RspiroError as exc:
            results = None
            run.not_run_reason = str(exc)
    if results is None and gli_rules:
        run.rules_not_run = tuple(r.id for r in gli_rules)
        if not run.not_run_reason:
            run.not_run_reason = "no Rscript configured or found"
    demote = any(r.id == "cohort.column_empty_by_format" for r in rules)
    blank = any(r.id == "image.empty_cell_blank" for r in rules)
    for ctx in contexts:
        if demote:
            ctx.empty_by_format = stats.empty_by_format.get(ctx.layout, frozenset())
        if blank:
            ctx.blank_on_scan = rules_image.blank_on_scan(ctx)
        for r in record_rules:
            _run_rule(ctx, r)
        if results is not None:
            for r in gli_rules:
                _run_rule(ctx, r, results)
        for r in cohort_rules:
            _run_rule(ctx, r, stats)
        run.flags.extend(ctx.flags)
    return run
