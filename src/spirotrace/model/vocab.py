"""Fixed vocabularies: value states, read methods, column roles and parameters.

Every template maps its row labels and column headers onto these names, so
every layout's output has the same columns. Adding a member is a visible,
one-line change here; nothing elsewhere derives vocabulary from a report.

There is deliberately no parameter for a name, date of birth, patient ID,
referrer, operator, physician or physiologist (the ``never_extract`` list),
so an observation of one cannot be constructed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class ValueState(StrEnum):
    """What the cell held (seam 2). Only ``VALUE`` carries a parsed value.

    A struck-through value (a trial marked "Not Usable") is still a readable
    ``VALUE``; the strikethrough is ``Observation.struck``, not a state.
    """

    VALUE = "value"
    EMPTY = "empty"
    DASH = "dash"
    NOT_ON_PAGE = "not_on_page"
    UNREADABLE = "unreadable"


class ReadMethod(StrEnum):
    """How the raw text was obtained.

    ``OCR_CELL`` names the per-cell second OCR reading. That reading lives only
    in ``Observation.second_reading`` (and the second-OCR cache), so it is
    never the read method of an observation itself: the second reading is a
    comparison and a suggestion, applied only through a reviewer event.
    """

    TEXT_LAYER = "text_layer"
    OCR = "ocr"
    OCR_CELL = "ocr_cell"
    POSITION_FALLBACK = "position_fallback"
    INFERRED = "inferred"
    MANUAL = "manual"


class TextSource(StrEnum):
    """Where a page's words came from."""

    TEXT_LAYER = "text_layer"
    OCR = "ocr"
    NONE = "none"


class RatioForm(StrEnum):
    """How a ratio was printed; the stored value is always a fraction."""

    PERCENT = "percent"
    FRACTION = "fraction"


class ColumnRole(StrEnum):
    """The column a value was read from, or the kind of reading for non-table values.

    Pre-bronchodilator and post-bronchodilator columns never share a role, so
    pre and post values of one parameter never share a key.
    """

    MEASURED = "measured"
    PRE = "pre"
    POST = "post"
    LLN = "lln"
    POST_LLN = "post_lln"
    ULN = "uln"
    PREDICTED = "predicted"
    PCTPRED = "pctpred"
    POST_PCTPRED = "post_pctpred"
    Z = "z"
    POST_Z = "post_z"
    BDR = "bdr"
    PCTCHG = "pctchg"
    TRIAL = "trial"
    POST_TRIAL = "post_trial"
    TREND = "trend"
    TREND_PCTPRED = "trend_pctpred"
    TREND_Z = "trend_z"
    FREE_TEXT = "free_text"


VALUE_ROLES: frozenset[ColumnRole] = frozenset(
    {
        ColumnRole.MEASURED,
        ColumnRole.PRE,
        ColumnRole.POST,
        ColumnRole.PREDICTED,
        ColumnRole.LLN,
        ColumnRole.POST_LLN,
        ColumnRole.ULN,
        ColumnRole.TRIAL,
        ColumnRole.POST_TRIAL,
        ColumnRole.TREND,
    }
)
"""Roles holding a value in the parameter's own unit. The ratio rule applies here only."""

TRIAL_ROLES: frozenset[ColumnRole] = frozenset(
    {ColumnRole.TRIAL, ColumnRole.POST_TRIAL}
)


class ParameterKind(StrEnum):
    """Which parsed column an observation of the parameter may fill."""

    NUMBER = "number"
    CATEGORY = "category"
    DATE = "date"
    TEXT = "text"


class Parameter(StrEnum):
    """Standard parameter names. Lung function values keep their printed spelling."""

    # Lung function (rewrite plan list plus the values the current reports print)
    FEV1 = "FEV1"
    FVC = "FVC"
    FEV1_FVC = "FEV1_FVC"
    FEV6 = "FEV6"
    FIVC = "FIVC"
    PEF = "PEF"
    PIF = "PIF"
    FEF2575 = "FEF2575"
    FET = "FET"
    BEV = "BEV"
    TLC = "TLC"
    VC_MAX = "VC_MAX"
    IC = "IC"
    FRC = "FRC"
    ERV = "ERV"
    RV = "RV"
    RV_TLC = "RV_TLC"
    FRC_TLC = "FRC_TLC"
    DLCO = "DLCO"
    DLCOC = "DLCOc"
    KCO = "KCO"
    VA = "VA"
    # Demographics and anthropometrics
    AGE = "age"
    HEIGHT = "height"
    WEIGHT = "weight"
    BMI = "bmi"
    SEX = "sex"
    ETHNICITY = "ethnicity"
    SMOKER = "smoker"
    TEST_DATE = "test_date"
    # Test context
    HAEMOGLOBIN = "haemoglobin"
    BAROMETRIC_PRESSURE = "barometric_pressure"
    SALBUTAMOL_DOSE = "salbutamol_dose"
    BRONCHODILATOR_GIVEN = "bronchodilator_given"
    CONSENT = "consent"
    PROVISIONAL_REPORT = "provisional_report"
    BDR_SIGNIFICANT = "bdr_significant"
    TESTING_ROOM = "testing_room"
    REFERENCE_SPIROMETRY = "reference_spirometry"
    REFERENCE_VOLUMES = "reference_volumes"
    REFERENCE_GAS_TRANSFER = "reference_gas_transfer"
    SOFTWARE_VERSION = "software_version"
    DEVICE_SERIAL = "device_serial"
    # Session quality
    SESSION_QUALITY = "session_quality"
    FEV1_GRADE = "fev1_grade"
    FVC_GRADE = "fvc_grade"
    SPIROMETRY_GRADE = "spirometry_grade"
    LUNG_VOLUMES_GRADE = "lung_volumes_grade"
    DLCO_GRADE = "dlco_grade"
    FENO_GRADE = "feno_grade"
    FEV1_VARIABILITY = "fev1_variability"
    FEV1_VARIABILITY_PCT = "fev1_variability_pct"
    FVC_VARIABILITY = "fvc_variability"
    FVC_VARIABILITY_PCT = "fvc_variability_pct"
    TRIAL_NUMBER = "trial_number"
    # Free text
    TECHNICAL_COMMENTS = "technical_comments"
    INTERPRETATION_SPIROMETRY = "interpretation_spirometry"
    INTERPRETATION_VOLUMES = "interpretation_volumes"
    INTERPRETATION_GAS_TRANSFER = "interpretation_gas_transfer"
    INTERPRETATION_PATTERN = "interpretation_pattern"
    REFERRAL_REASON = "referral_reason"
    RESPIRATORY_MEDICATION = "respiratory_medication"
    SMOKING_VAPING_STATUS = "smoking_vaping_status"


@dataclass(frozen=True, slots=True)
class ParameterInfo:
    """What kind of value a parameter holds and whether it is clinical free text.

    Parameters
    ----------
    kind
        The parsed column the parameter fills.
    ratio
        True for ratios stored as a fraction with the printed form kept.
    contains_free_text
        True for clinical fields that later stages write only to
        ``*_CONTAINS_DATA`` outputs; the export guard reads this.
    site_identifier
        True for values that identify the testing site or its equipment
        rather than the subject (device serial, software version); the
        export guard decides whether they leave ``share/``.
    """

    kind: ParameterKind
    ratio: bool = False
    contains_free_text: bool = False
    site_identifier: bool = False


_N = ParameterKind.NUMBER
_C = ParameterKind.CATEGORY
_D = ParameterKind.DATE
_T = ParameterKind.TEXT

PARAMETER_INFO: dict[Parameter, ParameterInfo] = {
    Parameter.FEV1: ParameterInfo(_N),
    Parameter.FVC: ParameterInfo(_N),
    Parameter.FEV1_FVC: ParameterInfo(_N, ratio=True),
    Parameter.FEV6: ParameterInfo(_N),
    Parameter.FIVC: ParameterInfo(_N),
    Parameter.PEF: ParameterInfo(_N),
    Parameter.PIF: ParameterInfo(_N),
    Parameter.FEF2575: ParameterInfo(_N),
    Parameter.FET: ParameterInfo(_N),
    Parameter.BEV: ParameterInfo(_N),
    Parameter.TLC: ParameterInfo(_N),
    Parameter.VC_MAX: ParameterInfo(_N),
    Parameter.IC: ParameterInfo(_N),
    Parameter.FRC: ParameterInfo(_N),
    Parameter.ERV: ParameterInfo(_N),
    Parameter.RV: ParameterInfo(_N),
    Parameter.RV_TLC: ParameterInfo(_N, ratio=True),
    Parameter.FRC_TLC: ParameterInfo(_N, ratio=True),
    Parameter.DLCO: ParameterInfo(_N),
    Parameter.DLCOC: ParameterInfo(_N),
    Parameter.KCO: ParameterInfo(_N),
    Parameter.VA: ParameterInfo(_N),
    Parameter.AGE: ParameterInfo(_N),
    Parameter.HEIGHT: ParameterInfo(_N),
    Parameter.WEIGHT: ParameterInfo(_N),
    Parameter.BMI: ParameterInfo(_N),
    Parameter.SEX: ParameterInfo(_C),
    Parameter.ETHNICITY: ParameterInfo(_C),
    Parameter.SMOKER: ParameterInfo(_C),
    Parameter.TEST_DATE: ParameterInfo(_D),
    Parameter.HAEMOGLOBIN: ParameterInfo(_N),
    Parameter.BAROMETRIC_PRESSURE: ParameterInfo(_N),
    Parameter.SALBUTAMOL_DOSE: ParameterInfo(_N, contains_free_text=True),
    Parameter.BRONCHODILATOR_GIVEN: ParameterInfo(_C, contains_free_text=True),
    Parameter.CONSENT: ParameterInfo(_C, contains_free_text=True),
    Parameter.PROVISIONAL_REPORT: ParameterInfo(_C, contains_free_text=True),
    Parameter.BDR_SIGNIFICANT: ParameterInfo(_C, contains_free_text=True),
    Parameter.TESTING_ROOM: ParameterInfo(_T, contains_free_text=True),
    Parameter.REFERENCE_SPIROMETRY: ParameterInfo(_T),
    Parameter.REFERENCE_VOLUMES: ParameterInfo(_T),
    Parameter.REFERENCE_GAS_TRANSFER: ParameterInfo(_T),
    Parameter.SOFTWARE_VERSION: ParameterInfo(_T, site_identifier=True),
    Parameter.DEVICE_SERIAL: ParameterInfo(_T, site_identifier=True),
    Parameter.SESSION_QUALITY: ParameterInfo(_T),
    Parameter.FEV1_GRADE: ParameterInfo(_C),
    Parameter.FVC_GRADE: ParameterInfo(_C),
    Parameter.SPIROMETRY_GRADE: ParameterInfo(_C),
    Parameter.LUNG_VOLUMES_GRADE: ParameterInfo(_C),
    Parameter.DLCO_GRADE: ParameterInfo(_C),
    Parameter.FENO_GRADE: ParameterInfo(_C),
    Parameter.FEV1_VARIABILITY: ParameterInfo(_N),
    Parameter.FEV1_VARIABILITY_PCT: ParameterInfo(_N),
    Parameter.FVC_VARIABILITY: ParameterInfo(_N),
    Parameter.FVC_VARIABILITY_PCT: ParameterInfo(_N),
    Parameter.TRIAL_NUMBER: ParameterInfo(_N),
    Parameter.TECHNICAL_COMMENTS: ParameterInfo(_T, contains_free_text=True),
    Parameter.INTERPRETATION_SPIROMETRY: ParameterInfo(_T, contains_free_text=True),
    Parameter.INTERPRETATION_VOLUMES: ParameterInfo(_T, contains_free_text=True),
    Parameter.INTERPRETATION_GAS_TRANSFER: ParameterInfo(_T, contains_free_text=True),
    Parameter.INTERPRETATION_PATTERN: ParameterInfo(_C, contains_free_text=True),
    Parameter.REFERRAL_REASON: ParameterInfo(_T, contains_free_text=True),
    Parameter.RESPIRATORY_MEDICATION: ParameterInfo(_T, contains_free_text=True),
    Parameter.SMOKING_VAPING_STATUS: ParameterInfo(_T, contains_free_text=True),
}

RATIO_PARAMETERS: frozenset[Parameter] = frozenset(
    p for p, info in PARAMETER_INFO.items() if info.ratio
)
FREE_TEXT_PARAMETERS: frozenset[Parameter] = frozenset(
    p for p, info in PARAMETER_INFO.items() if info.contains_free_text
)
SITE_IDENTIFIER_PARAMETERS: frozenset[Parameter] = frozenset(
    p for p, info in PARAMETER_INFO.items() if info.site_identifier
)

NEVER_EXTRACT_WORDS: frozenset[str] = frozenset(
    {
        # the person
        "name",
        "surname",
        "birth",
        "dob",
        "id",
        "nhi",
        "mrn",
        "patient",
        "address",
        "phone",
        "email",
        # the people around the test
        "referrer",
        "requester",
        "operator",
        "physician",
        "physiologist",
        "doctor",
        "consultant",
        "gp",
        "technician",
        "nurse",
        "clinician",
        "staff",
        # the sign-off line on the lab continuation page: a staff name and date
        "signed by",
        "authorised by",
        "final:",
    }
)
"""Words and label phrases that may not appear in any parameter name or be
declared as a template field. Matched by :func:`never_extract_hits`; a test
enforces it for the parameters here."""

_WORD_BREAK_RE = re.compile(r"[_\W]+")


def _normalise(text: str) -> str:
    return " ".join(_WORD_BREAK_RE.split(text.lower())).strip()


def never_extract_hits(text: str) -> frozenset[str]:
    """Return the :data:`NEVER_EXTRACT_WORDS` entries that ``text`` contains.

    Matching is case-insensitive on whole words: underscores and punctuation
    count as word breaks, so ``"signed_by_date"`` hits ``"signed by"`` and
    ``"Final: Dr X"`` hits ``"final:"``, while ``"grid"`` does not hit ``"id"``.
    """
    haystack = f" {_normalise(text)} "
    return frozenset(
        entry for entry in NEVER_EXTRACT_WORDS if f" {_normalise(entry)} " in haystack
    )


def kind_of(parameter: Parameter) -> ParameterKind:
    """Return the parsed-column kind of ``parameter``."""
    return PARAMETER_INFO[parameter].kind
