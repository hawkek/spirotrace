"""Rules that run after derive, on a record's derived rows (scope ``derived``).

Each rule is called with the record's context (its resolved observations) and
a mapping of derived name to row; a row has ``value`` (``""`` when not
computed), ``status``, ``basis`` and ``inputs`` (observation keys). The
report's own statements are checked against what the numbers give.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from typing import Protocol

from spirotrace.model import ColumnRole, ObservationKey, Parameter, ValueState

from .context import RecordContext
from .flags import Flag, Severity
from .registry import rule
from .thresholds import T

C, N = Severity.CHECK, Severity.NOTE


class DerivedLike(Protocol):
    @property
    def value(self) -> str: ...
    @property
    def status(self) -> str: ...
    @property
    def basis(self) -> str: ...
    @property
    def inputs(self) -> Sequence[ObservationKey]: ...


Derived = Mapping[str, DerivedLike]

PATTERN_COMPAT: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "normal": (frozenset({"normal"}), frozenset()),
    "obstruction": (frozenset({"obstructive"}), frozenset()),
    "obstruction, possible mixed": (frozenset({"obstructive", "mixed"}), frozenset()),
    "possible restriction": (frozenset({"restrictive", "nonspecific"}), frozenset()),
    "restriction": (frozenset({"restrictive"}), frozenset()),
    "mixed": (frozenset({"mixed"}), frozenset({"obstructive"})),
    "non-specific": (frozenset({"nonspecific"}), frozenset({"restrictive"})),
}
"""Report categories that agree with each computed pattern (agree, near miss)."""


@rule(
    "derived.pattern_not_computed",
    "derived",
    C,
    "A pattern needs the ratio and FVC z (or value and LLN) unflagged; say so when it cannot be computed",
    scope="derived",
)
def pattern_not_computed(ctx: RecordContext, derived: Derived) -> Iterator[Flag]:
    row = derived.get("pattern")
    if row is not None and row.value == "":
        yield ctx.flag(
            "derived.pattern_not_computed",
            "pattern not computed: FEV1/FVC or FVC z-score / LLN missing or flagged",
            row.inputs,
        )


@rule(
    "derived.bdr_exactly_threshold",
    "derived",
    N,
    "A change of exactly the threshold is positive under the lab's >= rule, not under ATS/ERS 2022 >",
    scope="derived",
)
def bdr_exactly_threshold(ctx: RecordContext, derived: Derived) -> Iterator[Flag]:
    t = T("bdr_pct_pred")
    for name in ("bdr_fev1_pct_pred", "bdr_fvc_pct_pred"):
        row = derived.get(name)
        if row is None or row.value == "":
            continue
        if abs(float(row.value) - t) < 1e-9:
            yield ctx.flag(
                "derived.bdr_exactly_threshold",
                f"change of exactly {t:g}% of predicted: positive under the lab's >= rule, "
                "not under the ATS/ERS 2022 > rule",
                row.inputs,
            )


@rule(
    "derived.bdr_column_not_pct_pred",
    "derived",
    N,
    "The printed BDR column is used for the 2022 rule only when it is the change in percent predicted",
    scope="derived",
)
def bdr_column_not_pct_pred(ctx: RecordContext, derived: Derived) -> Iterator[Flag]:
    for name in ("bdr_fev1_pct_pred", "bdr_fvc_pct_pred"):
        row = derived.get(name)
        if row is None or not row.basis.startswith("note:"):
            continue
        yield ctx.flag(
            "derived.bdr_column_not_pct_pred",
            row.basis.removeprefix("note:").strip(),
            row.inputs,
        )


@rule(
    "free_text.report_pattern_vs_computed",
    "free_text",
    (C, N),
    "The pattern stated in the report must agree with the pattern computed from the z-scores",
    scope="derived",
)
def report_pattern_vs_computed(ctx: RecordContext, derived: Derived) -> Iterator[Flag]:
    calc, rep = derived.get("pattern"), derived.get("report_pattern")
    prism = derived.get("prism")
    if calc is None or rep is None or not calc.value or rep.value in ("", "other"):
        return
    ok, near = PATTERN_COMPAT[calc.value]
    if calc.value == "normal" and prism is not None and prism.value == "yes":
        near = near | {"nonspecific"}  # PRISm: the report may call this non-specific
    if rep.value in ok:
        return
    sev = N if rep.value in near else C
    yield ctx.flag(
        "free_text.report_pattern_vs_computed",
        f"computed pattern '{calc.value}' differs from the report's '{rep.value}' "
        "(check the z-scores, LLNs and the interpretation text)",
        (*calc.inputs, *rep.inputs),
        severity=sev,
    )


@rule(
    "free_text.bdr_statement_vs_computed",
    "free_text",
    C,
    "The report's statement on bronchodilator response must agree with the computed response",
    scope="derived",
)
def bdr_statement_vs_computed(ctx: RecordContext, derived: Derived) -> Iterator[Flag]:
    pos = derived.get("bdr_positive_2022")
    st = ctx.get(Parameter.BDR_SIGNIFICANT, ColumnRole.FREE_TEXT)
    if (
        pos is None
        or pos.value == ""
        or st is None
        or st.value_state is not ValueState.VALUE
        or not st.parsed_text
    ):
        return
    if st.parsed_text != pos.value:
        yield ctx.flag(
            "free_text.bdr_statement_vs_computed",
            f"report says bronchodilator response significant = {st.parsed_text}, "
            f"numbers give {pos.value}",
            (st.key, *pos.inputs),
        )
