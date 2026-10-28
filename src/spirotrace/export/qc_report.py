"""The QC report (plan section 8): one self-contained HTML page with the run, the
flags raw and after review with their correction yield, review effort,
completeness per variable, variable distributions as strip-and-box charts,
the derived variables, the reading, and warnings. It shows values (the
distributions), so its name carries ``_CONTAINS_DATA``; the counts the export
guard sends to ``share/`` come from the same tables.
"""

from __future__ import annotations

import html
import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from spirotrace.checks import Severity
from spirotrace.derive import DerivedRow, DeriveRun
from spirotrace.layouts import conditions as cond
from spirotrace.model import TextSource, ValueState
from spirotrace.resolve import Resolved
from spirotrace.store import Event, RawStore, Row

from .dataset import Dataset, column_name, in_wide_table, is_numeric_column

QC_REPORT_FILE = "qc_report_CONTAINS_DATA.html"
OUTLIER_IQR = 3.0
"""Values beyond this many interquartile ranges from the quartiles are listed."""

Table = tuple[Sequence[str], list[Row]]


@dataclass(slots=True)
class QcTables:
    """Every table of the report as rows of strings, so the HTML and the shareable
    counts come from one source."""

    run: list[tuple[str, str]] = field(default_factory=list)
    flags_by_layer: Table = ((), [])
    flags_by_rule: Table = ((), [])
    effort: list[tuple[str, str]] = field(default_factory=list)
    reviewers: dict[str, int] = field(default_factory=dict)
    """initials -> number (the share/ summary names reviewers by number only)."""
    completeness: Table = ((), [])
    distributions: Table = ((), [])
    distribution_values: dict[tuple[str, str], list[tuple[str, float]]] = field(
        default_factory=dict
    )
    """(column, layout) -> (record id, value) for the charts (values: not shared)."""
    derived: Table = ((), [])
    pattern_agreement: Table = ((), [])
    reading: Table = ((), [])
    warnings: list[str] = field(default_factory=list)


def _pct(a: int, b: int) -> str:
    return "" if not b else f"{100 * a / b:.0f}"


def _layout_of_pages(store: RawStore) -> dict[tuple[str, int], str]:
    out: dict[tuple[str, int], str] = {}
    for r in store.records:
        for p in r.record.pages:
            out[(r.record.file_hash, p)] = r.record.layout
    return out


def _wall_minutes(a: str, b: str) -> float | None:
    try:
        return (
            datetime.fromisoformat(b) - datetime.fromisoformat(a)
        ).total_seconds() / 60
    except ValueError:
        return None


def build_tables(
    store: RawStore,
    resolved: Resolved,
    derived: DeriveRun,
    dataset: Dataset,
    events: Sequence[Event],
    sessions: Sequence[Row],
    rspiro_version: str,
    tesseract_version: str,
) -> QcTables:
    t = QcTables()
    layouts = Counter(r.record.layout for r in store.records)
    unreadable = sum(1 for f in store.flags if f.rule_id == "input.file_unreadable")
    page_layout = _layout_of_pages(store)
    blank = sum(
        1
        for p in store.pages
        if p.page_type is None and p.word_count < 10 and p.ink < 0.001
    )
    no_text = sum(
        1
        for p in store.pages
        if p.text_source is TextSource.NONE
        and not (p.word_count < 10 and p.ink < 0.001)
    )
    ocr_pages = sum(1 for p in store.pages if p.text_source is TextSource.OCR)
    t.run = [
        ("files", str(len(store.file_names))),
        ("files that could not be read", str(unreadable)),
        ("records", str(len(store.records))),
        *[(f"records: {k}", str(n)) for k, n in sorted(layouts.items())],
        ("pages", str(len(store.pages))),
        *[
            (f"pages: {layout} / {ptype}", str(n))
            for (layout, ptype), n in sorted(
                Counter(
                    (
                        page_layout.get((p.file_hash, p.page), "?"),
                        p.page_type or "(none)",
                    )
                    for p in store.pages
                ).items()
            )
        ],
        ("blank pages", str(blank)),
        ("pages without a text layer", str(no_text)),
        ("pages read by Tesseract", str(ocr_pages)),
        ("settings hash", str(store.stamp.get("settings_hash", ""))[:12]),
        ("code version", str(store.stamp.get("code_version", ""))),
        ("tesseract version", tesseract_version or "(not used)"),
        ("rspiro", rspiro_version or "(absent)"),
    ]

    # --- flags ---
    raw = Counter((f.layer, f.severity.value) for f in store.flags)
    after = Counter(
        (r.flag.layer, r.flag.severity.value)
        for r in resolved.flags_resolved
        if r.change != "cleared"
    )
    rows: list[Row] = [
        {
            "layer": layer,
            "severity": sev,
            "raw": str(raw.get((layer, sev), 0)),
            "after_review": str(after.get((layer, sev), 0)),
        }
        for layer, sev in sorted(set(raw) | set(after))
    ]
    t.flags_by_layer = (("layer", "severity", "raw", "after_review"), rows)
    settled = {k for k, by in resolved.values.items() if by.last_event_id}
    status_of = {k: v.status for k, v in resolved.values.items()}
    by_rule: dict[str, Counter] = defaultdict(Counter)
    for f in store.flags:
        c = by_rule[f.rule_id]
        c["flags"] += 1
        if f.severity in (Severity.ERROR, Severity.CHECK) and f.keys:
            c["reviewable"] += 1
            if any(k in settled for k in f.keys):
                c["answered"] += 1
                st = status_of.get(f.keys[0], "")
                if st == "corrected":
                    c["value_changed"] += 1
                elif st == "confirmed":
                    c["kept"] += 1
                elif st == "unreadable":
                    c["unreadable"] += 1
    cleared = Counter(
        r.flag.rule_id for r in resolved.flags_resolved if r.change == "cleared"
    )
    new = Counter(r.flag.rule_id for r in resolved.flags_resolved if r.change == "new")
    rows = []
    for rid in sorted(set(by_rule) | set(new)):
        c = by_rule[rid]
        rows.append(
            {
                "rule_id": rid,
                "raw": str(c["flags"]),
                "reviewable": str(c["reviewable"]),
                "answered": str(c["answered"]),
                "value_changed": str(c["value_changed"]),
                "kept": str(c["kept"]),
                "unreadable": str(c["unreadable"]),
                "yield_pct": _pct(c["value_changed"], c["answered"]),
                "cleared": str(cleared.get(rid, 0)),
                "new_after_review": str(new.get(rid, 0)),
            }
        )
    t.flags_by_rule = (
        (
            "rule_id",
            "raw",
            "reviewable",
            "answered",
            "value_changed",
            "kept",
            "unreadable",
            "yield_pct",
            "cleared",
            "new_after_review",
        ),
        rows,
    )

    # --- review effort (wall-clock from sessions, per answer from elapsed_ms) ---
    reviewers = sorted({e.reviewer for e in events} | {s["reviewer"] for s in sessions})
    t.reviewers = {r: i + 1 for i, r in enumerate(reviewers)}
    per_reviewer_events = Counter(e.reviewer for e in events)
    wall: dict[str, float] = defaultdict(float)
    for s in sessions:
        m = _wall_minutes(s["started"], s["ended"])
        if m is not None and m >= 0:
            wall[s["reviewer"]] += m
    elapsed = [e.elapsed_ms for e in events if e.elapsed_ms is not None]
    per_record: dict[str, list[str]] = defaultdict(list)
    for e in events:
        if e.shown_at:
            per_record[e.record_id].append(e.shown_at)
        per_record[e.record_id].append(e.time)
    record_minutes = []
    for times in per_record.values():
        ts = sorted(x for x in times if x)
        if len(ts) >= 2:
            m = _wall_minutes(ts[0], ts[-1])
            if m is not None:
                record_minutes.append(m)
    effort: list[tuple[str, str]] = [
        ("events", str(len(events))),
        ("reviewers", str(len(reviewers))),
    ]
    for r in reviewers:
        n = t.reviewers[r]
        effort.append((f"reviewer {n}: answers", str(per_reviewer_events.get(r, 0))))
        effort.append(
            (f"reviewer {n}: wall-clock minutes (sessions)", f"{wall.get(r, 0.0):.1f}")
        )
    effort.append(("records reviewed", str(len(per_record))))
    if record_minutes:
        effort.append(
            (
                "median minutes per record (first shown to last answer)",
                f"{statistics.median(record_minutes):.2f}",
            )
        )
    if elapsed:
        effort.append(("sum of per-answer seconds", f"{sum(elapsed) / 1000:.0f}"))
        effort.append(
            ("median seconds per answer", f"{statistics.median(elapsed) / 1000:.1f}")
        )
    effort.append(("open reviewer disagreements", str(len(resolved.disagreements))))
    effort.append(("orphan events", str(len(resolved.orphans))))
    t.effort = effort

    # --- completeness per wide column and layout ---
    layout_of = {r.record_id: r.record.layout for r in store.records}
    comp: dict[tuple[str, str], Counter] = defaultdict(Counter)
    for key, rv in resolved.values.items():
        if not in_wide_table(key):
            continue
        name = column_name(key)
        c = comp[(name, layout_of.get(rv.observation.record_id, "?"))]
        o = rv.resolved
        if o.value_state is ValueState.NOT_ON_PAGE:
            continue
        c["applicable"] += 1
        if o.value_state is ValueState.VALUE:
            c["read"] += 1
        if rv.usable and rv.open_severity != "check":
            c["confident"] += 1
        if rv.machine_confirmed_by:
            c["machine_confirmed"] += 1
        if rv.status == "corrected":
            c["corrected"] += 1
        if rv.status == "unreadable" or o.value_state is ValueState.UNREADABLE:
            c["unreadable"] += 1
        flagged = rv.open_severity in ("error", "check")
        if rv.observation.marked:
            c["marked"] += 1
            c["marked_flagged"] += int(flagged)
        else:
            c["unmarked"] += 1
            c["unmarked_flagged"] += int(flagged)
    rows = []
    for (name, layout), c in sorted(comp.items()):
        rows.append(
            {
                "variable": name,
                "layout": layout,
                "n_applicable": str(c["applicable"]),
                "n_read": str(c["read"]),
                "n_confident": str(c["confident"]),
                "pct_confident": _pct(c["confident"], c["applicable"]),
                "n_machine_confirmed": str(c["machine_confirmed"]),
                "n_corrected": str(c["corrected"]),
                "n_unreadable": str(c["unreadable"]),
                "n_marked": str(c["marked"]),
                "pct_flagged_marked": _pct(c["marked_flagged"], c["marked"]),
                "pct_flagged_unmarked": _pct(c["unmarked_flagged"], c["unmarked"]),
            }
        )
    t.completeness = (
        (
            "variable",
            "layout",
            "n_applicable",
            "n_read",
            "n_confident",
            "pct_confident",
            "n_machine_confirmed",
            "n_corrected",
            "n_unreadable",
            "n_marked",
            "pct_flagged_marked",
            "pct_flagged_unmarked",
        ),
        rows,
    )

    # --- distributions ---
    values: dict[tuple[str, str], list[tuple[str, float]]] = defaultdict(list)
    for key, rv in resolved.values.items():
        if not in_wide_table(key) or not is_numeric_column(key) or not rv.usable:
            continue
        if rv.resolved.parsed_value is None:
            continue
        values[(column_name(key), layout_of.get(rv.observation.record_id, "?"))].append(
            (rv.observation.record_id, rv.resolved.parsed_value)
        )
    rows = []
    for (name, layout), pairs in sorted(values.items()):
        xs = sorted(v for _, v in pairs)
        q = statistics.quantiles(xs, n=4) if len(xs) >= 2 else [xs[0], xs[0], xs[0]]
        iqr = q[2] - q[0]
        lo, hi = q[0] - OUTLIER_IQR * iqr, q[2] + OUTLIER_IQR * iqr
        outliers = [rid for rid, v in pairs if v < lo or v > hi]
        rows.append(
            {
                "name": name,
                "layout": layout,
                "n": str(len(xs)),
                "min": f"{xs[0]:g}",
                "q1": f"{q[0]:g}",
                "median": f"{q[1]:g}",
                "q3": f"{q[2]:g}",
                "max": f"{xs[-1]:g}",
                "n_outliers": str(len(outliers)),
                "outlier_records": " ".join(sorted(outliers)),
            }
        )
    t.distributions = (
        (
            "name",
            "layout",
            "n",
            "min",
            "q1",
            "median",
            "q3",
            "max",
            "n_outliers",
            "outlier_records",
        ),
        rows,
    )
    t.distribution_values = dict(values)

    # --- derived ---
    rows = []
    for name in (
        "pattern",
        "fev1_severity",
        "prism",
        "bdr_positive_2022",
        "report_pattern",
        "pattern_gli",
    ):
        c = Counter(
            (layout_of.get(r.record_id, "?"), r.value or "(not computed)")
            for r in derived.rows
            if r.name == name
        )
        for (layout, value), n in sorted(c.items()):
            rows.append(
                {"derived": name, "layout": layout, "category": value, "n": str(n)}
            )
    resting = sum(
        1 for r in derived.rows if r.value and "check" in r.input_open_severities
    )
    rows.append(
        {
            "derived": "(any)",
            "layout": "(all)",
            "category": "resting on an open check",
            "n": str(resting),
        }
    )
    t.derived = (("derived", "layout", "category", "n"), rows)
    flagged_pattern: dict[str, str] = {}
    for f in derived.flags:
        if f.rule_id == "free_text.report_pattern_vs_computed":
            flagged_pattern[f.record_id] = (
                "near miss" if f.severity is Severity.NOTE else "disagree"
            )
    agreement: Counter = Counter()
    gli_agreement: Counter = Counter()
    for rid, rows_of in _by_record(derived).items():
        calc, rep, gli = (
            rows_of.get("pattern"),
            rows_of.get("report_pattern"),
            rows_of.get("pattern_gli"),
        )
        if calc is None or not calc.value or rep is None or rep.value in ("", "other"):
            agreement["not computed"] += 1
        else:
            agreement[flagged_pattern.get(rid, "agree")] += 1
        if calc is None or gli is None or not calc.value or not gli.value:
            gli_agreement["not computed"] += 1
        else:
            gli_agreement["agree" if calc.value == gli.value else "disagree"] += 1
    rows = [
        {"comparison": "pattern vs report_pattern", "outcome": k, "n": str(n)}
        for k, n in sorted(agreement.items())
    ]
    rows += [
        {"comparison": "pattern vs pattern_gli", "outcome": k, "n": str(n)}
        for k, n in sorted(gli_agreement.items())
    ]
    t.pattern_agreement = (("comparison", "outcome", "n"), rows)

    # --- reading ---
    rows = []
    rm = Counter(
        (o.read_method.value, o.value_state.value)
        for r in store.records
        for o in r.observations.values()
    )
    rows += [
        {"item": "observations", "category": f"{m} / {s}", "n": str(n)}
        for (m, s), n in sorted(rm.items())
    ]
    ftd = Counter(
        c.key.parameter.value
        for r in store.records
        for c in r.conditions
        if c.code == cond.FREE_TEXT_DERIVED and c.key is not None
    )
    rows += [
        {"item": "free_text_derived", "category": p, "n": str(n)}
        for p, n in sorted(ftd.items())
    ]
    so = Counter(
        f.rule_id for f in store.flags if f.rule_id.startswith("ocr.second_reading")
    )
    rows += [
        {"item": "second OCR", "category": rid, "n": str(n)}
        for rid, n in sorted(so.items())
    ]
    t.reading = (("item", "category", "n"), rows)

    if resolved.orphans:
        t.warnings.append(
            f"{len(resolved.orphans)} review event(s) point at keys no longer in the store"
        )
    if unreadable:
        t.warnings.append(f"{unreadable} file(s) could not be read")
    if derived.not_run_reason:
        t.warnings.append(f"rspiro did not run: {derived.not_run_reason}")
    return t


def _by_record(derived: DeriveRun) -> dict[str, dict[str, DerivedRow]]:
    out: dict[str, dict[str, DerivedRow]] = defaultdict(dict)
    for r in derived.rows:
        out[r.record_id][r.name] = r
    return dict(out)


# --- HTML -----------------------------------------------------------------------------


def _esc(s: object) -> str:
    return html.escape(str(s))


def _table(columns: Sequence[str], rows: Iterable[Mapping[str, str]]) -> str:
    head = "".join(f"<th>{_esc(c)}</th>" for c in columns)
    body = "".join(
        "<tr>" + "".join(f"<td>{_esc(r.get(c, ''))}</td>" for c in columns) + "</tr>"
        for r in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _pairs(pairs: Iterable[tuple[str, str]]) -> str:
    return (
        "<table><tbody>"
        + "".join(f"<tr><th>{_esc(k)}</th><td>{_esc(v)}</td></tr>" for k, v in pairs)
        + "</tbody></table>"
    )


def strip_box_svg(values: Sequence[float], width: int = 420, height: int = 60) -> str:
    """One dot per record on a line, a box for the middle half, a tick at the median."""
    if not values:
        return ""
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    pad = 12

    def x(v: float) -> float:
        return pad + (v - lo) / span * (width - 2 * pad)

    q = statistics.quantiles(values, n=4) if len(values) >= 2 else [lo, lo, lo]
    mid = height / 2
    parts = [
        f'<svg class="dist" viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img">'
    ]
    parts.append(
        f'<line x1="{pad}" y1="{mid}" x2="{width - pad}" y2="{mid}" class="axis"/>'
    )
    parts.append(
        f'<rect x="{x(q[0]):.1f}" y="{mid - 12}" width="{max(1.0, x(q[2]) - x(q[0])):.1f}" height="24" class="box"/>'
    )
    parts.append(
        f'<line x1="{x(q[1]):.1f}" y1="{mid - 14}" x2="{x(q[1]):.1f}" y2="{mid + 14}" class="median"/>'
    )
    for v in values:
        parts.append(f'<circle cx="{x(v):.1f}" cy="{mid}" r="3" class="dot"/>')
    parts.append(f'<text x="{pad}" y="{height - 2}" class="lab">{lo:g}</text>')
    parts.append(
        f'<text x="{width - pad}" y="{height - 2}" class="lab end">{hi:g}</text>'
    )
    parts.append("</svg>")
    return "".join(parts)


CSS = """
body{font-family:system-ui,sans-serif;font-size:14px;margin:2em;max-width:1100px}
h1{font-size:1.5em}h2{font-size:1.2em;margin-top:2em;border-bottom:1px solid #ccc}
table{border-collapse:collapse;margin:.5em 0}th,td{border-bottom:1px solid #ddd;padding:3px 8px;text-align:left;vertical-align:top}
th{background:#f4f4f4}td:not(:first-child),th:not(:first-child){text-align:right}
.dist{display:block}.axis{stroke:#999}.box{fill:#dde8f5;stroke:#5b7fb0}.median{stroke:#1d3f73;stroke-width:2}
.dot{fill:#1d3f73;fill-opacity:.55}.lab{font-size:10px;fill:#555}.end{text-anchor:end}
.warn{color:#8a1c1c}.note{color:#555;font-size:.9em}
"""


def render_html(t: QcTables, title: str = "spirotrace QC report") -> str:
    out = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        f"<title>{_esc(title)}</title><style>{CSS}</style></head><body>",
        f"<h1>{_esc(title)}</h1>",
        (
            "<p class='note'>This file holds values and record ids (the distributions): it stays in outputs/. "
            "The counts in share/ come from the same tables through the export guard.</p>"
        ),
        "<h2>1. Run</h2>",
        _pairs(t.run),
        "<h2>2. Flags</h2><h3>By layer and severity, raw and after review</h3>",
        _table(*t.flags_by_layer),
        "<h3>By rule, with the correction yield among reviewed flags</h3>",
        (
            "<p class='note'>Yield is the share of answered flags whose value changed. It is an operational "
            "figure, not accuracy: it says nothing about errors that were never flagged.</p>"
        ),
        _table(*t.flags_by_rule),
        "<h2>3. Review effort</h2>",
        _pairs(t.effort),
        (
            "<p class='note'>Reviewers are numbered; initials are not written here or in share/. "
            "Wall-clock minutes come from the session files and from first shown to last answer per record.</p>"
        ),
        "<h2>4. Completeness per variable</h2>",
        _table(*t.completeness),
        "<h2>5. Variable distributions</h2>",
        (
            "<p class='note'>One dot per record, box for the middle half, tick at the median; records beyond "
            f"{OUTLIER_IQR:g} interquartile ranges from the quartiles are listed.</p>"
        ),
    ]
    cols, rows = t.distributions
    for r in rows:
        pairs = t.distribution_values.get((r["name"], r["layout"]), [])
        out.append(f"<h3>{_esc(r['name'])} ({_esc(r['layout'])})</h3>")
        out.append(strip_box_svg([v for _, v in pairs]))
        out.append(_table(cols, [r]))
    out += [
        "<h2>6. Derived</h2>",
        _table(*t.derived),
        _table(*t.pattern_agreement),
        "<h2>7. Reading</h2>",
        _table(*t.reading),
        "<h2>8. Warnings</h2>",
        "<ul>"
        + "".join(f"<li class='warn'>{_esc(w)}</li>" for w in t.warnings)
        + "</ul>"
        if t.warnings
        else "<p>None.</p>",
        "</body></html>",
    ]
    return "\n".join(out)


def summary_lines(t: QcTables) -> list[str]:
    """Sections 1, 2, 3, 6 and 7 as counts, reviewers by number: the share/ summary."""
    lines = ["spirotrace QC summary (counts only)", "", "== run"]
    # version strings and the settings hash stay in stamp.json and the HTML report
    lines += [
        f"{k}: {v}"
        for k, v in t.run
        if k not in ("settings hash", "code version", "tesseract version", "rspiro")
    ]
    lines += ["", "== flags by layer and severity (raw / after review)"]
    for r in t.flags_by_layer[1]:
        lines.append(f"{r['layer']} {r['severity']}: {r['raw']} / {r['after_review']}")
    lines += [
        "",
        "== flags by rule (raw, answered, value changed, kept, unreadable, yield %, cleared, new)",
    ]
    for r in t.flags_by_rule[1]:
        lines.append(
            f"{r['rule_id']}: {r['raw']} {r['answered']} {r['value_changed']} {r['kept']} "
            f"{r['unreadable']} {r['yield_pct'] or '-'} {r['cleared']} {r['new_after_review']}"
        )
    lines += ["", "== review effort"]
    lines += [f"{k}: {v}" for k, v in t.effort]
    lines += ["", "== derived"]
    for r in t.derived[1]:
        lines.append(f"{r['derived']} {r['layout']} {r['category']}: {r['n']}")
    for r in t.pattern_agreement[1]:
        lines.append(f"{r['comparison']} {r['outcome']}: {r['n']}")
    lines += ["", "== reading"]
    for r in t.reading[1]:
        lines.append(f"{r['item']} {r['category']}: {r['n']}")
    return lines


FIXED_WORDING: str = (
    "spirotrace QC summary (counts only) run flags by layer and severity raw after review "
    "rule answered value changed kept unreadable yield cleared new review effort derived reading "
    "files that could not be read records pages blank without a text layer read by Tesseract "
    "settings hash code version tesseract rspiro absent not used none events reviewers reviewer "
    "answers wall-clock minutes sessions reviewed median per record first shown to last answer "
    "sum of per-answer seconds open disagreements orphan any all resting on an open check "
    "not computed near miss agree disagree pattern vs report_pattern pattern_gli observations "
    "free_text_derived second OCR"
)
"""The words the summary writer uses; the guard masks every other non-numeric token."""
