"""The fixed vocabularies: complete, consistent and free of never_extract fields."""

import re

from spirotrace.model import (
    FREE_TEXT_PARAMETERS,
    NEVER_EXTRACT_WORDS,
    PARAMETER_INFO,
    RATIO_PARAMETERS,
    SITE_IDENTIFIER_PARAMETERS,
    VALUE_ROLES,
    ColumnRole,
    Parameter,
    ParameterKind,
    ReadMethod,
    TextSource,
    ValueState,
    kind_of,
)


def test_value_states_are_the_six_of_seam_2() -> None:
    assert [s.value for s in ValueState] == [
        "value",
        "empty",
        "dash",
        "not_on_page",
        "unreadable",
        "struck",
    ]


def test_read_methods_are_the_plan_list() -> None:
    assert [m.value for m in ReadMethod] == [
        "text_layer",
        "ocr",
        "ocr_cell",
        "position_fallback",
        "inferred",
        "manual",
    ]


def test_text_sources() -> None:
    assert [t.value for t in TextSource] == ["text_layer", "ocr", "none"]


def test_pre_and_post_roles_never_share_a_name() -> None:
    roles = {r.value for r in ColumnRole}
    for post in ("post", "post_lln", "post_pctpred", "post_z", "post_trial"):
        assert post in roles
    assert "best" not in roles, "Best is display position 1, not a role"


def test_value_roles_are_the_agreed_set() -> None:
    assert {r.value for r in VALUE_ROLES} == {
        "measured",
        "pre",
        "post",
        "predicted",
        "lln",
        "post_lln",
        "uln",
        "trial",
        "post_trial",
        "trend",
    }
    for role in ("pctpred", "post_pctpred", "z", "post_z", "bdr", "pctchg"):
        assert ColumnRole(role) not in VALUE_ROLES


def test_every_parameter_has_info_and_nothing_else_does() -> None:
    assert set(PARAMETER_INFO) == set(Parameter)
    for parameter in Parameter:
        assert isinstance(kind_of(parameter), ParameterKind)


def test_plan_lung_function_parameters_present() -> None:
    plan = [
        "FEV1",
        "FVC",
        "FEV1_FVC",
        "FIVC",
        "PEF",
        "FET",
        "TLC",
        "VC_MAX",
        "RV",
        "RV_TLC",
    ]
    plan += ["FRC", "ERV", "IC", "DLCO", "DLCOc", "KCO", "VA"]
    values = {p.value for p in Parameter}
    assert set(plan) <= values
    # printed on the current reports, added 14 Oct
    assert {"FEV6", "PIF", "FEF2575", "BEV", "FRC_TLC"} <= values


def test_ratio_parameters() -> None:
    assert {p.value for p in RATIO_PARAMETERS} == {"FEV1_FVC", "RV_TLC", "FRC_TLC"}
    for p in RATIO_PARAMETERS:
        assert kind_of(p) is ParameterKind.NUMBER


def test_clinical_free_text_parameters_are_marked() -> None:
    expected = {
        "smoking_vaping_status",
        "bronchodilator_given",
        "salbutamol_dose",
        "technical_comments",
        "interpretation_spirometry",
        "interpretation_volumes",
        "interpretation_gas_transfer",
        "interpretation_pattern",
        "referral_reason",
        "respiratory_medication",
        "consent",
        "provisional_report",
        "testing_room",
        "bdr_significant",
    }
    assert {p.value for p in FREE_TEXT_PARAMETERS} == expected


def test_never_extract_words_cover_people_and_contact_details() -> None:
    expected = {
        "name",
        "surname",
        "birth",
        "dob",
        "id",
        "nhi",
        "mrn",
        "patient",
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
        "address",
        "phone",
        "email",
    }
    assert expected <= NEVER_EXTRACT_WORDS


def test_site_identifiers_are_marked_for_the_export_guard() -> None:
    assert {p.value for p in SITE_IDENTIFIER_PARAMETERS} == {
        "device_serial",
        "software_version",
    }
    for parameter in Parameter:
        info = PARAMETER_INFO[parameter]
        assert info.site_identifier == (parameter in SITE_IDENTIFIER_PARAMETERS)


def test_no_parameter_names_a_never_extract_field() -> None:
    for parameter in Parameter:
        words = set(re.split(r"[_\W]+", parameter.value.lower())) | set(
            re.split(r"[_\W]+", parameter.name.lower())
        )
        hit = words & NEVER_EXTRACT_WORDS
        assert not hit, f"{parameter} names a never_extract field: {hit}"


def test_parameter_values_are_unique_and_key_safe() -> None:
    values = [p.value for p in Parameter]
    assert len(values) == len(set(values))
    for value in values + [r.value for r in ColumnRole]:
        assert ":" not in value and " " not in value
