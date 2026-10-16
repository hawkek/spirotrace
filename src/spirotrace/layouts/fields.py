"""Labelled header fields: ``Label  value`` pairs read by their label."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from spirotrace.ingest import BBox, Line, Word, bbox_of

from . import conditions as cond
from .conditions import Condition
from .text import Match, find_all_phrase, find_phrase, norm
from .tokens import _CONF, parse_date

FieldKind = Literal["num", "text", "date"]


@dataclass(frozen=True, slots=True)
class FieldSpec:
    """A header field: a name, the label variants to look for, and its kind."""

    name: str
    labels: tuple[str, ...]
    kind: FieldKind


@dataclass(slots=True)
class FieldRead:
    """What was read for one field.

    ``value`` is the number for ``num`` fields, the text for ``text`` fields,
    and for ``date`` fields the ISO date (None when not parsed). ``raw`` is
    the text after the label; ``""`` when nothing followed it.
    """

    name: str
    kind: FieldKind
    raw: str
    value: float | str | None
    bbox: BBox
    row_bbox: BBox
    conditions: list[Condition] = field(default_factory=list)


def header_fields(
    lines: Sequence[Line],
    specs: Sequence[FieldSpec],
    boundaries: Sequence[str],
    ymax: float,
    vocab: Mapping[str, Sequence[str]] | None = None,
) -> list[FieldRead]:
    """Read every field in ``specs`` from the lines above ``ymax``.

    Every candidate label position of every field is scored first, then the
    best scores are assigned, each position to one field only (an OCR'd
    "Weiqht" must not let Weight take the Height label and its value).
    ``boundaries`` are other labels on the same lines (never read as values)
    that end a value. ``vocab`` lists the expected categories of text fields;
    a value outside it is a condition, not an error.
    """
    vocab = vocab or {}
    region = [ln for ln in lines if ln.cy < ymax]
    cands: list[tuple[float, int, FieldSpec, Match]] = []
    for si, spec in enumerate(specs):
        for lab in spec.labels:
            for m in find_all_phrase(region, lab, thresh=0.8):
                cands.append((m.score, -si, spec, m))
    cands.sort(key=lambda c: (c[0], c[1]), reverse=True)
    found: dict[str, tuple[Match, FieldSpec]] = {}
    taken: list[Match] = []

    def overlaps(a: Match, b: Match) -> bool:
        return a.line is b.line and a.x0 < b.x1 and b.x0 < a.x1

    for _, _, spec, m in cands:
        if spec.name in found or any(overlaps(m, t) for t in taken):
            continue
        found[spec.name] = (m, spec)
        taken.append(m)
    bounds: list[Match] = []
    for lab in boundaries:
        bm = find_phrase(region, lab, thresh=0.8)
        if bm:
            bounds.append(bm)
    all_labels = [m for m, _ in found.values()] + bounds
    out: list[FieldRead] = []
    for m, spec in found.values():
        same = [
            w for w in m.line.words if w.x0 > m.x1 + 0.002 and abs(w.cy - m.cy) < 0.008
        ]
        stops = [
            o.x0
            for o in all_labels
            if o is not m and abs(o.cy - m.cy) < 0.008 and o.x0 > m.x1
        ]
        lim = min(stops) if stops else 1.0
        vw: list[Word] = [w for w in same if w.x1 <= lim + 0.005]
        raw = " ".join(w.text for w in vw).strip()
        bb = (
            bbox_of(vw)
            if vw
            else (m.x1, m.line.top, min(lim, m.x1 + 0.2), m.line.bottom)
        )
        rb = (m.x0, m.line.top, min(lim, 1.0), m.line.bottom)
        fr = FieldRead(spec.name, spec.kind, raw, None, bb, rb)
        if spec.kind == "num":
            joined = (
                re.sub(r"(\d)\s*([.,])\s*(\d)", r"\1\2\3", raw) if raw else ""
            )  # '172. 5'
            num = re.search(r"-?\d+(?:[.,]\d+)?", joined.translate(_CONF))
            if num:
                fr.value = float(num.group(0).replace(",", "."))
            elif raw:
                fr.conditions.append(Condition(cond.NOT_A_NUMBER, raw))
            else:
                fr.conditions.append(Condition(cond.FIELD_NO_VALUE))
        elif spec.kind == "date":
            d = parse_date(raw)
            fr.value = d.isoformat() if d else None
            if raw and d is None:
                fr.conditions.append(Condition(cond.DATE_NOT_PARSED, raw))
        else:
            fr.value = raw if raw != "" else None
            expected = vocab.get(spec.name)
            if raw and expected and not any(norm(raw) == norm(t) for t in expected):
                fr.conditions.append(Condition(cond.FIELD_UNEXPECTED_CATEGORY, raw))
        out.append(fr)
    return out
