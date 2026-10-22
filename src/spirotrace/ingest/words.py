"""Words and lines in page-normalised coordinates, line grouping and deskew.

Every coordinate is a fraction of the page width or height (0 to 1, origin
top-left), so geometry measured on one scan applies to any resolution.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass

BBox = tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class Word:
    """One word of the text layer (or of an OCR engine) with its box."""

    text: str
    x0: float
    x1: float
    top: float
    bottom: float

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.top + self.bottom) / 2

    @property
    def h(self) -> float:
        return self.bottom - self.top


@dataclass(frozen=True, slots=True)
class Line:
    """Words sharing a vertical centre, left to right."""

    words: tuple[Word, ...]

    @property
    def cy(self) -> float:
        return statistics.fmean(w.cy for w in self.words)

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)

    @property
    def x0(self) -> float:
        return min(w.x0 for w in self.words)

    @property
    def x1(self) -> float:
        return max(w.x1 for w in self.words)

    @property
    def top(self) -> float:
        return min(w.top for w in self.words)

    @property
    def bottom(self) -> float:
        return max(w.bottom for w in self.words)


def bbox_of(words: Sequence[Word]) -> BBox:
    """Smallest box around ``words`` (which must not be empty)."""
    return (
        min(w.x0 for w in words),
        min(w.top for w in words),
        max(w.x1 for w in words),
        max(w.bottom for w in words),
    )


def group_lines(words: Sequence[Word], tol: float | None = None) -> list[Line]:
    """Group words into text lines by vertical centre.

    The tolerance defaults to 35% of the median word height: scanned lines
    wobble, but neighbouring table rows sit more than half a word apart.
    """
    if not words:
        return []
    hs = sorted(w.h for w in words if w.h > 0) or [0.01]
    medh = hs[len(hs) // 2]
    tol = tol if tol is not None else max(0.35 * medh, 0.002)
    ws = sorted(words, key=lambda w: w.cy)
    lines: list[Line] = []
    cur = [ws[0]]
    cur_cy = ws[0].cy
    for w in ws[1:]:
        if abs(w.cy - cur_cy) <= tol:
            cur.append(w)
            cur_cy = statistics.fmean(x.cy for x in cur)
        else:
            lines.append(Line(tuple(sorted(cur, key=lambda w: w.x0))))
            cur, cur_cy = [w], w.cy
    lines.append(Line(tuple(sorted(cur, key=lambda w: w.x0))))
    return lines


def deskew(words: Sequence[Word]) -> tuple[list[Word], float]:
    """Estimate residual scan skew from long text lines and remove it.

    Returns the corrected words and the slope removed: 0.0 when fewer than
    three long lines exist, or the slope is negligible, or it is too large to
    be a scan skew (then it is left alone rather than guessed).
    """
    slopes = []
    for ln in group_lines(words):
        ws = ln.words
        if len(ws) >= 4 and ws[-1].cx - ws[0].cx > 0.3:
            xs = [w.cx for w in ws]
            ys = [w.cy for w in ws]
            mx, my = statistics.fmean(xs), statistics.fmean(ys)
            den = sum((x - mx) ** 2 for x in xs)
            if den > 0:
                slopes.append(
                    sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / den
                )
    if len(slopes) < 3:
        return list(words), 0.0
    s = statistics.median(slopes)
    if abs(s) < 1e-4 or abs(s) > 0.05:
        return list(words), 0.0
    out = []
    for w in words:
        d = -s * (w.cx - 0.5)
        out.append(Word(w.text, w.x0, w.x1, w.top + d, w.bottom + d))
    return out, s
