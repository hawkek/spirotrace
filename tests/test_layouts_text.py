"""Fuzzy phrase finding on lines."""

from spirotrace.ingest import Word, group_lines
from spirotrace.layouts import (
    find_all_phrase,
    find_phrase,
    has_line_start,
    has_phrase,
    has_title,
    norm,
    ratio,
)


def words(*items: tuple[str, float, float]) -> list[Word]:
    return [
        Word(t, x, x + 0.02 * max(1, len(t) // 2), y, y + 0.01) for t, x, y in items
    ]


LINES = group_lines(
    words(
        ("Section", 0.1, 0.1),
        ("Title", 0.2, 0.1),
        ("The", 0.1, 0.2),
        ("section", 0.15, 0.2),
        ("title", 0.25, 0.2),
        ("is", 0.35, 0.2),
        ("mentioned", 0.4, 0.2),
        ("here", 0.5, 0.2),
        ("Secti0n", 0.1, 0.3),  # OCR'd
        ("Tit1e", 0.2, 0.3),
        ("Note", 0.1, 0.4),
        ("section", 0.2, 0.4),
        ("title", 0.3, 0.4),
    )
)


def test_norm_and_ratio() -> None:
    assert norm("Z-Score (%)") == "zscore%"
    assert ratio("abc", "abc") == 1.0
    assert 0 < ratio("abc", "abd") < 1


def test_find_phrase_tolerates_ocr_and_prefers_best_or_first() -> None:
    best = find_phrase(LINES, "Section Title")
    assert best is not None and best.score == 1.0 and best.cy < 0.15
    first = find_phrase(LINES, "Section Title", first=True)
    assert first is not None and first.cy < 0.15
    ocr = find_phrase(LINES, "Section Title", ymin=0.25, ymax=0.35)
    assert ocr is not None and ocr.score < 1.0
    assert [w.text for w in ocr.words] == ["Secti0n", "Tit1e"]


def test_find_phrase_region_and_threshold() -> None:
    assert find_phrase(LINES, "Section Title", xmin=0.6) is None
    assert (
        find_phrase(LINES, "Section Title", ymin=0.25, ymax=0.35, thresh=0.99) is None
    )
    assert find_phrase(LINES, "unrelated words") is None


def test_find_all_phrase_one_per_line() -> None:
    hits = find_all_phrase(LINES, "section title")
    assert [round(m.cy, 1) for m in hits] == [0.1, 0.2, 0.3, 0.4]


def test_has_title_and_has_line_start() -> None:
    assert has_phrase(LINES, "section title")
    assert has_title(LINES, "Section Title")
    assert not has_title(LINES, "mentioned here")  # inside running text only
    assert has_line_start(LINES, "Section Title")
    assert not has_line_start(LINES, "title is")
