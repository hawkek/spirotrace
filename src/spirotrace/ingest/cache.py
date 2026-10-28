"""The raw cache (checkpoint 1): words per page, read once per file hash.

``cache/words/<file_hash>.csv`` holds every word after orientation and deskew,
``<file_hash>.pages.csv`` the page metadata ingest knows, and
``<file_hash>.stamp.json`` what wrote them (file hash, code version, Tesseract
version and the missing-pages setting). A stamp that differs rebuilds. Page
images are not cached: they render on demand from the PDF.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from spirotrace.model import TextSource

from .pdf import IngestedFile, IngestedPage, file_hash_of, load_pdf
from .tesseract import TesseractLike
from .words import Word, group_lines

WORDS_DIR = "words"
WORD_COLUMNS: tuple[str, ...] = (
    "page",
    "index",
    "text",
    "x0",
    "x1",
    "y0",
    "y1",
    "source",
    "confidence",
)
PAGE_COLUMNS: tuple[str, ...] = (
    "page",
    "word_count",
    "rotation",
    "skew",
    "ink",
    "text_source",
)


def cache_stamp_fields(
    file_hash: str, code_version: str, tesseract_version: str, missing_pages: bool
) -> dict[str, Any]:
    return {
        "file_hash": file_hash,
        "code_version": code_version,
        "tesseract_version": tesseract_version,
        "missing_pages": missing_pages,
    }


def _paths(cache_dir: Path, file_hash: str) -> tuple[Path, Path, Path]:
    folder = cache_dir / WORDS_DIR
    return (
        folder / f"{file_hash}.csv",
        folder / f"{file_hash}.pages.csv",
        folder / f"{file_hash}.stamp.json",
    )


def _write(cache_dir: Path, ingested: IngestedFile, stamp: dict[str, Any]) -> None:
    # local import: store depends on checks, which must not be a cost of ingest
    from spirotrace.store import write_json, write_rows

    words_path, pages_path, stamp_path = _paths(cache_dir, ingested.file_hash)
    rows = []
    for p in ingested.pages:
        for i, w in enumerate(p.words):
            rows.append(
                {
                    "page": str(p.page),
                    "index": str(i),
                    "text": w.text,
                    "x0": repr(w.x0),
                    "x1": repr(w.x1),
                    "y0": repr(w.top),
                    "y1": repr(w.bottom),
                    "source": p.text_source.value,
                    "confidence": "" if w.conf is None else repr(w.conf),
                }
            )
    write_rows(words_path, WORD_COLUMNS, rows)
    write_rows(
        pages_path,
        PAGE_COLUMNS,
        (
            {
                "page": str(p.page),
                "word_count": str(len(p.words)),
                "rotation": str(p.rotation),
                "skew": repr(p.skew),
                "ink": repr(p.ink),
                "text_source": p.text_source.value,
            }
            for p in ingested.pages
        ),
    )
    write_json(stamp_path, stamp)


def _read(
    cache_dir: Path, path: Path, data: bytes, file_hash: str
) -> IngestedFile | None:
    from spirotrace.store import StoreError, read_rows

    words_path, pages_path, _ = _paths(cache_dir, file_hash)
    try:
        word_rows = read_rows(words_path, WORD_COLUMNS)
        page_rows = read_rows(pages_path, PAGE_COLUMNS)
    except StoreError:
        return None
    by_page: dict[int, list[Word]] = {}
    for r in word_rows:
        by_page.setdefault(int(r["page"]), []).append(
            Word(
                r["text"],
                float(r["x0"]),
                float(r["x1"]),
                float(r["y0"]),
                float(r["y1"]),
                float(r["confidence"]) if r["confidence"] else None,
            )
        )
    pages = []
    for r in sorted(page_rows, key=lambda r: int(r["page"])):
        n = int(r["page"])
        words = by_page.get(n, [])
        pages.append(
            IngestedPage(
                n,
                tuple(words),
                tuple(group_lines(words)),
                TextSource(r["text_source"]),
                int(r["rotation"]),
                float(r["skew"]),
                float(r["ink"]),
            )
        )
    return IngestedFile(path, file_hash, data, tuple(pages))


def load_pdf_cached(
    path: Path,
    orient_words: frozenset[str],
    normalise: Callable[[str], str],
    cache_dir: Path | None,
    *,
    ocr_missing: bool = False,
    code_version: str = "",
    tesseract: TesseractLike | None = None,
) -> IngestedFile:
    """:func:`load_pdf` through the words cache (no cache when ``cache_dir`` is None).

    The stamp records the Tesseract version only when the words can depend on
    it (``ocr_missing``), so a Tesseract upgrade leaves text-layer words valid.
    """
    if cache_dir is None:
        return load_pdf(
            path, orient_words, normalise, ocr_missing=ocr_missing, tesseract=tesseract
        )
    data = Path(path).read_bytes()
    file_hash = file_hash_of(data)
    tesseract_version = tesseract.version if ocr_missing and tesseract else ""
    stamp = cache_stamp_fields(file_hash, code_version, tesseract_version, ocr_missing)
    _, _, stamp_path = _paths(cache_dir, file_hash)
    if stamp_path.is_file():
        try:
            stored = json.loads(stamp_path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            stored = None
        if stored == stamp:
            cached = _read(cache_dir, Path(path), data, file_hash)
            if cached is not None:
                return cached
    ingested = load_pdf(
        path, orient_words, normalise, ocr_missing=ocr_missing, tesseract=tesseract
    )
    _write(cache_dir, ingested, stamp)
    return ingested
