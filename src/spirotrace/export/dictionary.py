"""The data dictionary: one row per wide column, then one per rule, generated from
the vocabulary, the derive table and the rule registry, so the paper's methods
table and the dataset's dictionary cannot drift apart. It holds no values.
"""

from __future__ import annotations

from collections.abc import Sequence

from spirotrace.checks import RULES
from spirotrace.derive import DERIVED_NAMES
from spirotrace.model import (
    RATIO_PARAMETERS,
    TRIAL_ROLES,
    VALUE_ROLES,
    ColumnRole,
    Parameter,
    kind_of,
)
from spirotrace.store import Row

from .dataset import FIXED_COLUMNS, Dataset

DICTIONARY_FILE = "data_dictionary.csv"
DICTIONARY_COLUMNS: tuple[str, ...] = (
    "section",
    "name",
    "parameter",
    "column_role",
    "display_position",
    "kind",
    "unit",
    "stored_form",
    "source",
    "description",
    "blank_when",
    "n_records",
    "n_blank",
)
RULE_CATALOGUE_COLUMNS: tuple[str, ...] = (
    "rule_id",
    "layer",
    "severities",
    "rationale",
)

BLANK_WHEN = (
    "unreadable, excluded or under reviewer disagreement; an open error flag; "
    "or no value in the cell (empty, dash, not on the page)"
)

PARAMETER_DESCRIPTIONS: dict[Parameter, str] = {
    Parameter.FEV1: "forced expiratory volume in one second",
    Parameter.FVC: "forced vital capacity",
    Parameter.FEV1_FVC: "FEV1 over FVC, stored as a fraction whatever the printed form",
    Parameter.FEV6: "forced expiratory volume in six seconds",
    Parameter.FIVC: "forced inspiratory vital capacity",
    Parameter.PEF: "peak expiratory flow",
    Parameter.PIF: "peak inspiratory flow",
    Parameter.FEF2575: "mean forced expiratory flow between 25 and 75 percent of FVC",
    Parameter.FET: "forced expiratory time",
    Parameter.BEV: "back-extrapolated volume",
    Parameter.TLC: "total lung capacity",
    Parameter.VC_MAX: "largest vital capacity",
    Parameter.IC: "inspiratory capacity",
    Parameter.FRC: "functional residual capacity",
    Parameter.ERV: "expiratory reserve volume",
    Parameter.RV: "residual volume",
    Parameter.RV_TLC: "RV over TLC, stored as a fraction",
    Parameter.FRC_TLC: "FRC over TLC, stored as a fraction",
    Parameter.DLCO: "diffusing capacity for carbon monoxide (TLCO)",
    Parameter.DLCOC: "diffusing capacity corrected for haemoglobin",
    Parameter.KCO: "transfer coefficient (DLCO per litre of alveolar volume)",
    Parameter.VA: "alveolar volume",
    Parameter.AGE: "age at the test",
    Parameter.HEIGHT: "standing height",
    Parameter.WEIGHT: "body weight",
    Parameter.BMI: "body mass index",
    Parameter.SEX: "sex as printed",
    Parameter.ETHNICITY: "ethnic group as printed (needed by the GLI-2012 equations)",
    Parameter.SMOKER: "smoking status as printed",
    Parameter.TEST_DATE: "date of the test, ISO format",
    Parameter.HAEMOGLOBIN: "haemoglobin used for the DLCO correction",
    Parameter.BAROMETRIC_PRESSURE: "barometric pressure at the test",
    Parameter.SALBUTAMOL_DOSE: "bronchodilator dose given",
    Parameter.BRONCHODILATOR_GIVEN: "whether a bronchodilator was given",
    Parameter.CONSENT: "consent statement",
    Parameter.PROVISIONAL_REPORT: "whether the report is provisional",
    Parameter.BDR_SIGNIFICANT: "the report's own statement on bronchodilator response",
    Parameter.TESTING_ROOM: "testing room",
    Parameter.REFERENCE_SPIROMETRY: "reference equations named for spirometry",
    Parameter.REFERENCE_VOLUMES: "reference equations named for lung volumes",
    Parameter.REFERENCE_GAS_TRANSFER: "reference equations named for gas transfer",
    Parameter.SOFTWARE_VERSION: "software version printed on the report",
    Parameter.DEVICE_SERIAL: "device serial printed on the report",
    Parameter.SESSION_QUALITY: "the session-quality line as printed",
    Parameter.FEV1_GRADE: "quality grade of FEV1",
    Parameter.FVC_GRADE: "quality grade of FVC",
    Parameter.SPIROMETRY_GRADE: "quality grade of the spirometry",
    Parameter.LUNG_VOLUMES_GRADE: "quality grade of the lung volumes",
    Parameter.DLCO_GRADE: "quality grade of the gas transfer",
    Parameter.FENO_GRADE: "quality grade of the FeNO test",
    Parameter.FEV1_VARIABILITY: "difference between the two best FEV1 values",
    Parameter.FEV1_VARIABILITY_PCT: "that difference as a percentage of the best",
    Parameter.FVC_VARIABILITY: "difference between the two best FVC values",
    Parameter.FVC_VARIABILITY_PCT: "that difference as a percentage of the best",
    Parameter.TRIAL_NUMBER: "the printed trial number of a trial column",
    Parameter.TECHNICAL_COMMENTS: "technical comments",
    Parameter.INTERPRETATION_SPIROMETRY: "interpretation findings for spirometry",
    Parameter.INTERPRETATION_VOLUMES: "interpretation findings for lung volumes",
    Parameter.INTERPRETATION_GAS_TRANSFER: "interpretation findings for gas transfer",
    Parameter.INTERPRETATION_PATTERN: "the pattern phrase of the interpretation",
    Parameter.REFERRAL_REASON: "reason for referral",
    Parameter.RESPIRATORY_MEDICATION: "respiratory medication",
    Parameter.SMOKING_VAPING_STATUS: "smoking or vaping status",
}

ROLE_DESCRIPTIONS: dict[ColumnRole, str] = {
    ColumnRole.MEASURED: "the measured value",
    ColumnRole.PRE: "pre-bronchodilator (the summary best)",
    ColumnRole.POST: "post-bronchodilator (the summary best)",
    ColumnRole.LLN: "printed lower limit of normal",
    ColumnRole.POST_LLN: "printed lower limit of normal, post-bronchodilator",
    ColumnRole.ULN: "printed upper limit of normal",
    ColumnRole.PREDICTED: "printed predicted value",
    ColumnRole.PCTPRED: "printed percent of predicted",
    ColumnRole.POST_PCTPRED: "printed percent of predicted, post-bronchodilator",
    ColumnRole.Z: "printed z-score",
    ColumnRole.POST_Z: "printed z-score, post-bronchodilator",
    ColumnRole.BDR: "printed bronchodilator response column",
    ColumnRole.PCTCHG: "printed percent change",
    ColumnRole.TRIAL: "one pre-bronchodilator trial column",
    ColumnRole.POST_TRIAL: "one post-bronchodilator trial column",
    ColumnRole.TREND: "a trend-page value",
    ColumnRole.TREND_PCTPRED: "a trend-page percent of predicted",
    ColumnRole.TREND_Z: "a trend-page z-score",
    ColumnRole.FREE_TEXT: "read from the free text",
}

POSITION_NOTE = (
    "display position 1 is the Best column; the trials follow in their printed order"
)

DERIVED_DESCRIPTIONS: dict[str, str] = {
    "ratio_below_lln": "pre-bronchodilator FEV1/FVC below the lower limit (printed z, else value against printed LLN)",
    "fvc_below_lln": "pre-bronchodilator FVC below the lower limit",
    "fev1_below_lln": "pre-bronchodilator FEV1 below the lower limit",
    "tlc_below_lln": "TLC below the lower limit",
    "pattern": "ventilatory pattern by the ATS/ERS 2022 flowchart from the printed z and LLN",
    "prism": "preserved ratio impaired spirometry: normal ratio with FEV1 below the lower limit",
    "fev1_severity": "ATS/ERS 2022 grading of the FEV1 z-score",
    "bdr_fev1_pct_pred": "change in FEV1 after bronchodilator as percent of predicted",
    "bdr_fvc_pct_pred": "change in FVC after bronchodilator as percent of predicted",
    "bdr_positive_2022": "bronchodilator response at or above 10 percent of predicted (lab rule; ATS/ERS 2022 uses above 10)",
    "bdr_positive_2005": "bronchodilator response by the ATS/ERS 2005 rule (12 percent and 200 mL)",
    "report_pattern": "the pattern the report itself states",
    "grade_fev1": "harmonised quality grade of FEV1",
    "grade_fvc": "harmonised quality grade of FVC",
    "pattern_gli": "the same flowchart applied to the recalculated GLI z-scores",
}


def _gli_description(name: str) -> str:
    what = name.rsplit("_", 1)[1]
    words = {
        "z": "recalculated GLI z-score",
        "lln": "recalculated GLI lower limit of normal",
        "pred": "recalculated GLI predicted value",
        "pctpred": "recalculated percent of GLI predicted",
    }
    return f"{words.get(what, what)} from the resolved value and demographics"


def dictionary_rows(dataset: Dataset, n_records: int) -> list[Row]:
    rows: list[Row] = []
    for name in FIXED_COLUMNS:
        rows.append(
            {
                "section": "column",
                "name": name,
                "parameter": "",
                "column_role": "",
                "display_position": "",
                "kind": "number" if name.startswith("n_") else "text",
                "unit": "",
                "stored_form": "",
                "source": "record",
                "description": {
                    "record_id": "record identifier (file and layout); a participant number",
                    "layout": "the layout the record was read with",
                    "pages": "page numbers of the record in its file",
                    "n_open_errors": "values with an open error flag after review",
                    "n_open_checks": "values with an open check flag after review",
                    "n_corrected": "values corrected by a reviewer",
                }[name],
                "blank_when": "",
                "n_records": str(n_records),
                "n_blank": "0",
            }
        )
    for name in dataset.wide_columns[len(FIXED_COLUMNS) :]:
        key = dataset.column_keys.get(name)
        if key is not None:
            desc = f"{PARAMETER_DESCRIPTIONS.get(key.parameter, key.parameter.value)}: {ROLE_DESCRIPTIONS[key.column_role]}"
            if key.column_role in TRIAL_ROLES:
                desc += f"; {POSITION_NOTE}"
            ratio = key.parameter in RATIO_PARAMETERS and key.column_role in VALUE_ROLES
            rows.append(
                {
                    "section": "column",
                    "name": name,
                    "parameter": key.parameter.value,
                    "column_role": key.column_role.value,
                    "display_position": str(key.display_position)
                    if key.column_role in TRIAL_ROLES
                    else "",
                    "kind": kind_of(key.parameter).value,
                    "unit": dataset.units.get(name, ""),
                    "stored_form": "fraction" if ratio else "",
                    "source": "extracted",
                    "description": desc,
                    "blank_when": BLANK_WHEN,
                    "n_records": str(n_records),
                    "n_blank": str(dataset.blank_counts.get(name, 0)),
                }
            )
        else:
            rows.append(
                {
                    "section": "column",
                    "name": name,
                    "parameter": "",
                    "column_role": "",
                    "display_position": "",
                    "kind": "number"
                    if name.startswith(("gli_", "bdr_f"))
                    else "category",
                    "unit": "",
                    "stored_form": "",
                    "source": "derived",
                    "description": DERIVED_DESCRIPTIONS.get(name)
                    or _gli_description(name),
                    "blank_when": "not computed (the status file gives the reason)",
                    "n_records": str(n_records),
                    "n_blank": str(
                        sum(1 for r in dataset.wide_rows if r.get(name, "") == "")
                    ),
                }
            )
    for rule in sorted(RULES.values(), key=lambda r: r.id):
        rows.append(
            {
                "section": "rule",
                "name": rule.id,
                "parameter": "",
                "column_role": "",
                "display_position": "",
                "kind": rule.layer,
                "unit": "",
                "stored_form": "",
                "source": " ".join(s.value for s in rule.severities),
                "description": rule.why,
                "blank_when": "",
                "n_records": "",
                "n_blank": "",
            }
        )
    return rows


def rule_catalogue_rows() -> list[Row]:
    return [
        {
            "rule_id": r.id,
            "layer": r.layer,
            "severities": " ".join(s.value for s in r.severities),
            "rationale": r.why,
        }
        for r in sorted(RULES.values(), key=lambda r: r.id)
    ]


def rule_rationales() -> set[str]:
    """The rationales as fixed code strings, allowed verbatim by the export guard."""
    return {r.why for r in RULES.values()}


def rule_severity_labels() -> set[str]:
    """Every severity combination a rule declares, as the catalogue prints it."""
    return {" ".join(s.value for s in r.severities) for r in RULES.values()}


def derived_names_in(dataset: Dataset) -> Sequence[str]:
    return [
        n for n in dataset.derived_columns if n in DERIVED_NAMES or n.startswith("gli_")
    ]
