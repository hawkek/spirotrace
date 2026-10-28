"""The second reading: which cells, the crop box, the cache, the observation update,
the confidence and failure conditions. A fake engine answers from a queue; a live
test with Tesseract on a synthetic text-layer PDF runs where it is installed."""

from __future__ import annotations

from pathlib import Path

import pytest
from checks_helpers import P, R, cells
from pdf_helpers import PAGE_H, PAGE_W, make_pdf
from PIL import Image

from spirotrace.ingest import CELL_CONFIG_LABEL, TesseractError, tesseract_tool
from spirotrace.ingest.second_ocr import (
    SecondOcrCache,
    crop_box,
    eligible,
    second_read_records,
)
from spirotrace.layouts import conditions as cond
from spirotrace.model import Page, ReadMethod, TextSource

HASH = "ab" * 32


class FakeTool:
    version = "fake-1"

    def __init__(self, answers: list[tuple[str, float | None] | Exception]):
        self.answers = list(answers)
        self.calls = 0

    def page_words(self, image):
        return []

    def cell(self, image: Image.Image) -> tuple[str, float | None]:
        self.calls += 1
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a


def page(n: int = 1, skew: float = 0.0, rotation: int = 0) -> Page:
    return Page(HASH, n, "summary", n, 20, rotation, skew, 0.2, TextSource.TEXT_LAYER)


def white(data: bytes, index: int, dpi: int, rotation: int = 0) -> Image.Image:
    return Image.new("L", (int(PAGE_W * dpi / 72), int(PAGE_H * dpi / 72)), 255)


SPEC = {
    (P.FEV1, R.PRE): "3.05",  # eligible
    (P.FVC, R.Z): "",  # eligible: an empty cell looks in the column slot
    (P.AGE, R.MEASURED): "40",  # header field: not re-read
    (P.SEX, R.MEASURED): "Female",  # text: not re-read
    (P.FEV1, R.TREND): "3.00",  # trend row: not re-read
}


def test_eligible_selection() -> None:
    rec = cells(SPEC)
    flags = {k.parameter: eligible(o) for k, o in rec.observations.items()}
    assert flags[P.FEV1] is True or any(
        eligible(o) for k, o in rec.observations.items() if k.column_role is R.PRE
    )
    assert not eligible(
        next(o for k, o in rec.observations.items() if k.parameter is P.AGE)
    )
    assert not eligible(
        next(o for k, o in rec.observations.items() if k.parameter is P.SEX)
    )
    assert not eligible(
        next(o for k, o in rec.observations.items() if k.column_role is R.TREND)
    )
    manual = rec.put(P.FVC, R.PRE, "3.70", read_method=ReadMethod.MANUAL)
    assert not eligible(manual)


def test_crop_box_undoes_deskew_and_widens_empty_cells() -> None:
    rec = cells({(P.FEV1, R.PRE): "3.05", (P.FVC, R.PRE): ""})
    full = next(o for k, o in rec.observations.items() if k.parameter is P.FEV1)
    empty = next(o for k, o in rec.observations.items() if k.parameter is P.FVC)
    size = (1000, 2000)
    assert crop_box(full, page(), size) == (94, 192, 206, 248)
    # skew 0.01: the cell centre is at x 0.15, so the words were lifted by
    # 0.01 * (0.15 - 0.5) = -0.0035 at deskew; the crop moves back down by that
    skewed = crop_box(full, page(skew=0.01), size)
    assert skewed[1] == 192 - 7 and skewed[3] == 248 - 7
    assert crop_box(empty, page(), size)[0] == int((0.2 - 0.035 - 0.006) * 1000)


def test_readings_update_observations_and_fill_the_cache(tmp_path: Path) -> None:
    rec = cells(SPEC)
    tool = FakeTool([("3.05", 96.0), ("", None)])
    cache = SecondOcrCache(tmp_path, HASH)
    stats = second_read_records([rec], [page()], b"", tool, cache, render=white)
    assert (stats.cells, stats.read, stats.cached, stats.failed_records) == (2, 2, 0, 0)
    fev1 = next(
        o
        for k, o in rec.observations.items()
        if k.parameter is P.FEV1 and k.column_role is R.PRE
    )
    assert fev1.second_reading_run and fev1.second_reading == "3.05"
    fvc_z = next(o for k, o in rec.observations.items() if k.column_role is R.Z)
    assert fvc_z.second_reading_run and fvc_z.second_reading == ""
    confs = [c for c in rec.conditions if c.code == cond.SECOND_READING_CONFIDENCE]
    assert len(confs) == 1 and confs[0].detail == "96" and confs[0].key == fev1.key
    path = tmp_path / "second_ocr" / f"{HASH}.csv"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert CELL_CONFIG_LABEL in text and "fake-1" in text and "3.05" in text


def test_cache_hit_skips_the_engine_and_a_new_version_misses(tmp_path: Path) -> None:
    rec = cells(SPEC)
    cache = SecondOcrCache(tmp_path, HASH)
    second_read_records(
        [rec],
        [page()],
        b"",
        FakeTool([("3.05", 96.0), ("", None)]),
        cache,
        render=white,
    )
    again = cells(SPEC)
    tool = FakeTool([])
    stats = second_read_records(
        [again], [page()], b"", tool, SecondOcrCache(tmp_path, HASH), render=white
    )
    assert tool.calls == 0 and stats.cached == 2
    obs = next(
        o
        for k, o in again.observations.items()
        if k.parameter is P.FEV1 and k.column_role is R.PRE
    )
    assert obs.second_reading == "3.05"
    assert any(c.code == cond.SECOND_READING_CONFIDENCE for c in again.conditions)

    class Newer(FakeTool):
        version = "fake-2"

    third = cells(SPEC)
    newer = Newer([("3.06", 80.0), ("", None)])
    second_read_records(
        [third], [page()], b"", newer, SecondOcrCache(tmp_path, HASH), render=white
    )
    assert newer.calls == 2
    rows = (
        (tmp_path / "second_ocr" / f"{HASH}.csv")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    assert len(rows) == 1 + 4  # both versions kept


def test_failure_ends_the_record_with_a_condition(tmp_path: Path) -> None:
    rec = cells(SPEC)
    tool = FakeTool([TesseractError("boom"), ("", None)])
    stats = second_read_records(
        [rec], [page()], b"", tool, SecondOcrCache(None, HASH), render=white
    )
    assert stats.failed_records == 1 and stats.records_failed == ["11"]
    assert tool.calls == 1  # the record's other cells are not attempted
    failed = [c for c in rec.conditions if c.code == cond.SECOND_READING_FAILED]
    assert (
        len(failed) == 1
        and failed[0].key is None
        and failed[0].detail == "TesseractError"
    )
    assert not any(o.second_reading_run for o in rec.observations.values())


def test_no_cache_dir_means_in_memory_only(tmp_path: Path) -> None:
    rec = cells(SPEC)
    cache = SecondOcrCache(None, HASH)
    second_read_records(
        [rec],
        [page()],
        b"",
        FakeTool([("3.05", 90.0), ("", None)]),
        cache,
        render=white,
    )
    assert cache.path is None and not list(tmp_path.iterdir())


def test_live_second_reading_on_a_synthetic_pdf(tmp_path: Path) -> None:
    tool = tesseract_tool("")
    if tool is None:
        pytest.skip(
            "Tesseract is not installed (tools.tesseract); live reading not run"
        )
    # one number printed on a text-layer page; its box from the page geometry
    data = make_pdf([[("3.05", 200, 500)]])

    ingested = load_pdf_bytes(tmp_path, data)
    word = ingested.pages[0].words[0]
    rec = cells({(P.FEV1, R.PRE): "3.05"})
    key = next(iter(rec.observations))
    obs = rec.observations[key]
    from dataclasses import replace

    rec.observations[key] = replace(
        obs,
        bbox=(word.x0, word.x1, word.top, word.bottom)[:0]
        or (word.x0, word.top, word.x1, word.bottom),
    )
    pg = Page(HASH, 1, "summary", 1, 1, 0, 0.0, 0.01, TextSource.TEXT_LAYER)
    stats = second_read_records([rec], [pg], data, tool, SecondOcrCache(None, HASH))
    assert stats.read == 1
    assert rec.observations[key].second_reading == "3.05"


def load_pdf_bytes(tmp_path: Path, data: bytes):
    from spirotrace.ingest import load_pdf

    p = tmp_path / "one.pdf"
    p.write_bytes(data)
    return load_pdf(p, frozenset(), lambda s: s)
