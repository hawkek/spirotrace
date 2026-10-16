"""Words, lines, line grouping and deskew."""

from spirotrace.ingest import Line, Word, bbox_of, deskew, group_lines


def w(
    text: str, x0: float, top: float, width: float = 0.03, height: float = 0.01
) -> Word:
    return Word(text, x0, x0 + width, top, top + height)


def test_word_geometry() -> None:
    word = Word("a", 0.1, 0.3, 0.2, 0.24)
    assert word.cx == 0.2
    assert word.cy == 0.22
    assert abs(word.h - 0.04) < 1e-12


def test_line_text_and_extent() -> None:
    line = Line((w("one", 0.1, 0.5), w("two", 0.2, 0.5)))
    assert line.text == "one two"
    assert line.x0 == 0.1
    assert line.x1 == 0.23
    assert line.top == 0.5
    assert line.bottom == 0.51
    assert bbox_of(line.words) == (0.1, 0.5, 0.23, 0.51)


def test_group_lines_by_vertical_centre_sorted_left_to_right() -> None:
    words = [w("b", 0.2, 0.5), w("a", 0.1, 0.502), w("c", 0.1, 0.6), w("d", 0.3, 0.6)]
    lines = group_lines(words)
    assert [ln.text for ln in lines] == ["a b", "c d"]


def test_group_lines_empty() -> None:
    assert group_lines([]) == []


def test_group_lines_keeps_close_rows_apart() -> None:
    # two table rows 1.6% of the page apart, words 1% tall: never merged
    words = [w("r1", 0.1, 0.5), w("r2", 0.1, 0.516)]
    assert len(group_lines(words)) == 2


def test_deskew_removes_a_small_slope_from_long_lines() -> None:
    slope = 0.01
    words = []
    for row in range(3):
        base = 0.3 + 0.05 * row
        for i in range(5):
            x = 0.1 + 0.15 * i
            cx = x + 0.015
            words.append(
                Word(
                    f"w{row}{i}",
                    x,
                    x + 0.03,
                    base + slope * (cx - 0.5),
                    base + 0.01 + slope * (cx - 0.5),
                )
            )
    fixed, s = deskew(words)
    assert abs(s - slope) < 1e-9
    for row in range(3):
        tops = [x.top for x in fixed if x.text.startswith(f"w{row}")]
        assert max(tops) - min(tops) < 1e-9


def test_deskew_leaves_short_or_too_steep_pages_alone() -> None:
    few = [w("a", 0.1, 0.5), w("b", 0.5, 0.52)]
    assert deskew(few) == (few, 0.0)
    steep = []
    for row in range(3):
        base = 0.3 + 0.1 * row
        for i in range(5):
            x = 0.1 + 0.15 * i
            steep.append(
                Word(
                    "x",
                    x,
                    x + 0.03,
                    base + 0.2 * (x - 0.5),
                    base + 0.21 + 0.2 * (x - 0.5),
                )
            )
    assert deskew(steep)[1] == 0.0
