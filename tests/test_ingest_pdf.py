"""Opening PDFs: words with boxes, the page's own rotation, blank pages, hashing, failures."""

import hashlib
from pathlib import Path

import pytest
from pdf_helpers import PAGE_H, PAGE_W, make_pdf

from spirotrace.ingest import (
    IngestError,
    file_hash_of,
    ink_fraction,
    load_pdf,
    render_page,
)
from spirotrace.model import TextSource

ORIENT = frozenset({"alpha", "beta", "gamma", "delta", "parameter"})


def norm(s: str) -> str:
    return "".join(ch for ch in s.lower() if ch.isalnum())


ITEMS = [
    ("Alpha", 72, 760),
    ("Beta", 150, 760),
    ("Gamma", 230, 760),
    ("Delta", 300, 760),
    ("Parameter", 72, 700),
    ("1.23", 200, 700),
    ("4.56", 260, 700),
    *[(f"w{i}", 72 + 40 * i, 640) for i in range(10)],
]


def write(tmp_path: Path, data: bytes, name: str = "f.pdf") -> Path:
    p = tmp_path / name
    p.write_bytes(data)
    return p


def test_words_have_normalised_boxes_and_the_hash_is_sha256(tmp_path: Path) -> None:
    data = make_pdf([ITEMS])
    f = load_pdf(write(tmp_path, data), ORIENT, norm)
    assert f.file_hash == hashlib.sha256(data).hexdigest() == file_hash_of(data)
    assert len(f.pages) == 1
    page = f.pages[0]
    assert page.page == 1
    assert [w.text for w in page.words] == [t for t, _, _ in ITEMS]
    first = page.words[0]
    assert abs(first.x0 - 72 / PAGE_W) < 0.002
    assert abs(first.bottom - (PAGE_H - 760) / PAGE_H) < 0.004
    assert page.text_source is TextSource.TEXT_LAYER
    assert page.rotation == 0
    assert 0.0 < page.ink < 0.05
    assert [ln.text for ln in page.lines][:2] == [
        "Alpha Beta Gamma Delta",
        "Parameter 1.23 4.56",
    ]


def test_pages_own_rotate_entry_is_applied(tmp_path: Path) -> None:
    upright = load_pdf(write(tmp_path, make_pdf([ITEMS]), "a.pdf"), ORIENT, norm).pages[
        0
    ]
    # content stored sideways, /Rotate 90 turns it upright for the viewer
    sideways = [(t, PAGE_H - y, x) for t, x, y in ITEMS]
    rotated = load_pdf(
        write(tmp_path, make_pdf([sideways], [90]), "b.pdf"), ORIENT, norm
    ).pages[0]
    by_text = {w.text: w for w in rotated.words}
    assert set(by_text) == {w.text for w in upright.words}
    for a in upright.words:
        b = by_text[a.text]
        assert abs(a.x0 - b.x0) < 0.01 and abs(a.top - b.top) < 0.01
    assert rotated.rotation == 0  # no extra rotation beyond the page's own


def test_near_empty_page_gets_an_ink_measurement_and_counts_as_blank(
    tmp_path: Path,
) -> None:
    f = load_pdf(write(tmp_path, make_pdf([[("x", 72, 700)], ITEMS])), ORIENT, norm)
    blank, full = f.pages
    assert blank.ink < 0.001
    assert blank.is_blank
    assert full.ink > blank.ink and not full.is_blank
    empty = load_pdf(write(tmp_path, make_pdf([[]]), "e.pdf"), ORIENT, norm).pages[0]
    assert empty.words == ()
    assert empty.text_source is TextSource.NONE
    assert empty.is_blank


def test_render_and_ink(tmp_path: Path) -> None:
    data = make_pdf([ITEMS])
    img = render_page(data, 0, 36)
    assert img.size == (round(PAGE_W / 2), round(PAGE_H / 2))
    assert 0.0 <= ink_fraction(data, 0) < 0.05
    f = load_pdf(write(tmp_path, data), ORIENT, norm)
    assert f.render(1, 36).size == img.size


def test_unreadable_file_raises_ingest_error(tmp_path: Path) -> None:
    with pytest.raises(IngestError, match="could not be read"):
        load_pdf(write(tmp_path, b"not a pdf"), ORIENT, norm)


def test_ocr_missing_is_refused_until_ported(tmp_path: Path) -> None:
    with pytest.raises(IngestError, match="ocr.missing_pages"):
        load_pdf(write(tmp_path, make_pdf([ITEMS])), ORIENT, norm, ocr_missing=True)
