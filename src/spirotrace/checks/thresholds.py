"""The single threshold table: every tolerance, limit and cut-off the rules use,
with its source. A change here needs its source and a decisions-log entry;
nothing is tuned to make a check pass (coding file, seam 6).

Range limits come from v0.3.14 ``QC_LIMITS``, ``COL_LIMITS`` and
``HEADER_LIMITS``: device limits from the the device operator's manual
section 7 (volume +/-12 L, flow +/-16 L/s, barometric pressure 500 to 1060
hPa), the rest adult clinical plausibility ("adjust for your cohort").
Ratios are limited as fractions because the model stores them so.
"""

from __future__ import annotations

from dataclasses import dataclass

from spirotrace.model import ColumnRole, Parameter

P = Parameter
R = ColumnRole

MANUAL_S7 = "the device operator's manual s.7 (device range)"
MANUAL_S311 = "the device operator's manual s.3.11 (session quality)"
PHYSIOLOGICAL = "adult clinical plausibility (v0.3.14)"
V0314 = "v0.3.14 spiro_extract.py"


@dataclass(frozen=True, slots=True)
class Threshold:
    value: float
    source: str
    note: str = ""


@dataclass(frozen=True, slots=True)
class Limits:
    """Hard (error outside) and typical (check outside) limits of one quantity."""

    hard_low: float
    hard_high: float
    typical_low: float
    typical_high: float
    source: str


# --- range limits per parameter (value-like roles) ---------------------------

PARAMETER_LIMITS: dict[Parameter, Limits] = {
    P.FEV1: Limits(0.1, 8, 0.5, 6.0, f"{MANUAL_S7}; physiological"),
    P.FVC: Limits(0.2, 10, 0.8, 7.5, f"{MANUAL_S7}; physiological"),
    P.FIVC: Limits(0.2, 10, 0.8, 7.5, f"{MANUAL_S7}; physiological"),
    P.FEV6: Limits(0.2, 10, 0.8, 7.5, f"{MANUAL_S7}; physiological"),
    P.FEV1_FVC: Limits(0.2, 1.0, 0.35, 0.95, "a ratio cannot exceed 1"),
    P.FET: Limits(0.3, 40, 2, 20, f"FET < 2 s fails end-of-test ({MANUAL_S311})"),
    P.BEV: Limits(0.0, 1.0, 0.0, 0.3, PHYSIOLOGICAL),
    P.PEF: Limits(0.3, 16, 1.5, 14, f"flow +/-16 L/s ({MANUAL_S7})"),
    P.PIF: Limits(0.3, 16, 1.0, 12, f"flow +/-16 L/s ({MANUAL_S7})"),
    P.FEF2575: Limits(0.05, 16, 0.3, 7, f"flow +/-16 L/s ({MANUAL_S7})"),
    P.TLC: Limits(1, 12, 2.5, 10, f"volume +/-12 L ({MANUAL_S7}); physiological"),
    P.VC_MAX: Limits(0.2, 10, 0.8, 7.5, PHYSIOLOGICAL),
    P.IC: Limits(0.2, 7, 0.8, 5.5, PHYSIOLOGICAL),
    P.FRC: Limits(0.5, 10, 1.0, 7.0, PHYSIOLOGICAL),
    P.ERV: Limits(0.0, 5, 0.1, 3.0, PHYSIOLOGICAL),
    P.RV: Limits(0.2, 8, 0.5, 5.0, PHYSIOLOGICAL),
    P.RV_TLC: Limits(0.05, 0.85, 0.15, 0.65, PHYSIOLOGICAL),
    P.FRC_TLC: Limits(0.15, 0.95, 0.30, 0.80, PHYSIOLOGICAL),
    P.DLCO: Limits(1, 60, 5, 45, PHYSIOLOGICAL),
    P.DLCOC: Limits(1, 60, 5, 45, PHYSIOLOGICAL),
    P.KCO: Limits(0.5, 12, 1.5, 8, PHYSIOLOGICAL),
    P.VA: Limits(0.8, 12, 2.5, 10, PHYSIOLOGICAL),
    P.AGE: Limits(3, 110, 16, 95, PHYSIOLOGICAL),
    P.HEIGHT: Limits(100, 230, 140, 205, PHYSIOLOGICAL),
    P.WEIGHT: Limits(20, 300, 35, 180, PHYSIOLOGICAL),
    P.BMI: Limits(10, 80, 15, 50, PHYSIOLOGICAL),
    P.BAROMETRIC_PRESSURE: Limits(
        500, 1060, 950, 1050, f"operating range ({MANUAL_S7})"
    ),
    P.HAEMOGLOBIN: Limits(5, 22, 9, 18, PHYSIOLOGICAL),
    P.SALBUTAMOL_DOSE: Limits(50, 1000, 100, 400, PHYSIOLOGICAL),
}

# --- range limits per column role (derived columns) --------------------------

ROLE_LIMITS: dict[ColumnRole, Limits] = {
    R.PCTPRED: Limits(5, 300, 40, 150, f"percent predicted ({V0314})"),
    R.POST_PCTPRED: Limits(5, 300, 40, 150, f"percent predicted ({V0314})"),
    R.Z: Limits(-12, 8, -5, 3, f"GLI z-score ({V0314})"),
    R.POST_Z: Limits(-12, 8, -5, 3, f"GLI z-score ({V0314})"),
    R.BDR: Limits(-100, 100, -15, 40, f"bronchodilator response ({V0314})"),
    R.PCTCHG: Limits(-100, 200, -20, 60, f"percent change ({V0314})"),
}

VALUE_LIKE_ROLES: frozenset[ColumnRole] = frozenset(
    {
        R.MEASURED,
        R.PRE,
        R.POST,
        R.LLN,
        R.POST_LLN,
        R.ULN,
        R.PREDICTED,
        R.TRIAL,
        R.POST_TRIAL,
        R.FREE_TEXT,
    }
)
"""Roles whose limits are the parameter's own. Trend roles are not range-checked
(v0.3.14 did not check trend rows)."""


def limits_for(parameter: Parameter, role: ColumnRole) -> Limits | None:
    """The limits that apply to an observation, or None when it has none."""
    if role in ROLE_LIMITS:
        return ROLE_LIMITS[role]
    if role in VALUE_LIKE_ROLES:
        return PARAMETER_LIMITS.get(parameter)
    return None


# --- printed decimal places (layouts with a trials table: the device output) ---

DEVICE_DECIMALS: dict[Parameter, int] = {
    P.FEV1: 2,
    P.FVC: 2,
    P.FIVC: 2,
    P.FEV1_FVC: 3,
    P.FET: 1,
    P.PEF: 2,
    P.BEV: 2,
}
Z_DECIMALS = 2

GRADES: frozenset[str] = frozenset("ABCDEFU")
"""Session-quality grades (the device manual s.3.11; U = usable)."""

SEX_VOCABULARY: tuple[str, ...] = ("Female", "Male", "F", "M", "Other", "Unknown")
SMOKER_VOCABULARY: tuple[str, ...] = (
    "Yes",
    "No",
    "Former",
    "Ex",
    "Ex-smoker",
    "Current",
    "Never",
    "Unknown",
)

# --- named thresholds -------------------------------------------------------

THRESHOLDS: dict[str, Threshold] = {
    "z_lln": Threshold(-1.645, "GLI lower limit of normal, 5th centile"),
    "lln_vs_z_slack": Threshold(0.06, V0314, "z slack around -1.645"),
    "pctpred_sign_high": Threshold(102, V0314, "%pred at or above this with z <= -0.1"),
    "pctpred_sign_low": Threshold(98, V0314, "%pred at or below this with z >= 0.1"),
    "pctpred_sign_z": Threshold(0.1, V0314),
    "pred_sign_z": Threshold(
        0.05, V0314, "z beyond this when value and predicted disagree"
    ),
    "ratio_slack_fraction": Threshold(0.0015, V0314, "added to the rounding tolerance"),
    "ratio_slack_percent": Threshold(0.6, V0314, "points, lab FEV1 % FVC"),
    "pctpred_slack": Threshold(0.6, V0314, "points, added to the rounding tolerance"),
    "volume_ratio_points": Threshold(
        1.2, V0314, "RV/TLC and FRC/TLC, percentage points"
    ),
    "kco_relative": Threshold(0.03, V0314),
    "kco_absolute": Threshold(0.06, V0314),
    "dlcoc_ratio_low": Threshold(0.75, V0314, "Hb-corrected DLCO over DLCO"),
    "dlcoc_ratio_high": Threshold(1.33, V0314),
    "volume_sum_tolerance": Threshold(0.06, V0314, "L; TLC = FRC + IC etc."),
    "volume_order_margin": Threshold(0.01, V0314, "L; rounding"),
    "ic_vc_max_margin": Threshold(0.05, V0314, "L"),
    "fev1_fvc_margin": Threshold(0.005, V0314, "L; rounding"),
    "post_pre_ratio_slack": Threshold(0.002, V0314),
    "bdr_column_tolerance": Threshold(1.5, V0314, "points"),
    "bmi_slack": Threshold(0.1, V0314, "kg/m2 added to the rounding tolerance"),
    "trend_match_lab": Threshold(0.011, V0314),
    "variability_a_b": Threshold(
        0.150, f"{MANUAL_S311}; ATS/ERS 2019 allows 0.150 L for A"
    ),
    "variability_c": Threshold(0.200, MANUAL_S311),
    "variability_pct_slack": Threshold(0.1, V0314, "points"),
    "variability_pct_rounding": Threshold(0.005, V0314, "L half-unit of variability"),
    "bev_absolute": Threshold(0.150, f"{MANUAL_S311}; ATS/ERS 2019", "L"),
    "bev_fraction_of_fvc": Threshold(0.05, f"{MANUAL_S311}; ATS/ERS 2019"),
    "date_earliest_year": Threshold(1990, V0314),
    "cohort_robust_z": Threshold(5.0, V0314, "robust SD from the cohort median"),
    "cohort_min_values": Threshold(20, V0314),
    "column_empty_share": Threshold(
        0.9, "README 0.3.16", "empty in 90% or more of one layout"
    ),
    "column_empty_min_records": Threshold(
        10, "port", "a layout with fewer records cannot define a format"
    ),
    "gli_range_slack": Threshold(0.006, V0314, "z, around the recalculated range"),
    "gli_rounding_gap": Threshold(0.03, V0314, "z; device rounding (source open)"),
    "gli_trial_gap": Threshold(
        0.5, V0314, "z; a trial match beyond this may be chance"
    ),
    "gli_lln_slack": Threshold(1e-9, V0314, "added to half a unit of the printed LLN"),
    "gli_pctpred_slack": Threshold(0.6, V0314, "points"),
    "gli_age_min": Threshold(3, "GLI-2012 range"),
    "gli_age_max": Threshold(95, "GLI-2012 range"),
    "gli_age_below": Threshold(0.5, V0314, "printed age may be rounded"),
    "gli_age_above": Threshold(0.999, V0314, "printed age may be truncated"),
    "gli_height_step_decimal": Threshold(0.05, V0314, "cm; height printed to 0.1 cm"),
    "gli_height_step_whole": Threshold(0.5, V0314, "cm; height printed to 1 cm"),
    "gli_several_disagree": Threshold(2, V0314, "z disagreements per record"),
    "second_reading_confidence": Threshold(
        50, V0314, "Tesseract confidence for a check"
    ),
}

THRESHOLDS["hb_reference_male"] = Threshold(
    14.6, "ERS/ATS 2017 DLCO standard (Graham et al.)", "g/dL"
)
THRESHOLDS["hb_reference_female"] = Threshold(
    13.4, "ERS/ATS 2017 DLCO standard (Graham et al.)", "g/dL"
)

DLCO_SI_UNITS = False
"""Whether the lab prints TLCO, KCO and VA in SI units (mmol/min/kPa). The v0.3.14
range limits (DLCO 5 to 45 typical, KCO 1.5 to 8) fit ml/min/mmHg, so traditional
units are assumed; Kirsty confirms on a redacted report."""


def T(name: str) -> float:  # short alias used throughout the rules
    return THRESHOLDS[name].value
