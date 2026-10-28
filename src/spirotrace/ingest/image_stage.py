"""Stage 4 image checks: what the scan shows in a cell that the text layer
cannot say (README 0.3.16 "scan image check", not in v0.3.14).

Each page is rendered once at 300 dpi with its rotation; a cell's pixel box is
the second reading's (deskew undone, an empty cell looked for in the column
slot to its left) without its margin. On a numeric value cell the stage looks
for a horizontal ink line through the digits (the device strikes through the
trials it marks "Not Usable"; the number stays readable and is kept, so the
observation gets ``struck``) and for red ink (the lab prints out-of-range
values in red, so the observation gets ``marked``). On an empty cell it
measures the ink: something printed there is an OCR drop; nothing is the
report's format. The decisions use the thresholds the caller passes (they live
in the threshold table with their source) and are recorded as reading
conditions with the measurement as the detail; the rules in the image layer
turn them into flags. Nothing here changes a value.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace

from PIL import Image, ImageChops, ImageOps

from spirotrace.layouts import ReadingCondition
from spirotrace.layouts import conditions as cond
from spirotrace.model import (
    ColumnRole,
    Observation,
    Page,
    ParameterKind,
    ValueState,
    kind_of,
)

from .pdf import render_page
from .second_ocr import MIN_CROP_PX, SECOND_READING_ROLES, RecordLike, crop_box
from .tesseract import otsu_binarise

DPI = 300
INK_DARK = 160
"""Grayscale below this is ink: the blank-page check's cut (:func:`ink_fraction`).
A fixed cut, not Otsu, because Otsu on a blank cell splits the scanner noise."""
RED_MIN = 120
"""Red channel at or above this, with the dominance threshold, is red ink."""
CELL_ROLES: frozenset[ColumnRole] = SECOND_READING_ROLES | {ColumnRole.MEASURED}
"""The cells the stage looks at: the table cells the second reading re-reads plus
the ``measured`` column, which is the lab layout's value column (the red print).
Header fields share that role and are looked at too; they are never struck and
rarely red. Trend rows and free text are not looked at."""

Renderer = Callable[[bytes, int, int, int], Image.Image]


@dataclass(frozen=True, slots=True)
class ImageThresholds:
    """The cut-offs the stage applies (values from ``checks.thresholds``)."""

    struck_row_dark_fraction: float
    struck_min_aspect: float
    empty_cell_ink: float
    red_text_fraction: float
    red_pixel_dominance: int


@dataclass(slots=True)
class ImageStats:
    """Counts only."""

    cells: int = 0
    struck: int = 0
    ink_in_empty: int = 0
    blank_empty: int = 0
    red: int = 0
    skipped_small: int = 0

    def add(self, other: ImageStats) -> None:
        self.cells += other.cells
        self.struck += other.struck
        self.ink_in_empty += other.ink_in_empty
        self.blank_empty += other.blank_empty
        self.red += other.red
        self.skipped_small += other.skipped_small


def eligible_value(obs: Observation) -> bool:
    """A printed number in a table cell with a box: checked for a strike and red ink."""
    return (
        kind_of(obs.key.parameter) is ParameterKind.NUMBER
        and obs.key.column_role in CELL_ROLES
        and obs.bbox is not None
        and obs.value_state is ValueState.VALUE
    )


def eligible_empty(obs: Observation) -> bool:
    """A number cell the text layer left empty, with a box: its slot is measured."""
    return (
        kind_of(obs.key.parameter) is ParameterKind.NUMBER
        and obs.key.column_role in CELL_ROLES
        and obs.bbox is not None
        and obs.value_state is ValueState.EMPTY
    )


# --- measurements on one cell crop ---------------------------------------------


def ink_fraction_of(crop: Image.Image) -> float:
    """Fraction of dark pixels in the crop (fixed grayscale cut)."""
    hist = ImageOps.grayscale(crop).histogram()
    total = sum(hist)
    return sum(hist[:INK_DARK]) / total if total else 0.0


def red_fraction_of(crop: Image.Image, dominance: int) -> float:
    """Fraction of pixels whose red channel is high and exceeds green and blue by
    ``dominance``: red print; black print and the white page give 0."""
    r, g, b = crop.convert("RGB").split()
    excess = ImageChops.subtract(r, ImageChops.lighter(g, b))  # clipped at 0
    red = ImageChops.multiply(
        r.point(lambda p: 255 if p >= RED_MIN else 0),
        excess.point(lambda p: 255 if p >= dominance else 0),
    )
    hist = red.histogram()
    total = sum(hist)
    return hist[255] / total if total else 0.0


def struck_row_fraction(crop: Image.Image) -> tuple[float, float]:
    """The darkest row in the middle third of the digits, as a share of the ink
    width, and the ink's width over its height.

    A strike line runs dark through the gaps between characters, where a row
    through printed digits does not. Returns ``(0.0, 0.0)`` for a crop with no ink.
    """
    ink = ImageOps.invert(otsu_binarise(crop, border=0))  # ink is 255
    xs, ys = ink.getprojection()
    cols = [x for x, v in enumerate(xs) if v]
    rows = [y for y, v in enumerate(ys) if v]
    if not cols or not rows:
        return 0.0, 0.0
    x0, x1 = cols[0], cols[-1] + 1
    y0, y1 = rows[0], rows[-1] + 1
    width, height = x1 - x0, y1 - y0
    band_top = y0 + height // 3
    band_bottom = max(band_top + 1, y0 + (2 * height) // 3)
    darkest = 0.0
    for y in range(band_top, band_bottom):
        dark = ink.crop((x0, y, x1, y + 1)).histogram()[255]
        darkest = max(darkest, dark / width)
    return darkest, width / height


# --- the stage -------------------------------------------------------------------


def image_check_records(
    records: Iterable[RecordLike],
    pages: Sequence[Page],
    data: bytes,
    thresholds: ImageThresholds,
    *,
    render: Renderer | None = None,
) -> ImageStats:
    """Look at every eligible cell of ``records`` on the rendered pages of ``data``;
    updates the observations (``struck``, ``marked``) and conditions in place."""
    draw = render or render_page
    stats = ImageStats()
    by_number: Mapping[int, Page] = {p.page: p for p in pages}
    images: dict[int, Image.Image] = {}

    def image_of(n: int) -> Image.Image:
        if n not in images:
            images[n] = draw(data, n - 1, DPI, by_number[n].rotation).convert("RGB")
        return images[n]

    for rec in records:
        for key, obs in list(rec.observations.items()):
            if key.page not in by_number:
                continue
            value, empty = eligible_value(obs), eligible_empty(obs)
            if not (value or empty):
                continue
            img = image_of(key.page)
            box = crop_box(obs, by_number[key.page], img.size, margin_x=0, margin_y=0)
            if box[2] - box[0] < MIN_CROP_PX or box[3] - box[1] < MIN_CROP_PX:
                stats.skipped_small += 1
                continue
            stats.cells += 1
            crop = img.crop(box)
            seen: list[tuple[str, str]] = []  # (condition code, measurement)
            if value:
                darkest, aspect = struck_row_fraction(crop)
                struck = (
                    darkest >= thresholds.struck_row_dark_fraction
                    and aspect >= thresholds.struck_min_aspect
                )
                red_share = red_fraction_of(crop, thresholds.red_pixel_dominance)
                red = red_share >= thresholds.red_text_fraction
                if struck:
                    stats.struck += 1
                    seen.append((cond.IMAGE_STRUCK_LINE, f"{darkest:.2f}"))
                if red:
                    stats.red += 1
                    seen.append((cond.IMAGE_RED_TEXT, f"{red_share:.3f}"))
                if struck or red:
                    rec.observations[key] = replace(
                        obs, struck=obs.struck or struck, marked=obs.marked or red
                    )
            else:
                share = ink_fraction_of(crop)
                if share >= thresholds.empty_cell_ink:
                    stats.ink_in_empty += 1
                    seen.append((cond.IMAGE_INK_IN_EMPTY_CELL, f"{share:.3f}"))
                else:
                    stats.blank_empty += 1
                    seen.append((cond.IMAGE_EMPTY_CELL_BLANK, f"{share:.3f}"))
            for code, detail in seen:
                rec.conditions.append(
                    ReadingCondition(rec.record_id, key.page, key, code, detail)
                )
    return stats
