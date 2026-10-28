"""The run: PDFs to the extraction store (stages 1 to 5), and export's first half
(resolve and derive) to ``outputs/``.

``run_project`` follows flow 2 of the runtime sequences: settings, the reader,
each file through the words cache and the reader (one bad file gets an
input-layer error and the run continues), the rules with one bridge call, the
cohort pass, the store write and counts to the console. ``export_project``
reads the raw store and the events, resolves, reruns the rules over the
resolved values (cohort pass included), derives, runs the post-derive rules
and writes checkpoint 4. Console output is counts only.
"""

from __future__ import annotations

import importlib
import shutil
import sys
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from spirotrace.checks import CheckRun, Flag, check_records
from spirotrace.config import Settings
from spirotrace.derive import DeriveRun, derive_records
from spirotrace.ingest import file_hash_of
from spirotrace.layouts import (
    ReadingCondition,
    base_record_id,
    subject_id_from_stem,
    unique_record_id,
)
from spirotrace.layouts import conditions as cond
from spirotrace.model import Page, Record
from spirotrace.resolve import Resolved, merge_events, resolve_records
from spirotrace.rspiro import RspiroBridge
from spirotrace.store import (
    RAW_DIR,
    RawStore,
    ReadRecord,
    StoreError,
    code_version,
    raw_stamp_fields,
    read_events,
    read_raw,
    read_stamp,
    stamp_matches,
    write_raw,
)
from spirotrace.store.outputs import outputs_stamp_fields, write_outputs

REPORTS_DIR = "reports"
CACHE_DIR = "cache"
REVIEW_DIR = "review"
OUTPUTS_DIR = "outputs"
RUNS_DIR = "runs"
UNRECOGNISED_LAYOUT = "unrecognised"

Console = Callable[[str], None]


class PipelineError(RuntimeError):
    """The run cannot start: a setting asks for something not available."""


class FileReadLike(Protocol):
    """What a reader returns for one PDF."""

    @property
    def file_hash(self) -> str: ...
    @property
    def pages(self) -> Sequence[Page]: ...
    @property
    def records(self) -> Sequence[Any]: ...


Reader = Callable[..., FileReadLike]
"""``reader(path, settings, used_ids, cache_dir=...)``."""


def output_folder(project_dir: Path, profile: str | None) -> Path:
    """``outputs/`` for the base settings, ``runs/<name>/`` for a profile."""
    return (
        project_dir / OUTPUTS_DIR
        if profile is None
        else project_dir / RUNS_DIR / profile
    )


def load_reader(settings: Settings, project_dir: Path) -> Reader:
    """Import the reader named by ``templates.reader``.

    The folders in ``templates.dirs`` go on ``sys.path`` first (relative to the
    project folder, or absolute). An empty key means the packaged reader, which
    does not exist yet and is refused with a message naming the key.
    """
    spec = settings.templates.reader
    if not spec:
        raise PipelineError(
            "no layout reader: the package ships none yet; set [templates] reader = "
            '"package.module:function" in spiro.toml (and its folder in templates.dirs)'
        )
    for d in settings.templates.dirs:
        folder = Path(d)
        if not folder.is_absolute():
            folder = project_dir / folder
        s = str(folder.resolve())
        if s not in sys.path:
            sys.path.insert(0, s)
    module_name, sep, func_name = spec.partition(":")
    if not sep or not module_name or not func_name:
        raise PipelineError(
            f"templates.reader must be package.module:function, got {spec!r}"
        )
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise PipelineError(f"templates.reader {spec!r}: {exc}") from exc
    fn = getattr(module, func_name, None)
    if not callable(fn):
        raise PipelineError(f"templates.reader {spec!r}: no function {func_name!r}")
    return fn


def find_tesseract(configured: str) -> str | None:
    if configured:
        return configured if Path(configured).is_file() else None
    found = shutil.which("tesseract")
    if found:
        return found
    default = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
    return str(default) if default.is_file() else None


def check_tools(settings: Settings) -> None:
    """Refuse a run that asks for a stage not available (plan: stop before ingest)."""
    if settings.ocr.second_ocr:
        raise PipelineError(
            "ocr.second_ocr = true is not supported until the second reading is built "
            "(A4); set it to false to run"
        )
    if settings.ocr.missing_pages:
        raise PipelineError(
            "ocr.missing_pages = true is not supported until the second reading is built "
            "(A4); set it to false to run"
        )


def pdf_files(folder: Path) -> list[Path]:
    """PDFs directly in ``folder`` (case-insensitive suffix, sorted)."""
    if not folder.is_dir():
        return []
    return sorted(
        (p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"),
        key=lambda p: (p.name.lower(), p.name),
    )


def failed_record(
    path: Path, settings: Settings, used_ids: set[str], why: str
) -> ReadRecord:
    """A record for a PDF that could not be read: one input-layer error, nothing else."""
    try:
        data = path.read_bytes()
    except OSError:
        data = path.name.encode("utf-8")
    file_hash = file_hash_of(data)
    subject_id = subject_id_from_stem(path.stem, settings.subject_id.pattern)
    record_id = unique_record_id(base_record_id(subject_id, file_hash), used_ids)
    record = Record(record_id, file_hash, UNRECOGNISED_LAYOUT, subject_id, (1,))
    rec = ReadRecord(record)
    rec.conditions.append(
        ReadingCondition(record_id, None, None, cond.FILE_UNREADABLE, why)
    )
    return rec


@dataclass(slots=True)
class RunResult:
    store: RawStore
    check: CheckRun
    failed_files: int = 0
    files: int = 0
    raw_dir: Path | None = None
    rebuilt: bool = True
    notices: list[str] = field(default_factory=list)

    def summary_lines(self) -> list[str]:
        """Counts only: never a record id, a value or a file name."""
        layouts = Counter(r.record.layout for r in self.store.records)
        out = [
            f"files: {self.files} ({self.failed_files} could not be read)",
            f"records: {len(self.store.records)}",
            *(f"  {k}: {n}" for k, n in sorted(layouts.items())),
            f"observations: {sum(len(r.observations) for r in self.store.records)}",
            "flags by layer and severity:",
            *(
                f"  {layer:12s} {sev:8s} {n:5d}"
                for (layer, sev), n in sorted(self.check.counts().items())
            ),
        ]
        if self.check.rules_not_run:
            out.append(
                f"rules not run ({len(self.check.rules_not_run)}): {self.check.not_run_reason}"
            )
        else:
            out.append(f"gli subjects sent to rspiro: {self.check.gli_subjects}")
        out.extend(self.notices)
        return out


def run_project(
    project_dir: Path,
    settings: Settings,
    reader: Reader | None = None,
    *,
    profile: str | None = None,
    bridge: RspiroBridge | None = None,
    console: Console | None = None,
) -> RunResult:
    """Stages 1 to 5 over every PDF in ``reports/``; writes ``<outputs>/raw/``."""
    say = console or (lambda _m: None)
    check_tools(settings)
    reader = reader or load_reader(settings, project_dir)
    code = code_version()
    cache_dir = project_dir / CACHE_DIR
    used_ids: set[str] = set()
    store = RawStore()
    files = pdf_files(project_dir / REPORTS_DIR)
    failed = 0
    for path in files:
        try:
            read = reader(path, settings, used_ids, cache_dir=cache_dir)
        except Exception as exc:  # noqa: BLE001 - one bad file must not stop the run
            failed += 1
            rec = failed_record(path, settings, used_ids, f"{type(exc).__name__}")
            store.records.append(rec)
            store.file_names[rec.record.file_hash] = path.name
            continue
        store.file_names[read.file_hash] = path.name
        store.pages.extend(read.pages)
        for r in read.records:
            store.records.append(
                ReadRecord(r.record, dict(r.observations), list(r.conditions))
            )
    if bridge is None:
        bridge = RspiroBridge.from_settings_path(settings.tools.rscript)
    check = check_records(store.records, settings, bridge=bridge)
    store.flags = list(check.flags)
    templates: dict[str, int] = {}
    for r in store.records:
        for o in r.observations.values():
            templates[o.key.template_id] = max(
                templates.get(o.key.template_id, 0), o.template_version
            )
    fields = raw_stamp_fields(
        settings.settings_hash,
        settings.templates.reader,
        templates,
        store.file_names,
        second_ocr=settings.ocr.second_ocr,
        missing_pages=settings.ocr.missing_pages,
    )
    raw_dir = output_folder(project_dir, profile) / RAW_DIR
    previous = read_stamp(raw_dir)
    notices: list[str] = []
    stamp = write_raw(raw_dir, store, fields, notices.append, code)
    result = RunResult(
        store,
        check,
        failed,
        len(files),
        raw_dir,
        rebuilt=not stamp_matches(previous, stamp),
        notices=notices,
    )
    if previous is not None and result.rebuilt:
        notices.append("raw store rebuilt: the previous stamp differed")
    for line in result.summary_lines():
        say(line)
    return result


@dataclass(slots=True)
class ExportResult:
    resolved: Resolved
    derived: DeriveRun
    outputs_dir: Path
    notices: list[str] = field(default_factory=list)

    def summary_lines(self) -> list[str]:
        statuses = Counter(v.status for v in self.resolved.values.values())
        changes = Counter(f.change for f in self.resolved.flags_resolved)
        out = [
            f"events: {self.resolved.events_count} ({len(self.resolved.orphans)} orphan)",
            f"reviewers: {len(self.resolved.reviewers)}",
            f"reviewer disagreements: {len(self.resolved.disagreements)}",
            "resolved values by status:",
            *(f"  {s:22s} {n:6d}" for s, n in sorted(statuses.items())),
            "flags after review: "
            + ", ".join(f"{c} {n}" for c, n in sorted(changes.items())),
            f"derived rows: {len(self.derived.rows)} ({self.derived.not_computed} not computed)",
            f"post-derive flags: {len(self.derived.flags)}",
        ]
        if self.derived.rspiro_version:
            out.append("rspiro: available")
        elif self.derived.gli_inputs == 0:
            out.append("rspiro: not run (no record had usable GLI inputs)")
        else:
            out.append("rspiro: absent (gli_* and pattern_gli not computed)")
            if self.derived.not_run_reason:
                out.append(f"  {self.derived.not_run_reason}")
        out.extend(self.notices)
        return out


def export_project(
    project_dir: Path,
    settings: Settings,
    *,
    profile: str | None = None,
    bridge: RspiroBridge | None = None,
    console: Console | None = None,
) -> ExportResult:
    """Stages 7 and 8: resolve against the events, derive, write checkpoint 4."""
    say = console or (lambda _m: None)
    out_dir = output_folder(project_dir, profile)
    raw_dir = out_dir / RAW_DIR
    notices: list[str] = []
    try:
        store = read_raw(raw_dir, notices.append)
    except StoreError as exc:
        raise PipelineError(
            f"no raw store to export: {exc}; run `spirotrace run` first"
        ) from exc
    events = read_events(project_dir / REVIEW_DIR, notices.append)
    merged = merge_events(events)
    if bridge is None:
        bridge = RspiroBridge.from_settings_path(settings.tools.rscript)
    resolved = resolve_records(store, merged, settings, bridge=bridge)
    derived = derive_records(resolved, settings, bridge=bridge)
    fields = outputs_stamp_fields(store.stamp, events, derived.rspiro_version)
    write_outputs(out_dir, resolved, derived, fields, notices.append)
    result = ExportResult(resolved, derived, out_dir, notices)
    for line in result.summary_lines():
        say(line)
    return result


def flags_by_rule(flags: Sequence[Flag]) -> dict[str, int]:
    return dict(Counter(f.rule_id for f in flags))
