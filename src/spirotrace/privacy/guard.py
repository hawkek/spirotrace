"""The export guard: the only code that writes to ``share/``.

A shareable file is one of four named files. Table columns are declared as
numeric (digits allowed), as fixed text (every cell must be one of the code's
own strings, such as a rule rationale) or as vocabulary (every token must be a
name the package defines: parameters, roles, layers, rule ids, severities,
value states, read methods, statuses, layouts, column names). Anything else
becomes ``???``. Column names that would carry a value, raw text, a note, a
message or a record id are refused outright. A text summary is checked token
by token against the same vocabulary, the numbers (counts), and the fixed
wording its writer declares. The guard never sees a value: the writers pass
counts, and a test plants identifiers in every table to prove they do not pass.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

from spirotrace.checks import LAYERS, RULES, Severity
from spirotrace.model import ColumnRole, Parameter, ReadMethod, ValueState
from spirotrace.store import Notice, Row, write_bytes, write_rows

SHARE_DIR = "share"
QC_SUMMARY_FILE = "qc_summary.txt"
VARIABLE_SUMMARY_FILE = "variable_summary.csv"
PAGE_SUMMARY_FILE = "page_summary.csv"
RULE_CATALOGUE_FILE = "rule_catalogue.csv"
SHAREABLE_FILES: frozenset[str] = frozenset(
    {QC_SUMMARY_FILE, VARIABLE_SUMMARY_FILE, PAGE_SUMMARY_FILE, RULE_CATALOGUE_FILE}
)

FORBIDDEN_COLUMN_WORDS: frozenset[str] = frozenset(
    {
        "value",
        "values",
        "raw",
        "raw_text",
        "text",
        "note",
        "notes",
        "message",
        "detail",
        "reading",
        "record_id",
        "record",
        "subject",
        "subject_id",
        "file",
        "file_name",
        "name",
        "date",
        "reviewer",
    }
)
"""A column named like one of these would carry a value or an identifier: refused."""

MASK = "???"
_TOKEN_RE = re.compile(r"[A-Za-z0-9_.\-/%+]+|[^A-Za-z0-9_.\-/%+\s]+")
_NUMBER_RE = re.compile(r"^[+-]?\d+(\.\d+)?%?$")


class GuardError(ValueError):
    """A write to share/ that the guard refuses."""


def base_vocabulary(extra: Iterable[str] = ()) -> frozenset[str]:
    """Every name the package defines, lower-cased, plus ``extra`` (column names, layouts)."""
    words: set[str] = set()
    words.update(p.value for p in Parameter)
    words.update(r.value for r in ColumnRole)
    words.update(LAYERS)
    words.update(RULES)
    words.update(s.value for s in Severity)
    words.update(v.value for v in ValueState)
    words.update(m.value for m in ReadMethod)
    words.update(
        (
            "accepted_unflagged",
            "confirmed",
            "corrected",
            "unreadable",
            "excluded",
            "open_flag",
            "reviewer_disagreement",
            "new",
            "cleared",
            "unchanged",
            "computed",
        )
    )
    words.update(extra)
    return frozenset(w.lower() for w in words)


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text)


def mask_text(
    text: str, vocabulary: frozenset[str], fixed_words: frozenset[str]
) -> str:
    """Replace every token that is not a number, a vocabulary name or declared wording."""
    out: list[str] = []
    pos = 0
    for m in _TOKEN_RE.finditer(text):
        out.append(text[pos : m.start()])
        tok = m.group(0)
        low = tok.lower().strip(".,;:()")
        if (
            _NUMBER_RE.match(tok)
            or not re.search(r"[A-Za-z0-9]", tok)
            or low in vocabulary
            or low in fixed_words
        ):
            out.append(tok)
        else:
            out.append(MASK)
        pos = m.end()
    out.append(text[pos:])
    return "".join(out)


def _check_name(folder: Path, name: str) -> Path:
    if name not in SHAREABLE_FILES:
        raise GuardError(
            f"{name} is not a shareable file; share/ takes only {sorted(SHAREABLE_FILES)}"
        )
    return folder / name


def write_shareable_table(
    share_dir: Path,
    name: str,
    columns: Sequence[str],
    rows: Iterable[Mapping[str, str]],
    *,
    numeric_columns: Iterable[str] = (),
    fixed_text: Mapping[str, Iterable[str]] | None = None,
    vocabulary: frozenset[str] | None = None,
    notice: Notice | None = None,
) -> tuple[Path, int]:
    """Write a counts table to share/; returns the path and how many cells were masked."""
    path = _check_name(share_dir, name)
    bad = [c for c in columns if c.lower() in FORBIDDEN_COLUMN_WORDS]
    if bad:
        raise GuardError(
            f"{name}: column(s) {', '.join(bad)} would carry values or identifiers"
        )
    numeric = set(numeric_columns)
    fixed = {k: {v for v in vs} for k, vs in (fixed_text or {}).items()}
    vocab = vocabulary if vocabulary is not None else base_vocabulary(columns)
    masked = 0
    out: list[Row] = []
    for r in rows:
        row: Row = {}
        for c in columns:
            v = str(r.get(c, ""))
            if c in numeric:
                row[c] = v if v == "" or _NUMBER_RE.match(v) else MASK
            elif c in fixed:
                row[c] = v if v in fixed[c] else MASK
            else:
                row[c] = v if v == "" or v.lower() in vocab else MASK
            if row[c] == MASK:
                masked += 1
        out.append(row)
    written = write_rows(path, columns, out, notice or (lambda _m: None))
    return written, masked


def write_shareable_text(
    share_dir: Path,
    name: str,
    lines: Iterable[str],
    *,
    fixed_wording: str | Iterable[str],
    vocabulary: frozenset[str] | None = None,
    notice: Notice | None = None,
) -> tuple[Path, int]:
    """Write a counts summary to share/: every token must be a number, a vocabulary
    name or a word of the declared fixed wording; returns the path and masked tokens."""
    path = _check_name(share_dir, name)
    vocab = vocabulary if vocabulary is not None else base_vocabulary()
    words: set[str] = set()
    wording = [fixed_wording] if isinstance(fixed_wording, str) else list(fixed_wording)
    for w in wording:
        words.update(t.lower().strip(".,;:()") for t in _tokens(w))
    fixed = frozenset(words)
    out_lines = []
    masked = 0
    for line in lines:
        m = mask_text(line, vocab, fixed)
        masked += m.count(MASK)
        out_lines.append(m)
    text = "\n".join(out_lines) + "\n"
    written = write_bytes(path, text.encode("utf-8"), notice or (lambda _m: None))
    return written, masked
