"""Generic table reader: columns anchored on right edges, rows by label, order or position.

Numbers on the reports are right-aligned, so every column is anchored on
its right edge. Columns come from the header words when they were read,
from the value columns the numbers form when they were not, and from an
expected column sequence when the header was only partly read. Rows are
matched by label; a row whose label was not read is placed by the gaps
between labelled rows, by order when every required row is present, or by
a measured height template the caller supplies.
"""

from __future__ import annotations

import itertools
import re
import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from spirotrace.ingest import BBox, Line, Word, bbox_of

from . import conditions as cond
from .conditions import Condition
from .text import find_phrase, norm, ratio
from .tokens import STAR_CHARS, is_numericish, is_unit

ColumnSeq = Sequence[tuple[str, str]]
"""Expected columns as ``(phase, name)`` pairs, left to right."""

_CANON_TRANS = str.maketrans({"O": "0", "I": "1", "L": "1", "|": "1", "!": "1"})


def canon_label(s: str) -> str:
    """Row label reduced to upper-case alphanumerics with OCR digit fixes."""
    s = s.upper().replace("_", "").replace(" ", "")
    s = s.translate(_CANON_TRANS)
    return re.sub(r"[^A-Z0-9%/]", "", s)


def label_text(words: Sequence[Word]) -> str:
    """Row label without unit tokens such as ``[L]``, ``[%]``, ``[ml/(min*mmHg)]``.

    Stops at a bracketed token or at the first wide horizontal gap (the unit
    column).
    """
    out = []
    prev = None
    for w in words:
        t = w.text
        if prev is not None and w.x0 - prev.x1 > 0.04:
            break
        prev = w
        if t[:1] in "[({" or "mmhg" in t.lower() or t.lower() in ("cm", "sec]"):
            break
        out.append(t)
    return " ".join(out)


TRIALNUM = str.maketrans(
    {"s": "5", "o": "0", "l": "1", "i": "1", "|": "1", "b": "8", "z": "2", "g": "9"}
)
TRIAL_RE = r"tr[il1|]a[l1|i]?"
TRIALNUM_RE = r"[0-9soilbzg|]{1,2}"
_TRIAL_HEADER_RE = re.compile(TRIAL_RE + "(" + TRIALNUM_RE + ")")

HEADER_NAMES: dict[str, tuple[str, ...]] = {
    "best": ("best", "8est"),
    "pre": ("pre",),
    "post": ("post",),
    "lln": ("lln", "ln", "11n", "lin", "iln", "llin", "l1n", "1ln"),
    "uln": ("uln", "u1n"),
    "pctpred": ("%pred", "%prea", "%pre", "%pned", "pred%", "%predicted"),
    "pred": ("pred", "prea"),
    "bdr": ("bdr", "8dr"),
    "pctchg": ("%chg", "chg", "%change"),
}
"""Column header words and their OCR variants, by column name."""


def header_name(tok: str) -> str | None:
    """Column name for a header token, ``t<n>`` for a trial header, else None."""
    n = norm(tok)
    for name, variants in HEADER_NAMES.items():
        if n in variants:
            return name
    if "score" in n or n in ("zscore", "2score", "z"):
        return "z"
    m = _TRIAL_HEADER_RE.fullmatch(n)
    if m:
        num = m.group(1).translate(TRIALNUM)
        if num.isdigit():
            return f"t{int(num)}"
    return None


def merge_header_tokens(words: Sequence[Word]) -> list[Word]:
    """Join split header tokens: ``%`` + ``Pred``, ``Trial`` + ``3``, ``Z-`` + ``Score``."""
    out: list[Word] = []
    i = 0
    while i < len(words):
        w = words[i]
        nxt = words[i + 1] if i + 1 < len(words) else None
        n = norm(w.text)
        if nxt is not None and nxt.x0 - w.x1 < 0.03:
            nn = norm(nxt.text)
            if (
                (n == "%" and nn.startswith("pred"))
                or (re.fullmatch(TRIAL_RE, n) and re.fullmatch(TRIALNUM_RE, nn))
                or (n in ("z", "z-", "2z") and "score" in nn)
            ):
                out.append(
                    Word(
                        w.text + nxt.text,
                        w.x0,
                        nxt.x1,
                        min(w.top, nxt.top),
                        max(w.bottom, nxt.bottom),
                    )
                )
                i += 2
                continue
        out.append(w)
        i += 1
    return out


@dataclass(slots=True)
class Col:
    """A table column: name, phase and the right edge its values align to."""

    name: str
    phase: str
    cx: float
    span: tuple[float, float] | None = None


@dataclass(frozen=True, slots=True)
class RowSpec:
    """A row the table should have: its parameter and the label variants."""

    param: str
    labels: tuple[str, ...]
    required: bool = True


@dataclass(slots=True)
class Cell:
    """One cell: raw text, boxes and how the row was identified."""

    raw: str
    bbox: BBox
    row_bbox: BBox | None
    inferred: str | None = None
    """None (label read), ``gap``, ``complete`` (by order) or ``template``."""
    label_raw: str = ""
    label_conflict: bool = False
    empty_in_filled_col: bool = False
    row_empty: bool = False


@dataclass(slots=True)
class TableResult:
    cells: dict[tuple[str, str, str], Cell] = field(default_factory=dict)
    """``(param, phase, column name)`` to cell."""
    columns: list[Col] = field(default_factory=list)
    conditions: list[Condition] = field(default_factory=list)
    rows_found: list[str] = field(default_factory=list)


def columns_from_header(
    hdr_words: Sequence[Word], super_words: Sequence[Word] | None, stop_after_z: bool
) -> list[Col]:
    """Columns named by the header words, with pre/post phase from a super-header."""
    toks = merge_header_tokens(sorted(hdr_words, key=lambda w: w.x0))
    cols: list[list[Any]] = []
    for w in toks:
        nm = header_name(w.text)
        if nm is None:
            continue
        cols.append([nm, w.x1])
    if stop_after_z:
        for i, c in enumerate(cols):
            if c[0] == "z":
                cols = cols[: i + 1]
                break
    if not cols:
        return []
    post_x = None
    for w in super_words or []:
        if header_name(w.text) == "post":
            post_x = w.x0 - 0.02
    out = []
    seen_best = 0
    for nm, x in cols:
        phase = "pre"
        if nm in ("pre", "post"):
            phase = nm
            nm = "value"
        if nm == "best":
            seen_best += 1
        if (post_x is not None and x >= post_x) or (post_x is None and seen_best >= 2):
            phase = "post"
        if nm == "bdr":
            phase = "post"
        out.append(Col(nm, phase, x))
    return out


def cluster_x(xs: Sequence[float], gap: float = 0.025) -> list[float]:
    """Mean of each run of x positions closer than ``gap``."""
    xs = sorted(xs)
    cl: list[list[float]] = []
    for x in xs:
        if cl and x - cl[-1][-1] < gap:
            cl[-1].append(x)
        else:
            cl.append([x])
    return [statistics.fmean(c) for c in cl]


def value_clusters(
    region: Sequence[Line], value_xmin: float, value_xmax: float
) -> list[tuple[float, tuple[float, float]]]:
    """Group numeric tokens into columns by horizontal overlap.

    Works for right- and left-aligned numbers; keeps columns supported by
    several rows (drops stray chart digits). Returns ``(right edge, span)``
    per column.
    """
    toks = []
    for li, ln in enumerate(region):
        for w in ln.words:
            if (
                is_numericish(w.text)
                and not is_unit(w.text)
                and value_xmin < w.cx < value_xmax
            ):
                toks.append((w.x0, w.x1, li))
    if not toks:
        return []
    # a token much wider than the rest is usually two numbers OCR'd as one word
    # ('6.805.60'); letting it chain two columns together would put every value
    # of that table into the wrong column. Leave it out of the column finding
    # (its cell is still read, and flagged as not a number).
    merged = set()
    for ln in region:
        for w in ln.words:
            if re.search(r"\d[.,]\d+[.,]\d", w.text) or re.search(
                r"\d\s*[-–]\s*\d+[.,]\d", w.text[1:]
            ):
                merged.add((w.x0, w.x1))
    toks = [t for t in toks if (t[0], t[1]) not in merged] or toks
    toks.sort()
    groups = [[toks[0]]]
    for t in toks[1:]:
        if t[0] <= max(g[1] for g in groups[-1]) + 0.003:
            groups[-1].append(t)
        else:
            groups.append([t])
    n_lines = len({li for *_, li in toks})
    min_support = 1 if n_lines <= 2 else max(2, round(0.25 * n_lines))
    out = []
    for g in groups:
        if len({li for *_, li in g}) >= min_support:
            out.append(
                (max(t[1] for t in g), (min(t[0] for t in g), max(t[1] for t in g)))
            )
    return out


def name_columns(
    hdr_cols: list[Col],
    clusters: list[float],
    expected_seqs: Sequence[ColumnSeq] | None,
    default_phase: str,
) -> tuple[list[Col], list[Condition]]:
    """Decide column names and anchor positions from header and value columns."""
    conditions: list[Condition] = []
    seqs = list(expected_seqs or [])
    # A header word with no value column under it, to the right of every value
    # column, is not a table heading: a small z-score graph can carry its own
    # "Z-Score" heading on the same line. If the table's own heading was not
    # read, that graph heading used to be taken as the z column and shifted
    # the fitted column positions by one.
    if clusters and hdr_cols:
        csp = (
            statistics.median([b - a for a, b in itertools.pairwise(clusters)])
            if len(clusters) >= 2
            else 0.06
        )
        far = [h for h in hdr_cols if h.cx > max(clusters) + 0.6 * csp]
        if far:
            hdr_cols = [h for h in hdr_cols if h not in far]
            conditions.append(
                Condition(
                    cond.HEADER_GRAPH_HEADING_IGNORED,
                    ", ".join(f"'{h.name}' at x={h.cx:.2f}" for h in far),
                )
            )

    def snap_all(hxs: list[float]) -> list[float]:
        """Mutual-nearest matching of header anchors to value columns."""
        out = list(hxs)
        if not clusters:
            return out
        sp = min((b - a for a, b in itertools.pairwise(hxs)), default=0.08)
        for i, x in enumerate(hxs):
            c = min(clusters, key=lambda c: abs(c - x))
            back = min(range(len(hxs)), key=lambda k: abs(hxs[k] - c))
            if back == i and abs(c - x) < 0.75 * sp:
                out[i] = c
        return out

    # 1. header fully read and matching an expected layout: trust it (snap anchors to values)
    hdr_sig = [("value" if h.name == "best" else h.name, h.phase) for h in hdr_cols]
    for seq in seqs:
        if hdr_sig == [(n, p) for p, n in seq]:
            xs = snap_all([h.cx for h in hdr_cols])
            return [
                Col(h.name, h.phase, x) for h, x in zip(hdr_cols, xs, strict=True)
            ], conditions
    by_len = [s for s in seqs if len(s) == len(clusters)]
    if clusters and by_len:
        seq = by_len[0]
        cols = [Col(n, p, x) for (p, n), x in zip(seq, clusters, strict=True)]
        # verify against whatever header tokens were read
        for h in hdr_cols:
            i = min(range(len(cols)), key=lambda k: abs(cols[k].cx - h.cx))
            if (cols[i].name, cols[i].phase) != (h.name, h.phase) and not (
                h.name == "best" and cols[i].name == "value"
            ):
                conditions.append(
                    Condition(
                        cond.HEADER_OVER_OTHER_COLUMN,
                        f"'{h.name}' over '{cols[i].name}'",
                    )
                )
        if not hdr_cols:
            conditions.append(Condition(cond.COLUMNS_NAMED_BY_POSITION))
        return cols, conditions
    if hdr_cols and clusters and len(hdr_cols) == len(clusters):
        return [
            Col(c.name, c.phase, x) for c, x in zip(hdr_cols, clusters, strict=True)
        ], conditions
    if hdr_cols and not seqs:
        # e.g. trial tables: header defines the columns; snap to value columns where possible
        xs = snap_all([h.cx for h in hdr_cols])
        if clusters and len(clusters) != len(hdr_cols):
            conditions.append(
                Condition(
                    cond.HEADER_VALUE_COUNT_MISMATCH,
                    f"header {len(hdr_cols)}, values {len(clusters)}; header positions used",
                )
            )
        return [
            Col(h.name, h.phase, x) for h, x in zip(hdr_cols, xs, strict=True)
        ], conditions
    if hdr_cols and clusters and seqs:
        # partial header: place every expected column using the header tokens that were read
        seq = max(seqs, key=len)
        known: dict[int, float] = {}
        j = 0
        for h in hdr_cols:
            while j < len(seq) and not (
                seq[j][1] == h.name or (h.name == "best" and seq[j][1] == "value")
            ):
                j += 1
            if j < len(seq):
                known[j] = h.cx
                j += 1
        b: float | None
        a = 0.0
        if len(known) >= 2:
            ks = sorted(known)
            b = (known[ks[-1]] - known[ks[0]]) / (ks[-1] - ks[0])
            a = known[ks[0]] - b * ks[0]
            if (
                len(clusters) >= 3
            ):  # guard: spacing implied by the headers must fit the value columns
                csp = statistics.median(
                    [y - x for x, y in itertools.pairwise(clusters)]
                )
                if not 0.6 * csp <= b <= 1.4 * csp:
                    b = csp
                    a = statistics.median([known[k] - b * k for k in ks])
                    conditions.append(Condition(cond.HEADER_SPACING_INCONSISTENT))
        elif len(known) == 1 and len(clusters) >= 2:
            b = statistics.median(y - x for x, y in itertools.pairwise(clusters))
            k0 = next(iter(known))
            a = known[k0] - b * k0
        else:
            b = None
        if b and b > 0:
            exp_x = [a + b * i for i in range(len(seq))]
            anchor = list(exp_x)
            taken: set[int] = set()
            for x in clusters:
                i = min(range(len(seq)), key=lambda k: abs(exp_x[k] - x))
                if abs(exp_x[i] - x) <= 0.5 * b and i not in taken:
                    taken.add(i)
                    anchor[i] = x
                else:
                    conditions.append(
                        Condition(cond.VALUE_COLUMN_UNMATCHED, f"x={x:.3f}")
                    )
            # columns without numeric values still get an anchor, so text there is flagged
            cols = [Col(seq[i][1], seq[i][0], anchor[i]) for i in range(len(seq))]
            conditions.append(Condition(cond.HEADER_PARTLY_READ))
            return cols, conditions
    if hdr_cols:
        if clusters:
            conditions.append(
                Condition(
                    cond.HEADER_VALUE_COUNT_MISMATCH,
                    f"header {len(hdr_cols)}, values {len(clusters)}; header positions used",
                )
            )
        return hdr_cols, conditions
    if clusters and not seqs:
        conditions.append(Condition(cond.COLUMNS_GENERIC_NAMES))
        return [
            Col(f"c{i + 1}", default_phase, x) for i, x in enumerate(clusters)
        ], conditions
    conditions.append(
        Condition(cond.COLUMNS_UNDETERMINED, f"{len(clusters)} value columns")
    )
    return [], conditions


def merge_close_lines(lines: Sequence[Line], tol: float = 0.006) -> list[Line]:
    """Join lines whose centres are closer than ``tol`` (a wobbly scanned row)."""
    out: list[Line] = []
    for ln in sorted(lines, key=lambda ln: ln.cy):
        if out and ln.cy - out[-1].cy < tol:
            out[-1] = Line(tuple(sorted(out[-1].words + ln.words, key=lambda w: w.x0)))
        else:
            out.append(ln)
    return out


def match_label(
    lab_words: Sequence[Word], specs: Sequence[RowSpec], used: set[str]
) -> tuple[str | None, str]:
    """Best row for a label, if it is clearly one row and that row is not taken."""
    txt = label_text(lab_words)
    cl = canon_label(txt)
    if not cl:
        return None, txt
    scores = sorted(
        ((ratio(cl, canon_label(lab)), s.param) for s in specs for lab in s.labels),
        reverse=True,
    )
    if not scores:
        return None, txt
    best, p = scores[0]
    second = next((sc for sc, q in scores if q != p), 0)
    if best >= 0.8 and (best == 1.0 or best - second >= 0.1) and p not in used:
        return p, txt
    return None, txt


def parse_table(
    lines: Sequence[Line],
    y0: float,
    y1: float,
    row_specs: Sequence[RowSpec],
    hdr_words: Sequence[Word] | None = None,
    super_words: Sequence[Word] | None = None,
    value_xmin: float = 0.18,
    value_xmax: float = 0.97,
    expected_seqs: Sequence[ColumnSeq] | None = None,
    stop_after_z: bool = False,
    default_phase: str = "pre",
    fixed_columns: list[Col] | None = None,
    skip_lines: Sequence[str] = (),
    row_template: tuple[float, Sequence[tuple[str, float]]] | None = None,
    structural_blanks: frozenset[tuple[str, str]] = frozenset(),
) -> TableResult:
    """Read the table between ``y0`` and ``y1``.

    Parameters
    ----------
    lines
        The page's lines.
    y0, y1
        Vertical extent of the table body (header excluded).
    row_specs
        Rows expected, in printed order.
    hdr_words, super_words
        Words of the column header line and of the pre/post line above it.
    value_xmin, value_xmax
        Horizontal extent where values sit.
    expected_seqs
        Known column sequences for this table, used when the header is
        missing or partly read.
    stop_after_z
        Ignore header words right of the z column (a graph's axis labels).
    default_phase
        Phase for columns named by position.
    fixed_columns
        Columns to use as given, skipping column detection.
    skip_lines
        Phrases marking lines inside the region that are not rows.
    row_template
        ``(y of the table title, [(param, height below the title), ...])``:
        rows whose label was not read are placed by their height on the
        page (the positional fallback). None switches it off.
    structural_blanks
        ``(param, column name)`` cells the report never fills, so their
        emptiness is not a condition.
    """
    conditions: list[Condition] = []
    region = [
        ln
        for ln in lines
        if y0 < ln.cy < y1
        and not any(find_phrase([ln], s, thresh=0.8) for s in skip_lines)
    ]
    region = merge_close_lines(region)

    # ---- columns (anchored on right edges: numbers are right-aligned)
    if fixed_columns is not None:
        cols = fixed_columns
    else:
        hdr_cols = columns_from_header(hdr_words or [], super_words, stop_after_z)
        vc = value_clusters(region, value_xmin, value_xmax)
        clusters = [a for a, _ in vc]
        cols, conds = name_columns(hdr_cols, clusters, expected_seqs, default_phase)
        conditions += conds
        spans = dict(vc)
        for col in cols:
            col.span = spans.get(col.cx)
    if not cols:
        return TableResult({}, [], conditions, [])
    cols = sorted(cols, key=lambda c: c.cx)
    seen: dict[tuple[str, str], int] = {}
    for col in cols:
        nk = (col.name, col.phase)
        if nk in seen:
            seen[nk] += 1
            conditions.append(Condition(cond.COLUMN_NAME_TWICE, col.name))
            col.name = f"{col.name}_{seen[nk]}"
        else:
            seen[nk] = 1
    xs = [c.cx for c in cols]
    spacing = min((b - a for a, b in itertools.pairwise(xs)), default=0.08)
    label_xmax = min(xs) - 0.04 - 0.3 * spacing
    right_lim = max(xs) + 0.3 * spacing

    # ---- candidate row lines
    rows: list[dict[str, Any]] = []
    for ln in region:
        ws: list[Word] = []
        for w in sorted(ln.words, key=lambda w: w.x0):
            # a '*' read as its own word belongs to the number just left of it
            t = w.text.strip()
            if (
                t
                and all(ch in STAR_CHARS for ch in t)
                and ws
                and is_numericish(ws[-1].text)
                and w.x0 - ws[-1].x1 < 0.02
            ):
                prev_w = ws[-1]
                ws[-1] = Word(
                    prev_w.text + t, prev_w.x0, prev_w.x1, prev_w.top, prev_w.bottom
                )  # keep the number's right edge
                continue
            ws.append(w)
        lab = [w for w in ws if w.cx < label_xmax]
        # every token in the value area is kept, so text where a number is expected gets flagged
        vals = [
            w
            for w in ws
            if w.cx >= label_xmax
            and w.x1 <= right_lim + 0.01
            and not is_unit(w.text)
            and (is_numericish(w.text) or re.search(r"[A-Za-z0-9]", w.text))
        ]
        if lab or vals:
            rows.append(
                {
                    "cy": statistics.fmean(w.cy for w in ws),
                    "lab": lab,
                    "vals": vals,
                    "param": None,
                }
            )
    specs = list(row_specs)
    req_order = [s.param for s in specs if s.required]
    used: set[str] = set()
    for row in rows:
        p, txt = match_label(row["lab"], specs, used)
        row["label_raw"] = txt
        if p:
            row["param"] = p
            used.add(p)

    # rows whose label was not read, placed by their height on the page (fixed report layout)
    if row_template is not None:
        y_anchor, rows_t = row_template
        tmap = dict(rows_t)
        obs = [
            (row["cy"] - y_anchor) / tmap[row["param"]]
            for row in rows
            if row["param"] in tmap and tmap[row["param"]] > 0
        ]
        scale = min(1.05, max(0.95, statistics.median(obs))) if len(obs) >= 2 else 1.0
        for row in sorted(rows, key=lambda row: row["cy"]):
            if row["param"] is None and row["vals"]:
                dy = row["cy"] - y_anchor
                best = min(
                    ((abs(dy - scale * t), p) for p, t in rows_t if p not in used),
                    default=None,
                )
                if best and best[0] < 0.0045:
                    row["param"], row["inferred"] = best[1], "template"
                    used.add(best[1])

    # complete table: every required row present as a line -> assign by order, labels verify
    optional_seen = any(row["param"] and row["param"] not in req_order for row in rows)
    positional = False
    if len(rows) == len(req_order) and not optional_seen:
        conflicts = [
            (row["param"], p)
            for row, p in zip(rows, req_order, strict=True)
            if row["param"] and row["param"] != p
        ]
        if not conflicts:
            positional = True
            for row, p in zip(rows, req_order, strict=True):
                if row["param"] is None:
                    row["param"] = p
                    row["inferred"] = "complete"
                    # flag only when the unread label looks more like ANOTHER row
                    # (e.g. 'PEE' placed as FET by position); a garbled label that
                    # still resembles its own row is fine
                    cl = canon_label(row.get("label_raw") or "")
                    if cl:
                        sc: dict[str, float] = {}
                        for sp in specs:
                            for variant in sp.labels:
                                sc[sp.param] = max(
                                    sc.get(sp.param, 0), ratio(cl, canon_label(variant))
                                )
                        other = max((v for q, v in sc.items() if q != p), default=0)
                        row["label_conflict"] = other >= 0.6 and other > sc.get(p, 0)
            used = set(req_order)
        else:
            conditions.append(
                Condition(cond.ROW_LABELS_DISAGREE_WITH_ORDER, str(conflicts))
            )
    if not positional:
        anchors = [row for row in rows if row["param"]]
        pitch = 0.016
        if len(anchors) >= 2:
            ds = [b["cy"] - a["cy"] for a, b in itertools.pairwise(anchors)]
            pitch = max(0.008, min(0.03, statistics.median(ds)))
        del pitch  # kept in v0.3.14 but unused there too
        unmatched = [
            row
            for row in rows
            if row["param"] is None and (row["vals"] or len(row["label_raw"]) >= 2)
        ]
        order_idx = {p: i for i, p in enumerate(req_order)}
        bounds = (
            [(-1, -1.0)]
            + [
                (order_idx[a["param"]], a["cy"])
                for a in anchors
                if a["param"] in order_idx
            ]
            + [(len(req_order), 2.0)]
        )
        for (ia, ya), (ib, yb) in itertools.pairwise(bounds):
            missing = [p for p in req_order[ia + 1 : ib] if p not in used]
            gap_lines = [row for row in unmatched if ya < row["cy"] < yb]
            if missing and len(missing) == len(gap_lines):
                for p, row in zip(
                    missing, sorted(gap_lines, key=lambda row: row["cy"]), strict=True
                ):
                    row["param"] = p
                    row["inferred"] = "gap"
                    used.add(p)
                    unmatched.remove(row)
        for row in unmatched:
            if row["vals"]:
                conditions.append(
                    Condition(
                        cond.ROW_UNRECOGNISED_IGNORED,
                        f"'{row['label_raw']}' with {len(row['vals'])} values",
                    )
                )
        for p in req_order:
            if p not in used:
                conditions.append(Condition(cond.ROW_NOT_FOUND, p))
    anchors = sorted([row for row in rows if row["param"]], key=lambda row: row["cy"])

    # ---- assign value tokens to (row, column): overlap with the column's value span,
    # else nearest right edge
    cells: dict[tuple[str, str, str], Cell] = {}
    col_tol = 0.5 * spacing
    for col in cols:
        if col.span is None:
            col.span = (col.cx - 0.035, col.cx)

    def pick_col(w: Word) -> int | None:
        if (
            w.x0 > cols[-1].cx - 0.005
        ):  # starts right of the last column: chart text, not a value
            return -1
        ov = [
            (min(w.x1, c.span[1]) - max(w.x0, c.span[0]), i)
            for i, c in enumerate(cols)
            if c.span
        ]
        best = max(ov)
        if best[0] > 0:
            return best[1]
        i = min(range(len(cols)), key=lambda k: abs(cols[k].cx - w.x1))
        return i if abs(cols[i].cx - w.x1) <= col_tol else None

    for a in anchors:
        row_words = a["lab"] + a["vals"]
        rb: BBox | None = None
        if row_words:
            b0 = bbox_of(row_words)
            rb = (min(b0[0], 0.03), b0[1], max(b0[2], right_lim), b0[3])
        by_col: dict[int, list[Word]] = {i: [] for i in range(len(cols))}
        for w in a["vals"]:
            i = pick_col(w)
            if i == -1:
                continue
            if i is not None:
                by_col[i].append(w)
            else:
                conditions.append(
                    Condition(cond.TOKEN_NOT_UNDER_COLUMN, f"row {a['param']}")
                )
        for i, col in enumerate(cols):
            ws2 = sorted(by_col[i], key=lambda w: w.x0)
            if ws2:
                parts: list[str] = []
                prev = None
                for w in ws2:
                    if prev is not None and w.x0 - prev.x1 > 0.012:
                        parts.append(" ")
                    parts.append(w.text)
                    prev = w
                raw = "".join(parts)
                bb = bbox_of(ws2)
            else:
                raw = ""
                cy = a["cy"]
                bb = (col.cx - 0.04, cy - 0.008, col.cx + 0.005, cy + 0.008)
            cells[(a["param"], col.phase, col.name)] = Cell(
                raw,
                bb,
                rb,
                a.get("inferred"),
                a.get("label_raw", ""),
                a.get("label_conflict", False),
            )
    # blank cells: note where the column is mostly filled and the row is mostly filled
    # (structurally empty cells, e.g. IC without reference values, are not noted);
    # a row with no values at all gets its normally-filled cells noted
    rows_p = {k[0] for k in cells}
    for ck, cell in cells.items():
        if cell.raw:
            continue
        row_fill = [cells[(ck[0], col.phase, col.name)].raw != "" for col in cols]
        others = [q for q in rows_p if q != ck[0] and (q, ck[1], ck[2]) in cells]
        col_fill = [cells[(q, ck[1], ck[2])].raw != "" for q in others]
        col_mostly = bool(col_fill) and sum(col_fill) >= 0.5 * len(col_fill)
        if (ck[0], ck[2]) in structural_blanks:
            continue
        if col_mostly and sum(row_fill) > 0.5 * len(row_fill):
            cell.empty_in_filled_col = True
        elif col_mostly and ck[2] in ("value", "best") and not any(row_fill):
            cell.row_empty = True
    for a in anchors:
        if not any(cells[(a["param"], col.phase, col.name)].raw for col in cols):
            conditions.append(Condition(cond.ROW_NO_VALUES, a["param"]))
    return TableResult(cells, cols, conditions, [a["param"] for a in anchors])
