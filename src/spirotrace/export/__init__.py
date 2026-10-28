"""Export (stage 9): the dataset views, the data dictionary, the QC report, and the
shareable counts through the export guard.

Everything here is generated from the resolved values and derived rows and
never hand-edited. Files that hold values, free text or record ids carry
``_CONTAINS_DATA``; only :mod:`spirotrace.privacy` writes to ``share/``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from spirotrace.derive import PATTERNS, DeriveRun
from spirotrace.derive.derive import REPORT_PATTERNS
from spirotrace.privacy import (
    PAGE_SUMMARY_FILE,
    QC_SUMMARY_FILE,
    RULE_CATALOGUE_FILE,
    VARIABLE_SUMMARY_FILE,
    base_vocabulary,
    write_shareable_table,
    write_shareable_text,
)
from spirotrace.resolve import Resolved
from spirotrace.store import Event, Notice, RawStore, Row, write_bytes, write_rows

from .dataset import (
    DATASET_WIDE_FILE,
    FREE_TEXT_FILE,
    STATUS_LONG_FILE,
    VALUES_LONG_FILE,
    WORKBOOK_FILE,
    Dataset,
    build_dataset,
    column_name,
    write_dataset_files,
    write_workbook,
)
from .dictionary import (
    DICTIONARY_COLUMNS,
    DICTIONARY_FILE,
    RULE_CATALOGUE_COLUMNS,
    dictionary_rows,
    rule_catalogue_rows,
    rule_rationales,
    rule_severity_labels,
)
from .qc_report import (
    FIXED_WORDING,
    QC_REPORT_FILE,
    QcTables,
    build_tables,
    render_html,
    strip_box_svg,
    summary_lines,
)

__all__ = [
    "DATASET_WIDE_FILE",
    "DICTIONARY_COLUMNS",
    "DICTIONARY_FILE",
    "FIXED_WORDING",
    "FREE_TEXT_FILE",
    "QC_REPORT_FILE",
    "RULE_CATALOGUE_COLUMNS",
    "STATUS_LONG_FILE",
    "VALUES_LONG_FILE",
    "WORKBOOK_FILE",
    "Dataset",
    "ExportFiles",
    "QcTables",
    "build_dataset",
    "build_tables",
    "column_name",
    "dictionary_rows",
    "export_dataset",
    "render_html",
    "rule_catalogue_rows",
    "strip_box_svg",
    "summary_lines",
    "write_dataset_files",
    "write_workbook",
]


@dataclass(slots=True)
class ExportFiles:
    outputs: list[Path] = field(default_factory=list)
    shared: list[Path] = field(default_factory=list)
    masked_cells: int = 0
    """Tokens the guard replaced in share/: 0 is the expectation; more means a writer leaked."""
    tables: QcTables | None = None


def export_dataset(
    out_dir: Path,
    share_dir: Path,
    store: RawStore,
    resolved: Resolved,
    derived: DeriveRun,
    events: Sequence[Event],
    sessions: Sequence[Row],
    *,
    rspiro_version: str = "",
    tesseract_version: str = "",
    notice: Notice | None = None,
) -> ExportFiles:
    """Write the dataset views, dictionary, workbook and QC report to ``out_dir`` and
    the four counts files to ``share_dir`` through the guard."""
    say = notice or (lambda _m: None)
    files = ExportFiles()
    dataset = build_dataset(store, resolved, derived)
    files.outputs += write_dataset_files(out_dir, dataset, say)
    dict_rows = dictionary_rows(dataset, len(store.records))
    files.outputs.append(
        write_rows(out_dir / DICTIONARY_FILE, DICTIONARY_COLUMNS, dict_rows, say)
    )
    files.outputs.append(
        write_workbook(
            out_dir / WORKBOOK_FILE,
            dataset,
            dict_rows,
            DICTIONARY_COLUMNS,
            derived.rows,
            say,
        )
    )
    tables = build_tables(
        store,
        resolved,
        derived,
        dataset,
        events,
        sessions,
        rspiro_version,
        tesseract_version,
    )
    files.tables = tables
    files.outputs.append(
        write_bytes(out_dir / QC_REPORT_FILE, render_html(tables).encode("utf-8"), say)
    )
    # share/: counts only, every file through the guard
    layouts = {r.record.layout for r in store.records}
    page_types = {p.page_type for p in store.pages if p.page_type}
    categories = [
        *PATTERNS,
        *REPORT_PATTERNS,
        "within normal limits",
        "mild",
        "moderate",
        "severe",
        "yes",
        "no",
        "not usable",
        *"ABCDEFU",
    ]
    # category phrases are matched token by token
    category_words = [w for c in categories for w in c.replace(",", " ").split()]
    vocab = base_vocabulary(
        [*dataset.wide_columns, *layouts, *page_types, *category_words, "(none)", "?"]
    )
    path, masked = write_shareable_text(
        share_dir,
        QC_SUMMARY_FILE,
        summary_lines(tables),
        fixed_wording=FIXED_WORDING,
        vocabulary=vocab,
        notice=say,
    )
    files.shared.append(path)
    files.masked_cells += masked
    cols, rows = tables.completeness
    path, masked = write_shareable_table(
        share_dir,
        VARIABLE_SUMMARY_FILE,
        cols,
        rows,
        numeric_columns=[c for c in cols if c.startswith(("n_", "pct_"))],
        vocabulary=vocab,
        notice=say,
    )
    files.shared.append(path)
    files.masked_cells += masked
    page_rows: list[Row] = []
    for k, v in tables.run:
        if k.startswith("pages: "):
            layout, _, ptype = k.removeprefix("pages: ").partition(" / ")
            page_rows.append({"layout": layout, "page_type": ptype, "n_pages": v})
    path, masked = write_shareable_table(
        share_dir,
        PAGE_SUMMARY_FILE,
        ("layout", "page_type", "n_pages"),
        page_rows,
        numeric_columns=["n_pages"],
        vocabulary=vocab,
        notice=say,
    )
    files.shared.append(path)
    files.masked_cells += masked
    path, masked = write_shareable_table(
        share_dir,
        RULE_CATALOGUE_FILE,
        RULE_CATALOGUE_COLUMNS,
        rule_catalogue_rows(),
        fixed_text={
            "rationale": rule_rationales(),
            "severities": rule_severity_labels(),
        },
        vocabulary=vocab,
        notice=say,
    )
    files.shared.append(path)
    files.masked_cells += masked
    return files
