"""Consistency layer: values on one report checked against each other
(v0.3.14 ``validate``, ``validate_common``, ``trend_crosscheck_A``).

Any value that fails a cross-check is flagged on every value involved in it.
A value an earlier rule flagged as an error is left out, as the old script
left out unparseable and out-of-range values.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from spirotrace.model import (
    ColumnRole,
    Observation,
    Parameter,
    ParameterKind,
    RatioForm,
    ValueState,
    kind_of,
)
from spirotrace.model.vocab import PARAMETER_INFO

from .context import RecordContext, half_unit
from .flags import Flag, Severity, Suggestion
from .registry import rule
from .thresholds import T

E, C, N, CONFIRM = Severity.ERROR, Severity.CHECK, Severity.NOTE, Severity.CONFIRM
P, R = Parameter, ColumnRole

PRE_POST = ((R.PRE, R.POST),)
SPIRO_CORE = (P.FEV1, P.FVC, P.FEV1_FVC, P.FIVC)
VOLUME_PARAMETERS = (
    P.TLC,
    P.VC_MAX,
    P.IC,
    P.FRC,
    P.ERV,
    P.RV,
    P.RV_TLC,
    P.FRC_TLC,
    P.DLCO,
    P.DLCOC,
    P.KCO,
    P.VA,
)


def _fmt(x: float) -> str:
    return f"{x:g}"


# --- header -------------------------------------------------------------------


@rule(
    "consistency.bmi",
    "consistency",
    E,
    "The printed BMI must equal weight over height squared",
)
def bmi(ctx: RecordContext) -> Iterator[Flag]:
    h, w, b = (ctx.usable(p, R.MEASURED) for p in (P.HEIGHT, P.WEIGHT, P.BMI))
    if (
        h is None
        or w is None
        or b is None
        or not h.parsed_value
        or w.parsed_value is None
    ):
        return
    calc = w.parsed_value / (h.parsed_value / 100) ** 2
    tol = calc * (0.5 / w.parsed_value + 2 * 0.5 / h.parsed_value) + T("bmi_slack")
    if abs(calc - (b.parsed_value or 0)) > tol:
        yield ctx.flag(
            "consistency.bmi",
            f"BMI {_fmt(b.parsed_value or 0)} vs weight/height^2 = {calc:.1f}",
            [h, w, b],
        )


@rule(
    "consistency.header_across_pages",
    "consistency",
    (E, C),
    "A header field read on two pages with different values was misread on one of them",
)
def header_across_pages(ctx: RecordContext) -> Iterator[Flag]:
    for slot, obs in sorted(ctx.by_slot.items(), key=lambda kv: kv[0]):
        param = slot[0]
        if len(obs) < 2 or PARAMETER_INFO[param].contains_free_text:
            continue
        pages = {o.key.page for o in obs}
        if len(pages) < 2:
            continue
        first = obs[0]
        for other in obs[1:]:
            if _same_value(first, other):
                continue
            numeric = kind_of(param) is ParameterKind.NUMBER and (
                first.parsed_value is not None or other.parsed_value is not None
            )
            yield ctx.flag(
                "consistency.header_across_pages",
                f"conflicting values on pages {first.key.page} and {other.key.page}",
                [first, other],
                severity=E if numeric else C,
            )


def _same_value(a: Observation, b: Observation) -> bool:
    if a.value_state is not b.value_state:
        return (
            a.value_state is not ValueState.VALUE
            and b.value_state is not ValueState.VALUE
        )
    if a.value_state is not ValueState.VALUE:
        return True
    if a.parsed_value is not None or b.parsed_value is not None:
        return (
            a.parsed_value is not None
            and b.parsed_value is not None
            and abs(a.parsed_value - b.parsed_value) < 1e-9
        )
    return (a.parsed_text or "") == (b.parsed_text or "")


# --- physical order -----------------------------------------------------------


def _lt(
    ctx: RecordContext,
    rule_id: str,
    small: Observation | None,
    big: Observation | None,
    margin: float,
    sev: Severity | None = None,
) -> Iterator[Flag]:
    if (
        small is None
        or big is None
        or small.parsed_value is None
        or big.parsed_value is None
    ):
        return
    if small.parsed_value > big.parsed_value + margin:
        yield ctx.flag(
            rule_id,
            f"{small.key.parameter.value} {_fmt(small.parsed_value)} should not exceed "
            f"{big.key.parameter.value} {_fmt(big.parsed_value)}",
            [small, big],
            severity=sev,
        )


@rule(
    "consistency.fev1_not_above_fvc",
    "consistency",
    E,
    "FEV1 cannot exceed the FVC it is part of",
)
def fev1_not_above_fvc(ctx: RecordContext) -> Iterator[Flag]:
    for role in (R.PRE, R.POST):
        yield from _lt(
            ctx,
            "consistency.fev1_not_above_fvc",
            ctx.usable(P.FEV1, role),
            ctx.usable(P.FVC, role),
            T("fev1_fvc_margin"),
        )


@rule(
    "consistency.trial_fev1_not_above_fvc",
    "consistency",
    E,
    "FEV1 cannot exceed FVC within a trial",
)
def trial_fev1_not_above_fvc(ctx: RecordContext) -> Iterator[Flag]:
    for role in (R.TRIAL, R.POST_TRIAL):
        for pos in ctx.positions(P.FEV1, role):
            yield from _lt(
                ctx,
                "consistency.trial_fev1_not_above_fvc",
                ctx.usable(P.FEV1, role, pos),
                ctx.usable(P.FVC, role, pos),
                T("fev1_fvc_margin"),
            )


@rule(
    "consistency.volume_order",
    "consistency",
    (E, C),
    "Lung volume compartments are smaller than the capacities that contain them",
)
def volume_order(ctx: RecordContext) -> Iterator[Flag]:
    tlc = ctx.usable(P.TLC, R.MEASURED)
    for small in (P.RV, P.FRC, P.VC_MAX, P.IC):
        yield from _lt(
            ctx,
            "consistency.volume_order",
            ctx.usable(small, R.MEASURED),
            tlc,
            T("volume_order_margin"),
        )
    yield from _lt(
        ctx,
        "consistency.volume_order",
        ctx.usable(P.ERV, R.MEASURED),
        ctx.usable(P.FRC, R.MEASURED),
        T("volume_order_margin"),
    )
    yield from _lt(
        ctx,
        "consistency.volume_order",
        ctx.usable(P.IC, R.MEASURED),
        ctx.usable(P.VC_MAX, R.MEASURED),
        T("ic_vc_max_margin"),
        sev=C,
    )


@rule(
    "consistency.dlcoc_band",
    "consistency",
    C,
    "The haemoglobin correction moves DLCO by a bounded amount",
)
def dlcoc_band(ctx: RecordContext) -> Iterator[Flag]:
    d, dc = ctx.usable(P.DLCO, R.MEASURED), ctx.usable(P.DLCOC, R.MEASURED)
    if d is None or dc is None or not d.parsed_value or dc.parsed_value is None:
        return
    ratio = dc.parsed_value / d.parsed_value
    if not T("dlcoc_ratio_low") <= ratio <= T("dlcoc_ratio_high"):
        yield ctx.flag(
            "consistency.dlcoc_band",
            f"Hb-corrected DLCO ({_fmt(dc.parsed_value)}) differs from DLCO "
            f"({_fmt(d.parsed_value)}) by more than expected",
            [d, dc],
        )


@rule(
    "consistency.dlcoc_direction",
    "consistency",
    C,
    "Correcting DLCO for a low haemoglobin raises it and for a high one lowers it",
)
def dlcoc_direction(ctx: RecordContext) -> Iterator[Flag]:
    d, dc = ctx.usable(P.DLCO, R.MEASURED), ctx.usable(P.DLCOC, R.MEASURED)
    hb = ctx.usable(P.HAEMOGLOBIN, R.MEASURED) or ctx.usable(P.HAEMOGLOBIN, R.FREE_TEXT)
    sex = (ctx.text(P.SEX, R.MEASURED) or "").strip().lower()
    if d is None or dc is None or hb is None or not sex:
        return
    ref = T("hb_reference_male") if sex.startswith("m") else T("hb_reference_female")
    assert (
        hb.parsed_value is not None
        and d.parsed_value is not None
        and dc.parsed_value is not None
    )
    if abs(hb.parsed_value - ref) < 1e-9:
        return
    expect_up = hb.parsed_value < ref
    if (
        dc.parsed_value > d.parsed_value
    ) != expect_up and dc.parsed_value != d.parsed_value:
        yield ctx.flag(
            "consistency.dlcoc_direction",
            f"Hb {_fmt(hb.parsed_value)} is {'below' if expect_up else 'above'} the reference "
            f"{ref:g}, so DLCOc should be {'above' if expect_up else 'below'} DLCO",
            [d, dc, hb],
        )


# --- ratios, percent predicted, z --------------------------------------------


@dataclass(frozen=True, slots=True)
class _Three:
    a: Observation
    b: Observation
    r: Observation


def _ratio_check(
    ctx: RecordContext,
    rule_id: str,
    a: Observation | None,
    b: Observation | None,
    r: Observation | None,
    sev: Severity | None = None,
) -> Iterator[Flag]:
    if a is None or b is None or r is None or not b.parsed_value:
        return
    assert a.parsed_value is not None and r.parsed_value is not None
    calc = a.parsed_value / b.parsed_value
    percent = r.printed_form is RatioForm.PERCENT
    slack = T("ratio_slack_percent") / 100 if percent else T("ratio_slack_fraction")
    tol = (
        calc * (half_unit(a) / a.parsed_value + half_unit(b) / b.parsed_value)
        + half_unit(r)
        + slack
    )
    if abs(calc - r.parsed_value) > tol:
        yield ctx.flag(
            rule_id,
            f"{r.key.parameter.value} {_fmt(r.parsed_value)} but "
            f"{a.key.parameter.value}/{b.key.parameter.value} gives {calc:.3f} (tol {tol:.3f})",
            [a, b, r],
            severity=sev,
        )


@rule(
    "consistency.ratio_matches_values",
    "consistency",
    (E, C),
    "A printed ratio must equal the quotient of the values it is made from, within rounding",
)
def ratio_matches_values(ctx: RecordContext) -> Iterator[Flag]:
    rid = "consistency.ratio_matches_values"
    for role_v in (R.PRE, R.POST):
        r = ctx.usable(P.FEV1_FVC, role_v)
        # the lab's FEV1 % FVC definition is method-dependent, so a percent form is a check
        sev = C if r is not None and r.printed_form is RatioForm.PERCENT else E
        yield from _ratio_check(
            ctx, rid, ctx.usable(P.FEV1, role_v), ctx.usable(P.FVC, role_v), r, sev
        )
    for role in (R.TRIAL, R.POST_TRIAL):
        for pos in ctx.positions(P.FEV1_FVC, role):
            yield from _ratio_check(
                ctx,
                rid,
                ctx.usable(P.FEV1, role, pos),
                ctx.usable(P.FVC, role, pos),
                ctx.usable(P.FEV1_FVC, role, pos),
                E,
            )
    tlc = ctx.usable(P.TLC, R.MEASURED)
    for part, ratio_p in ((P.RV, P.RV_TLC), (P.FRC, P.FRC_TLC)):
        a, r = ctx.usable(part, R.MEASURED), ctx.usable(ratio_p, R.MEASURED)
        if a is None or tlc is None or r is None or not tlc.parsed_value:
            continue
        assert a.parsed_value is not None and r.parsed_value is not None
        calc = a.parsed_value / tlc.parsed_value
        if abs(calc - r.parsed_value) * 100 > T("volume_ratio_points"):
            yield ctx.flag(
                rid,
                f"{ratio_p.value} {_fmt(r.parsed_value)} vs {part.value}/TLC = {calc:.3f}",
                [a, tlc, r],
                severity=E,
            )


@rule(
    "consistency.kco_matches",
    "consistency",
    E,
    "KCO is DLCO over alveolar volume",
)
def kco_matches(ctx: RecordContext) -> Iterator[Flag]:
    d, va, kco = (ctx.usable(p, R.MEASURED) for p in (P.DLCO, P.VA, P.KCO))
    if d is None or va is None or kco is None or not va.parsed_value:
        return
    assert d.parsed_value is not None and kco.parsed_value is not None
    calc = d.parsed_value / va.parsed_value
    if abs(calc - kco.parsed_value) > T("kco_relative") * kco.parsed_value + T(
        "kco_absolute"
    ):
        yield ctx.flag(
            "consistency.kco_matches",
            f"KCO {_fmt(kco.parsed_value)} vs DLCO/VA = {calc:.2f}",
            [d, va, kco],
        )


@rule(
    "consistency.pctpred_matches_pred",
    "consistency",
    E,
    "Percent predicted is one hundred times the value over the predicted value",
)
def pctpred_matches_pred(ctx: RecordContext) -> Iterator[Flag]:
    for param in VOLUME_PARAMETERS:
        v, p, pr = (ctx.usable(param, r) for r in (R.MEASURED, R.PCTPRED, R.PREDICTED))
        if v is None or p is None or pr is None or not pr.parsed_value:
            continue
        assert v.parsed_value is not None and p.parsed_value is not None
        calc = 100 * v.parsed_value / pr.parsed_value
        tol = (
            calc
            * (
                half_unit(v) / max(v.parsed_value, 1e-6)
                + half_unit(pr) / pr.parsed_value
            )
            + half_unit(p)
            + T("pctpred_slack")
        )
        if abs(calc - p.parsed_value) > tol:
            yield ctx.flag(
                "consistency.pctpred_matches_pred",
                f"{param.value} %pred {_fmt(p.parsed_value)} but 100*value/predicted gives {calc:.1f}",
                [v, p, pr],
            )


@rule(
    "consistency.lln_pred_uln_order",
    "consistency",
    E,
    "The lower limit lies below the predicted value, which lies below the upper limit",
)
def lln_pred_uln_order(ctx: RecordContext) -> Iterator[Flag]:
    for param in VOLUME_PARAMETERS:
        lo, pr, hi = (ctx.usable(param, r) for r in (R.LLN, R.PREDICTED, R.ULN))
        if (
            lo is not None
            and pr is not None
            and not (lo.parsed_value or 0) < (pr.parsed_value or 0)
        ):
            yield ctx.flag(
                "consistency.lln_pred_uln_order",
                f"{param.value} LLN {_fmt(lo.parsed_value or 0)} not below predicted {_fmt(pr.parsed_value or 0)}",
                [lo, pr],
            )
        if (
            hi is not None
            and pr is not None
            and not (pr.parsed_value or 0) < (hi.parsed_value or 0)
        ):
            yield ctx.flag(
                "consistency.lln_pred_uln_order",
                f"{param.value} predicted {_fmt(pr.parsed_value or 0)} not below ULN {_fmt(hi.parsed_value or 0)}",
                [pr, hi],
            )


@rule(
    "consistency.volume_sums",
    "consistency",
    C,
    "TLC is FRC plus IC and RV plus VC, and RV is FRC minus ERV, within method-dependent slack",
)
def volume_sums(ctx: RecordContext) -> Iterator[Flag]:
    tol = T("volume_sum_tolerance")
    for total, parts, signs in (
        (P.TLC, (P.FRC, P.IC), (1, 1)),
        (P.RV, (P.FRC, P.ERV), (1, -1)),
        (P.TLC, (P.RV, P.VC_MAX), (1, 1)),
    ):
        t = ctx.usable(total, R.MEASURED)
        vs = [ctx.usable(p, R.MEASURED) for p in parts]
        if t is None or any(v is None for v in vs):
            continue
        calc = sum(
            s * (v.parsed_value or 0)
            for s, v in zip(signs, vs, strict=True)
            if v is not None
        )
        if abs(calc - (t.parsed_value or 0)) > tol:
            yield ctx.flag(
                "consistency.volume_sums",
                f"{total.value} {_fmt(t.parsed_value or 0)} vs {calc:.2f} from "
                f"{' and '.join(p.value for p in parts)}",
                [t, *[v for v in vs if v is not None]],
            )


@rule(
    "consistency.lln_vs_z",
    "consistency",
    E,
    "A value below its lower limit must carry a z below -1.645, and above it a z above",
)
def lln_vs_z(ctx: RecordContext) -> Iterator[Flag]:
    for v, lo, z in _value_lln_z(ctx):
        assert (
            v.parsed_value is not None
            and lo.parsed_value is not None
            and z.parsed_value is not None
        )
        hv = half_unit(v) + half_unit(lo)
        zl, slack = T("z_lln"), T("lln_vs_z_slack")
        if v.parsed_value < lo.parsed_value - hv and z.parsed_value > zl + slack:
            yield ctx.flag(
                "consistency.lln_vs_z",
                f"{v.key.parameter.value} below LLN but z={_fmt(z.parsed_value)} > {zl}",
                [v, lo, z],
            )
        if v.parsed_value > lo.parsed_value + hv and z.parsed_value < zl - slack:
            yield ctx.flag(
                "consistency.lln_vs_z",
                f"{v.key.parameter.value} above LLN but z={_fmt(z.parsed_value)} < {zl}",
                [v, lo, z],
            )


def _value_lln_z(
    ctx: RecordContext,
) -> Iterator[tuple[Observation, Observation, Observation]]:
    """(value, LLN, z) triples of the pre spirometry rows and the measured lab rows."""
    for param in SPIRO_CORE:
        v, lo, z = (
            ctx.usable(param, R.PRE),
            ctx.usable(param, R.LLN),
            ctx.usable(param, R.Z),
        )
        if v is not None and lo is not None and z is not None:
            yield v, lo, z
    for param in VOLUME_PARAMETERS:
        v, lo, z = (
            ctx.usable(param, R.MEASURED),
            ctx.usable(param, R.LLN),
            ctx.usable(param, R.Z),
        )
        if v is not None and lo is not None and z is not None:
            yield v, lo, z


@rule(
    "consistency.pctpred_sign_vs_z",
    "consistency",
    E,
    "Percent predicted above one hundred goes with a positive z and below with a negative one",
)
def pctpred_sign_vs_z(ctx: RecordContext) -> Iterator[Flag]:
    for param, vrole in [(p, R.PRE) for p in SPIRO_CORE] + [
        (p, R.MEASURED) for p in VOLUME_PARAMETERS
    ]:
        z, p = ctx.usable(param, R.Z), ctx.usable(param, R.PCTPRED)
        if z is None or p is None or ctx.usable(param, vrole) is None:
            continue
        assert z.parsed_value is not None and p.parsed_value is not None
        zz, pp = z.parsed_value, p.parsed_value
        zt = T("pctpred_sign_z")
        if (pp >= T("pctpred_sign_high") and zz <= -zt) or (
            pp <= T("pctpred_sign_low") and zz >= zt
        ):
            yield ctx.flag(
                "consistency.pctpred_sign_vs_z",
                f"sign mismatch: {param.value} %pred {_fmt(pp)} but z={_fmt(zz)}",
                [p, z],
            )


@rule(
    "consistency.pred_sign_vs_z",
    "consistency",
    E,
    "A value above its predicted value goes with a positive z and below with a negative one",
)
def pred_sign_vs_z(ctx: RecordContext) -> Iterator[Flag]:
    for param in VOLUME_PARAMETERS:
        v, pr, z = (
            ctx.usable(param, R.MEASURED),
            ctx.usable(param, R.PREDICTED),
            ctx.usable(param, R.Z),
        )
        if v is None or pr is None or z is None:
            continue
        assert (
            v.parsed_value is not None
            and pr.parsed_value is not None
            and z.parsed_value is not None
        )
        d = v.parsed_value - pr.parsed_value
        band = 2 * half_unit(v) + half_unit(pr)
        zt = T("pred_sign_z")
        if (d > band and z.parsed_value < -zt) or (d < -band and z.parsed_value > zt):
            yield ctx.flag(
                "consistency.pred_sign_vs_z",
                f"sign mismatch between {param.value} value-predicted and z={_fmt(z.parsed_value)}",
                [v, pr, z],
            )


# --- pre and post ---------------------------------------------------------------


@rule(
    "consistency.post_pre_ratio",
    "consistency",
    E,
    "Post over pre of the values must equal post over pre of percent predicted, as predicted is shared",
)
def post_pre_ratio(ctx: RecordContext) -> Iterator[Flag]:
    for param in SPIRO_CORE:
        pv, qv = ctx.usable(param, R.PRE), ctx.usable(param, R.POST)
        pp, qp = ctx.usable(param, R.PCTPRED), ctx.usable(param, R.POST_PCTPRED)
        if any(
            x is None or not x.parsed_value or x.parsed_value <= 0
            for x in (pv, qv, pp, qp)
        ):
            continue
        assert pv and qv and pp and qp
        assert (
            pv.parsed_value and qv.parsed_value and pp.parsed_value and qp.parsed_value
        )
        r1 = qv.parsed_value / pv.parsed_value
        r2 = qp.parsed_value / pp.parsed_value
        tol = r1 * (
            half_unit(pv) / pv.parsed_value
            + half_unit(qv) / qv.parsed_value
            + 0.5 / pp.parsed_value
            + 0.5 / qp.parsed_value
        ) + T("post_pre_ratio_slack")
        if abs(r1 - r2) > tol:
            yield ctx.flag(
                "consistency.post_pre_ratio",
                f"{param.value}: post/pre ratio of values ({r1:.3f}) and of %pred ({r2:.3f}) disagree",
                [pv, qv, pp, qp],
            )


@rule(
    "consistency.bdr_column",
    "consistency",
    C,
    "The printed bronchodilator response must be either the change in percent predicted or the percent change from baseline",
)
def bdr_column(ctx: RecordContext) -> Iterator[Flag]:
    tol = T("bdr_column_tolerance")
    for param in SPIRO_CORE:
        bdr = ctx.usable(param, R.BDR)
        pp, qp = ctx.usable(param, R.PCTPRED), ctx.usable(param, R.POST_PCTPRED)
        if bdr is None or pp is None or qp is None:
            continue
        assert (
            bdr.parsed_value is not None
            and pp.parsed_value is not None
            and qp.parsed_value is not None
        )
        d1 = qp.parsed_value - pp.parsed_value
        pv, qv = ctx.usable(param, R.PRE), ctx.usable(param, R.POST)
        d2 = (
            100 * (qv.parsed_value - pv.parsed_value) / pv.parsed_value
            if pv is not None
            and qv is not None
            and pv.parsed_value
            and qv.parsed_value is not None
            else None
        )
        if abs(bdr.parsed_value - d1) > tol and (
            d2 is None or abs(bdr.parsed_value - d2) > tol
        ):
            yield ctx.flag(
                "consistency.bdr_column",
                f"BDR {_fmt(bdr.parsed_value)} matches neither change in %pred ({_fmt(d1)}) "
                "nor % change from baseline",
                [bdr],
            )


# --- trials against the summary ------------------------------------------------


@rule(
    "consistency.best_among_trials",
    "consistency",
    E,
    "The best value is one of the trial values",
)
def best_among_trials(ctx: RecordContext) -> Iterator[Flag]:
    for role in (R.TRIAL, R.POST_TRIAL):
        for param in (P.FEV1, P.FVC):
            best = ctx.usable(param, role, 1)
            trials = [
                ctx.usable(param, role, pos)
                for pos in ctx.positions(param, role)
                if pos != 1
            ]
            vals = [
                t.parsed_value
                for t in trials
                if t is not None and t.parsed_value is not None
            ]
            if best is None or best.parsed_value is None or not vals:
                continue
            if not any(abs(best.parsed_value - v) < 1e-9 for v in vals):
                yield ctx.flag(
                    "consistency.best_among_trials",
                    f"best {param.value} ({_fmt(best.parsed_value)}) not found among the "
                    f"{len(vals)} trial values",
                    [best],
                )


@rule(
    "consistency.summary_equals_trial_best",
    "consistency",
    E,
    "The summary page's best value repeats the trial page's best value",
)
def summary_equals_trial_best(ctx: RecordContext) -> Iterator[Flag]:
    for vrole, trole in ((R.PRE, R.TRIAL), (R.POST, R.POST_TRIAL)):
        for param in (P.FEV1, P.FVC, P.FEV1_FVC, P.FIVC, P.FET):
            a, b = ctx.usable(param, vrole), ctx.usable(param, trole, 1)
            if (
                a is None
                or b is None
                or a.parsed_value is None
                or b.parsed_value is None
            ):
                continue
            if abs(a.parsed_value - b.parsed_value) > 1e-9:
                yield ctx.flag(
                    "consistency.summary_equals_trial_best",
                    f"{param.value} summary {_fmt(a.parsed_value)} differs from trial-page best "
                    f"{_fmt(b.parsed_value)}",
                    [a, b],
                )


# --- session quality ------------------------------------------------------------


@rule(
    "consistency.grade_vs_variability",
    "consistency",
    C,
    "A good grade with large between-trial variability contradicts the grade's definition",
)
def grade_vs_variability(ctx: RecordContext) -> Iterator[Flag]:
    limits = {
        "A": T("variability_a_b"),
        "B": T("variability_a_b"),
        "C": T("variability_c"),
    }
    for role in (R.PRE, R.POST):
        for gp, vp in (
            (P.FEV1_GRADE, P.FEV1_VARIABILITY),
            (P.FVC_GRADE, P.FVC_VARIABILITY),
        ):
            g, var = ctx.get(gp, role), ctx.usable(vp, role)
            if g is None or var is None or g.value_state is not ValueState.VALUE:
                continue
            lim = limits.get(g.parsed_text or "")
            assert var.parsed_value is not None
            if lim is not None and var.parsed_value > lim + 1e-9:
                yield ctx.flag(
                    "consistency.grade_vs_variability",
                    f"grade {g.parsed_text} but variability {_fmt(var.parsed_value)} L exceeds {lim:g} L",
                    [g, var],
                )


@rule(
    "consistency.variability_pct",
    "consistency",
    C,
    "The printed variability percent is the variability over the best value",
)
def variability_pct(ctx: RecordContext) -> Iterator[Flag]:
    for role, trole in ((R.PRE, R.TRIAL), (R.POST, R.POST_TRIAL)):
        for param, vp, pp in (
            (P.FEV1, P.FEV1_VARIABILITY, P.FEV1_VARIABILITY_PCT),
            (P.FVC, P.FVC_VARIABILITY, P.FVC_VARIABILITY_PCT),
        ):
            var, pct = ctx.usable(vp, role), ctx.usable(pp, role)
            best = ctx.value(param, trole, 1)
            if best is None:
                best = ctx.value(param, role)
            if var is None or pct is None or not best:
                continue
            assert var.parsed_value is not None and pct.parsed_value is not None
            calc = 100 * var.parsed_value / best
            if abs(calc - pct.parsed_value) > 100 * T(
                "variability_pct_rounding"
            ) / best + T("variability_pct_slack"):
                yield ctx.flag(
                    "consistency.variability_pct",
                    f"{param.value} variability {_fmt(var.parsed_value)} L is {calc:.1f}% of best, "
                    f"report says {_fmt(pct.parsed_value)}%",
                    [var, pct],
                )


@rule(
    "consistency.bev_acceptability",
    "consistency",
    N,
    "A back-extrapolated volume above the acceptability criterion means the trial may not be acceptable",
)
def bev_acceptability(ctx: RecordContext) -> Iterator[Flag]:
    for role in (R.TRIAL, R.POST_TRIAL):
        for pos in ctx.positions(P.BEV, role):
            bev, fvc = ctx.usable(P.BEV, role, pos), ctx.value(P.FVC, role, pos)
            if bev is None or bev.parsed_value is None or not fvc:
                continue
            if (
                bev.parsed_value
                > max(T("bev_absolute"), T("bev_fraction_of_fvc") * fvc) + 1e-9
            ):
                yield ctx.flag(
                    "consistency.bev_acceptability",
                    f"BEV {_fmt(bev.parsed_value)} L exceeds 150 ml / 5% FVC acceptability criterion; "
                    "trial may not be acceptable",
                    [bev],
                )


def _grade_text(text: str | None) -> str | None:
    if text is None:
        return None
    g = text.strip().upper()
    return {"USABLE": "U", "NOT USABLE": "not usable", "UNUSABLE": "not usable"}.get(
        g, g
    )


@rule(
    "consistency.grade_sources_disagree",
    "consistency",
    N,
    "The session-quality line and the technical comments should give the same grade",
)
def grade_sources_disagree(ctx: RecordContext) -> Iterator[Flag]:
    for gp in (P.FEV1_GRADE, P.FVC_GRADE):
        sq = ctx.get(gp, R.PRE)
        ft = ctx.get(gp, R.FREE_TEXT) or ctx.get(P.SPIROMETRY_GRADE, R.FREE_TEXT)
        if (
            sq is None
            or ft is None
            or sq.value_state is not ValueState.VALUE
            or ft.value_state is not ValueState.VALUE
        ):
            continue
        a, b = _grade_text(sq.parsed_text), _grade_text(ft.parsed_text)
        if a and b and a != b:
            yield ctx.flag(
                "consistency.grade_sources_disagree",
                f"session quality line says {a}, technical comments say {b}",
                [sq, ft],
            )


# --- trend pages -----------------------------------------------------------------


def _visit_positions(ctx: RecordContext) -> list[int]:
    """Trend visit positions whose date equals the record's test date."""
    td = ctx.text(P.TEST_DATE, R.MEASURED)
    if not td:
        return []
    return [
        pos
        for pos in ctx.positions(P.TEST_DATE, R.TREND)
        if ctx.text(P.TEST_DATE, R.TREND, pos) == td
    ]


def _has_value_trend(ctx: RecordContext) -> bool:
    return any(ctx.positions(p, R.TREND) for p in (P.TLC, P.DLCO, P.WEIGHT, P.BMI))


@rule(
    "consistency.trend_page_portable",
    "consistency",
    (CONFIRM, C),
    "The trend page repeats the test date's values, read independently, so agreement backs them",
)
def trend_page_portable(ctx: RecordContext) -> Iterator[Flag]:
    if _has_value_trend(ctx):
        return
    positions = _visit_positions(ctx)
    if not positions:
        return
    for param in (P.FEV1, P.FVC):
        for trole, roles in (
            (R.TREND, (R.PRE, R.POST)),
            (R.TREND_PCTPRED, (R.PCTPRED, R.POST_PCTPRED)),
            (R.TREND_Z, (R.Z, R.POST_Z)),
        ):
            tv = next(
                (
                    ctx.value(param, trole, pos)
                    for pos in positions
                    if ctx.value(param, trole, pos) is not None
                ),
                None,
            )
            if tv is None:
                continue
            cands = [c for c in (ctx.get(param, r) for r in roles) if c is not None]
            if not cands:
                continue
            hits = [
                c
                for c in cands
                if ctx.is_usable(c) and abs((c.parsed_value or 0) - tv) < 1e-9
            ]
            if hits:
                yield ctx.flag(
                    "consistency.trend_page_portable",
                    "trend page repeats this value",
                    hits,
                    severity=CONFIRM,
                )
                continue
            yield ctx.flag(
                "consistency.trend_page_portable",
                f"trend page for this test date reads {_fmt(tv)}",
                [cands[0]],
                severity=C,
                suggestion=Suggestion(_fmt(tv), "trend page"),
            )


@rule(
    "consistency.trend_row_lab",
    "consistency",
    E,
    "The trend table's row for the visit date repeats the page-one values",
)
def trend_row_lab(ctx: RecordContext) -> Iterator[Flag]:
    if not _has_value_trend(ctx):
        return
    positions = _visit_positions(ctx)
    if not positions:
        return
    for param, role in (
        (P.FEV1, R.PRE),
        (P.FVC, R.PRE),
        (P.TLC, R.MEASURED),
        (P.DLCO, R.MEASURED),
        (P.WEIGHT, R.MEASURED),
        (P.BMI, R.MEASURED),
    ):
        tv = next(
            (
                ctx.value(param, R.TREND, pos)
                for pos in positions
                if ctx.value(param, R.TREND, pos) is not None
            ),
            None,
        )
        v = ctx.usable(param, role)
        if tv is None or v is None or v.parsed_value is None:
            continue
        if abs(tv - v.parsed_value) > T("trend_match_lab"):
            yield ctx.flag(
                "consistency.trend_row_lab",
                f"{param.value} {_fmt(v.parsed_value)} differs from trend-table value {_fmt(tv)} "
                "for the same visit",
                [v],
            )
