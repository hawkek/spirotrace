"""The local review app: one page, served on 127.0.0.1 only.

``spirotrace review`` builds the queue from ``outputs/raw/`` and the events so
far, serves one HTML page with inline script, renders the flagged cell's
snippet on demand from the report's PDF, validates each answer server-side,
appends it to the reviewer's event file and reruns the record's rules so
neighbouring items clear or appear at once. Timing is recorded per answer
(``shown_at``, ``elapsed_ms``) and per session (wall-clock start and end in
``sessions_<initials>.csv``). Console output is counts only; the server never
logs a request line (they carry record ids).

Rerun scope (G2 answer 7): the record rules on every answer; the gli rules
only when the answered key is a gli input and a bridge is configured; the
cohort rules at export. Flags of a layer not rerun are kept from before.
"""

from __future__ import annotations

import io
import json
import threading
import uuid
import webbrowser
from collections import OrderedDict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from PIL import Image, ImageDraw

from spirotrace import __version__
from spirotrace.checks import Flag
from spirotrace.config import Settings
from spirotrace.ingest import render_page
from spirotrace.ingest.second_ocr import crop_box
from spirotrace.model import ModelError, ObservationKey, Page
from spirotrace.resolve import merge_events, resolve_records
from spirotrace.rspiro import RspiroBridge
from spirotrace.store import (
    Event,
    RawStore,
    append_event,
    append_session,
    new_event_id,
    next_sequence,
    now_iso,
    read_events,
)

from .answers import AnswerError, parse_answer
from .queue import (
    CoreField,
    QueueItem,
    build_queue,
    is_gli_input,
    raw_open_flags,
    shown_value,
)

REPORTS_DIR = "reports"
REVIEW_DIR = "review"
SNIPPET_DPI = 300
SNIPPET_MARGIN = 1.5
"""Margin around the cell, in cell heights."""
PAGE_VIEW_WIDTH = 1400
PAGE_CACHE = 4
"""Rendered pages kept in memory (the last few looked at)."""
BOX_COLOUR = (220, 40, 40)
ALLOWED_HOSTS = ("127.0.0.1", "localhost", "[::1]")

Console = Callable[[str], None]


class ReviewError(RuntimeError):
    """A request the service refuses (shown to the reviewer, never fatal)."""


@dataclass(slots=True)
class ReviewService:
    """The queue's state for one server session; thread-safe through one lock."""

    project_dir: Path
    settings: Settings
    store: RawStore
    reviewer: str
    bridge: RspiroBridge | None = None
    core_fields: tuple[CoreField, ...] = ()
    core_only: bool = False
    render: Callable[[bytes, int, int, int], Image.Image] = render_page
    events: list[Event] = field(default_factory=list)
    open_flags: dict[str, list[Flag]] = field(default_factory=dict)
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    started: str = field(default_factory=now_iso)
    answers: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _render_lock: threading.Lock = field(default_factory=threading.Lock)
    _in_flight: set[str] = field(default_factory=set)
    _pages: OrderedDict[tuple[str, int], Image.Image] = field(
        default_factory=OrderedDict
    )
    _page_rows: dict[tuple[str, int], Page] = field(default_factory=dict)
    _closed: bool = False

    def __post_init__(self) -> None:
        self._page_rows = {(p.file_hash, p.page): p for p in self.store.pages}
        self.events = read_events(self.project_dir / REVIEW_DIR)
        merged = merge_events(self.events)
        if merged.count == 0:
            self.open_flags = raw_open_flags(self.store)
        else:
            # answers from earlier sessions: the queue starts from the rerun
            resolved = resolve_records(
                self.store, merged, self.settings, bridge=self.bridge
            )
            self.open_flags = {
                r.record_id: resolved.open_flags(r.record_id)
                for r in self.store.records
            }
            if self.bridge is None:
                # gli flags cannot be rerun without R: keep the raw run's
                raw = raw_open_flags(self.store)
                for rid, flags in self.open_flags.items():
                    flags.extend(f for f in raw.get(rid, ()) if f.layer == "gli")

    # --- the queue ------------------------------------------------------------------

    def queue(self) -> list[QueueItem]:
        with self._lock:
            return build_queue(
                self.store,
                self.open_flags,
                merge_events(self.events),
                self.reviewer,
                self.core_fields,
                core_only=self.core_only,
            )

    def items(self, *, show_answered: bool = False) -> list[dict[str, Any]]:
        return [it.to_json() for it in self.queue() if show_answered or not it.answered]

    def counts(self) -> dict[str, int]:
        q = self.queue()
        return {
            "items": len(q),
            "open": sum(1 for it in q if not it.answered),
            "core": sum(1 for it in q if it.core),
            "records": len({it.record_id for it in q}),
            "answers": self.answers,
        }

    def status(self) -> dict[str, Any]:
        return {
            "reviewer": self.reviewer,
            "session_id": self.session_id,
            "started": self.started,
            "core_only": self.core_only,
            "has_core_fields": bool(self.core_fields),
            **self.counts(),
        }

    # --- answers --------------------------------------------------------------------

    def _lookup(self, record_id: str, key_string: str) -> tuple[Any, ObservationKey]:
        rec = self.store.by_id().get(record_id)
        if rec is None:
            raise ReviewError("unknown record")
        try:
            key = ObservationKey.from_string(key_string)
        except (ModelError, ValueError) as exc:
            raise ReviewError(f"bad key: {exc}") from exc
        if key not in rec.observations:
            raise ReviewError("unknown cell for this record")
        return rec, key

    def answer(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Validate, append the event, rerun the record; the new counts come back."""
        record_id = str(payload.get("record_id", ""))
        key_string = str(payload.get("key", ""))
        text = str(payload.get("answer", ""))
        shown_at = str(payload.get("shown_at", ""))
        elapsed = payload.get("elapsed_ms")
        elapsed_ms = int(elapsed) if isinstance(elapsed, (int, float)) else None
        rec, key = self._lookup(record_id, key_string)
        obs = rec.observations[key]
        with self._lock:
            if key_string in self._in_flight:
                raise ReviewError("that cell is being saved; wait a moment")
            self._in_flight.add(key_string)
        try:
            merged = merge_events(self.events)
            mine = merged.latest.get(key_string, {}).get(self.reviewer)
            answer = parse_answer(text, key, has_own_answer=mine is not None)
            open_rules = " ".join(
                sorted(
                    {
                        f.rule_id
                        for f in self.open_flags.get(record_id, ())
                        if key in f.keys
                    }
                )
            )
            review_dir = self.project_dir / REVIEW_DIR
            event = Event(
                new_event_id(),
                next_sequence(review_dir, self.reviewer),
                now_iso(),
                self.reviewer,
                record_id,
                key_string,
                answer.action,
                answer.value,
                before_raw=obs.raw_text,
                before_value=shown_value(obs),
                note=answer.note,
                open_rules=open_rules,
                shown_at=shown_at,
                elapsed_ms=elapsed_ms,
                source="app",
                tool_version=__version__,
                template_id=key.template_id,
                template_version=str(obs.template_version),
            )
            append_event(review_dir, event)
            with self._lock:
                self.events.append(event)
                self.answers += 1
            self._rerun(record_id, key)
        finally:
            with self._lock:
                self._in_flight.discard(key_string)
        return {"ok": True, "action": answer.action, **self.counts()}

    def _rerun(self, record_id: str, key: ObservationKey) -> None:
        """The record's rules over its resolved values; layers not rerun are kept."""
        bridge = self.bridge if is_gli_input(key) else None
        kept_layers = {"cohort"} | (set() if bridge is not None else {"gli"})
        with self._lock:
            merged = merge_events(self.events)
            previous = list(self.open_flags.get(record_id, ()))
        resolved = resolve_records(
            self.store, merged, self.settings, bridge=bridge, record_ids=[record_id]
        )
        fresh = [
            f for f in resolved.open_flags(record_id) if f.layer not in kept_layers
        ]
        kept = [f for f in previous if f.layer in kept_layers]
        with self._lock:
            self.open_flags[record_id] = fresh + kept

    # --- images ---------------------------------------------------------------------

    def _page_image(self, file_hash: str, page_no: int) -> tuple[Image.Image, Page]:
        page = self._page_rows.get((file_hash, page_no))
        if page is None:
            raise ReviewError("no page row for this cell")
        name = self.store.file_names.get(file_hash)
        if not name:
            raise ReviewError("the report file name is not in the store")
        path = self.project_dir / REPORTS_DIR / name
        with self._render_lock:
            cached = self._pages.get((file_hash, page_no))
            if cached is not None:
                self._pages.move_to_end((file_hash, page_no))
                return cached, page
            if not path.is_file():
                raise ReviewError("the report is not in reports/ any more")
            img = self.render(
                path.read_bytes(), page_no - 1, SNIPPET_DPI, page.rotation
            ).convert("RGB")
            self._pages[(file_hash, page_no)] = img
            while len(self._pages) > PAGE_CACHE:
                self._pages.popitem(last=False)
            return img, page

    def _cell_box(
        self, record_id: str, key_string: str
    ) -> tuple[Image.Image, tuple[int, int, int, int]]:
        rec, key = self._lookup(record_id, key_string)
        obs = rec.observations[key]
        if obs.bbox is None:
            raise ReviewError("this cell has no box on the page")
        img, page = self._page_image(key.file_hash, key.page)
        return img, crop_box(obs, page, img.size, margin_x=0, margin_y=0)

    def snippet_png(self, record_id: str, key_string: str) -> bytes:
        """The cell with a margin of 1.5 cell heights around it, boxed."""
        img, (x0, y0, x1, y1) = self._cell_box(record_id, key_string)
        m = int(max(8, (y1 - y0) * SNIPPET_MARGIN))
        w, h = img.size
        crop = img.crop(
            (max(0, x0 - m), max(0, y0 - m), min(w, x1 + m), min(h, y1 + m))
        )
        draw = ImageDraw.Draw(crop)
        ox, oy = x0 - max(0, x0 - m), y0 - max(0, y0 - m)
        draw.rectangle(
            (ox - 2, oy - 2, ox + (x1 - x0) + 2, oy + (y1 - y0) + 2),
            outline=BOX_COLOUR,
            width=3,
        )
        return _png(crop)

    def page_png(self, record_id: str, key_string: str) -> bytes:
        """The whole page, scaled down, with the cell boxed."""
        img, (x0, y0, x1, y1) = self._cell_box(record_id, key_string)
        page = img.copy()
        ImageDraw.Draw(page).rectangle(
            (x0 - 6, y0 - 6, x1 + 6, y1 + 6), outline=BOX_COLOUR, width=6
        )
        w, h = page.size
        if w > PAGE_VIEW_WIDTH:
            page = page.resize((PAGE_VIEW_WIDTH, int(h * PAGE_VIEW_WIDTH / w)))
        return _png(page)

    # --- the session ----------------------------------------------------------------

    def close(self) -> dict[str, Any]:
        """Append the session row once; counts for the console."""
        with self._lock:
            if self._closed:
                return {"answers": self.answers}
            self._closed = True
        ended = now_iso()
        append_session(
            self.project_dir / REVIEW_DIR,
            self.reviewer,
            self.session_id,
            self.started,
            ended,
            self.answers,
        )
        return {"answers": self.answers, "started": self.started, "ended": ended}


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def page_html() -> str:
    return (
        resources.files(__package__).joinpath("page.html").read_text(encoding="utf-8")
    )


# --- HTTP -----------------------------------------------------------------------------


def _handler_for(service: ReviewService, stop: Callable[[], None]) -> type:
    class Handler(BaseHTTPRequestHandler):
        server_version = "spirotrace"
        sys_version = ""

        def log_message(self, format: str, *args: Any) -> None:
            # request lines carry record ids: nothing is ever logged
            return None

        # -- helpers --

        def _host_ok(self) -> bool:
            # the old tool's rule: only a browser on this machine is answered
            host = self.headers.get("Host") or ""
            if host.startswith("["):
                name = host[: host.find("]") + 1]
            else:
                name = host.split(":", 1)[0]
            return name in ALLOWED_HOSTS

        def _send(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
            self._send(
                status,
                json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                "application/json; charset=utf-8",
            )

        def _query(self) -> dict[str, str]:
            q = parse_qs(urlsplit(self.path).query)
            return {k: v[-1] for k, v in q.items()}

        # -- routes --

        def do_GET(self) -> None:
            if not self._host_ok():
                self._json(HTTPStatus.FORBIDDEN, {"error": "local requests only"})
                return
            route = urlsplit(self.path).path
            q = self._query()
            try:
                if route == "/":
                    self._send(
                        HTTPStatus.OK,
                        page_html().encode("utf-8"),
                        "text/html; charset=utf-8",
                    )
                elif route == "/items":
                    self._json(
                        HTTPStatus.OK,
                        {
                            "items": service.items(
                                show_answered=q.get("answered") == "1"
                            )
                        },
                    )
                elif route == "/status":
                    self._json(HTTPStatus.OK, service.status())
                elif route in ("/snippet", "/page"):
                    make = (
                        service.snippet_png if route == "/snippet" else service.page_png
                    )
                    png = make(q.get("record", ""), q.get("key", ""))
                    self._send(HTTPStatus.OK, png, "image/png")
                else:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "no such page"})
            except (ReviewError, AnswerError) as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

        def do_POST(self) -> None:
            if not self._host_ok():
                self._json(HTTPStatus.FORBIDDEN, {"error": "local requests only"})
                return
            route = urlsplit(self.path).path
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            try:
                payload = json.loads(raw.decode("utf-8")) if raw else {}
                if not isinstance(payload, dict):
                    raise ReviewError("the body must be a JSON object")
                if route == "/answer":
                    self._json(HTTPStatus.OK, service.answer(payload))
                elif route == "/quit":
                    self._json(HTTPStatus.OK, {"ok": True})
                    threading.Thread(target=stop, daemon=True).start()
                else:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "no such action"})
            except (ReviewError, AnswerError) as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            except (ValueError, UnicodeDecodeError) as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": f"bad request: {exc}"})

    return Handler


class ReviewServer:
    """The HTTP server around a :class:`ReviewService`; ``serve`` blocks."""

    def __init__(self, service: ReviewService, port: int = 0) -> None:
        self.service = service
        self.httpd = ThreadingHTTPServer(
            ("127.0.0.1", port), _handler_for(service, self.stop)
        )
        self.httpd.daemon_threads = True

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.httpd.server_address[1]}/"

    def stop(self) -> None:
        self.httpd.shutdown()

    def serve(self, *, open_browser: bool = True) -> dict[str, Any]:
        """Serve until stopped (the page's Finish button or Ctrl+C); the session
        row is written on the way out."""
        if open_browser:
            webbrowser.open(self.url)
        try:
            self.httpd.serve_forever(poll_interval=0.2)
        except KeyboardInterrupt:
            pass
        finally:
            self.httpd.server_close()
        return self.service.close()


def serve_review(
    project_dir: Path,
    settings: Settings,
    store: RawStore,
    reviewer: str,
    *,
    port: int = 0,
    open_browser: bool = True,
    core_fields: Iterable[CoreField] = (),
    core_only: bool = False,
    bridge: RspiroBridge | None = None,
    console: Console | None = None,
) -> dict[str, Any]:
    """``spirotrace review``: build the service, print counts, serve, close."""
    say = console or (lambda _m: None)
    service = ReviewService(
        project_dir,
        settings,
        store,
        reviewer,
        bridge=bridge,
        core_fields=tuple(core_fields),
        core_only=core_only,
    )
    server = ReviewServer(service, port)
    c = service.counts()
    say(
        f"queue: {c['items']} items ({c['open']} open for this reviewer, "
        f"{c['core']} core) over {c['records']} records"
    )
    say(f"review app: {server.url} (Finish in the page, or Ctrl+C, ends the session)")
    result = server.serve(open_browser=open_browser)
    say(f"session ended: {result['answers']} answers")
    return result


def summary_of(sessions: Sequence[dict[str, str]]) -> dict[str, int]:
    """Counts for the console from session rows (never initials)."""
    return {
        "sessions": len(sessions),
        "answers": sum(int(r.get("answers") or 0) for r in sessions),
    }
