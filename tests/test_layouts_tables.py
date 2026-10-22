"""The generic table reader on neutral synthetic tables.

Rows are named P1..P5 and columns use the generic header words; no real
layout's geometry is used.
"""

from spirotrace.ingest import Word, group_lines
from spirotrace.layouts import (
    Col,
    RowSpec,
    canon_label,
    header_name,
    label_text,
    merge_header_tokens,
    parse_table,
)
from spirotrace.layouts import conditions as cond

ROWS = [
    RowSpec("P1", ("Alpha 1", "Alpha1")),
    RowSpec("P2", ("Beta",)),
    RowSpec("P3", ("Alpha 1 % Beta",)),
    RowSpec("P4", ("Gamma 100",)),
    RowSpec("P5", ("Beta IN",)),
]
SEQS = [[("pre", "value"), ("pre", "lln"), ("pre", "pctpred"), ("pre", "z")]]
XS = [0.25, 0.31, 0.37, 0.43]  # left edges of the four value columns
Y_HDR = 0.20
Y_ROWS = [0.22, 0.235, 0.25, 0.265, 0.28]


def w(t: str, x0: float, top: float, width: float = 0.02) -> Word:
    return Word(t, x0, x0 + width, top, top + 0.01)


def header_words() -> list[Word]:
    return [
        w(t, x, Y_HDR)
        for t, x in zip(["Pre", "LLN", "%Pred", "Z-Score"], XS, strict=True)
    ]


def table_words(
    values: dict[str, list[str]], labels: dict[str, list[str]] | None = None
) -> list[Word]:
    """Rows P1..P5 with their label words (default labels) and value tokens."""
    default_labels = {
        "P1": ["Alpha", "1"],
        "P2": ["Beta"],
        "P3": ["Alpha", "1", "%", "Beta"],
        "P4": ["Gamma", "100"],
        "P5": ["Beta", "IN"],
    }
    labels = {**default_labels, **(labels or {})}
    out: list[Word] = []
    for (param, y), unit in zip(
        zip(ROWS, Y_ROWS, strict=True),
        ["[L]", "[L]", "[%]", "[sec]", "[L]"],
        strict=True,
    ):
        p = param.param
        x = 0.04
        for tok in labels[p]:
            out.append(w(tok, x, y, 0.015))
            x += 0.02
        out.append(w(unit, 0.21, y))
        for xv, v in zip(XS, values.get(p, []), strict=False):
            if v:
                out.append(w(v, xv, y))
    return out


VALUES = {
    "P1": ["3.20", "2.55", "97", "-0.21"],
    "P2": ["4.30", "3.40", "101", "~0.07"],
    "P3": ["74", "63", "96", "-0.35"],
    "P4": ["9.1", "", "", ""],
    "P5": ["4.20", "3.40", "98", "-0.12"],
}


def read(words: list[Word], hdr: list[Word] | None, **kw: object):
    args: dict[str, object] = {
        "value_xmin": 0.235,
        "value_xmax": 0.62,
        "expected_seqs": SEQS,
        "stop_after_z": True,
        **kw,
    }
    return parse_table(group_lines(words), Y_HDR + 0.005, 0.30, ROWS, hdr, None, **args)  # type: ignore[arg-type]


def raw_of(t, param: str, col: str) -> str:
    return t.cells[(param, "pre", col)].raw


def test_header_helpers() -> None:
    assert canon_label("Alpha 1 % Beta") == "A1PHA1%BETA"  # L reads as 1 (OCR)
    assert canon_label("A1pha I") == "A1PHA1"
    assert (
        label_text([w("Alpha", 0.04, 0.2), w("1", 0.06, 0.2), w("[L]", 0.21, 0.2)])
        == "Alpha 1"
    )
    assert (
        label_text([w("Alpha", 0.04, 0.2), w("far", 0.2, 0.2)]) == "Alpha"
    )  # wide gap: unit column
    assert header_name("%Pred") == "pctpred"
    assert header_name("Z-Score") == "z"
    assert header_name("8est") == "best"
    assert header_name("Trial 3") == "t3"
    assert header_name("TriaI s") == "t5"
    assert header_name("Alpha") is None
    merged = merge_header_tokens(
        [
            w("%", 0.3, 0.2, 0.01),
            w("Pred", 0.311, 0.2),
            w("Trial", 0.5, 0.2),
            w("2", 0.521, 0.2),
        ]
    )
    assert [m.text for m in merged] == ["%Pred", "Trial2"]


def test_full_table_rows_by_label_columns_by_header() -> None:
    t = read(table_words(VALUES), header_words())
    assert t.rows_found == ["P1", "P2", "P3", "P4", "P5"]
    assert [c.name for c in t.columns] == ["value", "lln", "pctpred", "z"]
    assert raw_of(t, "P1", "value") == "3.20"
    assert raw_of(t, "P2", "z") == "~0.07"
    assert raw_of(t, "P4", "lln") == ""  # empty cell kept as a cell
    assert all(c.inferred is None for c in t.cells.values())
    assert [c.code for c in t.conditions] == []
    # unit labels never become values
    assert not any(cell.raw.startswith("[") for cell in t.cells.values())


def test_header_not_read_columns_named_by_position() -> None:
    t = read(table_words(VALUES), None)
    assert [c.name for c in t.columns] == ["value", "lln", "pctpred", "z"]
    assert raw_of(t, "P5", "z") == "-0.12"
    assert [c.code for c in t.conditions] == [cond.COLUMNS_NAMED_BY_POSITION]


def test_table_shifted_right_anchoring_holds() -> None:
    shifted = [
        Word(x.text, x.x0 + 0.05, x.x1 + 0.05, x.top, x.bottom)
        for x in table_words(VALUES)
    ]
    hdr = [
        Word(x.text, x.x0 + 0.05, x.x1 + 0.05, x.top, x.bottom) for x in header_words()
    ]
    t = read(shifted, hdr)
    assert raw_of(t, "P1", "value") == "3.20" and raw_of(t, "P3", "z") == "-0.35"


def test_graph_heading_right_of_the_values_is_ignored() -> None:
    hdr = [*header_words(), w("Z-Score", 0.58, Y_HDR, 0.05)]
    t = read(table_words(VALUES), hdr, stop_after_z=False)
    assert [c.name for c in t.columns] == ["value", "lln", "pctpred", "z"]
    assert cond.HEADER_GRAPH_HEADING_IGNORED in [c.code for c in t.conditions]
    assert raw_of(t, "P1", "z") == "-0.21"


def test_second_z_column_is_kept_with_a_suffix() -> None:
    # a fifth value column at x=0.49 under a second "Z-Score" heading
    extra = [
        w("0.10", 0.49, y)
        for p, y in zip(["P1", "P2", "P3", "P4", "P5"], Y_ROWS, strict=True)
        if p != "P4"
    ]
    hdr = [*header_words(), w("Z-Score", 0.49, Y_HDR)]
    t = read([*table_words(VALUES), *extra], hdr, stop_after_z=False)
    assert [c.name for c in t.columns] == ["value", "lln", "pctpred", "z", "z_2"]
    assert cond.COLUMN_NAME_TWICE in [c.code for c in t.conditions]
    assert raw_of(t, "P1", "z_2") == "0.10"
    assert raw_of(t, "P1", "z") == "-0.21"


def test_row_labels_dropped_complete_table_assigned_by_order() -> None:
    words = table_words(VALUES, labels={"P2": [], "P4": []})
    t = read(words, header_words())
    assert t.rows_found == ["P1", "P2", "P3", "P4", "P5"]
    assert t.cells[("P2", "pre", "value")].inferred == "complete"
    assert t.cells[("P4", "pre", "value")].inferred == "complete"
    assert t.cells[("P1", "pre", "value")].inferred is None


def test_row_label_dropped_with_a_row_missing_is_placed_by_gap() -> None:
    values = {p: v for p, v in VALUES.items() if p != "P4"}
    words = [x for x in table_words(values, labels={"P2": []}) if x.top != Y_ROWS[3]]
    t = read(words, header_words())
    assert t.cells[("P2", "pre", "value")].inferred == "gap"
    assert raw_of(t, "P2", "value") == "4.30"
    assert cond.ROW_NOT_FOUND in [c.code for c in t.conditions]


def test_row_template_places_unlabelled_rows_by_height() -> None:
    values = {p: v for p, v in VALUES.items() if p != "P4"}
    words = [
        x
        for x in table_words(values, labels={"P2": [], "P5": []})
        if x.top != Y_ROWS[3]
    ]
    template = (
        0.18,
        [
            (p, y + 0.005 - 0.18)
            for p, y in zip(["P1", "P2", "P3", "P4", "P5"], Y_ROWS, strict=True)
        ],
    )
    t = read(words, header_words(), row_template=template)
    assert t.cells[("P2", "pre", "value")].inferred == "template"
    assert t.cells[("P5", "pre", "value")].inferred == "template"
    assert raw_of(t, "P5", "value") == "4.20"
    off = read(words, header_words(), row_template=None)
    assert ("P5", "pre", "value") not in off.cells or off.cells[
        ("P5", "pre", "value")
    ].inferred != "template"


def test_star_as_its_own_word_joins_the_number_on_its_left() -> None:
    words = [*table_words(VALUES), w("*", 0.271, Y_ROWS[0], 0.005)]
    t = read(words, header_words())
    assert raw_of(t, "P1", "value") == "3.20*"
    attached = table_words({**VALUES, "P2": ["4.30*", "3.40", "101", "0.07"]})
    assert raw_of(read(attached, header_words()), "P2", "value") == "4.30*"


def test_merged_token_does_not_chain_columns() -> None:
    values = {**VALUES, "P1": ["3.202.55", "", "97", "-0.21"]}
    words = [
        x if x.text != "3.202.55" else Word(x.text, x.x0, x.x0 + 0.075, x.top, x.bottom)
        for x in table_words(values)
    ]
    t = read(words, header_words())
    assert [c.name for c in t.columns] == ["value", "lln", "pctpred", "z"]
    assert raw_of(t, "P2", "lln") == "3.40"


def test_empty_cell_in_a_filled_column_is_noted_not_structural() -> None:
    values = {**VALUES, "P2": ["4.30", "", "101", "0.07"]}
    t = read(table_words(values), header_words())
    assert t.cells[("P2", "pre", "lln")].raw == ""
    assert t.cells[("P2", "pre", "lln")].empty_in_filled_col
    assert not t.cells[("P4", "pre", "lln")].empty_in_filled_col  # row mostly empty
    t2 = read(
        table_words(values),
        header_words(),
        structural_blanks=frozenset({("P2", "lln")}),
    )
    assert not t2.cells[("P2", "pre", "lln")].empty_in_filled_col


def test_trial_header_defines_columns_without_expected_sequence() -> None:
    hdr = [
        w(t, x, Y_HDR, 0.04)
        for t, x in zip(["Best", "Trial 2", "Trial 1", "Trial 3"], XS, strict=True)
    ]
    t = parse_table(
        group_lines(table_words(VALUES)),
        Y_HDR + 0.005,
        0.30,
        ROWS,
        hdr,
        None,
        value_xmin=0.18,
        value_xmax=0.99,
    )
    assert [c.name for c in t.columns] == ["best", "t2", "t1", "t3"]
    assert raw_of(t, "P1", "t1") == "97"


def test_trial_header_unread_gives_generic_columns() -> None:
    t = parse_table(
        group_lines(table_words(VALUES)),
        Y_HDR + 0.005,
        0.30,
        ROWS,
        None,
        None,
        value_xmin=0.18,
        value_xmax=0.99,
    )
    assert [c.name for c in t.columns] == ["c1", "c2", "c3", "c4"]
    assert cond.COLUMNS_GENERIC_NAMES in [c.code for c in t.conditions]


def test_fixed_columns_are_used_as_given() -> None:
    cols = [
        Col("value", "post", 0.27),
        Col("lln", "post", 0.33),
        Col("pctpred", "post", 0.39),
        Col("z", "post", 0.45),
    ]
    t = parse_table(
        group_lines(table_words(VALUES)),
        Y_HDR + 0.005,
        0.30,
        ROWS,
        fixed_columns=cols,
        value_xmin=0.235,
        value_xmax=0.62,
    )
    assert t.cells[("P1", "post", "value")].raw == "3.20"


def test_no_values_and_no_header_gives_no_columns() -> None:
    t = read(table_words({}), None)
    assert t.columns == []
    assert [c.code for c in t.conditions] == [cond.COLUMNS_UNDETERMINED]
