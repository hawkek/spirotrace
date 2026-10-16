"""Fuzzy phrase finding on lines of words (OCR tolerant)."""

from __future__ import annotations

import difflib
import re
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from spirotrace.ingest import Line, Word

_NORM_RE = re.compile(r"[^a-z0-9%/+]")


def norm(s: str) -> str:
    """Lowercase alphanumerics (plus ``% / +``), everything else dropped."""
    return _NORM_RE.sub("", s.lower())


def ratio(a: str, b: str) -> float:
    """Similarity of two strings, 0 to 1."""
    return difflib.SequenceMatcher(None, a, b).ratio()


@dataclass(frozen=True, slots=True)
class Match:
    """A phrase found on a line: the words that matched and how well."""

    line: Line
    words: tuple[Word, ...]
    score: float

    @property
    def cy(self) -> float:
        return statistics.fmean(w.cy for w in self.words)

    @property
    def x0(self) -> float:
        return min(w.x0 for w in self.words)

    @property
    def x1(self) -> float:
        return max(w.x1 for w in self.words)


def find_phrase(
    lines: Sequence[Line],
    phrase: str,
    ymin: float = 0.0,
    ymax: float = 1.0,
    xmin: float = 0.0,
    xmax: float = 1.0,
    thresh: float = 0.8,
    first: bool = False,
) -> Match | None:
    """Fuzzy-find ``phrase`` within the given page region.

    Word runs one shorter and one longer than the phrase are also tried, so a
    split or merged OCR token still matches. Returns the best match above
    ``thresh``, or with ``first=True`` the top-most one; None if nothing
    reaches the threshold.
    """
    target = norm(phrase)
    n = len(phrase.split())
    best: Match | None = None
    hits: list[Match] = []
    for ln in lines:
        if not (ymin <= ln.cy <= ymax):
            continue
        ws = [w for w in ln.words if xmin <= w.cx <= xmax]
        for k in sorted({max(1, n - 1), n, n + 1}):
            for i in range(len(ws) - k + 1):
                cand = norm("".join(w.text for w in ws[i : i + k]))
                if not cand or abs(len(cand) - len(target)) > max(3, len(target) // 2):
                    continue
                r = ratio(cand, target)
                if r >= thresh:
                    hits.append(Match(ln, tuple(ws[i : i + k]), r))
                if best is None or r > best.score:
                    best = Match(ln, tuple(ws[i : i + k]), r)
    if not hits:
        return None
    if first:
        return min(hits, key=lambda m: (round(m.cy, 3), -m.score))
    return max(hits, key=lambda m: m.score)


def find_all_phrase(
    lines: Sequence[Line], phrase: str, thresh: float = 0.8, **kw: Any
) -> list[Match]:
    """Every line's best match of ``phrase`` above ``thresh``, in line order."""
    out = []
    for ln in lines:
        m = find_phrase([ln], phrase, thresh=thresh, **kw)
        if m:
            out.append(m)
    return out


def has_phrase(lines: Sequence[Line], phrase: str, **kw: Any) -> bool:
    return find_phrase(lines, phrase, **kw) is not None


def has_title(lines: Sequence[Line], phrase: str, **kw: Any) -> bool:
    """Phrase that stands as a (short) section title line, not inside running text."""
    n = len(phrase.split())
    short = [ln for ln in lines if len(ln.words) <= n + 2]
    return find_phrase(short, phrase, **kw) is not None


def has_line_start(lines: Sequence[Line], phrase: str, **kw: Any) -> bool:
    """Phrase at the start of a line (a footnote or heading), not inside a sentence."""
    for ln in lines:
        m = find_phrase([ln], phrase, **kw)
        if m is not None and m.words[0] is min(ln.words, key=lambda w: w.x0):
            return True
    return False
