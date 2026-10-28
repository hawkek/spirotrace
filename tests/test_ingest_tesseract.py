"""Tesseract as a subprocess: TSV parsing, version parsing, cell binarisation, and a
live reading where Tesseract is installed (skipped with the reason otherwise)."""

from __future__ import annotations

import pytest
from PIL import Image, ImageDraw, ImageFont

from spirotrace.ingest import (
    TesseractError,
    TsvWord,
    find_tesseract,
    otsu_binarise,
    parse_tsv,
    parse_version,
    tesseract_tool,
)

TSV = (
    "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
    "1\t1\t0\t0\t0\t0\t0\t0\t300\t80\t-1\t\n"
    "4\t1\t1\t1\t1\t0\t12\t23\t74\t29\t-1\t\n"
    "5\t1\t1\t1\t1\t1\t12\t23\t74\t29\t95.569138\t3.05\n"
    "5\t1\t1\t1\t1\t2\t90\t23\t10\t29\t40\t \n"
)


def test_parse_tsv_keeps_word_rows_with_text() -> None:
    words = parse_tsv(TSV)
    assert words == [TsvWord("3.05", 12, 23, 74, 29, 95.569138)]
    assert parse_tsv("") == []


def test_parse_tsv_refuses_an_unknown_header() -> None:
    with pytest.raises(TesseractError, match="header"):
        parse_tsv("a\tb\n1\t2\n")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("tesseract v5.5.3.20260724\n leptonica-1.87.0\n", "5.5.3.20260724"),
        ("tesseract 5.3.0\n", "5.3.0"),
        ("", ""),
    ],
)
def test_parse_version(text: str, expected: str) -> None:
    assert parse_version(text) == expected


def test_otsu_binarise_is_black_and_white_with_a_white_border() -> None:
    img = Image.new("RGB", (40, 20), (200, 200, 200))
    ImageDraw.Draw(img).rectangle((10, 5, 30, 15), fill=(40, 40, 40))
    out = otsu_binarise(img, border=4)
    assert out.size == (48, 28)
    assert set(out.tobytes()) <= {0, 255}
    assert out.getpixel((0, 0)) == 255 and out.getpixel((24, 14)) == 0


def test_find_tesseract_with_a_missing_configured_path(tmp_path) -> None:
    assert find_tesseract(str(tmp_path / "nope.exe")) is None
    assert tesseract_tool(str(tmp_path / "nope.exe")) is None


def _digits_image(text: str) -> Image.Image:
    img = Image.new("L", (320, 90), 255)
    try:
        font = ImageFont.truetype("arial.ttf", 44)
    except OSError:
        font = ImageFont.load_default()
    ImageDraw.Draw(img).text((12, 18), text, fill=0, font=font)
    return img


def test_live_cell_and_page_reading() -> None:
    tool = tesseract_tool("")
    if tool is None:
        pytest.skip(
            "Tesseract is not installed (tools.tesseract); live reading not run"
        )
    assert tool.version
    text, conf = tool.cell(_digits_image("3.05"))
    assert text == "3.05" and conf is not None and conf > 0
    words = tool.page_words(_digits_image("3.05"))
    assert [w.text for w in words] == ["3.05"]
    assert 0 <= words[0].x0 < words[0].x1 <= 1 and words[0].conf is not None
