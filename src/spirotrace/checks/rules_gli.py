"""GLI layer: the printed z-scores, lower limits, predicted and percent
predicted values against a recalculation through the rspiro bridge.

Inputs per record: sex, age, height and the ethnic group named in the
reference-equation line; the printed value's rounding interval; age printed
truncated or rounded; height to half a printed unit. A printed value inside
the recalculated range is confirmed; one outside is a check on the value and
the z. A device may compute the z from one trial's values rather than the
printed best (a match explains the gap but does not confirm it); for the ratio
the candidates also include FEV1 / max(FVC, FIVC) and, from README 0.3.15,
best FEV1 / best FVC.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field

from spirotrace.model import ColumnRole, Observation, Parameter, ValueState
from spirotrace.rspiro import ETHNIC_GROUPS, GliRange, GliResults, GliSubject

from .context import RecordContext, half_unit
from .flags import Flag, Severity
from .registry import rule
from .thresholds import DLCO_SI_UNITS, T

E, C, N, CONFIRM = Severity.ERROR, Severity.CHECK, Severity.NOTE, Severity.CONFIRM
P, R = Parameter, ColumnRole

ETHNIC_PATTERNS: tuple[tuple[str, int], ...] = (
    (r"cauc|white|europ", 1),
    (r"african|black", 2),
    (r"north\s*-?\s*east|\bne\b|n\.?e\.? ?asian", 3),
    (r"south\s*-?\s*east|\bse\b|s\.?e\.? ?asian", 4),
    (r"other|mixed", 5),
)
OTHER_EQUATIONS = re.compile(
    r"\bgli\b|\b(?:19|20)\d\d\b|nhanes|eccs|ecsc|knudson|hankinson|\bjrs\b|global",
    re.IGNORECASE,
)
"""A reference text that names an equation set or a year: without "2012" it is
not GLI 2012 and the record is skipped."""
SPIRO_PHASES: tuple[
    tuple[str, ColumnRole, ColumnRole, ColumnRole, ColumnRole, ColumnRole], ...
] = (
    ("pre", R.PRE, R.LLN, R.PCTPRED, R.Z, R.TRIAL),
    ("post", R.POST, R.POST_LLN, R.POST_PCTPRED, R.POST_Z, R.POST_TRIAL),
)
DIFFUSION: tuple[tuple[Parameter, str], ...] = (
    (P.DLCO, "TLCO"),
    (P.KCO, "KCO"),
    (P.VA, "VA"),
)
GLI_PARAM: dict[Parameter, str] = {P.FEV1: "FEV1", P.FVC: "FVC", P.FEV1_FVC: "FEV1FVC"}


@dataclass(frozen=True, slots=True)
class Demographics:
    sex: int
    ethnicity: int
    age_lo: float
    age_hi: float
    height_lo: float
    height_hi: float


@dataclass(slots=True)
class GliInputs:
    """What one record sends to the bridge, keyed so the results come back to it."""

    subjects: list[GliSubject] = field(default_factory=list)
    skipped: str = ""


def demographics(ctx: RecordContext) -> tuple[Demographics | None, str]:
    """The record's GLI inputs, or (None, reason)."""
    sex_text = (ctx.text(P.SEX, R.MEASURED) or "").strip().lower()
    sex = 2 if sex_text.startswith("f") else (1 if sex_text.startswith("m") else None)
    age, ht = (
        ctx.usable_unflagged(P.AGE, R.MEASURED),
        ctx.usable_unflagged(P.HEIGHT, R.MEASURED),
    )
    ref = ctx.text(P.REFERENCE_SPIROMETRY, R.MEASURED) or ""
    if OTHER_EQUATIONS.search(ref) and "2012" not in ref:
        # a layout whose label carries the equation stores only the group (e.g.
        # "Caucasian"); only a text naming other equations or another year skips
        return None, "reference equations are not GLI 2012"
    eth = next(
        (code for pat, code in ETHNIC_PATTERNS if re.search(pat, ref, re.IGNORECASE)),
        None,
    )
    missing = [
        name
        for name, x in (
            ("sex", sex),
            ("age", age),
            ("height", ht),
            ("GLI ethnic group", eth),
        )
        if x is None
    ]
    if missing:
        return None, "missing or flagged: " + ", ".join(missing)
    assert age is not None and ht is not None and sex is not None and eth is not None
    assert age.parsed_value is not None and ht.parsed_value is not None
    if not T("gli_age_min") <= age.parsed_value <= T("gli_age_max"):
        return (
            None,
            f"age {age.parsed_value:g} is outside the GLI-2012 range (3 to 95 years)",
        )
    hstep = (
        T("gli_height_step_decimal")
        if re.search(r"[.,]", ht.raw_text)
        else T("gli_height_step_whole")
    )
    return (
        Demographics(
            sex,
            eth,
            max(T("gli_age_min"), age.parsed_value - T("gli_age_below")),
            min(T("gli_age_max"), age.parsed_value + T("gli_age_above")),
            ht.parsed_value - hstep,
            ht.parsed_value + hstep,
        ),
        "",
    )


def _vh(o: Observation | None) -> tuple[float, float] | None:
    if o is None or o.parsed_value is None:
        return None
    return o.parsed_value, half_unit(o)


def gli_inputs(ctx: RecordContext) -> GliInputs:
    """Build the bridge subjects for one record (ids ``<record>|<phase>[|<candidate>]``)."""
    demo, why = demographics(ctx)
    if demo is None:
        return GliInputs(skipped=why)

    def make(
        sid: str, values: dict[str, tuple[float, float]], **kw: bool
    ) -> GliSubject:
        return GliSubject(
            sid,
            demo.sex,
            demo.ethnicity,
            demo.age_lo,
            demo.age_hi,
            demo.height_lo,
            demo.height_hi,
            values,
            **kw,
        )

    out = GliInputs()
    rid = ctx.record_id
    for phase, vrole, _lrole, _prole, zrole, trole in SPIRO_PHASES:
        values = {}
        for param, name in GLI_PARAM.items():
            vh = _vh(ctx.usable_unflagged(param, vrole))
            if vh is not None:
                values[name] = vh
        if not values:
            continue
        alt = (
            phase == "pre"
            and ctx.get(P.FEV1_FVC, zrole, 2) is not None
            or ctx.get(P.FEV1, zrole, 2) is not None
        )
        out.subjects.append(make(f"{rid}|{phase}", values, alt=bool(alt)))
        # the device may compute z from one trial: send every trial column too
        positions = sorted(
            {pos for p in GLI_PARAM for pos in ctx.positions(p, trole) if pos != 1}
        )
        for pos in positions:
            tv = {}
            for param, name in GLI_PARAM.items():
                vh = _vh(ctx.usable_unflagged(param, trole, pos))
                if vh is not None:
                    tv[name] = vh
            if tv:
                out.subjects.append(make(f"{rid}|{phase}|pos{pos}", tv))
        f1, fv, fi = (ctx.usable_unflagged(p, vrole) for p in (P.FEV1, P.FVC, P.FIVC))
        if f1 is not None and fv is not None and f1.parsed_value and fv.parsed_value:
            if fi is not None and fi.parsed_value and fi.parsed_value > fv.parsed_value:
                ratio = f1.parsed_value / fi.parsed_value
                h = ratio * (
                    half_unit(f1) / f1.parsed_value + half_unit(fi) / fi.parsed_value
                )
                out.subjects.append(
                    make(f"{rid}|{phase}|fivc", {"FEV1FVC": (ratio, h)})
                )
            # README 0.3.15: the printed Best ratio is one trial's ratio; ATS/ERS defines
            # the ratio from the best values, which some devices use for the z
            ratio = f1.parsed_value / fv.parsed_value
            h = ratio * (
                half_unit(f1) / f1.parsed_value + half_unit(fv) / fv.parsed_value
            )
            out.subjects.append(make(f"{rid}|{phase}|best", {"FEV1FVC": (ratio, h)}))
    dvals = {}
    for param, name in DIFFUSION:
        vh = _vh(ctx.usable_unflagged(param, R.MEASURED))
        if vh is not None:
            dvals[name] = vh
    if dvals:
        out.subjects.append(make(f"{rid}|diffusion", dvals, si=DLCO_SI_UNITS))
    return out


def _gap(z: float, g: GliRange) -> float:
    assert g.z_min is not None and g.z_max is not None
    if z > g.z_max:
        return z - g.z_max
    if z < g.z_min:
        return z - g.z_min
    return 0.0


def _inside(z: float, g: GliRange) -> bool:
    assert g.z_min is not None and g.z_max is not None
    s = T("gli_range_slack")
    return g.z_min - s <= z <= g.z_max + s


@dataclass(slots=True)
class _Row:
    """One printed (value, z, LLN, %pred, predicted) set and its recalculation."""

    label: str
    v: Observation
    z: Observation | None
    lln: Observation | None
    pctpred: Observation | None
    pred: Observation | None
    g: GliRange
    candidates: list[tuple[str, GliRange]]
    z2: Observation | None = None


def _rows(ctx: RecordContext, results: GliResults) -> Iterator[_Row]:
    rid = ctx.record_id
    for phase, vrole, lrole, prole, zrole, trole in SPIRO_PHASES:
        for param, name in GLI_PARAM.items():
            g = results.get((f"{rid}|{phase}", name))
            v = ctx.usable_unflagged(param, vrole)
            if g is None or v is None:
                continue
            cands = []
            for pos in sorted(
                {pos for p in GLI_PARAM for pos in ctx.positions(p, trole) if pos != 1}
            ):
                tg = results.get((f"{rid}|{phase}|pos{pos}", name))
                if tg is not None and tg.has_z:
                    cands.append((f"trial position {pos}", tg))
            if param is P.FEV1_FVC:
                for cid, label in (
                    ("best", "best FEV1 / best FVC"),
                    ("fivc", "FEV1/max(FVC,FIVC)"),
                ):
                    tg = results.get((f"{rid}|{phase}|{cid}", name))
                    if tg is not None and tg.has_z:
                        cands.append((label, tg))
            yield _Row(
                f"{param.value} {phase}",
                v,
                ctx.usable_unflagged(param, zrole),
                ctx.usable_unflagged(param, lrole),
                ctx.usable_unflagged(param, prole),
                None,
                g,
                cands,
                ctx.usable_unflagged(param, zrole, 2),
            )
    for param, name in DIFFUSION:
        g = results.get((f"{rid}|diffusion", name))
        v = ctx.usable_unflagged(param, R.MEASURED)
        if g is None or v is None:
            continue
        yield _Row(
            param.value,
            v,
            ctx.usable_unflagged(param, R.Z),
            ctx.usable_unflagged(param, R.LLN),
            ctx.usable_unflagged(param, R.PCTPRED),
            ctx.usable_unflagged(param, R.PREDICTED),
            g,
            [],
        )


DEMO = "age, height, sex and ethnic group as read"


@rule(
    "gli.z_agrees",
    "gli",
    CONFIRM,
    "A printed z inside the range recalculated from the printed value backs both",
    scope="gli",
)
def z_agrees(ctx: RecordContext, results: GliResults) -> Iterator[Flag]:
    for row in _rows(ctx, results):
        if row.z is None or not row.g.has_z or row.z.parsed_value is None:
            continue
        if _inside(row.z.parsed_value, row.g):
            yield ctx.flag(
                "gli.z_agrees",
                f"{row.label}: z matches the GLI recalculation",
                [row.v, row.z],
            )


@rule(
    "gli.z_agrees_from_best_ratio",
    "gli",
    CONFIRM,
    "A ratio z that matches best FEV1 over best FVC is computed as ATS/ERS defines the ratio",
    scope="gli",
)
def z_agrees_from_best_ratio(ctx: RecordContext, results: GliResults) -> Iterator[Flag]:
    for row in _rows(ctx, results):
        if row.z is None or not row.g.has_z or row.z.parsed_value is None:
            continue
        if _inside(row.z.parsed_value, row.g):
            continue
        for label, g in row.candidates:
            if label == "best FEV1 / best FVC" and _inside(row.z.parsed_value, g):
                yield ctx.flag(
                    "gli.z_agrees_from_best_ratio",
                    f"{row.label}: z matches GLI-2012 for best FEV1 / best FVC rather than the printed ratio",
                    [row.v, row.z],
                )


def _trial_matches(row: _Row) -> list[str]:
    assert row.z is not None and row.z.parsed_value is not None
    return [
        label
        for label, g in row.candidates
        if label != "best FEV1 / best FVC" and _inside(row.z.parsed_value, g)
    ]


@rule(
    "gli.z_matches_trial",
    "gli",
    N,
    "A z that matches one trial's values rather than the printed best explains the gap without confirming it",
    scope="gli",
)
def z_matches_trial(ctx: RecordContext, results: GliResults) -> Iterator[Flag]:
    for row in _rows(ctx, results):
        if row.z is None or not row.g.has_z or row.z.parsed_value is None:
            continue
        z = row.z.parsed_value
        if _inside(z, row.g) or any(
            lb == "best FEV1 / best FVC" and _inside(z, g) for lb, g in row.candidates
        ):
            continue
        names = _trial_matches(row)
        gap = _gap(z, row.g)
        if names and abs(gap) <= T("gli_trial_gap"):
            yield ctx.flag(
                "gli.z_matches_trial",
                f"{row.label}: z matches GLI-2012 for {', '.join(names)} rather than the printed "
                f"best value (GLIdiff {gap:+.3f}); the device appears to compute z from that",
                [row.z],
            )


@rule(
    "gli.z_far_matches_trial",
    "gli",
    C,
    "A z far from the printed best that matches a trial may match by chance",
    scope="gli",
)
def z_far_matches_trial(ctx: RecordContext, results: GliResults) -> Iterator[Flag]:
    for row in _rows(ctx, results):
        if row.z is None or not row.g.has_z or row.z.parsed_value is None:
            continue
        z = row.z.parsed_value
        if _inside(z, row.g) or any(
            lb == "best FEV1 / best FVC" and _inside(z, g) for lb, g in row.candidates
        ):
            continue
        names = _trial_matches(row)
        gap = _gap(z, row.g)
        if names and abs(gap) > T("gli_trial_gap"):
            assert row.g.z_min is not None and row.g.z_max is not None
            yield ctx.flag(
                "gli.z_far_matches_trial",
                f"{row.label}: z={z:g} is far from GLI-2012 for the printed best "
                f"({row.g.z_min:.2f} to {row.g.z_max:.2f}); it matches {', '.join(names)}, "
                f"which may be chance (GLIdiff {gap:+.3f})",
                [row.v, row.z],
            )


@rule(
    "gli.z_within_rounding",
    "gli",
    N,
    "A z within device rounding of the recalculated range is neither confirmed nor suspect",
    scope="gli",
)
def z_within_rounding(ctx: RecordContext, results: GliResults) -> Iterator[Flag]:
    for row in _rows(ctx, results):
        if row.z is None or not row.g.has_z or row.z.parsed_value is None:
            continue
        z = row.z.parsed_value
        if _inside(z, row.g) or any(_inside(z, g) for _, g in row.candidates):
            continue
        gap = _gap(z, row.g)
        if abs(gap) <= T("gli_rounding_gap"):
            yield ctx.flag(
                "gli.z_within_rounding",
                f"{row.label}: z differs from the GLI recalculation by {gap:+.3f} "
                f"(within device rounding; not confirmed) (GLIdiff {gap:+.3f})",
                [row.z],
            )


@rule(
    "gli.z_disagrees",
    "gli",
    C,
    "A printed z that does not fit the printed value for the demographics as read is a misread somewhere",
    scope="gli",
)
def z_disagrees(ctx: RecordContext, results: GliResults) -> Iterator[Flag]:
    for row in _rows(ctx, results):
        if row.z is None or not row.g.has_z or row.z.parsed_value is None:
            continue
        z = row.z.parsed_value
        if _inside(z, row.g) or any(_inside(z, g) for _, g in row.candidates):
            continue
        gap = _gap(z, row.g)
        if abs(gap) <= T("gli_rounding_gap"):
            continue
        assert (
            row.g.z_min is not None
            and row.g.z_max is not None
            and row.v.parsed_value is not None
        )
        yield ctx.flag(
            "gli.z_disagrees",
            f"{row.label}: z={z:g} but GLI from value {row.v.parsed_value:g} and {DEMO} gives "
            f"{row.g.z_min:.2f} to {row.g.z_max:.2f} (GLIdiff {gap:+.3f})",
            [row.v, row.z],
        )


@rule(
    "gli.several_disagree",
    "gli",
    C,
    "Two or more z disagreements on one record point at the age, height, sex or ethnic group",
    scope="gli",
)
def several_disagree(ctx: RecordContext, results: GliResults) -> Iterator[Flag]:
    n = len(ctx.flags_of("gli.z_disagrees"))
    if n >= T("gli_several_disagree"):
        yield ctx.flag(
            "gli.several_disagree",
            f"{n} z-scores disagree with the GLI recalculation: check age, height, sex and the "
            "ethnic group / reference first",
        )


@rule(
    "gli.not_checked",
    "gli",
    N,
    "A recalculation that returned no value (outside the equations' range) checked nothing",
    scope="gli",
)
def not_checked(ctx: RecordContext, results: GliResults) -> Iterator[Flag]:
    for row in _rows(ctx, results):
        if row.z is not None and not row.g.has_z:
            yield ctx.flag(
                "gli.not_checked",
                f"{row.label}: GLI recalculation returned no value for this z-score (not checked)",
                [row.z],
            )


@rule(
    "gli.lln_agrees",
    "gli",
    CONFIRM,
    "A printed lower limit inside the recalculated range backs it",
    scope="gli",
)
def lln_agrees(ctx: RecordContext, results: GliResults) -> Iterator[Flag]:
    for row in _rows(ctx, results):
        verdict = _lln_verdict(row)
        if verdict is True:
            assert row.lln is not None
            yield ctx.flag(
                "gli.lln_agrees",
                f"{row.label}: LLN matches the GLI recalculation",
                [row.lln],
            )


@rule(
    "gli.lln_disagrees",
    "gli",
    C,
    "A printed lower limit outside the recalculated range was misread or rests on other demographics",
    scope="gli",
)
def lln_disagrees(ctx: RecordContext, results: GliResults) -> Iterator[Flag]:
    for row in _rows(ctx, results):
        if _lln_verdict(row) is False:
            assert (
                row.lln is not None
                and row.g.lln_min is not None
                and row.g.lln_max is not None
            )
            yield ctx.flag(
                "gli.lln_disagrees",
                f"{row.label}: LLN {row.lln.parsed_value:g} but the GLI LLN for {DEMO} is "
                f"{row.g.lln_min:.3f} to {row.g.lln_max:.3f}",
                [row.lln],
            )


def _lln_verdict(row: _Row) -> bool | None:
    if (
        row.lln is None
        or row.lln.parsed_value is None
        or row.g.lln_min is None
        or row.g.lln_max is None
    ):
        return None
    tol = half_unit(row.lln) + T("gli_lln_slack")
    return row.g.lln_min - tol <= row.lln.parsed_value <= row.g.lln_max + tol


def _pctpred_bounds(row: _Row) -> tuple[float, float] | None:
    if (
        row.pctpred is None
        or row.pctpred.parsed_value is None
        or not row.g.pred_min
        or not row.g.pred_max
    ):
        return None
    assert row.v.parsed_value is not None
    h = half_unit(row.v)
    return 100 * (row.v.parsed_value - h) / row.g.pred_max, 100 * (
        row.v.parsed_value + h
    ) / row.g.pred_min


@rule(
    "gli.pctpred_agrees",
    "gli",
    CONFIRM,
    "A printed percent predicted inside the range from the value and the predicted range backs it",
    scope="gli",
)
def pctpred_agrees(ctx: RecordContext, results: GliResults) -> Iterator[Flag]:
    for row in _rows(ctx, results):
        b = _pctpred_bounds(row)
        if b is None:
            continue
        assert row.pctpred is not None and row.pctpred.parsed_value is not None
        if (
            b[0] - T("gli_pctpred_slack")
            <= row.pctpred.parsed_value
            <= b[1] + T("gli_pctpred_slack")
        ):
            yield ctx.flag(
                "gli.pctpred_agrees",
                f"{row.label}: %pred matches the GLI recalculation",
                [row.pctpred],
            )


@rule(
    "gli.pctpred_disagrees",
    "gli",
    C,
    "A printed percent predicted outside the recalculated range was misread, or the value was",
    scope="gli",
)
def pctpred_disagrees(ctx: RecordContext, results: GliResults) -> Iterator[Flag]:
    for row in _rows(ctx, results):
        b = _pctpred_bounds(row)
        if b is None:
            continue
        assert row.pctpred is not None and row.pctpred.parsed_value is not None
        if not (
            b[0] - T("gli_pctpred_slack")
            <= row.pctpred.parsed_value
            <= b[1] + T("gli_pctpred_slack")
        ):
            yield ctx.flag(
                "gli.pctpred_disagrees",
                f"{row.label}: %pred {row.pctpred.parsed_value:g} but GLI gives {b[0]:.0f} to {b[1]:.0f}% "
                f"of predicted for {DEMO}",
                [row.v, row.pctpred],
            )


def _pred_verdict(row: _Row) -> bool | None:
    if (
        row.pred is None
        or row.pred.parsed_value is None
        or row.g.pred_min is None
        or row.g.pred_max is None
    ):
        return None
    tol = half_unit(row.pred) + T("gli_lln_slack")
    return row.g.pred_min - tol <= row.pred.parsed_value <= row.g.pred_max + tol


@rule(
    "gli.pred_agrees",
    "gli",
    CONFIRM,
    "A printed predicted value inside the recalculated range backs it",
    scope="gli",
)
def pred_agrees(ctx: RecordContext, results: GliResults) -> Iterator[Flag]:
    for row in _rows(ctx, results):
        if _pred_verdict(row) is True:
            assert row.pred is not None
            yield ctx.flag(
                "gli.pred_agrees",
                f"{row.label}: predicted matches the GLI recalculation",
                [row.pred],
            )


@rule(
    "gli.pred_disagrees",
    "gli",
    C,
    "A printed predicted value outside the recalculated range rests on other demographics or equations",
    scope="gli",
)
def pred_disagrees(ctx: RecordContext, results: GliResults) -> Iterator[Flag]:
    for row in _rows(ctx, results):
        if _pred_verdict(row) is False:
            assert (
                row.pred is not None
                and row.g.pred_min is not None
                and row.g.pred_max is not None
            )
            yield ctx.flag(
                "gli.pred_disagrees",
                f"{row.label}: predicted {row.pred.parsed_value:g} but GLI gives "
                f"{row.g.pred_min:.3f} to {row.g.pred_max:.3f} for {DEMO}",
                [row.pred],
            )


@rule(
    "gli.second_z_identified",
    "gli",
    N,
    "A second z column is named by the equation it matches, so its reference is known",
    scope="gli",
)
def second_z_identified(ctx: RecordContext, results: GliResults) -> Iterator[Flag]:
    s = T("gli_range_slack")
    for row in _rows(ctx, results):
        if row.z2 is None or row.z2.parsed_value is None:
            continue
        cands: list[tuple[str, float, float]] = []
        if row.g.has_z:
            assert row.g.z_min is not None and row.g.z_max is not None
            cands.append(
                ("GLI-2012 (ethnic group on the report)", row.g.z_min, row.g.z_max)
            )
        if row.g.zgl_min is not None and row.g.zgl_max is not None:
            cands.append(("GLI global (race-neutral)", row.g.zgl_min, row.g.zgl_max))
        for e, ze in enumerate(row.g.zeth, start=1):
            if ze is not None:
                cands.append((f"GLI-2012 {ETHNIC_GROUPS[e]}", ze[0], ze[1]))
        if not cands:
            continue
        hit = [
            name for name, lo, hi in cands if lo - s <= row.z2.parsed_value <= hi + s
        ]
        if hit:
            yield ctx.flag(
                "gli.second_z_identified",
                f"{row.label}: second z-score matches {' and '.join(hit)}",
                [row.z2],
            )
        else:
            yield ctx.flag(
                "gli.second_z_identified",
                f"{row.label}: second z-score matches none of the recalculated equations: "
                + "; ".join(f"{name} {lo:.2f} to {hi:.2f}" for name, lo, hi in cands),
                [row.z2],
            )


@rule(
    "gli.skipped",
    "gli",
    N,
    "A record whose demographics or reference do not allow a recalculation is said so, not passed",
    scope="gli",
)
def skipped(ctx: RecordContext, results: GliResults) -> Iterator[Flag]:
    inputs = gli_inputs(ctx)
    if inputs.skipped and _has_anything_to_check(ctx):
        yield ctx.flag("gli.skipped", f"GLI recalculation skipped ({inputs.skipped})")


def _has_anything_to_check(ctx: RecordContext) -> bool:
    return any(
        o.value_state is ValueState.VALUE
        for p in (*GLI_PARAM, *[d for d, _ in DIFFUSION])
        for r in (R.Z, R.POST_Z, R.LLN, R.PCTPRED)
        for o in ctx.all(p, r)
    )
