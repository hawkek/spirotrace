"""Open a PDF once: words per page with orientation fixed, ink, page images.

This is the only module that opens PDFs. The text layer is read with
pdfplumber, which applies a page's own ``/Rotate``. A page whose content is
stored sideways without ``/Rotate`` is detected by scoring the words formed
at each of the four orientations (the character boxes are turned and
regrouped into words) and keeping the orientation that reads best. Page
images come from pypdfium2 with the same extra rotation applied.
"""

from __future__ import annotations

import hashlib
import io
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pdfplumber
import pypdfium2 as pdfium  # type: ignore[import-untyped]
from pdfplumber.utils import extract_words
from PIL import Image, ImageOps

from spirotrace.model import TextSource

from .tesseract import PAGE_DPI, TesseractLike
from .words import Line, Word, deskew, group_lines

ROTATIONS = (0, 90, 180, 270)

BLANK_MAX_WORDS = 10
"""A page with fewer words than this and almost no ink is a blank sheet."""
BLANK_MAX_INK = 0.001
"""Dark-pixel fraction below which a near-wordless page is blank (a sign-off
page measured 0.2% ink, table pages 13% to 40%)."""
UPRIGHT_SCORE = 4
"""Orientation words needed at rotation 0 to skip trying the other three."""


class IngestError(RuntimeError):
    """A PDF could not be read, or a setting asks for a step not yet ported."""


@dataclass(frozen=True, slots=True)
class IngestedPage:
    """One page's words after orientation and deskew."""

    page: int
    """1-based page number in the file."""
    words: tuple[Word, ...]
    lines: tuple[Line, ...]
    text_source: TextSource
    rotation: int
    """Extra rotation applied beyond the page's own ``/Rotate``: 0, 90, 180, 270."""
    skew: float
    ink: float
    """Dark-pixel fraction of the page image (v0.3.14 measured it only for
    near-wordless pages; the pages table wants it for every page)."""

    @property
    def is_blank(self) -> bool:
        return len(self.words) < BLANK_MAX_WORDS and self.ink < BLANK_MAX_INK


@dataclass(frozen=True, slots=True)
class IngestedFile:
    """A PDF's bytes, hash and pages."""

    path: Path
    file_hash: str
    data: bytes
    pages: tuple[IngestedPage, ...]

    def render(self, page: int, dpi: int) -> Image.Image:
        """Render a 1-based page at ``dpi`` with its extra rotation applied."""
        return render_page(self.data, page - 1, dpi, self.pages[page - 1].rotation)


def file_hash_of(data: bytes) -> str:
    """SHA-256 of the file bytes, lowercase hex (the model's file hash)."""
    return hashlib.sha256(data).hexdigest()


def _rotate_chars(
    chars: list[dict[str, Any]], k: int, width: float, height: float
) -> list[dict[str, Any]]:
    """Character boxes as they would sit after turning the page by ``k`` degrees."""
    if k == 0:
        return chars
    out = []
    for c in chars:
        x0, x1, top, bottom = c["x0"], c["x1"], c["top"], c["bottom"]
        if k == 90:
            nx0, nx1, nt, nb = height - bottom, height - top, x0, x1
        elif k == 180:
            nx0, nx1, nt, nb = width - x1, width - x0, height - bottom, height - top
        else:
            nx0, nx1, nt, nb = top, bottom, width - x1, width - x0
        d = dict(c)
        d.update(x0=nx0, x1=nx1, top=nt, bottom=nb, doctop=nt, upright=True)
        out.append(d)
    return out


def _words_at(
    chars: list[dict[str, Any]], k: int, width: float, height: float
) -> list[Word]:
    w2, h2 = (height, width) if k in (90, 270) else (width, height)
    out = []
    for w in extract_words(
        _rotate_chars(chars, k, width, height),
        keep_blank_chars=False,
        use_text_flow=False,
    ):
        t = w["text"].strip()
        if t:
            out.append(
                Word(t, w["x0"] / w2, w["x1"] / w2, w["top"] / h2, w["bottom"] / h2)
            )
    return out


def render_page(data: bytes, index: int, dpi: int, rotation: int = 0) -> Image.Image:
    """Render page ``index`` (0-based) of ``data`` as a PIL image."""
    doc = pdfium.PdfDocument(data)
    try:
        img = doc[index].render(scale=dpi / 72, rotation=rotation).to_pil()
    finally:
        doc.close()
    return img


def ink_fraction(
    data: bytes, index: int, dpi: int = 50, margin: float = 0.03, dark: int = 160
) -> float:
    """Fraction of dark pixels inside the page, ignoring a margin (scanner edge shadows)."""
    g = ImageOps.grayscale(render_page(data, index, dpi))
    w, h = g.size
    g = g.crop(
        (int(margin * w), int(margin * h), int((1 - margin) * w), int((1 - margin) * h))
    )
    hist = g.histogram()
    return sum(hist[:dark]) / max(1, sum(hist))


def orientation_score(
    words: list[Word], orient_words: frozenset[str], normalise: Callable[[str], str]
) -> int:
    """Count words that read as common report words: the upright orientation wins."""
    return sum(1 for w in words if normalise(w.text) in orient_words)


def load_pdf(
    path: Path,
    orient_words: frozenset[str],
    normalise: Callable[[str], str],
    *,
    ocr_missing: bool = False,
    tesseract: TesseractLike | None = None,
) -> IngestedFile:
    """Read every page of ``path``.

    Parameters
    ----------
    path
        The PDF.
    orient_words, normalise
        Words (after ``normalise``) that mark the upright orientation; the
        layout code supplies them.
    ocr_missing
        Read a page that has no text layer and is not blank with Tesseract
        (``ocr.missing_pages``); its words carry ``text_source`` ``ocr``.
    tesseract
        The engine for ``ocr_missing``; required when it is True.

    Raises
    ------
    IngestError
        If the file cannot be read, or ``ocr_missing`` is True without an engine.
    """
    if ocr_missing and tesseract is None:
        raise IngestError(
            "ocr.missing_pages = true needs Tesseract: set tools.tesseract to its full "
            "path, or set missing_pages to false"
        )
    path = Path(path)
    data = path.read_bytes()
    pages: list[IngestedPage] = []
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for i, pg in enumerate(pdf.pages):
                width, height = float(pg.width), float(pg.height)
                chars = pg.chars
                best: tuple[int, int, list[Word]] | None = None
                for extra in ROTATIONS:
                    words = _words_at(chars, extra, width, height)
                    sc = orientation_score(words, orient_words, normalise)
                    if best is None or sc > best[0]:
                        best = (sc, extra, words)
                    if extra == 0 and (sc >= UPRIGHT_SCORE or not words):
                        break
                assert best is not None
                _, extra, words = best
                ink = ink_fraction(data, i)
                source = TextSource.TEXT_LAYER if words else TextSource.NONE
                if (
                    ocr_missing
                    and tesseract is not None
                    and len(words) < BLANK_MAX_WORDS
                    and ink >= BLANK_MAX_INK
                ):
                    # no text layer but ink on the page: the copier's OCR missed it
                    ocr_words = tesseract.page_words(render_page(data, i, PAGE_DPI))
                    if ocr_words:
                        words, source = ocr_words, TextSource.OCR
                words, skew = deskew(words)
                pages.append(
                    IngestedPage(
                        i + 1,
                        tuple(words),
                        tuple(group_lines(words)),
                        source,
                        extra,
                        skew,
                        ink,
                    )
                )
    except (
        Exception
    ) as exc:  # a corrupt or password-protected file must not stop the run
        raise IngestError(
            f"{path.name}: could not be read ({type(exc).__name__}: {exc})"
        ) from exc
    return IngestedFile(path, file_hash_of(data), data, tuple(pages))
