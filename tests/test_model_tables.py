"""Record, Page, ObservationKey and Observation: invariants and exact row round trips.

All values are synthetic.
"""

from dataclasses import FrozenInstanceError, fields, replace
from hashlib import sha256
from typing import Any

import pytest

from spirotrace.model import (
    ColumnRole,
    ModelError,
    Observation,
    ObservationKey,
    Page,
    Parameter,
    RatioForm,
    ReadMethod,
    Record,
    TextSource,
    ValueState,
    parse_ratio,
)

HASH = sha256(b"synthetic report").hexdigest()
OTHER_HASH = sha256(b"another synthetic report").hexdigest()


def key(**overrides: Any) -> ObservationKey:
    base: dict[str, Any] = {
        "file_hash": HASH,
        "page": 2,
        "template_id": "spiro_a",
        "parameter": Parameter.FEV1,
        "column_role": ColumnRole.PRE,
        "display_position": 1,
    }
    base.update(overrides)
    return ObservationKey(**base)


def obs(**overrides: Any) -> Observation:
    base: dict[str, Any] = {
        "key": key(),
        "record_id": "11",
        "template_version": 3,
        "raw_text": "3.52",
        "parsed_value": 3.52,
        "parsed_text": None,
        "unit": "L",
        "printed_form": None,
        "marked": False,
        "bbox": (100.0, 200.5, 140.25, 212.0),
        "read_method": ReadMethod.TEXT_LAYER,
        "ocr_confidence": None,
        "second_reading_run": False,
        "second_reading": None,
        "value_state": ValueState.VALUE,
    }
    base.update(overrides)
    return Observation(**base)


def page(**overrides: Any) -> Page:
    base: dict[str, Any] = {
        "file_hash": HASH,
        "page": 1,
        "page_type": "summary",
        "footer_page_number": 1,
        "word_count": 412,
        "rotation": 0,
        "skew": -0.35,
        "ink": 0.1234,
        "text_source": TextSource.TEXT_LAYER,
    }
    base.update(overrides)
    return Page(**base)


def record(**overrides: Any) -> Record:
    base: dict[str, Any] = {
        "record_id": "11",
        "file_hash": HASH,
        "layout": "spiro_a",
        "subject_id": "11",
        "pages": (1, 2),
    }
    base.update(overrides)
    return Record(**base)


# --- Record -----------------------------------------------------------------


@pytest.mark.parametrize(
    "record_id",
    [
        # subject id from the file name, one or two layouts
        "11",
        "11A",
        "11B",
        "7",
        "0011",
        "123456",
        # a second, third ... file for the same subject id
        "11-2",
        "11-3",
        "11A-2",
        "11B-10",
        # no subject id in the file name: "f" plus the first 8 hex of the file hash
        "f" + HASH[:8],
        "f" + HASH[:8] + "A",
        "f" + HASH[:8] + "B-2",
    ],
)
def test_record_id_forms_accepted(record_id: str) -> None:
    assert record(record_id=record_id).record_id == record_id


@pytest.mark.parametrize(
    "record_id",
    [
        "11C",
        "11a",
        "A11",
        "11 A",
        "",
        "11AB",
        "11-A",
        "eleven",
        "11.0",
        # duplicate suffix starts at 2 and has no leading zero
        "11-1",
        "11-0",
        "11-02",
        "11-",
        "11--2",
        # the layout letter comes before the duplicate suffix
        "11-2A",
        # the hash form is "f" plus exactly 8 lowercase hex characters
        "f" + HASH[:7],
        "f" + HASH[:9],
        "F" + HASH[:8],
        "f" + HASH[:8].upper(),
        "g" + HASH[:8],
        HASH[:8],
    ],
)
def test_record_id_forms_refused(record_id: str) -> None:
    with pytest.raises(ModelError, match="record_id"):
        record(record_id=record_id)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"file_hash": HASH.upper()},
        {"file_hash": HASH[:40]},
        {"layout": "Spiro A"},
        {"pages": ()},
        {"pages": (0, 1)},
        {"pages": (2, 1)},
        {"pages": (1, 1)},
    ],
)
def test_record_invariants(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ModelError):
        record(**kwargs)


def test_record_round_trip_including_empty_subject_id() -> None:
    for r in (record(), record(record_id="11B", subject_id="", pages=(3,))):
        row = r.to_row()
        assert tuple(row) == Record.COLUMNS
        assert Record.from_row(row) == r


# --- Page -------------------------------------------------------------------


def test_page_round_trip_with_and_without_optional_columns() -> None:
    for p in (
        page(),
        page(
            page_type=None, footer_page_number=None, word_count=0, rotation=270, ink=0.0
        ),
        page(text_source=TextSource.OCR, skew=0.0, ink=1.0),
    ):
        row = p.to_row()
        assert tuple(row) == Page.COLUMNS
        assert Page.from_row(row) == p


@pytest.mark.parametrize(
    "kwargs",
    [
        {"page": 0},
        {"page_type": ""},
        {"footer_page_number": 0},
        {"word_count": -1},
        {"rotation": 45},
        {"skew": float("nan")},
        {"ink": 1.5},
        {"ink": -0.1},
        {"text_source": "ocr"},
    ],
)
def test_page_invariants(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ModelError):
        page(**kwargs)


# --- ObservationKey ---------------------------------------------------------


def test_key_string_form_round_trips() -> None:
    k = key(
        parameter=Parameter.FEV1_FVC,
        column_role=ColumnRole.POST_TRIAL,
        display_position=3,
    )
    text = k.to_string()
    assert text == f"{HASH}:2:spiro_a:FEV1_FVC:post_trial:3"
    assert ObservationKey.from_string(text) == k
    assert ObservationKey.from_row(k.to_row()) == k
    assert tuple(k.to_row()) == ObservationKey.COLUMNS


def test_every_parameter_and_role_round_trips_through_the_string() -> None:
    for parameter in Parameter:
        role = (
            ColumnRole.TRIAL
            if parameter is Parameter.TRIAL_NUMBER
            else ColumnRole.MEASURED
        )
        k = key(parameter=parameter, column_role=role)
        assert ObservationKey.from_string(k.to_string()) == k
    for role in ColumnRole:
        k = key(column_role=role)
        assert ObservationKey.from_string(k.to_string()) == k


@pytest.mark.parametrize(
    "text",
    [
        f"{HASH}:2:spiro_a:FEV1:pre",
        f"{HASH}:2:spiro_a:FEV1:pre:1:extra",
        f"{HASH}:2:spiro_a:FEV_ONE:pre:1",
        f"{HASH}:2:spiro_a:FEV1:best:1",
        f"{HASH}:two:spiro_a:FEV1:pre:1",
        f"{HASH}:2:spiro_a:FEV1:pre:0",
        f"{HASH[:10]}:2:spiro_a:FEV1:pre:1",
    ],
)
def test_bad_key_strings_refused(text: str) -> None:
    with pytest.raises(ModelError):
        ObservationKey.from_string(text)


def test_key_is_hashable_and_ordered() -> None:
    a = key(display_position=1)
    b = key(display_position=2)
    c = key(page=3)
    assert len({a, b, c, key()}) == 3
    assert sorted([c, b, a]) == [a, b, c]


def test_trial_number_needs_a_trial_role() -> None:
    assert key(parameter=Parameter.TRIAL_NUMBER, column_role=ColumnRole.POST_TRIAL)
    with pytest.raises(ModelError, match="trial_number"):
        key(parameter=Parameter.TRIAL_NUMBER, column_role=ColumnRole.PRE)


def test_pre_and_post_values_have_distinct_keys() -> None:
    assert key(column_role=ColumnRole.PRE) != key(column_role=ColumnRole.POST)
    assert key(column_role=ColumnRole.Z) != key(column_role=ColumnRole.POST_Z)


# --- Observation: value_state and parsed value agree ------------------------

STATE_PAYLOADS = {
    ValueState.VALUE: {"raw_text": "3.52", "parsed_value": 3.52},
    ValueState.EMPTY: {"raw_text": "", "parsed_value": None},
    ValueState.DASH: {"raw_text": "-", "parsed_value": None},
    ValueState.NOT_ON_PAGE: {"raw_text": "", "parsed_value": None, "bbox": None},
    ValueState.UNREADABLE: {"raw_text": "3.S2", "parsed_value": None},
    ValueState.STRUCK: {"raw_text": "3.52", "parsed_value": None},
}


@pytest.mark.parametrize("state", list(ValueState))
def test_every_value_state_round_trips(state: ValueState) -> None:
    o = obs(value_state=state, **STATE_PAYLOADS[state])
    row = o.to_row()
    assert tuple(row) == Observation.COLUMNS
    assert Observation.from_row(row) == o


def test_all_states_are_covered() -> None:
    assert set(STATE_PAYLOADS) == set(ValueState)


@pytest.mark.parametrize("state", [s for s in ValueState if s is not ValueState.VALUE])
def test_non_value_state_with_a_parsed_value_refused(state: ValueState) -> None:
    payload = dict(STATE_PAYLOADS[state])
    payload["parsed_value"] = 3.52
    with pytest.raises(ModelError, match="must not carry a parsed value"):
        obs(value_state=state, **payload)
    payload["parsed_value"] = 0.0
    with pytest.raises(ModelError):
        obs(value_state=state, **payload)


def test_value_state_without_a_parsed_value_refused() -> None:
    with pytest.raises(ModelError, match="parsed_value"):
        obs(parsed_value=None)


def test_number_parameter_rejects_text_and_text_parameter_rejects_number() -> None:
    with pytest.raises(ModelError):
        obs(parsed_value=None, parsed_text="3.52")
    sex = key(parameter=Parameter.SEX, column_role=ColumnRole.MEASURED)
    with pytest.raises(ModelError):
        obs(key=sex, raw_text="F", parsed_value=1.0, parsed_text=None, unit=None)
    with pytest.raises(ModelError):
        obs(key=sex, raw_text="F", parsed_value=None, parsed_text="", unit=None)
    o = obs(key=sex, raw_text="F", parsed_value=None, parsed_text="female", unit=None)
    assert Observation.from_row(o.to_row()) == o


def test_date_parameter_needs_an_iso_date() -> None:
    k = key(parameter=Parameter.TEST_DATE, column_role=ColumnRole.MEASURED)
    o = obs(
        key=k,
        raw_text="03/04/2024",
        parsed_value=None,
        parsed_text="2024-04-03",
        unit=None,
    )
    assert Observation.from_row(o.to_row()) == o
    with pytest.raises(ModelError, match="ISO date"):
        obs(
            key=k,
            raw_text="03/04/2024",
            parsed_value=None,
            parsed_text="03/04/2024",
            unit=None,
        )


def test_unit_only_on_number_parameters_and_never_empty() -> None:
    with pytest.raises(ModelError, match="unit"):
        obs(unit="")
    k = key(parameter=Parameter.SEX, column_role=ColumnRole.MEASURED)
    with pytest.raises(ModelError, match="unit"):
        obs(key=k, raw_text="F", parsed_value=None, parsed_text="female", unit="L")


# --- Observation: ratios ----------------------------------------------------


def ratio_obs(role: ColumnRole, text: str, **overrides: Any) -> Observation:
    k = key(parameter=Parameter.FEV1_FVC, column_role=role)
    return obs(key=k, raw_text=text, **{"unit": None, **overrides})


def test_ratio_value_role_stores_fraction_with_printed_form() -> None:
    fraction, form = parse_ratio("78")
    o = ratio_obs(ColumnRole.PRE, "78", parsed_value=fraction, printed_form=form)
    assert o.parsed_value == 0.78 and o.printed_form is RatioForm.PERCENT
    row = o.to_row()
    assert row["parsed_value"] == "0.78" and row["printed_form"] == "percent"
    assert Observation.from_row(row) == o


def test_ratio_pctpred_is_a_plain_number_not_a_ratio() -> None:
    # The %pred of FEV1/FVC is a percent of predicted: "96" is the number 96.
    o = ratio_obs(ColumnRole.PCTPRED, "96", parsed_value=96.0)
    assert o.parsed_value == 96.0 and o.printed_form is None
    assert Observation.from_row(o.to_row()) == o
    for role in (
        ColumnRole.POST_PCTPRED,
        ColumnRole.Z,
        ColumnRole.POST_Z,
        ColumnRole.BDR,
    ):
        assert ratio_obs(role, "1.23", parsed_value=1.23).printed_form is None


def test_ratio_invariants() -> None:
    with pytest.raises(ModelError, match="printed_form"):
        ratio_obs(ColumnRole.PRE, "78", parsed_value=0.78)
    with pytest.raises(ModelError, match="fraction"):
        ratio_obs(
            ColumnRole.PRE, "78", parsed_value=78.0, printed_form=RatioForm.PERCENT
        )
    with pytest.raises(ModelError, match="printed_form"):
        ratio_obs(
            ColumnRole.PCTPRED, "96", parsed_value=96.0, printed_form=RatioForm.PERCENT
        )
    with pytest.raises(ModelError, match="printed_form"):
        obs(printed_form=RatioForm.FRACTION)
    with pytest.raises(ModelError, match="unit"):
        ratio_obs(
            ColumnRole.PRE,
            "78",
            parsed_value=0.78,
            printed_form=RatioForm.PERCENT,
            unit="%",
        )
    # a ratio that is not a value carries no printed form
    assert ratio_obs(
        ColumnRole.PRE, "", parsed_value=None, value_state=ValueState.EMPTY
    )


# --- Observation: second reading, bbox, marks ------------------------------


def test_second_reading_states_round_trip_and_stay_distinct() -> None:
    not_run = obs(second_reading_run=False, second_reading=None)
    read_nothing = obs(second_reading_run=True, second_reading="")
    read_value = obs(second_reading_run=True, second_reading="3.52")
    for o in (not_run, read_nothing, read_value):
        assert Observation.from_row(o.to_row()) == o
    assert len({not_run, read_nothing, read_value}) == 3
    assert (
        not_run.to_row()["second_reading"]
        == read_nothing.to_row()["second_reading"]
        == ""
    )
    assert not_run.to_row()["second_reading_run"] == "false"
    assert read_nothing.to_row()["second_reading_run"] == "true"


def test_second_reading_mismatch_refused() -> None:
    with pytest.raises(ModelError, match="second_reading"):
        obs(second_reading_run=True, second_reading=None)
    with pytest.raises(ModelError, match="second_reading"):
        obs(second_reading_run=False, second_reading="")


def test_second_reading_needs_a_bbox_on_a_page() -> None:
    # the second OCR crops the observation's bbox, so there is nothing to run on
    with pytest.raises(ModelError, match="second_reading_run"):
        obs(bbox=None, second_reading_run=True, second_reading="3.52")
    with pytest.raises(ModelError, match="second_reading_run"):
        obs(
            value_state=ValueState.NOT_ON_PAGE,
            raw_text="",
            parsed_value=None,
            bbox=None,
            second_reading_run=True,
            second_reading="",
        )
    assert obs(
        read_method=ReadMethod.POSITION_FALLBACK,
        second_reading_run=True,
        second_reading="3.52",
    )


@pytest.mark.parametrize("method", [ReadMethod.MANUAL, ReadMethod.INFERRED])
def test_manual_and_inferred_readings_have_no_ocr_fields(method: ReadMethod) -> None:
    with pytest.raises(ModelError, match="second_reading_run"):
        obs(read_method=method, second_reading_run=True, second_reading="3.52")
    with pytest.raises(ModelError, match="ocr_confidence"):
        obs(read_method=method, ocr_confidence=90.0)


def test_ocr_confidence_only_with_ocr_and_within_0_to_100() -> None:
    with pytest.raises(ModelError, match="ocr_confidence"):
        obs(read_method=ReadMethod.TEXT_LAYER, ocr_confidence=87.5)
    with pytest.raises(ModelError, match="ocr_confidence"):
        obs(read_method=ReadMethod.POSITION_FALLBACK, ocr_confidence=87.5)
    for bad in (-0.1, 100.1, 250.0):
        with pytest.raises(ModelError, match="ocr_confidence"):
            obs(read_method=ReadMethod.OCR, ocr_confidence=bad)
    for ok in (0.0, 100.0, 87.5, None):
        o = obs(read_method=ReadMethod.OCR, ocr_confidence=ok)
        assert Observation.from_row(o.to_row()) == o


def test_not_on_page_has_no_text_and_no_bbox() -> None:
    with pytest.raises(ModelError, match="not_on_page"):
        obs(
            value_state=ValueState.NOT_ON_PAGE,
            raw_text="x",
            parsed_value=None,
            bbox=None,
        )
    with pytest.raises(ModelError, match="not_on_page"):
        obs(value_state=ValueState.NOT_ON_PAGE, raw_text="", parsed_value=None)


def test_bbox_rules_and_round_trip() -> None:
    with pytest.raises(ModelError, match="bbox"):
        obs(bbox=(10.0, 10.0, 5.0, 20.0))
    with pytest.raises(ModelError, match="bbox"):
        obs(bbox=(10.0, 10.0, 20.0, float("inf")))
    o = obs(bbox=None, read_method=ReadMethod.MANUAL)
    row = o.to_row()
    assert row["bbox_x0"] == row["bbox_y1"] == ""
    assert Observation.from_row(row) == o
    row = obs().to_row()
    row["bbox_y1"] = ""
    with pytest.raises(ModelError, match="bbox"):
        Observation.from_row(row)


def test_marked_ocr_confidence_and_raw_text_round_trip() -> None:
    o = obs(
        raw_text="3.52 *",
        marked=True,
        read_method=ReadMethod.OCR,
        ocr_confidence=87.5,
        bbox=(1.5, 2.25, 3.125, 4.0625),
    )
    row = o.to_row()
    assert row["marked"] == "true" and row["ocr_confidence"] == "87.5"
    assert Observation.from_row(row) == o
    tricky = obs(
        raw_text=" ~3,52 – ", parsed_value=None, value_state=ValueState.UNREADABLE
    )
    assert Observation.from_row(tricky.to_row()) == tricky


def test_float_round_trip_is_exact_for_awkward_values() -> None:
    for value in (0.1, 1 / 3, 2.675, 1e-7, 123456.789):
        o = obs(parsed_value=value, raw_text=str(value))
        assert Observation.from_row(o.to_row()).parsed_value == value


# --- Rows and immutability --------------------------------------------------


def test_from_row_names_missing_columns() -> None:
    row = obs().to_row()
    del row["value_state"]
    with pytest.raises(ModelError, match="value_state"):
        Observation.from_row(row)
    with pytest.raises(ModelError, match="true or false"):
        Observation.from_row({**obs().to_row(), "marked": "yes"})


def test_columns_match_dataclass_fields() -> None:
    assert set(Record.COLUMNS) == {f.name for f in fields(Record)}
    assert set(Page.COLUMNS) == {f.name for f in fields(Page)}
    assert set(ObservationKey.COLUMNS) == {f.name for f in fields(ObservationKey)}
    flat = {f.name for f in fields(Observation)} - {"key", "bbox"}
    flat |= set(ObservationKey.COLUMNS) | {"bbox_x0", "bbox_y0", "bbox_x1", "bbox_y1"}
    assert set(Observation.COLUMNS) == flat
    assert len(Observation.COLUMNS) == len(set(Observation.COLUMNS))


def test_records_cannot_be_mutated() -> None:
    o = obs()
    for target, name in (
        (o, "raw_text"),
        (o.key, "page"),
        (record(), "pages"),
        (page(), "ink"),
    ):
        with pytest.raises(FrozenInstanceError):
            setattr(target, name, 1)
    assert isinstance(o.bbox, tuple) and isinstance(record().pages, tuple)
    assert replace(o, marked=True) != o


def test_other_file_other_key() -> None:
    assert key(file_hash=OTHER_HASH) != key()
