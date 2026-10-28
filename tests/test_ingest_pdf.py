"""Opening PDFs: words with boxes, the page's own rotation, blank pages, hashing, failures."""

import hashlib
from pathlib import Path

import pytest
from pdf_helpers import PAGE_H, PAGE_W, make_pdf

from spirotrace.ingest import (
    BLANK_MAX_INK,
    IngestError,
    Word,
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


def test_ocr_missing_needs_an_engine(tmp_path: Path) -> None:
    with pytest.raises(IngestError, match="needs Tesseract"):
        load_pdf(write(tmp_path, make_pdf([ITEMS])), ORIENT, norm, ocr_missing=True)


class _FakeTool:
    version = "fake"

    def __init__(self) -> None:
        self.pages = 0

    def page_words(self, image):
        self.pages += 1
        return [Word("3.05", 0.1, 0.2, 0.3, 0.32, 88.0)]

    def cell(self, image):
        return "", None


def image_only_pdf(tmp_path: Path) -> Path:
    """A scanned page with ink and no text layer: a grey picture saved as a PDF."""
    from PIL import Image, ImageDraw

    img = Image.new("L", (595, 842), 255)
    ImageDraw.Draw(img).rectangle((100, 100, 500, 700), fill=0)
    path = tmp_path / "scan.pdf"
    img.save(path, "PDF", resolution=72)
    return path


def test_ocr_missing_reads_a_page_without_a_text_layer(tmp_path: Path) -> None:
    path = image_only_pdf(tmp_path)
    plain = load_pdf(path, ORIENT, norm).pages[0]
    assert plain.text_source is TextSource.NONE and plain.ink > BLANK_MAX_INK
    tool = _FakeTool()
    page = load_pdf(path, ORIENT, norm, ocr_missing=True, tesseract=tool).pages[0]
    assert tool.pages == 1
    assert page.text_source is TextSource.OCR
    assert [w.text for w in page.words] == ["3.05"] and page.words[0].conf == 88.0


def test_ocr_missing_leaves_text_layer_and_blank_pages_alone(tmp_path: Path) -> None:
    tool = _FakeTool()
    f = load_pdf(
        write(tmp_path, make_pdf([ITEMS, []])),
        ORIENT,
        norm,
        ocr_missing=True,
        tesseract=tool,
    )
    assert tool.pages == 0
    assert f.pages[0].text_source is TextSource.TEXT_LAYER
    assert f.pages[1].text_source is TextSource.NONE and f.pages[1].is_blank
