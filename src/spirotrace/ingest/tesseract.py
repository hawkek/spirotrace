"""Tesseract as a subprocess: whole pages without a text layer, and single cells
for the second reading. No Python binding: the TSV output gives words, boxes and
confidences. The path comes from ``tools.tesseract`` (never assumed on PATH;
the usual Windows install folder is tried when the setting is empty). The
version is read once and stamped.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from PIL import Image, ImageOps

from .words import Word

WINDOWS_DEFAULT = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
CELL_CONFIG: tuple[str, ...] = (
    "--psm",
    "7",
    "-c",
    "tessedit_char_whitelist=0123456789.-,",
)
"""One text line, digits only (the old script's second reading)."""
CELL_CONFIG_LABEL = " ".join(CELL_CONFIG)
"""The config as the second-OCR cache stores it, so a changed setting misses."""
CELL_BORDER = 20
"""White pixels added round a binarised cell (Tesseract wants a margin)."""
PAGE_DPI = 300
"""Resolution for whole-page OCR of a page without a text layer."""


class TesseractError(RuntimeError):
    """Tesseract could not run or returned an error."""


@dataclass(frozen=True, slots=True)
class TsvWord:
    """One word of Tesseract's TSV output (pixel box, 0 to 100 confidence)."""

    text: str
    left: int
    top: int
    width: int
    height: int
    conf: float


def parse_tsv(text: str) -> list[TsvWord]:
    """The word rows (level 5) with non-empty text."""
    out: list[TsvWord] = []
    lines = text.splitlines()
    if not lines:
        return out
    header = lines[0].split("\t")
    try:
        idx = {
            name: header.index(name)
            for name in ("level", "left", "top", "width", "height", "conf", "text")
        }
    except ValueError as exc:
        raise TesseractError(f"unexpected TSV header: {header}") from exc
    for line in lines[1:]:
        parts = line.split("\t")
        if len(parts) <= idx["text"] or parts[idx["level"]] != "5":
            continue
        t = parts[idx["text"]].strip()
        if not t:
            continue
        out.append(
            TsvWord(
                t,
                int(parts[idx["left"]]),
                int(parts[idx["top"]]),
                int(parts[idx["width"]]),
                int(parts[idx["height"]]),
                float(parts[idx["conf"]]),
            )
        )
    return out


def parse_version(text: str) -> str:
    """``"5.5.3.20260724"`` from the first line of ``tesseract --version``."""
    first = text.strip().splitlines()[0] if text.strip() else ""
    m = re.search(r"tesseract\s+v?([0-9][\w.\-]*)", first, re.IGNORECASE)
    return m.group(1) if m else first.strip()


def otsu_binarise(image: Image.Image, border: int = CELL_BORDER) -> Image.Image:
    """Grayscale, autocontrast, Otsu threshold, white border: the old script's cell prep."""
    g = ImageOps.autocontrast(ImageOps.grayscale(image))
    hist = g.histogram()
    total = sum(hist)
    sum_all = sum(i * h for i, h in enumerate(hist))
    wb = sb = 0
    best, thr = -1.0, 128
    for t in range(256):
        wb += hist[t]
        if wb == 0 or wb == total:
            continue
        sb += t * hist[t]
        mb, mf = sb / wb, (sum_all - sb) / (total - wb)
        between = wb * (total - wb) * (mb - mf) ** 2
        if between > best:
            best, thr = between, t
    b = g.point(lambda p: 255 if p > thr else 0)
    return ImageOps.expand(b, border=border, fill=255)


class TesseractLike(Protocol):
    """What ingest and the second reading need from an OCR engine (tests fake it)."""

    @property
    def version(self) -> str: ...
    def page_words(self, image: Image.Image) -> list[Word]: ...
    def cell(self, image: Image.Image) -> tuple[str, float | None]: ...


@dataclass(frozen=True, slots=True)
class TesseractTool:
    path: str
    version: str
    timeout: float = 120.0

    @classmethod
    def from_path(cls, path: str) -> TesseractTool:
        """Probe ``path`` with ``--version``; raises :class:`TesseractError`."""
        try:
            r = subprocess.run(
                [path, "--version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise TesseractError(f"could not run tesseract at {path}: {exc}") from exc
        text = r.stdout or r.stderr
        if r.returncode != 0 or not text.strip():
            raise TesseractError(f"tesseract at {path} did not report a version")
        return cls(path, parse_version(text))

    def run_tsv(self, image: Image.Image, args: Sequence[str] = ()) -> list[TsvWord]:
        with tempfile.TemporaryDirectory(prefix="spirotrace-ocr-") as tmp:
            png = Path(tmp) / "cell.png"
            image.save(png, "PNG")
            try:
                r = subprocess.run(
                    [self.path, str(png), "stdout", *args, "tsv"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=self.timeout,
                    check=False,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                raise TesseractError(f"could not run tesseract: {exc}") from exc
        if r.returncode != 0:
            msg = (r.stderr or "").strip().splitlines()
            raise TesseractError(
                f"tesseract exit {r.returncode}: {msg[-1] if msg else 'no message'}"
            )
        return parse_tsv(r.stdout)

    def page_words(self, image: Image.Image) -> list[Word]:
        """Words of a whole page in page-normalised coordinates (confidence kept)."""
        w, h = image.size
        return [
            Word(
                t.text,
                t.left / w,
                (t.left + t.width) / w,
                t.top / h,
                (t.top + t.height) / h,
                t.conf,
            )
            for t in self.run_tsv(image)
            if t.conf > 0
        ]

    def cell(self, image: Image.Image) -> tuple[str, float | None]:
        """One cell, digits only: the text read and the lowest word confidence."""
        words = self.run_tsv(otsu_binarise(image), CELL_CONFIG)
        if not words:
            return "", None
        return "".join(t.text for t in words), min(t.conf for t in words)


def find_tesseract(configured: str) -> str | None:
    """The tesseract to run: the configured path if it exists, else PATH, else the
    Windows install folder."""
    if configured:
        return configured if Path(configured).is_file() else None
    found = shutil.which("tesseract")
    if found:
        return found
    return str(WINDOWS_DEFAULT) if WINDOWS_DEFAULT.is_file() else None


def tesseract_tool(configured: str) -> TesseractTool | None:
    """A probed tool, or None when there is none to run."""
    path = find_tesseract(configured)
    if path is None:
        return None
    try:
        return TesseractTool.from_path(path)
    except TesseractError:
        return None
