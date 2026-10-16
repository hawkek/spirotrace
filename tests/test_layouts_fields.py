"""Labelled header fields read by their label."""

from spirotrace.ingest import Word, group_lines
from spirotrace.layouts import FieldSpec, header_fields
from spirotrace.layouts import conditions as cond

SPECS = [
    FieldSpec("age", ("Age",), "num"),
    FieldSpec("sex", ("Sex",), "text"),
    FieldSpec("date", ("Test Date",), "date"),
    FieldSpec("height", ("Height",), "num"),
    FieldSpec("weight", ("Weight",), "num"),
]
BOUNDS = ["Surname", "Clinic"]


def w(t: str, x: float, y: float) -> Word:
    return Word(t, x, x + 0.015 * max(1, len(t) // 2), y, y + 0.01)


def page(*items: tuple[str, float, float]):
    return group_lines([w(*i) for i in items])


def test_fields_read_values_up_to_the_next_label() -> None:
    lines = page(
        ("Surname", 0.05, 0.10),
        ("Doe", 0.19, 0.10),
        ("Height", 0.43, 0.10),
        ("172.5", 0.57, 0.10),
        ("cm", 0.62, 0.10),
        ("Age", 0.05, 0.12),
        ("45", 0.19, 0.12),
        ("Weight", 0.43, 0.12),
        ("74", 0.57, 0.12),
        ("kg", 0.61, 0.12),
        ("Sex", 0.05, 0.14),
        ("Female", 0.19, 0.14),
        ("Clinic", 0.43, 0.14),
        ("Room", 0.57, 0.14),
        ("Test", 0.05, 0.16),
        ("Date", 0.09, 0.16),
        ("12/03/2025", 0.19, 0.16),
        ("10:20", 0.28, 0.16),
    )
    got = {
        f.name: f
        for f in header_fields(
            lines, SPECS, BOUNDS, ymax=0.2, vocab={"sex": ["Female", "Male"]}
        )
    }
    assert got["age"].value == 45.0 and got["age"].raw == "45"
    assert got["height"].value == 172.5 and got["height"].raw == "172.5 cm"
    assert got["weight"].value == 74.0
    assert got["sex"].value == "Female" and got["sex"].conditions == []
    assert got["date"].value == "2025-03-12" and got["date"].raw == "12/03/2025 10:20"
    # the boundary labels are never read as fields
    assert "Surname" not in {f.raw for f in got.values()} and "Doe" not in {
        f.raw for f in got.values()
    }


def test_ocr_damaged_label_does_not_steal_another_fields_value() -> None:
    lines = page(
        ("Height", 0.05, 0.10),
        ("172", 0.19, 0.10),
        ("Weiqht", 0.05, 0.12),
        ("74", 0.19, 0.12),
    )
    got = {f.name: f for f in header_fields(lines, SPECS, BOUNDS, ymax=0.2)}
    assert got["height"].value == 172.0
    assert got["weight"].value == 74.0


def test_field_conditions() -> None:
    lines = page(
        ("Age", 0.05, 0.10),
        ("n/a", 0.19, 0.10),
        ("Height", 0.05, 0.12),
        ("Sex", 0.05, 0.14),
        ("Unknownish", 0.19, 0.14),
        ("Test", 0.05, 0.16),
        ("Date", 0.09, 0.16),
        ("soon", 0.19, 0.16),
    )
    got = {
        f.name: f
        for f in header_fields(
            lines, SPECS, BOUNDS, ymax=0.2, vocab={"sex": ["Female", "Male"]}
        )
    }
    assert got["age"].value is None and [c.code for c in got["age"].conditions] == [
        cond.NOT_A_NUMBER
    ]
    assert got["height"].raw == "" and [c.code for c in got["height"].conditions] == [
        cond.FIELD_NO_VALUE
    ]
    assert [c.code for c in got["sex"].conditions] == [cond.FIELD_UNEXPECTED_CATEGORY]
    assert got["date"].value is None and [c.code for c in got["date"].conditions] == [
        cond.DATE_NOT_PARSED
    ]
    assert "weight" not in got  # label absent: nothing read, the caller notes it


def test_split_decimal_in_a_number_is_joined() -> None:
    lines = page(("Height", 0.05, 0.10), ("172.", 0.19, 0.10), ("5", 0.24, 0.10))
    got = header_fields(lines, SPECS, BOUNDS, ymax=0.2)
    assert got[0].value == 172.5
