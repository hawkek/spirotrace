"""The derived variables, ported from the old script's ``derived_fields``."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import ClassVar

from spirotrace.checks import RecordContext, enabled_rules
from spirotrace.checks.flags import Flag
from spirotrace.checks.rules_gli import DIFFUSION, GLI_PARAM, SPIRO_PHASES, demographics
from spirotrace.checks.thresholds import DLCO_SI_UNITS, T
from spirotrace.config import Settings
from spirotrace.model import ColumnRole, ObservationKey, Parameter
from spirotrace.resolve import Resolved, ResolvedValue
from spirotrace.rspiro import GliResults, GliSubject, RspiroBridge, RspiroError
from spirotrace.store import ReadRecord, Row

P, R = Parameter, ColumnRole

PATTERNS: tuple[str, ...] = (
    "normal",
    "obstruction",
    "obstruction, possible mixed",
    "possible restriction",
    "restriction",
    "mixed",
    "non-specific",
)
REPORT_PATTERNS: tuple[str, ...] = (
    "normal",
    "obstructive",
    "restrictive",
    "mixed",
    "nonspecific",
    "other",
)
DERIVED_NAMES: tuple[str, ...] = (
    "ratio_below_lln",
    "fvc_below_lln",
    "fev1_below_lln",
    "tlc_below_lln",
    "pattern",
    "prism",
    "fev1_severity",
    "bdr_fev1_pct_pred",
    "bdr_fvc_pct_pred",
    "bdr_positive_2022",
    "bdr_positive_2005",
    "report_pattern",
    "grade_fev1",
    "grade_fvc",
    "pattern_gli",
)
"""Fixed-name rows; the ``gli_<param>_<phase>_<what>`` rows are added per record."""

NOT_COMPUTED_RSPIRO = "not computed: rspiro absent"
YES_NO = {True: "yes", False: "no", None: ""}


@dataclass(frozen=True, slots=True)
class DerivedRow:
    """One derived value of one record, with its provenance."""

    record_id: str
    name: str
    value: str
    basis: str = ""
    inputs: tuple[ObservationKey, ...] = ()
    input_statuses: tuple[str, ...] = ()
    input_open_severities: tuple[str, ...] = ()
    status: str = "computed"

    COLUMNS: ClassVar[tuple[str, ...]] = (
        "record_id",
        "name",
        "value",
        "basis",
        "inputs",
        "input_statuses",
        "input_open_severities",
        "status",
    )

    def to_row(self) -> Row:
        return {
            "record_id": self.record_id,
            "name": self.name,
            "value": self.value,
            "basis": self.basis,
            "inputs": " ".join(k.to_string() for k in self.inputs),
            "input_statuses": " ".join(self.input_statuses),
            "input_open_severities": " ".join(
                s or "-" for s in self.input_open_severities
            ),
            "status": self.status,
        }


@dataclass(slots=True)
class DeriveRun:
    rows: list[DerivedRow] = field(default_factory=list)
    flags: list[Flag] = field(default_factory=list)
    rspiro_version: str = ""
    """Empty when no bridge ran (gli_* and pattern_gli are then not computed)."""
    not_run_reason: str = ""
    gli_inputs: int = 0
    """Subject-phases sent to the bridge; 0 means no record had usable demographics."""

    @property
    def not_computed(self) -> int:
        return sum(1 for r in self.rows if r.status != "computed")

    def of_record(self, record_id: str) -> dict[str, DerivedRow]:
        return {r.name: r for r in self.rows if r.record_id == record_id}


# --- helpers over one record's resolved values --------------------------------


class _Values:
    """One record's resolved values, indexed by slot; ``usable`` applies derive's rule."""

    def __init__(self, record_id: str, values: Mapping[ObservationKey, ResolvedValue]):
        self.record_id = record_id
        self.by_slot: dict[tuple[Parameter, ColumnRole, int], list[ResolvedValue]] = {}
        for k, v in values.items():
            self.by_slot.setdefault(
                (k.parameter, k.column_role, k.display_position), []
            ).append(v)
        for lst in self.by_slot.values():
            lst.sort(key=lambda v: v.key.page)
        self.used: list[ResolvedValue] = []

    def get(self, p: Parameter, r: ColumnRole, pos: int = 1) -> ResolvedValue | None:
        lst = self.by_slot.get((p, r, pos))
        return lst[0] if lst else None

    def usable(self, p: Parameter, r: ColumnRole, pos: int = 1) -> ResolvedValue | None:
        v = self.get(p, r, pos)
        return v if v is not None and v.usable else None

    def number(self, p: Parameter, r: ColumnRole, pos: int = 1) -> float | None:
        v = self.usable(p, r, pos)
        if v is None or v.resolved.parsed_value is None:
            return None
        self.used.append(v)
        return v.resolved.parsed_value

    def text(self, p: Parameter, r: ColumnRole, pos: int = 1) -> str | None:
        v = self.usable(p, r, pos)
        if v is None or v.resolved.parsed_text is None:
            return None
        self.used.append(v)
        return v.resolved.parsed_text

    def has_role(self, r: ColumnRole) -> bool:
        return any(role is r for (_, role, _) in self.by_slot)

    def has_parameter(self, p: Parameter) -> bool:
        return any(param is p for (param, _, _) in self.by_slot)

    def take(self) -> list[ResolvedValue]:
        """The inputs used since the last call."""
        used, self.used = self.used, []
        return used


def _row(
    vals: _Values,
    name: str,
    value: str | None,
    basis: str = "",
    inputs: Iterable[ResolvedValue] | None = None,
    status: str | None = None,
) -> DerivedRow:
    ins = list(vals.take() if inputs is None else inputs)
    seen: set[ObservationKey] = set()
    uniq = []
    for v in ins:
        if v.key not in seen:
            seen.add(v.key)
            uniq.append(v)
    return DerivedRow(
        vals.record_id,
        name,
        "" if value is None else value,
        basis,
        tuple(v.key for v in uniq),
        tuple(v.status for v in uniq),
        tuple(v.open_severity for v in uniq),
        status
        if status is not None
        else ("computed" if value is not None else "not computed"),
    )


# --- the physiology ---------------------------------------------------------------


def _below_lln(
    vals: _Values, p: Parameter, vrole: ColumnRole, lrole: ColumnRole, zrole: ColumnRole
) -> tuple[bool | None, str]:
    """Below the lower limit by z when usable, else by value against the printed LLN."""
    z = vals.number(p, zrole)
    if z is not None:
        return z < T("z_lln"), "z"
    v, lln = vals.number(p, vrole), vals.number(p, lrole)
    if v is not None and lln is not None:
        return v < lln, "lln"
    return None, ""


def pattern_from_flags(
    obstructed: bool | None, low_fvc: bool | None, low_tlc: bool | None
) -> str | None:
    """The ATS/ERS 2022 flowchart on the pre-bronchodilator ratio, FVC and TLC."""
    if (
        obstructed is not None
        and low_fvc is None
        and low_tlc is not None
        and (obstructed or low_tlc)
    ):
        # FVC not usable, but TLC decides: obstruction with or without low TLC, or restriction
        return ("mixed" if low_tlc else "obstruction") if obstructed else "restriction"
    if obstructed is None or low_fvc is None:
        return None
    if low_tlc is not None:
        if obstructed:
            return "mixed" if low_tlc else "obstruction"
        return "restriction" if low_tlc else ("non-specific" if low_fvc else "normal")
    if obstructed:
        return "obstruction, possible mixed" if low_fvc else "obstruction"
    return "possible restriction" if low_fvc else "normal"


def pattern_from_text(text: str | None) -> str | None:
    """The report's category from its wording (the old script's reading)."""
    t = (text or "").lower()
    if not t:
        return None
    if "mixed" in t or ("obstruct" in t and "restrict" in t):
        return "mixed"
    if "obstruct" in t:
        return "obstructive"
    if "restrict" in t:
        return "restrictive"
    if re.search(r"non-?\s?specific|prism|preserved ratio", t):
        return "nonspecific"
    if "normal" in t:
        return "normal"
    return "other"


def severity_of(z: float | None) -> str | None:
    """ATS/ERS 2022 three-level grading of the FEV1 z-score."""
    if z is None:
        return None
    if z >= T("z_lln"):
        return "within normal limits"
    if z >= T("severity_mild"):
        return "mild"
    return "moderate" if z >= T("severity_moderate") else "severe"


def _grade(text: str | None) -> str | None:
    if text is None:
        return None
    g = text.strip().upper()
    return {"USABLE": "U", "NOT USABLE": "not usable", "UNUSABLE": "not usable"}.get(
        g, g
    )


def _report_pattern_from_findings(vals: _Values) -> str | None:
    spiro = vals.text(P.INTERPRETATION_SPIROMETRY, R.MEASURED)
    vols = vals.text(P.INTERPRETATION_VOLUMES, R.MEASURED)
    if spiro is None:
        return None
    s = {c.strip() for c in spiro.split(";") if c.strip()}
    v = {c.strip() for c in (vols or "").split(";") if c.strip()}
    low_vol = bool(v & {"reduced", "restrictive"})
    if "mixed" in s or ("obstructive" in s and ("restrictive" in s or low_vol)):
        return "mixed"
    if "obstructive" in s:
        return "obstructive"
    if "restrictive" in s:
        # restriction needs low lung volumes; with normal volumes it is non-specific
        return "nonspecific" if "normal" in v else "restrictive"
    if "nonspecific" in s:
        return "nonspecific"
    if "normal" in s:
        return "normal"
    return "other"


def _whole_text(vals: _Values) -> str:
    parts: list[str] = []
    for (p, r, _), lst in vals.by_slot.items():
        if r is R.MEASURED and p in (
            P.TECHNICAL_COMMENTS,
            P.INTERPRETATION_SPIROMETRY,
            P.INTERPRETATION_VOLUMES,
            P.INTERPRETATION_GAS_TRANSFER,
        ):
            parts.extend(v.resolved.raw_text for v in lst)
    return re.sub(r"\s+", " ", "\n".join(parts))


def _derive_record(vals: _Values, has_tlc: bool) -> list[DerivedRow]:
    rows: list[DerivedRow] = []
    obs, b1 = _below_lln(vals, P.FEV1_FVC, R.PRE, R.LLN, R.Z)
    rows.append(_row(vals, "ratio_below_lln", YES_NO[obs] or None, b1))
    lfvc, b2 = _below_lln(vals, P.FVC, R.PRE, R.LLN, R.Z)
    rows.append(_row(vals, "fvc_below_lln", YES_NO[lfvc] or None, b2))
    lfev1, b3 = _below_lln(vals, P.FEV1, R.PRE, R.LLN, R.Z)
    rows.append(_row(vals, "fev1_below_lln", YES_NO[lfev1] or None, b3))
    tlc: bool | None = None
    b4 = ""
    if has_tlc:
        tlc, b4 = _below_lln(vals, P.TLC, R.MEASURED, R.LLN, R.Z)
        rows.append(_row(vals, "tlc_below_lln", YES_NO[tlc] or None, b4))
    inputs = [r for r in rows]
    pat = pattern_from_flags(obs, lfvc, tlc)
    pat_inputs = [
        v
        for name in ("ratio_below_lln", "fvc_below_lln", "tlc_below_lln")
        for row in inputs
        if row.name == name
        for v in _values_of(vals, row.inputs)
    ]
    rows.append(_row(vals, "pattern", pat, f"ratio:{b1} fvc:{b2} tlc:{b4}", pat_inputs))
    prism = (not obs and lfev1) if obs is not None and lfev1 is not None else None
    prism_inputs = [
        v
        for row in inputs
        if row.name in ("ratio_below_lln", "fev1_below_lln")
        for v in _values_of(vals, row.inputs)
    ]
    rows.append(_row(vals, "prism", YES_NO[prism] or None, b3, prism_inputs))
    z1 = vals.number(P.FEV1, R.Z)
    rows.append(_row(vals, "fev1_severity", severity_of(z1), "FEV1 z"))
    # the pattern stated in the report
    phrase = vals.text(P.INTERPRETATION_PATTERN, R.FREE_TEXT)
    rep_basis = "interpretation pattern phrase"
    rcat = pattern_from_text(phrase)
    if rcat is None:
        rcat = _report_pattern_from_findings(vals)
        rep_basis = "per-test findings"
    if rcat is None:
        flat = _whole_text(vals)
        m = re.search(
            r"(?:spirometry|results)[^.]{0,80}?within (?:the )?normal limits|normal spirometry",
            flat,
            re.IGNORECASE,
        )
        rcat = "normal" if m else None
        rep_basis = "whole text" if m else ""
    rows.append(_row(vals, "report_pattern", rcat, rep_basis))
    rows.extend(_bdr_rows(vals))
    for t, gp in (("fev1", P.FEV1_GRADE), ("fvc", P.FVC_GRADE)):
        sqv = _grade(vals.text(gp, R.PRE))
        sq_inputs = vals.take()
        ftv = _grade(
            vals.text(gp, R.FREE_TEXT) or vals.text(P.SPIROMETRY_GRADE, R.FREE_TEXT)
        )
        ft_inputs = vals.take()
        rows.append(
            _row(
                vals,
                f"grade_{t}",
                sqv or ftv,
                "session quality" if sqv else ("comments" if ftv else ""),
                sq_inputs if sqv else ft_inputs,
            )
        )
    return rows


def _values_of(vals: _Values, keys: Iterable[ObservationKey]) -> list[ResolvedValue]:
    out: list[ResolvedValue] = []
    for k in keys:
        lst = vals.by_slot.get((k.parameter, k.column_role, k.display_position), [])
        out.extend(v for v in lst if v.key == k)
    return out


def _bdr_rows(vals: _Values) -> list[DerivedRow]:
    rows: list[DerivedRow] = []
    if not any(
        vals.has_role(r) for r in (R.POST, R.POST_PCTPRED, R.POST_Z, R.POST_LLN, R.BDR)
    ):
        return rows
    chg: dict[str, tuple[float, str]] = {}
    absd: dict[str, tuple[float, float]] = {}
    tol = T("bdr_column_tolerance")
    for p in (P.FEV1, P.FVC):
        b = vals.number(p, R.BDR)
        p0, p1 = vals.number(p, R.PCTPRED), vals.number(p, R.POST_PCTPRED)
        v0, v1 = vals.number(p, R.PRE), vals.number(p, R.POST)
        d_pred = (p1 - p0) if p0 is not None and p1 is not None else None
        d_base = (
            100 * (v1 - v0) / v0
            if v0 is not None and v1 is not None and v0 > 0
            else None
        )
        basis = ""
        if b is not None:
            # the 2022 rule needs the change as % of predicted; the BDR column could be
            # the % change from baseline, so it is used only when it matches the %pred change
            if d_pred is not None and abs(b - d_pred) <= tol:
                chg[p.value] = (b, "BDR column (% of predicted)")
            elif d_pred is not None:
                chg[p.value] = (
                    d_pred,
                    "post - pre %pred (rounded); BDR column is not % of predicted",
                )
                if d_base is not None and abs(b - d_base) <= tol:
                    basis = (
                        f"note: {p.value} BDR column {b:g} is the % change from baseline, "
                        f"so the 2022 rule used the change in %pred ({d_pred:g})"
                    )
            else:
                basis = (
                    f"note: {p.value}: BDR column {b:g} not used: %pred not read, so it cannot "
                    "be told apart from a % change from baseline"
                )
        elif d_pred is not None:
            chg[p.value] = (d_pred, "post - pre %pred (rounded)")
        if v0 is not None and v1 is not None and v0 > 0:
            absd[p.value] = (v1 - v0, 100 * (v1 - v0) / v0)
        c = chg.get(p.value)
        rows.append(
            _row(
                vals,
                f"bdr_{p.value.lower()}_pct_pred",
                None if c is None else f"{round(c[0], 1):g}",
                basis or (c[1] if c else ""),
            )
        )
    pos22: bool | None = None
    inputs = [v for row in rows for v in _values_of(vals, row.inputs)]
    if chg:
        t = T("bdr_pct_pred")
        hit = [c >= t - 1e-9 for c, _ in chg.values()]
        pos22 = True if any(hit) else (False if len(chg) == 2 else None)
    rows.append(
        _row(
            vals,
            "bdr_positive_2022",
            YES_NO[pos22] or None,
            ">= 10% of predicted",
            inputs,
        )
    )
    pos05: bool | None = None
    if absd:
        pos05 = (
            True
            if any(
                d >= T("bdr_2005_litres") - 1e-9 and r >= T("bdr_2005_pct") - 1e-9
                for d, r in absd.values()
            )
            else (False if len(absd) == 2 else None)
        )
    rows.append(
        _row(
            vals,
            "bdr_positive_2005",
            YES_NO[pos05] or None,
            ">= 12% and >= 200 mL",
            inputs,
        )
    )
    return rows


# --- the GLI recalculation (point values) --------------------------------------


def _gli_subjects(vals: _Values, ctx: RecordContext) -> tuple[list[GliSubject], str]:
    """The record's point subjects, or none with the reason (the demographics)."""
    demo, why = demographics(ctx)
    if demo is None:
        return [], why
    age, ht = vals.number(P.AGE, R.MEASURED), vals.number(P.HEIGHT, R.MEASURED)
    vals.take()
    if age is None or ht is None:
        return [], "missing or flagged: age or height"
    out: list[GliSubject] = []
    rid = vals.record_id
    for phase, vrole, _l, _p, _z, _t in SPIRO_PHASES:
        values = {}
        for param, name in GLI_PARAM.items():
            x = vals.number(param, vrole)
            if x is not None:
                values[name] = (x, 0.0)
        vals.take()
        if values:
            out.append(
                GliSubject(
                    f"{rid}|{phase}", demo.sex, demo.ethnicity, age, age, ht, ht, values
                )
            )
    dvals = {}
    for param, name in DIFFUSION:
        x = vals.number(param, R.MEASURED)
        if x is not None:
            dvals[name] = (x, 0.0)
    vals.take()
    if dvals:
        out.append(
            GliSubject(
                f"{rid}|measured",
                demo.sex,
                demo.ethnicity,
                age,
                age,
                ht,
                ht,
                dvals,
                si=DLCO_SI_UNITS,
            )
        )
    return out, ""


def _gli_rows(
    vals: _Values, results: GliResults | None, available: bool, why: str
) -> list[DerivedRow]:
    """``why`` is the record's reason for sending nothing to the bridge, else ``""``."""
    rows: list[DerivedRow] = []
    rid = vals.record_id
    if why:
        status = f"not computed: {why}"
    elif not available:
        status = NOT_COMPUTED_RSPIRO
    else:
        status = "not computed: no recalculation returned"
    phases = [(phase, vrole) for phase, vrole, *_ in SPIRO_PHASES]
    slots = [
        (phase, vrole, param, name)
        for phase, vrole in phases
        for param, name in GLI_PARAM.items()
    ]
    slots += [("measured", R.MEASURED, param, name) for param, name in DIFFUSION]
    zs: dict[str, float] = {}
    for phase, vrole, param, name in slots:
        v = vals.usable(param, vrole)
        if v is None or v.resolved.parsed_value is None:
            continue
        g = results.get((f"{rid}|{phase}", name)) if results else None
        base = f"gli_{param.value}_{phase}"
        demo_inputs = [
            x for p in (P.AGE, P.HEIGHT, P.SEX) if (x := vals.get(p, R.MEASURED))
        ]
        inputs = [v, *demo_inputs]
        value = v.resolved.parsed_value
        if g is None or not available:
            for what in ("z", "lln", "pred", "pctpred"):
                rows.append(_row(vals, f"{base}_{what}", None, "", inputs, status))
            continue
        z = g.z_min if g.z_min is not None else None
        pred = g.pred_min
        rows.append(
            _row(vals, f"{base}_z", None if z is None else f"{z:.2f}", "", inputs)
        )
        rows.append(
            _row(
                vals,
                f"{base}_lln",
                None if g.lln_min is None else f"{g.lln_min:.3f}",
                "",
                inputs,
            )
        )
        rows.append(
            _row(
                vals,
                f"{base}_pred",
                None if pred is None else f"{pred:.3f}",
                "",
                inputs,
            )
        )
        rows.append(
            _row(
                vals,
                f"{base}_pctpred",
                None if not pred else f"{100 * value / pred:.1f}",
                "",
                inputs,
            )
        )
        if z is not None:
            zs[f"{param.value}|{phase}"] = z
    # the same flowchart on the recalculated pre-bronchodilator z
    if why or not available:
        rows.append(_row(vals, "pattern_gli", None, "", [], status))
        return rows
    rz, fz = zs.get("FEV1_FVC|pre"), zs.get("FVC|pre")
    obs = None if rz is None else rz < T("z_lln")
    low_fvc = None if fz is None else fz < T("z_lln")
    tlc: bool | None = None
    tlc_basis = ""
    if vals.has_parameter(P.TLC):
        tlc, tlc_basis = _below_lln(vals, P.TLC, R.MEASURED, R.LLN, R.Z)
    inputs = [
        v for p in (P.FEV1_FVC, P.FVC) if (v := vals.usable(p, R.PRE))
    ] + vals.take()
    rows.append(
        _row(
            vals,
            "pattern_gli",
            pattern_from_flags(obs, low_fvc, tlc),
            f"ratio:{'z' if rz is not None else ''} fvc:{'z' if fz is not None else ''} "
            f"tlc:{tlc_basis}{' (printed)' if tlc_basis else ''}",
            inputs,
        )
    )
    return rows


# --- the entry point -------------------------------------------------------------


def derive_records(
    resolved: Resolved,
    settings: Settings,
    *,
    bridge: RspiroBridge | None = None,
    gli_results: GliResults | None = None,
) -> DeriveRun:
    """Derive every record of ``resolved``; run the post-derive rules."""
    run = DeriveRun()
    contexts: dict[str, RecordContext] = {}
    values: dict[str, _Values] = {}
    subjects: list[GliSubject] = []
    reasons: dict[str, str] = {}
    for rec in resolved.records:
        usable_only = ReadRecord(
            rec.record,
            {k: o for k, o in rec.observations.items() if resolved.values[k].usable},
            list(rec.conditions),
        )
        ctx = RecordContext.of(usable_only)
        contexts[rec.record_id] = ctx
        vals = _Values(rec.record_id, resolved.of_record(rec.record_id))
        values[rec.record_id] = vals
        own, why = _gli_subjects(vals, ctx)
        subjects.extend(own)
        reasons[rec.record_id] = why
    run.gli_inputs = len(subjects)
    results = gli_results
    available = results is not None
    # R is only known to be there once it has answered: an empty input is never
    # sent, so it cannot stand in for a successful run
    if results is None and bridge is not None and subjects:
        try:
            results = bridge.compute(subjects)
            available = True
            run.rspiro_version = bridge.version() or "rspiro"
        except RspiroError as exc:
            run.not_run_reason = str(exc)
    elif results is not None:
        run.rspiro_version = "fixture"
    derived_rules = [
        r
        for r in enabled_rules(settings.rules.off, settings.rules.layers_off)
        if r.scope == "derived"
    ]
    for rec in resolved.records:
        vals, ctx = values[rec.record_id], contexts[rec.record_id]
        rows = _derive_record(vals, has_tlc=vals.has_parameter(P.TLC))
        rows.extend(_gli_rows(vals, results, available, reasons[rec.record_id]))
        run.rows.extend(rows)
        by_name = {r.name: r for r in rows}
        for r in derived_rules:
            for f in r.fn(ctx, by_name):
                run.flags.append(f)
    return run
