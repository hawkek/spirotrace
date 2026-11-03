"""review: the keyboard answers, the queue, the service and the local server.

Synthetic records from checks_helpers; the server tests run the pipeline on
the fake reader's two tiny PDFs in tmp_path and talk to a real
ThreadingHTTPServer on a free port of 127.0.0.1.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from checks_helpers import HASH, P, R, cells, run
from test_pipeline import fake_reader, project

from spirotrace import cli
from spirotrace.config import load_settings
from spirotrace.layouts import conditions as cond
from spirotrace.model import ObservationKey
from spirotrace.pipeline import run_project
from spirotrace.resolve import merge_events
from spirotrace.review import (
    AnswerError,
    ReviewError,
    ReviewServer,
    ReviewService,
    build_queue,
    is_gli_input,
    parse_answer,
    raw_open_flags,
    record_sort_key,
)
from spirotrace.store import Event, RawStore, ReadRecord, read_events, read_sessions

LAYOUT = "layout_x"


def key(p=P.FEV1, r=R.PRE, pos=1, page=1) -> ObservationKey:
    return ObservationKey(HASH, page, LAYOUT, p, r, pos)


# --- answers --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "action", "value"),
    [
        ("=", "as_read", ""),
        (" NA ", "not_readable", ""),
        ("empty", "empty", ""),
        ("-", "dash", ""),
        ("struck", "struck", ""),
        ("struck 2.98", "struck", "2.98"),
        ("3.05", "typed", "3.05"),
        ("3,05", "typed", "3,05"),
    ],
)
def test_keyboard_answers_map_to_actions(text: str, action: str, value: str) -> None:
    a = parse_answer(text, key(), has_own_answer=False)
    assert (a.action, a.value, a.note) == (action, value, "")


def test_exclude_needs_a_note_and_withdraw_needs_an_own_answer() -> None:
    a = parse_answer("x  pre and post swapped", key(), has_own_answer=False)
    assert (a.action, a.note) == ("exclude", "pre and post swapped")
    with pytest.raises(AnswerError, match="note"):
        parse_answer("x", key(), has_own_answer=False)
    with pytest.raises(AnswerError, match="withdraw"):
        parse_answer("withdraw", key(), has_own_answer=False)
    assert parse_answer("withdraw", key(), has_own_answer=True).action == "withdraw"
    with pytest.raises(AnswerError, match="type an answer"):
        parse_answer("   ", key(), has_own_answer=False)


def test_typed_values_are_validated_by_kind() -> None:
    with pytest.raises(AnswerError, match="not a number"):
        parse_answer("abc", key(), has_own_answer=False)
    with pytest.raises(AnswerError, match="not a number"):
        parse_answer("struck abc", key(), has_own_answer=False)
    # a ratio in its printed form, a date day first, a category as typed
    assert parse_answer("82", key(P.FEV1_FVC), has_own_answer=False).value == "82"
    date_key = key(P.TEST_DATE, R.MEASURED)
    assert parse_answer("03/11/2026", date_key, has_own_answer=False).action == "typed"
    with pytest.raises(AnswerError, match="date"):
        parse_answer("yesterday", date_key, has_own_answer=False)
    assert parse_answer("Female", key(P.SEX, R.MEASURED), has_own_answer=False).value


# --- the queue ------------------------------------------------------------------------


def ev(seq: int, action: str, value: str = "", reviewer: str = "KH", k=None) -> Event:
    return Event(
        f"{seq:032x}",
        seq,
        f"2026-11-02T10:{seq:02d}:00+13:00",
        reviewer,
        "11",
        (k or key()).to_string(),
        action,
        value,
        note="not this test" if action == "exclude" else "",
    )


SPEC = {
    (P.FEV1, R.PRE): "3.05",
    (P.FVC, R.PRE): "3.70",
    (P.FEV1_FVC, R.PRE): "0.824",
    (P.FEV1, R.Z): "-0.50",
    (P.FVC, R.Z): "x",  # ocr error
    (P.PEF, R.PRE): "15.0",  # outside the typical range, inside the possible: a check
}


def store_of(spec=SPEC, record_id: str = "11") -> RawStore:
    rec = cells(spec, record_id)
    return RawStore(
        records=[ReadRecord(rec.record, dict(rec.observations), list(rec.conditions))],
        flags=run(rec),
        file_names={HASH: f"{record_id}.pdf"},
    )


def test_queue_has_one_item_per_flagged_cell_errors_first() -> None:
    store = store_of()
    q = build_queue(store, raw_open_flags(store), merge_events([]), "KH")
    cells_in_queue = [(it.key.parameter, it.key.column_role, it.severity) for it in q]
    assert (P.FVC, R.Z, "error") == cells_in_queue[0]
    assert all(sev == "check" for _, _, sev in cells_in_queue[1:])
    assert len({it.key for it in q}) == len(q)
    severities = {f["severity"] for it in q for f in it.flags}
    assert severities <= {"error", "check"}  # notes and confirms are never queued
    first = q[0]
    assert first.raw_text == "x" and first.value_state == "unreadable"
    assert {c["role"] for c in first.row} == {"pre"}  # the same row's other cells
    j = first.to_json()
    assert j["key"] == first.key.to_string() and j["has_image"] and not j["answered"]


def test_core_fields_come_first_and_core_only_filters() -> None:
    store = store_of()
    core = ((P.PEF, R.PRE),)
    q = build_queue(store, raw_open_flags(store), merge_events([]), "KH", core)
    assert q[0].core and (q[0].key.parameter, q[0].key.column_role) == core[0]
    assert not q[1].core and q[1].severity == "error"
    only = build_queue(
        store, raw_open_flags(store), merge_events([]), "KH", core, core_only=True
    )
    assert [(it.key.parameter, it.key.column_role) for it in only] == [core[0]]


def test_own_answers_mark_the_item_and_others_are_shown() -> None:
    store = store_of()
    bad = key(P.FVC, R.Z)
    merged = merge_events(
        [ev(1, "typed", "-0.3", k=bad), ev(2, "as_read", reviewer="AB", k=bad)]
    )
    q = build_queue(store, raw_open_flags(store), merged, "KH")
    item = next(it for it in q if it.key == bad)
    assert item.answered and item.mine == {
        "reviewer": "KH",
        "action": "typed",
        "value": "-0.3",
        "note": "",
    }
    assert item.others == [
        {"reviewer": "AB", "action": "as_read", "value": "", "note": ""}
    ]
    other = next(it for it in q if it.key != bad)
    assert not other.answered and other.mine is None


def test_record_level_flags_are_notes_on_the_items() -> None:
    rec = cells(SPEC)
    rec.note(cond.PARSER_CRASHED, "tables")
    store = RawStore(
        records=[ReadRecord(rec.record, dict(rec.observations), list(rec.conditions))],
        flags=run(rec),
    )
    q = build_queue(store, raw_open_flags(store), merge_events([]), "KH")
    assert any(f.record_level for f in store.flags)
    assert q and all(
        any(n.startswith("input.stage_failed") for n in it.record_notes) for it in q
    )


def test_record_order_and_gli_inputs() -> None:
    ids = ["12", "9", "100-2", "100", "9A", "f0a1b2c3d4"]
    assert sorted(ids, key=record_sort_key) == [
        "9",
        "9A",
        "12",
        "100",
        "100-2",
        "f0a1b2c3d4",
    ]
    assert is_gli_input(key(P.FEV1, R.PRE))
    assert is_gli_input(key(P.DLCO, R.MEASURED))
    assert is_gli_input(key(P.AGE, R.MEASURED))
    assert is_gli_input(key(P.FVC, R.POST_Z))
    assert not is_gli_input(key(P.FEV1, R.TRIAL, 2))
    assert not is_gli_input(key(P.PEF, R.PRE))
    assert not is_gli_input(key(P.TLC, R.MEASURED))


# --- the service ------------------------------------------------------------------------


def ran_project(tmp_path: Path) -> tuple[Path, RawStore]:
    from spirotrace.store import read_raw

    folder = project(tmp_path)
    run_project(folder, load_settings(folder), fake_reader)
    return folder, read_raw(folder / "outputs" / "raw")


def test_answer_appends_an_event_and_reruns_the_record(tmp_path: Path) -> None:
    folder, store = ran_project(tmp_path)
    svc = ReviewService(folder, load_settings(folder), store, "KH")
    q = svc.queue()
    assert [it.record_id for it in q] == ["11", "12"]
    assert svc.counts()["open"] == 2
    it = q[0]
    out = svc.answer(
        {
            "record_id": it.record_id,
            "key": it.key_string,
            "answer": "-0.3",
            "shown_at": "2026-11-02T10:00:00+13:00",
            "elapsed_ms": 4200,
        }
    )
    assert out["ok"] and out["action"] == "typed" and out["open"] == 1
    events = read_events(folder / "review")
    assert len(events) == 1
    e = events[0]
    assert (e.action, e.value, e.before_raw, e.reviewer) == ("typed", "-0.3", "x", "KH")
    assert e.open_rules == "ocr.not_a_number" and e.elapsed_ms == 4200
    assert e.shown_at == "2026-11-02T10:00:00+13:00" and e.source == "app"
    assert e.template_id == it.key.template_id
    # the record's error cleared: the item left the queue, record 12 is still there
    assert [i.record_id for i in svc.queue() if not i.answered] == ["12"]
    assert svc.items(show_answered=True)[0]["record_id"] == "11"
    # a bad answer is refused and writes nothing
    with pytest.raises(AnswerError):
        svc.answer({"record_id": "12", "key": q[1].key_string, "answer": "abc"})
    with pytest.raises(ReviewError, match="unknown"):
        svc.answer({"record_id": "99", "key": q[1].key_string, "answer": "="})
    assert len(read_events(folder / "review")) == 1
    closed = svc.close()
    rows = read_sessions(folder / "review")
    assert closed["answers"] == 1 and rows[0]["answers"] == "1"
    assert rows[0]["started"] <= rows[0]["ended"]
    assert svc.close()["answers"] == 1 and len(read_sessions(folder / "review")) == 1


def test_service_starts_from_the_rerun_when_events_exist(tmp_path: Path) -> None:
    folder, store = ran_project(tmp_path)
    svc = ReviewService(folder, load_settings(folder), store, "KH")
    it = svc.queue()[0]
    svc.answer({"record_id": it.record_id, "key": it.key_string, "answer": "-0.3"})
    again = ReviewService(folder, load_settings(folder), store, "AB")
    # the other reviewer sees record 11's error gone and 12's still open
    assert [i.record_id for i in again.queue()] == ["12"]
    assert again.counts()["answers"] == 0


def test_withdraw_reopens_the_item(tmp_path: Path) -> None:
    folder, store = ran_project(tmp_path)
    svc = ReviewService(folder, load_settings(folder), store, "KH")
    it = svc.queue()[0]
    svc.answer({"record_id": it.record_id, "key": it.key_string, "answer": "-0.3"})
    assert svc.counts()["open"] == 1
    svc.answer({"record_id": it.record_id, "key": it.key_string, "answer": "withdraw"})
    assert svc.counts()["open"] == 2
    assert [e.action for e in read_events(folder / "review")] == ["typed", "withdraw"]


def test_snippet_and_page_are_png_with_the_cell_boxed(tmp_path: Path) -> None:
    folder, store = ran_project(tmp_path)
    svc = ReviewService(folder, load_settings(folder), store, "KH")
    it = svc.queue()[0]
    snippet = svc.snippet_png(it.record_id, it.key_string)
    page = svc.page_png(it.record_id, it.key_string)
    assert snippet[:4] == b"\x89PNG" and page[:4] == b"\x89PNG"
    assert len(page) > len(snippet)
    # the page is rendered once and kept for the next cell of the same page
    svc.snippet_png(it.record_id, it.key_string)
    assert len(svc._pages) == 1
    with pytest.raises(ReviewError):
        svc.snippet_png(it.record_id, "not:a:key")
    other = svc.queue()[1]
    (folder / "reports" / store.file_names[other.key.file_hash]).unlink()
    with pytest.raises(ReviewError, match="reports/"):
        svc.snippet_png(other.record_id, other.key_string)


# --- the server -------------------------------------------------------------------------


class Client:
    def __init__(self, url: str) -> None:
        self.url = url.rstrip("/")

    def get(self, path: str, host: str | None = None):
        req = urllib.request.Request(self.url + path)
        if host:
            req.add_header("Host", host)
        return urllib.request.urlopen(req, timeout=10)

    def json(self, path: str) -> dict:
        with self.get(path) as r:
            return json.loads(r.read().decode("utf-8"))

    def post(self, path: str, payload: dict | None = None) -> tuple[int, dict]:
        body = json.dumps(payload or {}).encode("utf-8")
        req = urllib.request.Request(
            self.url + path,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))


@pytest.fixture
def served(tmp_path: Path):
    folder, store = ran_project(tmp_path)
    svc = ReviewService(folder, load_settings(folder), store, "KH")
    server = ReviewServer(svc, 0)
    done: dict = {}

    def run_server() -> None:
        done.update(server.serve(open_browser=False))

    t = threading.Thread(target=run_server, daemon=True)
    t.start()
    yield folder, svc, server, Client(server.url), done, t
    if t.is_alive():
        server.stop()
        t.join(5)


def test_server_serves_page_items_images_and_answers(served) -> None:
    folder, _svc, _server, c, done, t = served
    with c.get("/") as r:
        html = r.read().decode("utf-8")
    assert "spirotrace review" in html and "/answer" in html
    items = c.json("/items")["items"]
    assert len(items) == 2 and items[0]["record_id"] == "11"
    status = c.json("/status")
    assert status["reviewer"] == "KH" and status["open"] == 2
    with c.get(f"/snippet?record={items[0]['record_id']}&key={items[0]['key']}") as r:
        assert r.headers["Content-Type"] == "image/png" and r.read()[:4] == b"\x89PNG"
    with c.get(f"/page?record={items[0]['record_id']}&key={items[0]['key']}") as r:
        assert r.read()[:4] == b"\x89PNG"
    code, out = c.post(
        "/answer",
        {
            "record_id": items[0]["record_id"],
            "key": items[0]["key"],
            "answer": "-0.3",
            "shown_at": "2026-11-02T10:00:00+13:00",
            "elapsed_ms": 1500,
        },
    )
    assert code == 200 and out["ok"] and out["open"] == 1
    assert len(c.json("/items")["items"]) == 1
    assert len(c.json("/items?answered=1")["items"]) == 2
    code, out = c.post(
        "/answer", {"record_id": "12", "key": items[1]["key"], "answer": "abc"}
    )
    assert code == 400 and "not a number" in out["error"]
    code, out = c.post("/answer", {"record_id": "12", "key": "bad", "answer": "="})
    assert code == 400 and "key" in out["error"]
    code, out = c.post("/nothing")
    assert code == 404
    with pytest.raises(urllib.error.HTTPError) as exc:
        c.get("/nothing")
    assert exc.value.code == 404
    # requests from another host name are refused
    with pytest.raises(urllib.error.HTTPError) as exc:
        c.get("/items", host="evil.example")
    assert exc.value.code == 403
    code, out = c.post("/quit")
    assert code == 200 and out["ok"]
    t.join(10)
    assert not t.is_alive() and done["answers"] == 1
    assert read_sessions(folder / "review")[0]["answers"] == "1"
    assert len(read_events(folder / "review")) == 1


def test_cli_review_runs_headless_and_refuses_without_a_store(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    folder = tmp_path / "empty"
    assert cli.main(["init", str(folder)]) == 0
    assert cli.main(["review", "--project", str(folder), "--reviewer", "KH"]) == 2
    assert "run `spirotrace run` first" in capsys.readouterr().out

    folder, _store = ran_project(tmp_path / "study")
    assert cli.main(["review", "--project", str(folder), "--reviewer", "k h"]) == 2
    assert (
        cli.main(
            ["review", "--project", str(folder), "--reviewer", "KH", "--core-only"]
        )
        == 2
    )
    assert "CORE_FIELDS" in capsys.readouterr().out

    # a headless session: the server is stopped from another thread once it is up
    from spirotrace.review import server as server_mod

    started: dict = {}
    real_serve = server_mod.ReviewServer.serve

    def serve_and_stop(self, *, open_browser=True):
        started["url"] = self.url
        threading.Timer(0.3, self.stop).start()
        return real_serve(self, open_browser=open_browser)

    monkeypatch.setattr(server_mod.ReviewServer, "serve", serve_and_stop)
    assert (
        cli.main(
            ["review", "--project", str(folder), "--reviewer", "KH", "--no-browser"]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "queue: 2 items" in out and started["url"].startswith("http://127.0.0.1:")
    assert "session ended: 0 answers" in out
    # no record id on the console; the address carries a random port, so it goes first
    assert "11" not in out.replace(started["url"], "").replace("spirotrace 0", "")
    assert len(read_sessions(folder / "review")) == 1
