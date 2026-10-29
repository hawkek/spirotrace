"""Stage 4 image checks on synthetic cells drawn with Pillow: digits with and
without a strike line, an empty white cell, an empty cell with a digit printed in
it, a cell in red print. The measurement tests document the cells the thresholds
were set on (``checks.thresholds``, source "set on synthetic cells"); the stage
tests check the conditions, the observation flags and the rules; the pipeline test
shows the stage runs only when ``image.checks`` is true."""

from __future__ import annotations

from pathlib import Path

import pytest
from checks_helpers import HASH, FakeRecord, P, R, flags_of, record, run
from pdf_helpers import PAGE_H, PAGE_W
from PIL import Image, ImageDraw, ImageFont

from spirotrace import pipeline
from spirotrace.checks import THRESHOLDS, Severity
from spirotrace.checks.rules_image import image_thresholds
from spirotrace.config import load_settings
from spirotrace.ingest import image_stage
from spirotrace.ingest.image_stage import (
    ImageThresholds,
    image_check_records,
    ink_fraction_of,
    red_fraction_of,
    struck_row_fraction,
)
from spirotrace.layouts import Condition, ReadingCondition, build_observation
from spirotrace.layouts import conditions as cond
from spirotrace.model import ObservationKey, Page, ReadMethod, TextSource

FONT = ImageFont.load_default(size=26)
"""About a 10-point digit at 300 dpi."""
BLACK, RED, SCAN_RED = (0, 0, 0), (200, 30, 30), (170, 80, 80)
SLOT = (87, 32)
"""A column slot at 300 dpi: 0.035 of an A4 page wide, one text line high."""


def draw_cell(
    text: str,
    *,
    strike: bool = False,
    fill: tuple[int, int, int] = BLACK,
    size: tuple[int, int] = SLOT,
) -> Image.Image:
    im = Image.new("RGB", size, (255, 255, 255))
    d = ImageDraw.Draw(im)
    if text:
        d.text((4, 2), text, font=FONT, fill=fill)
    if strike:
        x0, y0, x1, y1 = d.textbbox((4, 2), text, font=FONT)
        y = (y0 + y1) // 2
        d.line((x0 - 2, y, x1 + 2, y), fill=fill, width=2)
    return im


# --- the measurements the thresholds were set on -----------------------------------

TEXTS = ("3.05", "-0.50", "0.824", "10", "4", "1", "7.1", "105")


@pytest.mark.parametrize("text", TEXTS)
def test_struck_row_fraction_separates_a_strike_from_printed_digits(text: str) -> None:
    plain, aspect = struck_row_fraction(draw_cell(text))
    struck, struck_aspect = struck_row_fraction(draw_cell(text, strike=True))
    cut = THRESHOLDS["struck_row_dark_fraction"].value
    print(f"cell {text!r}: plain {plain:.2f} struck {struck:.2f} (cut {cut})")
    assert plain <= 0.5 < cut <= struck  # digits leave gaps; the line does not
    assert struck_aspect >= THRESHOLDS["struck_min_aspect"].value
    if len(text) == 1:  # a lone digit is below the aspect guard
        assert aspect < THRESHOLDS["struck_min_aspect"].value


def test_struck_row_fraction_of_a_blank_cell_is_zero() -> None:
    assert struck_row_fraction(draw_cell("")) == (0.0, 0.0)


def test_empty_cell_ink_separates_a_digit_from_blank_and_a_short_dash() -> None:
    cut = THRESHOLDS["empty_cell_ink"].value
    digit, one, dash, blank = (
        ink_fraction_of(draw_cell(t)) for t in ("2", "1", "-", "")
    )
    print(
        f"ink: digit {digit:.3f} one {one:.3f} dash {dash:.3f} blank {blank} (cut {cut})"
    )
    assert blank == 0.0 and dash < cut <= one < digit
    # a short dash is the report's format (curated list 1.5), so it stays blank


def test_red_fraction_separates_red_print_from_black_and_grey() -> None:
    dom = int(THRESHOLDS["red_pixel_dominance"].value)
    cut = THRESHOLDS["red_text_fraction"].value
    red = red_fraction_of(draw_cell("3.05", fill=RED), dom)
    scan = red_fraction_of(draw_cell("3.05", fill=SCAN_RED), dom)
    print(f"red: red {red:.3f} scanned red {scan:.3f} (cut {cut})")
    assert red_fraction_of(draw_cell("3.05"), dom) == 0.0
    assert red_fraction_of(draw_cell("3.05", fill=(90, 90, 90)), dom) == 0.0
    assert cut <= scan <= red


def test_image_thresholds_come_from_the_table_with_a_source() -> None:
    t = image_thresholds()
    assert t.struck_row_dark_fraction == THRESHOLDS["struck_row_dark_fraction"].value
    for name in (
        "struck_row_dark_fraction",
        "struck_min_aspect",
        "empty_cell_ink",
        "red_text_fraction",
        "red_pixel_dominance",
    ):
        assert "synthetic cells" in THRESHOLDS[name].source


# --- the stage on a drawn page -----------------------------------------------------

DPI = 300
W, H = int(PAGE_W * DPI / 72), int(PAGE_H * DPI / 72)
CELL_W, CELL_H = 0.035, 32 / H


def page(skew: float = 0.0) -> Page:
    return Page(HASH, 1, "summary", 1, 20, 0, skew, 0.2, TextSource.TEXT_LAYER)


class DrawnPage:
    """Cells placed on a white A4 page; the renderer returns the drawing."""

    def __init__(self) -> None:
        self.image = Image.new("RGB", (W, H), (255, 255, 255))
        self.n = 0
        self.rendered = 0

    def place(self, cell: Image.Image | None) -> tuple[float, float, float, float]:
        """Paste ``cell`` on the next row and return its page-normalised box."""
        x0, y0 = 0.3, 0.1 + 0.03 * self.n
        self.n += 1
        if cell is not None:
            self.image.paste(cell, (int(x0 * W), int(y0 * H)))
        return (x0, y0, x0 + CELL_W, y0 + CELL_H)

    def render(self, data: bytes, index: int, dpi: int, rotation: int) -> Image.Image:
        assert (index, dpi, rotation) == (0, DPI, 0)
        self.rendered += 1
        return self.image


def put(
    rec: FakeRecord,
    parameter,
    role,
    raw: str,
    bbox,
    position: int = 1,
    *,
    conditions=(),
) -> ObservationKey:
    key = ObservationKey(HASH, 1, rec.record.layout, parameter, role, position)
    built = build_observation(key, rec.record_id, 1, raw, bbox, ReadMethod.TEXT_LAYER)
    rec.observations[key] = built.observation
    for c in (*conditions, *built.conditions):
        rec.conditions.append(ReadingCondition(rec.record_id, 1, key, c.code, c.detail))
    return key


def drawn_record() -> tuple[FakeRecord, DrawnPage, dict[str, ObservationKey]]:
    rec, pg = record(), DrawnPage()
    keys = {
        "plain": put(rec, P.FEV1, R.TRIAL, "3.05", pg.place(draw_cell("3.05")), 2),
        "struck": put(
            rec, P.FVC, R.TRIAL, "3.70", pg.place(draw_cell("3.70", strike=True)), 2
        ),
        "red": put(
            rec, P.TLC, R.MEASURED, "5.10", pg.place(draw_cell("5.10", fill=RED))
        ),
        "blank": put(
            rec,
            P.FEV1,
            R.LLN,
            "",
            pg.place(None),
            conditions=[Condition(cond.CELL_EMPTY_IN_FILLED_COLUMN)],
        ),
        "printed": put(
            rec,
            P.FVC,
            R.LLN,
            "",
            pg.place(draw_cell("2")),
            conditions=[Condition(cond.CELL_EMPTY_IN_FILLED_COLUMN)],
        ),
        # a header field shares the lab's value role and is looked at; a dash and a
        # cell without a box are not
        "header": put(rec, P.AGE, R.MEASURED, "40", pg.place(draw_cell("40"))),
        "dash": put(rec, P.PEF, R.PRE, "-", pg.place(draw_cell("-"))),
        "nobox": put(rec, P.FET, R.PRE, "7.1", None),
    }
    return rec, pg, keys


def test_stage_sets_struck_and_marked_and_records_the_conditions() -> None:
    rec, pg, keys = drawn_record()
    stats = image_check_records(
        [rec], [page()], b"", image_thresholds(), render=pg.render
    )
    assert pg.rendered == 1  # one render per page, whatever the number of cells
    assert (stats.cells, stats.struck, stats.red) == (6, 1, 1)
    assert (stats.ink_in_empty, stats.blank_empty, stats.skipped_small) == (1, 1, 0)
    obs = rec.observations
    assert obs[keys["struck"]].struck and not obs[keys["struck"]].marked
    assert obs[keys["red"]].marked and not obs[keys["red"]].struck
    assert not obs[keys["plain"]].struck and not obs[keys["plain"]].marked
    assert not obs[keys["header"]].struck and not obs[keys["header"]].marked
    by_code = {(c.code, c.key) for c in rec.conditions if c.code.startswith("image_")}
    assert by_code == {
        (cond.IMAGE_STRUCK_LINE, keys["struck"]),
        (cond.IMAGE_RED_TEXT, keys["red"]),
        (cond.IMAGE_EMPTY_CELL_BLANK, keys["blank"]),
        (cond.IMAGE_INK_IN_EMPTY_CELL, keys["printed"]),
    }
    # the value is kept
    assert obs[keys["struck"]].parsed_value == 3.70
    assert obs[keys["struck"]].value_state.value == "value"


def test_stage_skips_pages_it_has_no_row_for_and_too_small_boxes() -> None:
    rec = record()
    put(rec, P.FEV1, R.PRE, "3.05", (0.3, 0.1, 0.3005, 0.1005))
    pg = DrawnPage()
    stats = image_check_records(
        [rec], [page()], b"", image_thresholds(), render=pg.render
    )
    assert stats.skipped_small == 1 and stats.cells == 0
    pg = DrawnPage()
    stats = image_check_records(
        [rec],
        [Page(HASH, 2, "x", 2, 20, 0, 0.0, 0.2, TextSource.TEXT_LAYER)],
        b"",
        image_thresholds(),
        render=pg.render,
    )
    assert stats.cells == 0 and pg.rendered == 0  # no page row: not even rendered


def test_stage_applies_the_thresholds_it_is_given() -> None:
    rec, pg, keys = drawn_record()
    strict = ImageThresholds(
        struck_row_dark_fraction=1.1,
        struck_min_aspect=1.0,
        empty_cell_ink=1.0,
        red_text_fraction=1.0,
        red_pixel_dominance=60,
    )
    stats = image_check_records([rec], [page()], b"", strict, render=pg.render)
    assert (stats.struck, stats.red, stats.ink_in_empty, stats.blank_empty) == (
        0,
        0,
        0,
        2,
    )
    assert not rec.observations[keys["struck"]].struck


# --- the rules ----------------------------------------------------------------------


def checked_record() -> tuple[FakeRecord, dict[str, ObservationKey]]:
    rec, pg, keys = drawn_record()
    image_check_records([rec], [page()], b"", image_thresholds(), render=pg.render)
    return rec, keys


def test_struck_number_is_a_check_on_the_struck_cell_only() -> None:
    rec, keys = checked_record()
    flags = flags_of(run(rec), "image.struck_number")
    assert len(flags) == 1 and flags[0].severity is Severity.CHECK
    assert flags[0].keys == (keys["struck"],)
    assert "struck through" in flags[0].message and "3.70" not in flags[0].message


def test_printed_in_empty_cell_is_a_check() -> None:
    rec, keys = checked_record()
    flags = flags_of(run(rec), "image.printed_in_empty_cell")
    assert len(flags) == 1 and flags[0].severity is Severity.CHECK
    assert flags[0].keys == (keys["printed"],)


def test_blank_empty_cell_demotes_the_layout_check_to_a_note_with_this_rules_id() -> (
    None
):
    rec, keys = checked_record()
    flags = run(rec)
    blank = flags_of(flags, "image.empty_cell_blank")
    assert len(blank) == 1 and blank[0].severity is Severity.NOTE
    assert blank[0].keys == (keys["blank"],)
    # the printed cell keeps the layout check (and gets the image check)
    layout = flags_of(flags, "layout.cell_empty_in_filled_column")
    assert [f.keys for f in layout] == [(keys["printed"],)]
    # switching the image note off restores the layout check on the blank cell
    flags = run(rec, off=["image.empty_cell_blank"])
    assert not flags_of(flags, "image.empty_cell_blank")
    assert {
        f.keys[0] for f in flags_of(flags, "layout.cell_empty_in_filled_column")
    } == {
        keys["blank"],
        keys["printed"],
    }


def test_blank_cell_without_the_layout_condition_raises_nothing() -> None:
    rec, pg = record(), DrawnPage()
    put(rec, P.FEV1, R.LLN, "", pg.place(None))
    image_check_records([rec], [page()], b"", image_thresholds(), render=pg.render)
    flags = run(rec)
    assert not flags_of(flags, "image.empty_cell_blank")
    assert not flags_of(flags, "layout.cell_empty_in_filled_column")


def test_red_text_sets_marked_and_raises_no_flag() -> None:
    rec, keys = checked_record()
    assert rec.observations[keys["red"]].marked
    assert not any(
        f.rule_id.startswith("image.") and keys["red"] in f.keys for f in run(rec)
    )


# --- the pipeline runs the stage only when image.checks is true --------------------


def _project(tmp_path: Path) -> Path:
    from test_pipeline import project

    return project(tmp_path)


def test_pipeline_runs_the_stage_only_when_image_checks_is_true(
    tmp_path: Path, monkeypatch
) -> None:
    from test_pipeline import fake_reader

    folder = _project(tmp_path)
    (folder / "profiles").mkdir()
    (folder / "profiles" / "noimg.toml").write_text(
        "[image]\nchecks = false\n", encoding="utf-8"
    )
    renders = 0

    def strike_everything(
        data: bytes, index: int, dpi: int, rotation: int
    ) -> Image.Image:
        # every cell of the fake reader shares one box; draw a line through it
        nonlocal renders
        renders += 1
        w, h = int(PAGE_W * dpi / 72), int(PAGE_H * dpi / 72)
        im = Image.new("RGB", (w, h), (255, 255, 255))
        d = ImageDraw.Draw(im)
        at = (int(0.1 * w) + 4, int(0.1 * h) + 2)
        d.text(at, "3.05", font=FONT, fill=BLACK)
        x0, y0, x1, y1 = d.textbbox(at, "3.05", font=FONT)
        d.line((x0 - 2, (y0 + y1) // 2, x1 + 2, (y0 + y1) // 2), fill=BLACK, width=2)
        return im

    monkeypatch.setattr(image_stage, "render_page", strike_everything)
    lines: list[str] = []
    result = pipeline.run_project(
        folder, load_settings(folder), fake_reader, console=lines.append
    )
    assert result.image is not None and result.image.cells > 0 and renders == 2
    assert result.image.struck == result.image.cells
    text = "\n".join(lines)
    assert "image checks: cells" in text and "3.05" not in text
    assert any(f.rule_id == "image.struck_number" for f in result.store.flags)
    assert any(o.struck for r in result.store.records for o in r.observations.values())

    renders = 0
    off = pipeline.run_project(
        folder, load_settings(folder, "noimg"), fake_reader, profile="noimg"
    )
    assert off.image is None and renders == 0
    assert "image checks" not in "\n".join(off.summary_lines())
    assert not any(f.rule_id.startswith("image.") for f in off.store.flags)
