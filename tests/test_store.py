"""store: CSV conventions, the raw store round trip, stamps and the event files.

Everything written here is synthetic and goes to tmp_path.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from checks_helpers import P, R, cells, run

from spirotrace.checks import Flag, Severity, Suggestion
from spirotrace.model import ObservationKey, Page, TextSource
from spirotrace.store import (
    Event,
    RawStore,
    ReadRecord,
    StoreError,
    append_event,
    append_session,
    make_stamp,
    next_sequence,
    raw_stamp_fields,
    read_events,
    read_raw,
    read_rows,
    read_sessions,
    read_stamp,
    stamp_matches,
    write_raw,
    write_rows,
)
from spirotrace.store.raw import FLAGS_FILE, OBSERVATIONS_FILE, RECORDS_FILE

HASH = "ab" * 32


def a_store() -> RawStore:
    rec = cells(
        {
            (P.FEV1, R.PRE): "3.05",
            (P.FVC, R.PRE): "3.70",
            (P.FEV1_FVC, R.PRE): "82",
            (P.FEV1, R.Z): "-0.5",
        }
    )
    rec.note("page_blank", "", page=2)
    flags = run(rec)
    store = RawStore(
        records=[ReadRecord(rec.record, dict(rec.observations), list(rec.conditions))],
        pages=[Page(HASH, 1, "summary", 1, 120, 0, 0.0, 0.2, TextSource.TEXT_LAYER)],
        flags=flags,
        file_names={HASH: "11.pdf"},
    )
    return store


def fields() -> dict:
    return raw_stamp_fields("abc", "mod:fn", {"layout_x": 1}, [HASH])


# --- csv conventions ---------------------------------------------------------------


def test_rows_round_trip_utf8_and_tolerate_excel_cp1252(tmp_path: Path) -> None:
    path = tmp_path / "t.csv"
    write_rows(path, ("a", "b"), [{"a": "x", "b": "café"}])
    assert path.read_bytes().startswith(b"a,b\n")  # no BOM, LF line ends
    assert read_rows(path, ("a", "b")) == [{"a": "x", "b": "café"}]
    notices: list[str] = []
    path.write_bytes("a,b\r\nx,café\r\n".encode("cp1252"))
    assert read_rows(path, ("a",), notices.append)[0]["b"] == "café"
    assert notices and "not UTF-8" in notices[0]


def test_missing_column_and_missing_file_are_store_errors(tmp_path: Path) -> None:
    path = tmp_path / "t.csv"
    write_rows(path, ("a",), [{"a": "1"}])
    with pytest.raises(StoreError, match="missing columns"):
        read_rows(path, ("a", "b"))
    with pytest.raises(StoreError, match="not found"):
        read_rows(tmp_path / "none.csv")


def test_locked_file_is_written_alongside(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "t.csv"
    original = Path.write_bytes

    def locked(self: Path, data: bytes) -> int:
        if self == path:
            raise PermissionError("open in Excel")
        return original(self, data)

    monkeypatch.setattr(Path, "write_bytes", locked)
    notices: list[str] = []
    written = write_rows(path, ("a",), [{"a": "1"}], notices.append)
    assert written != path and written.parent == tmp_path and written.suffix == ".csv"
    assert "locked" in notices[0]


# --- raw store ----------------------------------------------------------------------


def test_raw_store_round_trips(tmp_path: Path) -> None:
    store = a_store()
    stamp = write_raw(tmp_path, store, fields(), code="0.0.1+test")
    assert stamp["code_version"] == "0.0.1+test"
    back = read_raw(tmp_path)
    assert [r.record for r in back.records] == [r.record for r in store.records]
    assert back.records[0].observations == store.records[0].observations
    assert back.records[0].conditions == store.records[0].conditions
    assert back.pages == store.pages
    assert back.flags == store.flags
    assert back.file_names == {HASH: "11.pdf"}
    assert back.stamp == stamp


def test_files_with_values_or_record_ids_say_so() -> None:
    for name in (RECORDS_FILE, OBSERVATIONS_FILE, FLAGS_FILE):
        assert "_CONTAINS_DATA" in name


def test_stamp_matches_ignores_written_at_only() -> None:
    a = make_stamp(fields(), code="x")
    b = {**a, "written_at": "later"}
    assert stamp_matches(a, b)
    assert not stamp_matches(a, {**a, "settings_hash": "other"})
    assert not stamp_matches(None, a)


def test_read_stamp_absent_or_broken_is_none(tmp_path: Path) -> None:
    assert read_stamp(tmp_path) is None
    (tmp_path / "stamp.json").write_text("{not json", encoding="utf-8")
    assert read_stamp(tmp_path) is None


def test_flag_row_round_trip_with_suggestion() -> None:
    key = ObservationKey(HASH, 1, "layout_x", P.FEV1, R.PRE, 1)
    f = Flag(
        "range.lost_decimal",
        "range",
        Severity.CHECK,
        "11",
        (key,),
        1,
        "lost decimal: 305?",
        Suggestion("3.05", "decimal point added"),
    )
    assert Flag.from_row(f.to_row()) == f
    assert f.flag_key == f"range.lost_decimal|11|{key.to_string()}"
    g = Flag.from_row({**f.to_row(), "message": "other words"})
    assert g.flag_key == f.flag_key  # the message is not part of the identity


# --- events -----------------------------------------------------------------------


def event(
    seq: int, action: str = "typed", value: str = "3.05", reviewer: str = "KH"
) -> Event:
    return Event(
        f"{seq:032x}",
        seq,
        f"2026-11-02T10:0{seq % 10}:00+13:00",
        reviewer,
        "11",
        ObservationKey(HASH, 1, "layout_x", P.FEV1, R.PRE, 1).to_string(),
        action,
        value,
        note="x" if action == "exclude" else "",
    )


def test_events_append_only_with_header_once(tmp_path: Path) -> None:
    review = tmp_path / "review"
    append_event(review, event(1))
    append_event(review, event(2, "as_read", ""))
    text = (review / "events_KH.csv").read_text(encoding="utf-8")
    assert text.count("schema_version,") == 1
    back = read_events(review)
    assert [e.sequence for e in back] == [1, 2]
    assert back[0] == event(1)
    assert next_sequence(review, "KH") == 3
    assert next_sequence(review, "AB") == 1


def test_event_validation() -> None:
    with pytest.raises(StoreError, match="action"):
        event(1, "delete")
    with pytest.raises(StoreError, match="note"):
        Event("a" * 32, 1, "t", "KH", "11", "k", "exclude")
    with pytest.raises(StoreError, match="reviewer"):
        event(1, reviewer="k h")


def test_event_file_of_another_reviewer_is_refused(tmp_path: Path) -> None:
    review = tmp_path / "review"
    append_event(review, event(1))
    (review / "events_AB.csv").write_bytes((review / "events_KH.csv").read_bytes())
    with pytest.raises(StoreError, match="reviewer"):
        read_events(review)


def test_newer_event_schema_is_refused(tmp_path: Path) -> None:
    review = tmp_path / "review"
    append_event(review, event(1))
    path = review / "events_KH.csv"
    path.write_text(
        path.read_text(encoding="utf-8").replace("\n1,", "\n9,"), encoding="utf-8"
    )
    with pytest.raises(StoreError, match="newer"):
        read_events(review)


def test_sessions_file(tmp_path: Path) -> None:
    review = tmp_path / "review"
    append_session(
        review, "KH", "s1", "2026-11-02T10:00:00+13:00", "2026-11-02T10:30:00+13:00", 12
    )
    rows = read_sessions(review)
    assert rows[0]["answers"] == "12" and rows[0]["reviewer"] == "KH"
    assert (
        read_events(tmp_path / "missing") == []
        and read_sessions(tmp_path / "missing") == []
    )


def test_stamp_json_is_sorted_and_ascii(tmp_path: Path) -> None:
    write_raw(tmp_path, a_store(), fields(), code="x")
    data = json.loads((tmp_path / "stamp.json").read_text(encoding="utf-8"))
    assert data["store_schema_version"] == 1 and data["file_hashes"] == [HASH]
