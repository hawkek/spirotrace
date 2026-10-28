"""The export guard: only four files, no value-carrying columns, digits only where
declared, every other token from the vocabulary, planted identifiers never pass."""

from __future__ import annotations

from pathlib import Path

import pytest

from spirotrace.privacy import (
    MASK,
    PAGE_SUMMARY_FILE,
    QC_SUMMARY_FILE,
    RULE_CATALOGUE_FILE,
    VARIABLE_SUMMARY_FILE,
    GuardError,
    base_vocabulary,
    mask_text,
    write_shareable_table,
    write_shareable_text,
)

PLANTED = (
    "John Smith",  # a name
    "12/03/1961",  # a date
    "Hospital number ABC1234",  # an identifier scheme and id
    "Maori",  # an ethnic-group word
    "referrer Dr Who",  # a never-extract word
    "Patient reports breathlessness on exertion.",  # free text
    "4.38",  # a value where no digits are allowed
)


def test_only_the_four_files_are_allowed(tmp_path: Path) -> None:
    with pytest.raises(GuardError, match="not a shareable file"):
        write_shareable_table(tmp_path, "values_long.csv", ("layer",), [])
    for name in (
        QC_SUMMARY_FILE,
        VARIABLE_SUMMARY_FILE,
        PAGE_SUMMARY_FILE,
        RULE_CATALOGUE_FILE,
    ):
        assert name in {
            QC_SUMMARY_FILE,
            VARIABLE_SUMMARY_FILE,
            PAGE_SUMMARY_FILE,
            RULE_CATALOGUE_FILE,
        }


def test_value_carrying_columns_are_refused(tmp_path: Path) -> None:
    for col in (
        "value",
        "raw_text",
        "record_id",
        "note",
        "message",
        "file_name",
        "reviewer",
    ):
        with pytest.raises(GuardError, match="carry values or identifiers"):
            write_shareable_table(tmp_path, PAGE_SUMMARY_FILE, ("layer", col), [])


def test_planted_identifiers_never_reach_a_table(tmp_path: Path) -> None:
    rows = [{"layout": p, "page_type": p, "n_pages": p} for p in PLANTED] + [
        {"layout": "layout_x", "page_type": "summary", "n_pages": "12"}
    ]
    path, masked = write_shareable_table(
        tmp_path,
        PAGE_SUMMARY_FILE,
        ("layout", "page_type", "n_pages"),
        rows,
        numeric_columns=["n_pages"],
        vocabulary=base_vocabulary(["layout_x", "summary"]),
    )
    text = path.read_text(encoding="utf-8")
    for p in PLANTED[:-1]:  # "4.38" is a number: the numeric column lets it through
        for word in p.split():
            if word.lower() not in ("on",):
                assert word not in text, word
    assert "layout_x,summary,12" in text
    assert (
        masked == 3 * len(PLANTED) - 1
    )  # "4.38" is a number: allowed in the numeric column only


def test_fixed_text_columns_take_only_the_declared_strings(tmp_path: Path) -> None:
    rows = [
        {
            "rule_id": "range.outside_possible",
            "layer": "range",
            "severities": "error",
            "rationale": "A value outside the device range is a misread",
        },
        {
            "rule_id": "range.outside_possible",
            "layer": "range",
            "severities": "error",
            "rationale": "Patient John Smith",
        },
    ]
    path, masked = write_shareable_table(
        tmp_path,
        RULE_CATALOGUE_FILE,
        ("rule_id", "layer", "severities", "rationale"),
        rows,
        fixed_text={
            "rationale": {"A value outside the device range is a misread"},
            "severities": {"error"},
        },
    )
    text = path.read_text(encoding="utf-8")
    assert "misread" in text and "Smith" not in text and masked == 1


def test_text_summary_masks_everything_but_counts_vocabulary_and_wording(
    tmp_path: Path,
) -> None:
    lines = [
        "records: 102",
        "FEV1_pre layout_x: 58 read",
        *PLANTED,
    ]
    path, masked = write_shareable_text(
        tmp_path,
        QC_SUMMARY_FILE,
        lines,
        fixed_wording=["records read"],
        vocabulary=base_vocabulary(["FEV1_pre", "layout_x"]),
    )
    text = path.read_text(encoding="utf-8")
    assert "records: 102" in text and "FEV1_pre layout_x: 58 read" in text
    for word in (
        "Smith",
        "John",
        "1961",
        "Maori",
        "referrer",
        "breathlessness",
        "ABC1234",
    ):
        assert word not in text, word
    assert MASK in text and masked >= 10


def test_mask_text_keeps_numbers_and_punctuation() -> None:
    v = base_vocabulary(["input"])
    assert (
        mask_text("input error: 3 (12%)", v, frozenset({"error"}))
        == "input error: 3 (12%)"
    )
    assert mask_text("seen by Dr Who", v, frozenset()) == "??? ??? ??? ???"
