"""Image layer (stage 4; README 0.3.16 features, not in v0.3.14): the image
stage's reading conditions become flags here.

A struck-through number is a check that also sets ``struck`` on the
observation (the value is kept; the analysis decides). Ink in a cell the text
layer left empty is a check: an OCR drop, also where no other rule fired. An
empty cell that is blank on the scan is the report's format, so it demotes
``layout.cell_empty_in_filled_column`` to a note carrying this rule's id, as
``cohort.column_empty_by_format`` does. Red print sets ``marked`` on the
observation (``image.red_text_marked`` in the curated list) and raises no
flag: the lab marks out-of-range values in red the way the device uses ``*``,
and the QC report compares flag rates on marked and unmarked values.
"""

from __future__ import annotations

from collections.abc import Iterator

from spirotrace.ingest.image_stage import ImageThresholds
from spirotrace.layouts import conditions as cond
from spirotrace.model import ObservationKey

from .context import RecordContext
from .flags import Flag, Severity
from .registry import rule
from .thresholds import T

C, N = Severity.CHECK, Severity.NOTE


def image_thresholds() -> ImageThresholds:
    """The image stage's cut-offs from the threshold table."""
    return ImageThresholds(
        struck_row_dark_fraction=T("struck_row_dark_fraction"),
        struck_min_aspect=T("struck_min_aspect"),
        empty_cell_ink=T("empty_cell_ink"),
        red_text_fraction=T("red_text_fraction"),
        red_pixel_dominance=int(T("red_pixel_dominance")),
    )


def blank_on_scan(ctx: RecordContext) -> frozenset[ObservationKey]:
    """Keys of empty cells the scan showed blank (the runner hands them to the
    layout rule so it leaves them to :func:`empty_cell_blank`)."""
    return frozenset(
        c.key for c in ctx.conditions_of(cond.IMAGE_EMPTY_CELL_BLANK) if c.key
    )


@rule(
    "image.struck_number",
    "image",
    C,
    "The device strikes through a trial it marks not usable; the number is printed "
    "and kept, the analysis decides",
)
def struck_number(ctx: RecordContext) -> Iterator[Flag]:
    for c in ctx.conditions_of(cond.IMAGE_STRUCK_LINE):
        if c.key is None:
            continue
        yield ctx.flag(
            "image.struck_number",
            f"number printed struck through on the scan (dark along {c.detail} of "
            "the digits' width); value kept",
            (c.key,),
        )


@rule(
    "image.printed_in_empty_cell",
    "image",
    C,
    "Something is printed in a cell the text layer left empty: an OCR drop, also "
    "where no other flag fired",
)
def printed_in_empty_cell(ctx: RecordContext) -> Iterator[Flag]:
    for c in ctx.conditions_of(cond.IMAGE_INK_IN_EMPTY_CELL):
        if c.key is None:
            continue
        yield ctx.flag(
            "image.printed_in_empty_cell",
            f"cell read as empty but the scan shows ink there (dark fraction {c.detail})",
            (c.key,),
        )


@rule(
    "image.empty_cell_blank",
    "image",
    N,
    "A cell blank on the scan is the report's format, not an OCR drop",
)
def empty_cell_blank(ctx: RecordContext) -> Iterator[Flag]:
    # only the cells the layout rule would have flagged; a column the cohort
    # already explains as the format keeps that note alone
    blank = ctx.blank_on_scan or blank_on_scan(ctx)
    for c in ctx.conditions_of(cond.CELL_EMPTY_IN_FILLED_COLUMN):
        if c.key is None or c.key not in blank:
            continue
        slot = (c.key.parameter, c.key.column_role, c.key.display_position)
        if slot in ctx.empty_by_format:
            continue
        yield ctx.flag(
            "image.empty_cell_blank",
            "cell empty although column has values in other rows; blank on the scan "
            "(the report's format)",
            (c.key,),
        )
