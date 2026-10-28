"""pipeline and cli: init, run with a fake reader, the raw store and stamp, export.

The fake reader builds records from cell texts without a layout; a tiny
text-layer PDF stands in for a report. Everything is synthetic, in tmp_path.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from checks_helpers import P, R, cells
from pdf_helpers import make_pdf

from spirotrace import cli
from spirotrace.config import load_settings
from spirotrace.ingest import file_hash_of
from spirotrace.model import Page, Record, TextSource
from spirotrace.pipeline import (
    PipelineError,
    export_project,
    load_reader,
    pdf_files,
    run_project,
)
from spirotrace.store import Event, append_event, read_raw
from spirotrace.store.outputs import DERIVED_FILE, RESOLVED_FILE

SPEC = {
    (P.FEV1, R.PRE): "3.05",
    (P.FVC, R.PRE): "3.70",
    (P.FEV1_FVC, R.PRE): "0.824",
    (P.FEV1, R.Z): "-0.50",
    (P.FEV1_FVC, R.Z): "-0.10",
    (P.FVC, R.Z): "x",
}


class FileRead:
    def __init__(self, file_hash: str, pages, records):
        self.file_hash, self.pages, self.records = file_hash, pages, records


def fake_reader(path: Path, settings, used_ids: set[str], cache_dir=None) -> FileRead:
    """Reads the cell spec for the file name; raises on a 'bad' file."""
    if path.stem.startswith("bad"):
        raise ValueError("corrupt")
    data = path.read_bytes()
    h = file_hash_of(data)
    rec = cells(SPEC, path.stem)
    record = Record(path.stem, h, "layout_x", path.stem, (1,))
    rec.record = record
    # re-key the observations on this file's hash
    obs = {}
    for k, o in rec.observations.items():
        nk = type(k)(
            h, k.page, k.template_id, k.parameter, k.column_role, k.display_position
        )
        obs[nk] = type(o)(**{**{f: getattr(o, f) for f in o.__slots__}, "key": nk})
    rec.observations = obs
    rec.conditions = [
        type(c)(
            c.record_id,
            c.page,
            None
            if c.key is None
            else type(c.key)(
                h,
                c.key.page,
                c.key.template_id,
                c.key.parameter,
                c.key.column_role,
                c.key.display_position,
            ),
            c.code,
            c.detail,
        )
        for c in rec.conditions
    ]
    used_ids.add(path.stem)
    page = Page(h, 1, "summary", 1, 10, 0, 0.0, 0.2, TextSource.TEXT_LAYER)
    return FileRead(h, [page], [rec])


def project(tmp_path: Path, reader: str = "") -> Path:
    assert cli.main(["init", str(tmp_path)]) == 0
    (tmp_path / "spiro.toml").write_text(
        f'[templates]\nreader = "{reader}"\n' if reader else "", encoding="utf-8"
    )
    for name in ("11", "12"):
        (tmp_path / "reports" / f"{name}.pdf").write_bytes(
            make_pdf([[(name, 50, 800)]])
        )
    return tmp_path


# --- init ------------------------------------------------------------------------


def test_init_creates_folders_and_never_overwrites(tmp_path: Path, capsys) -> None:
    folder = tmp_path / "study"
    assert cli.main(["init", str(folder)]) == 0
    for name in ("reports", "cache", "review", "outputs", "share"):
        assert (folder / name).is_dir()
    text = (folder / "spiro.toml").read_text(encoding="utf-8")
    assert "[templates]" in text and "reader" in text
    load_settings(folder)  # the generated file is valid and all defaults
    (folder / "spiro.toml").write_text("[ocr]\nsecond_ocr = true\n", encoding="utf-8")
    (folder / "stray.pdf").write_bytes(make_pdf([[("x", 50, 800)]]))
    assert cli.main(["init", str(folder)]) == 0
    out = capsys.readouterr().out
    assert "kept as it is" in out and "1 PDF(s) in the project folder" in out
    assert (folder / "spiro.toml").read_text(encoding="utf-8").startswith("[ocr]")


# --- the reader ----------------------------------------------------------------------


def test_missing_reader_names_the_key(tmp_path: Path) -> None:
    s = load_settings(project(tmp_path))
    with pytest.raises(PipelineError, match="templates\\] reader"):
        load_reader(s, tmp_path)


def test_reader_import_errors_are_pipeline_errors(tmp_path: Path) -> None:
    with pytest.raises(PipelineError, match="no_such_module"):
        load_reader(load_settings(project(tmp_path, "no_such_module.x:fn")), tmp_path)
    with pytest.raises(PipelineError, match="module:function"):
        load_reader(load_settings(project(tmp_path, "json")), tmp_path)
    with pytest.raises(PipelineError, match="no function"):
        load_reader(load_settings(project(tmp_path, "json:nope")), tmp_path)


def test_reader_from_templates_dirs(tmp_path: Path) -> None:
    folder = project(tmp_path)
    (folder / "mods").mkdir()
    (folder / "mods" / "my_reader.py").write_text(
        "def read(*a, **k):\n    return None\n", encoding="utf-8"
    )
    (folder / "spiro.toml").write_text(
        '[templates]\nreader = "my_reader:read"\ndirs = ["mods"]\n', encoding="utf-8"
    )
    fn = load_reader(load_settings(folder), folder)
    assert fn.__name__ == "read"


def test_second_ocr_setting_is_refused_until_a4(tmp_path: Path) -> None:
    folder = project(tmp_path)
    (folder / "spiro.toml").write_text("[ocr]\nsecond_ocr = true\n", encoding="utf-8")
    with pytest.raises(PipelineError, match="second_ocr"):
        run_project(folder, load_settings(folder), fake_reader)


# --- run -------------------------------------------------------------------------------


def test_run_writes_the_raw_store_and_counts_only(tmp_path: Path) -> None:
    folder = project(tmp_path)
    (folder / "reports" / "bad.pdf").write_bytes(b"not a pdf")
    lines: list[str] = []
    result = run_project(
        folder, load_settings(folder), fake_reader, console=lines.append
    )
    assert result.files == 3 and result.failed_files == 1
    assert len(result.store.records) == 3
    raw = folder / "outputs" / "raw"
    back = read_raw(raw)
    ids = [r.record_id for r in back.records]
    assert ids[:2] == ["11", "12"] and ids[2].startswith("f")  # no subject id in "bad"
    assert any(f.rule_id == "input.file_unreadable" for f in back.flags)
    assert back.file_names[back.records[0].record.file_hash] == "11.pdf"
    assert back.stamp["file_hashes"] == sorted(back.file_names)
    assert back.stamp["templates"] == {"layout_x": 1}
    text = "\n".join(lines)
    assert "records: 3" in text and "files: 3 (1 could not be read)" in text
    for secret in ("11.pdf", "bad", ".pdf", "3.05"):  # no file name or value
        assert secret not in text


def test_rerun_with_same_inputs_keeps_the_stamp(tmp_path: Path) -> None:
    folder = project(tmp_path)
    s = load_settings(folder)
    first = run_project(folder, s, fake_reader)
    assert first.rebuilt
    second = run_project(folder, s, fake_reader)
    assert not second.rebuilt
    (folder / "spiro.toml").write_text(
        '[rules]\noff = ["range.outside_typical"]\n', encoding="utf-8"
    )
    third = run_project(folder, load_settings(folder), fake_reader)
    assert third.rebuilt and "rebuilt" in " ".join(third.notices)


def test_profile_run_goes_to_runs_folder(tmp_path: Path) -> None:
    folder = project(tmp_path)
    (folder / "profiles").mkdir()
    (folder / "profiles" / "noimg.toml").write_text(
        "[image]\nchecks = false\n", encoding="utf-8"
    )
    result = run_project(
        folder, load_settings(folder, "noimg"), fake_reader, profile="noimg"
    )
    assert result.raw_dir == folder / "runs" / "noimg" / "raw"
    assert result.raw_dir.is_dir()


# --- export ----------------------------------------------------------------------------


def test_export_without_a_run_is_a_pipeline_error(tmp_path: Path) -> None:
    folder = project(tmp_path)
    with pytest.raises(PipelineError, match="spirotrace run"):
        export_project(folder, load_settings(folder))


def test_export_resolves_against_events_and_derives(tmp_path: Path) -> None:
    folder = project(tmp_path)
    s = load_settings(folder)
    run_project(folder, s, fake_reader)
    back = read_raw(folder / "outputs" / "raw")
    bad = next(
        k
        for k in back.records[0].observations
        if k.parameter is P.FVC and k.column_role is R.Z
    )
    append_event(
        folder / "review",
        Event(
            "a" * 32,
            1,
            "2026-11-02T10:00:00+13:00",
            "KH",
            "11",
            bad.to_string(),
            "typed",
            "-0.3",
        ),
    )
    lines: list[str] = []
    result = export_project(folder, s, console=lines.append)
    assert result.resolved.values[bad].status == "corrected"
    assert result.resolved.events_count == 1
    assert (folder / "outputs" / RESOLVED_FILE).is_file()
    assert (folder / "outputs" / DERIVED_FILE).is_file()
    assert (folder / "outputs" / "stamp.json").is_file()
    d = result.derived.of_record("11")
    assert d["pattern"].value == "normal"
    assert (
        result.derived.of_record("12")["pattern"].value == ""
    )  # its FVC z is still an error
    text = "\n".join(lines)
    assert "events: 1 (0 orphan)" in text
    # no record has demographics, so nothing is sent to R and R is not claimed
    assert "rspiro: not run" in text and result.derived.gli_inputs == 0
    assert "corrected" in text


def test_cli_run_and_export_exit_codes(tmp_path: Path, monkeypatch) -> None:
    folder = project(tmp_path)
    (folder / "mods").mkdir()
    (folder / "mods" / "fake_mod.py").write_text(
        "from test_pipeline import fake_reader as read\n", encoding="utf-8"
    )
    monkeypatch.syspath_prepend(str(Path(__file__).parent))
    (folder / "spiro.toml").write_text(
        '[templates]\nreader = "fake_mod:read"\ndirs = ["mods"]\n', encoding="utf-8"
    )
    # 1: the gli rules did not run (no Rscript configured in the test)
    assert cli.main(["run", "--project", str(folder)]) in (0, 1)
    assert (folder / "outputs" / "raw" / "stamp.json").is_file()
    assert cli.main(["export", "--project", str(folder)]) in (0, 1)
    assert (folder / "outputs" / RESOLVED_FILE).is_file()


def test_pdf_files_is_case_insensitive_and_sorted(tmp_path: Path) -> None:
    (tmp_path / "B.PDF").write_bytes(b"x")
    (tmp_path / "a.pdf").write_bytes(b"x")
    (tmp_path / "c.txt").write_bytes(b"x")
    assert [p.name for p in pdf_files(tmp_path)] == ["a.pdf", "B.PDF"]
    assert pdf_files(tmp_path / "none") == []
