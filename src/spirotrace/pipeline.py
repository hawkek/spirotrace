"""The run: PDFs to the extraction store (stages 1 to 5), and export's first half
(resolve and derive) to ``outputs/``.

``run_project`` follows flow 2 of the runtime sequences: settings, the reader,
each file through the words cache and the reader (one bad file gets an
input-layer error and the run continues), the image stage when ``image.checks``
is on, the second reading, the rules with one bridge call, the cohort pass, the store write and counts to the console. ``export_project``
reads the raw store and the events, resolves, reruns the rules over the
resolved values (cohort pass included), derives, runs the post-derive rules
and writes checkpoint 4. Console output is counts only.
"""

from __future__ import annotations

import importlib
import sys
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Protocol

from spirotrace.checks import CheckRun, Flag, check_records
from spirotrace.checks.rules_image import image_thresholds
from spirotrace.config import Settings
from spirotrace.derive import DeriveRun, derive_records
from spirotrace.export import ExportFiles, export_dataset
from spirotrace.ingest import TesseractTool, file_hash_of, tesseract_tool
from spirotrace.ingest.image_stage import ImageStats, image_check_records
from spirotrace.ingest.second_ocr import (
    SecondOcrCache,
    SecondOcrStats,
    second_read_records,
)
from spirotrace.layouts import (
    ReadingCondition,
    base_record_id,
    subject_id_from_stem,
    unique_record_id,
)
from spirotrace.layouts import conditions as cond
from spirotrace.model import Page, ReadMethod, Record, TextSource
from spirotrace.privacy import SHARE_DIR
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
    read_sessions,
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


def check_tools(settings: Settings) -> TesseractTool | None:
    """Stop before ingest when a setting needs Tesseract and there is none (decided
    14 Oct 2026); returns the probed tool when one is needed and found."""
    if not (settings.ocr.second_ocr or settings.ocr.missing_pages):
        return None
    tool = tesseract_tool(settings.tools.tesseract)
    if tool is None:
        raise PipelineError(
            "ocr.second_ocr or ocr.missing_pages is true but Tesseract was not found: set "
            "tools.tesseract to its full path, or turn the setting off"
        )
    return tool


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
    second_ocr: SecondOcrStats | None = None
    image: ImageStats | None = None

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
        if self.image is not None:
            i = self.image
            out.append(
                f"image checks: cells {i.cells}, struck {i.struck}, "
                f"ink in empty cells {i.ink_in_empty}, blank empty cells {i.blank_empty}, "
                f"red {i.red}"
            )
        if self.second_ocr is not None:
            s = self.second_ocr
            out.append(
                f"second OCR: cells {s.cells} (from cache {s.cached}, read {s.read}), "
                f"records failed {s.failed_records}"
            )
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
    tool = check_tools(settings)
    reader = reader or load_reader(settings, project_dir)
    ocr_stats = SecondOcrStats() if settings.ocr.second_ocr else None
    image_stats = ImageStats() if settings.image.checks else None
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
        own = [
            ReadRecord(r.record, dict(r.observations), list(r.conditions))
            for r in read.records
        ]
        mark_ocr_pages(own, read.pages)
        if image_stats is not None:
            image_stats.add(
                image_check_records(
                    own, read.pages, path.read_bytes(), image_thresholds()
                )
            )
        if ocr_stats is not None and tool is not None:
            ocr_stats.add(
                second_read_records(
                    own,
                    read.pages,
                    path.read_bytes(),
                    tool,
                    SecondOcrCache(cache_dir, read.file_hash),
                )
            )
        store.records.extend(own)
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
        tesseract_version=tool.version if tool is not None else "",
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
        second_ocr=ocr_stats,
        image=image_stats,
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
    files: ExportFiles | None = None

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
        if self.files is not None:
            out.append(
                f"files written: {len(self.files.outputs)} in outputs, "
                f"{len(self.files.shared)} in share (guard masked {self.files.masked_cells} tokens)"
            )
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
    files = export_dataset(
        out_dir,
        project_dir / SHARE_DIR,
        store,
        resolved,
        derived,
        events,
        read_sessions(project_dir / REVIEW_DIR, notices.append),
        rspiro_version=derived.rspiro_version,
        tesseract_version=str(store.stamp.get("tesseract_version", "")),
        notice=notices.append,
    )
    result = ExportResult(resolved, derived, out_dir, notices, files)
    for line in result.summary_lines():
        say(line)
    return result


def mark_ocr_pages(records: Sequence[ReadRecord], pages: Sequence[Page]) -> int:
    """Observations read from a page whose words came from Tesseract (missing text
    layer) get read method ``ocr``; the reader itself cannot tell. Returns the count.
    The per-cell confidence is not carried (the readers keep no words per cell).
    """
    ocr_pages = {p.page for p in pages if p.text_source is TextSource.OCR}
    if not ocr_pages:
        return 0
    n = 0
    for rec in records:
        for key, obs in list(rec.observations.items()):
            if key.page in ocr_pages and obs.read_method is ReadMethod.TEXT_LAYER:
                rec.observations[key] = replace(obs, read_method=ReadMethod.OCR)
                n += 1
    return n


def flags_by_rule(flags: Sequence[Flag]) -> dict[str, int]:
    return dict(Counter(f.rule_id for f in flags))
