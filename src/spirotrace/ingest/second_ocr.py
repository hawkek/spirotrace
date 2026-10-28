"""The second reading: every table number re-read from the scan with Tesseract,
one cell at a time, after read (A4; placement decided 14 October 2026).

The page is rendered at 450 dpi with its extra rotation; the cell's box is
taken from the observation (deskew undone, a small margin added, an empty cell
looked for in the column slot to its left), binarised and read with the digit
whitelist. Readings live in ``cache/second_ocr/<file_hash>.csv`` keyed by
page, pixel box, Tesseract version and config, so a rerun re-reads nothing and
a moved box re-reads only that cell. The reading goes into the observation's
``second_reading``; the rules in the ocr layer compare it with the first
reading. The confidence travels as a reading condition on the key; a failed
Tesseract call is a record-level condition and ends the record's readings.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Protocol

from PIL import Image

from spirotrace.layouts import ReadingCondition
from spirotrace.layouts import conditions as cond
from spirotrace.model import (
    ColumnRole,
    Observation,
    ObservationKey,
    Page,
    ParameterKind,
    ReadMethod,
    ValueState,
    kind_of,
)

from .pdf import render_page
from .tesseract import CELL_CONFIG_LABEL, TesseractError, TesseractLike

SECOND_OCR_DIR = "second_ocr"
DPI = 450
"""Render resolution of the second reading (the old script's)."""
MARGIN_X = 0.006
MARGIN_Y = 0.004
EMPTY_SLOT_WIDTH = 0.035
"""An empty cell has no box of its own: look in the column slot to its left."""
MIN_CROP_PX = 5

SECOND_READING_ROLES: frozenset[ColumnRole] = frozenset(
    {
        ColumnRole.PRE,
        ColumnRole.POST,
        ColumnRole.LLN,
        ColumnRole.POST_LLN,
        ColumnRole.ULN,
        ColumnRole.PREDICTED,
        ColumnRole.PCTPRED,
        ColumnRole.POST_PCTPRED,
        ColumnRole.Z,
        ColumnRole.POST_Z,
        ColumnRole.BDR,
        ColumnRole.PCTCHG,
        ColumnRole.TRIAL,
        ColumnRole.POST_TRIAL,
    }
)
"""Table roles of number parameters; header fields, trend rows and free text are not re-read."""
FIRST_READ_METHODS: frozenset[ReadMethod] = frozenset(
    {ReadMethod.TEXT_LAYER, ReadMethod.OCR, ReadMethod.POSITION_FALLBACK}
)

CACHE_COLUMNS: tuple[str, ...] = (
    "page",
    "px_x0",
    "px_y0",
    "px_x1",
    "px_y1",
    "tesseract_version",
    "config",
    "reading",
    "confidence",
)

PixelBox = tuple[int, int, int, int]
CacheKey = tuple[int, PixelBox, str, str]


class RecordLike(Protocol):
    @property
    def record_id(self) -> str: ...
    @property
    def observations(self) -> dict[ObservationKey, Observation]: ...
    @property
    def conditions(self) -> list[ReadingCondition]: ...


def eligible(obs: Observation) -> bool:
    """Table numbers with a box, read by the text layer, OCR or the position fallback."""
    return (
        kind_of(obs.key.parameter) is ParameterKind.NUMBER
        and obs.key.column_role in SECOND_READING_ROLES
        and obs.bbox is not None
        and obs.value_state is not ValueState.NOT_ON_PAGE
        and obs.read_method in FIRST_READ_METHODS
    )


def crop_box(obs: Observation, page: Page, size: tuple[int, int]) -> PixelBox:
    """The cell's pixel box on the rendered page: deskew undone, margins added."""
    assert obs.bbox is not None
    w, h = size
    x0, y0, x1, y1 = obs.bbox
    if not obs.raw_text:
        x0 = x1 - EMPTY_SLOT_WIDTH
    # deskew moved every word by -skew * (cx - 0.5); the image is not deskewed
    dy = page.skew * ((x0 + x1) / 2 - 0.5)
    return (
        int(max(0.0, x0 - MARGIN_X) * w),
        int(max(0.0, y0 + dy - MARGIN_Y) * h),
        int(min(1.0, x1 + MARGIN_X) * w),
        int(min(1.0, y1 + dy + MARGIN_Y) * h),
    )


class SecondOcrCache:
    """The readings of one file, loaded once and written back when changed."""

    def __init__(self, cache_dir: Path | None, file_hash: str):
        self.path = (
            None
            if cache_dir is None
            else cache_dir / SECOND_OCR_DIR / f"{file_hash}.csv"
        )
        self.rows: dict[CacheKey, tuple[str, float | None]] = {}
        self.dirty = False
        if self.path is not None and self.path.is_file():
            from spirotrace.store import read_rows

            for r in read_rows(self.path, CACHE_COLUMNS):
                key: CacheKey = (
                    int(r["page"]),
                    (
                        int(r["px_x0"]),
                        int(r["px_y0"]),
                        int(r["px_x1"]),
                        int(r["px_y1"]),
                    ),
                    r["tesseract_version"],
                    r["config"],
                )
                conf = float(r["confidence"]) if r["confidence"] else None
                self.rows[key] = (r["reading"], conf)

    def get(self, key: CacheKey) -> tuple[str, float | None] | None:
        return self.rows.get(key)

    def put(self, key: CacheKey, reading: str, confidence: float | None) -> None:
        self.rows[key] = (reading, confidence)
        self.dirty = True

    def save(self) -> None:
        if self.path is None or not self.dirty:
            return
        from spirotrace.store import write_rows

        write_rows(
            self.path,
            CACHE_COLUMNS,
            (
                {
                    "page": str(page),
                    "px_x0": str(box[0]),
                    "px_y0": str(box[1]),
                    "px_x1": str(box[2]),
                    "px_y1": str(box[3]),
                    "tesseract_version": version,
                    "config": config,
                    "reading": reading,
                    "confidence": "" if conf is None else repr(conf),
                }
                for (page, box, version, config), (reading, conf) in sorted(
                    self.rows.items(), key=lambda kv: (kv[0][0], kv[0][1])
                )
            ),
        )
        self.dirty = False


@dataclass(slots=True)
class SecondOcrStats:
    cells: int = 0
    cached: int = 0
    read: int = 0
    skipped_small: int = 0
    failed_records: int = 0
    records_failed: list[str] = field(default_factory=list)

    def add(self, other: SecondOcrStats) -> None:
        self.cells += other.cells
        self.cached += other.cached
        self.read += other.read
        self.skipped_small += other.skipped_small
        self.failed_records += other.failed_records


Renderer = Callable[[bytes, int, int, int], Image.Image]


def second_read_records(
    records: Iterable[RecordLike],
    pages: Sequence[Page],
    data: bytes,
    tool: TesseractLike,
    cache: SecondOcrCache,
    *,
    render: Renderer = render_page,
) -> SecondOcrStats:
    """Re-read every eligible observation of ``records``; updates them in place.

    ``data`` is the PDF's bytes; ``pages`` its page rows (rotation and skew).
    A Tesseract failure ends that record's readings with the condition
    ``second_reading_failed``; the other records go on.
    """
    stats = SecondOcrStats()
    by_number: Mapping[int, Page] = {p.page: p for p in pages}
    images: dict[int, Image.Image] = {}

    def image_of(n: int) -> Image.Image:
        if n not in images:
            images[n] = render(data, n - 1, DPI, by_number[n].rotation)
        return images[n]

    for rec in records:
        for key, obs in list(rec.observations.items()):
            if not eligible(obs) or key.page not in by_number:
                continue
            page = by_number[key.page]
            img = image_of(key.page)
            box = crop_box(obs, page, img.size)
            if box[2] - box[0] < MIN_CROP_PX or box[3] - box[1] < MIN_CROP_PX:
                stats.skipped_small += 1
                continue
            stats.cells += 1
            ck: CacheKey = (key.page, box, tool.version, CELL_CONFIG_LABEL)
            hit = cache.get(ck)
            if hit is not None:
                reading, conf = hit
                stats.cached += 1
            else:
                try:
                    reading, conf = tool.cell(img.crop(box))
                except TesseractError as exc:
                    stats.failed_records += 1
                    stats.records_failed.append(rec.record_id)
                    rec.conditions.append(
                        ReadingCondition(
                            rec.record_id,
                            key.page,
                            None,
                            cond.SECOND_READING_FAILED,
                            type(exc).__name__,
                        )
                    )
                    break
                cache.put(ck, reading, conf)
                stats.read += 1
            rec.observations[key] = replace(
                obs, second_reading_run=True, second_reading=reading
            )
            if reading and conf is not None:
                rec.conditions.append(
                    ReadingCondition(
                        rec.record_id,
                        key.page,
                        key,
                        cond.SECOND_READING_CONFIDENCE,
                        f"{conf:.0f}",
                    )
                )
    cache.save()
    return stats
