"""Token grammar: what a cell's text means (number, dash, empty, marked) and dates.

Which characters count as a printed dash, which OCR confusions are repaired
(``O`` for ``0``, ``~`` for a minus) and which characters are the report's
out-of-range marker are decided here and nowhere else.

A cell holding only ``~``, ``_`` or ``=`` is OCR's reading of a printed dash
(the scanner's short horizontal stroke); it is a dash, with the ``dash_variant``
flag so the reading can be noted. A leading ``~`` or ``_`` before digits is a
minus sign instead.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

DASHES: frozenset[str] = frozenset({"-", "–", "—", "−", "--", "‐", "‑"})
"""Printed-dash forms and their common OCR readings."""

_DASH_VARIANTS = ("‐", "‑", "‒", "–", "—", "−", "﹣", "－")

DASH_OCR_VARIANTS: frozenset[str] = frozenset({"~", "_", "="})
"""What OCR makes of a printed dash on its own in a cell."""
_DASH_OCR_RE = re.compile(r"[~_=]+")

_CONF = str.maketrans(
    {
        "O": "0",
        "o": "0",
        "D": "0",
        "Q": "0",
        "l": "1",
        "I": "1",
        "|": "1",
        "i": "1",
        "!": "1",
        "S": "5",
        "s": "5",
        "B": "8",
        "Z": "2",
        "z": "2",
        "g": "9",
        "q": "9",
        ",": ".",
        "–": "-",
        "—": "-",
        "−": "-",
    }
)
"""OCR letter-for-digit confusions repaired inside a numeric token."""

STAR_CHARS = "*•●∗◊°"
"""The report's out-of-range marker and what OCR makes of it."""

FLAG_STAR = "star"
FLAG_MINUS_GUESS = "minus_guess"
FLAG_EMPTY = "empty"
FLAG_DASH = "dash"
FLAG_DASH_VARIANT = "dash_variant"
FLAG_COMMA = "comma"
FLAG_CHAR_FIX = "char_fix"
FLAG_UNPARSEABLE = "unparseable"

_NUMERICISH_RE = re.compile(r"[-–—−‐‑+~_]?[\dOoDQlI|i!SsBZzgq.,·]+%?")
_PLAIN_NUMBER_RE = re.compile(r"-?\d+(\.\d+)?")


@dataclass(frozen=True, slots=True)
class NumberParse:
    """Result of :func:`parse_number`.

    ``text`` is the repaired numeric string (``"-0.55"`` for ``"~0.55"``),
    empty when no number was found; the ratio parser reads it.
    """

    value: float | None
    flags: frozenset[str]
    decimals: int | None
    text: str


def clean_token(t: str) -> str:
    return t.strip().strip("[](){}:;,'\"`~_ ")


def is_numericish(t: str) -> bool:
    """True for a dash or a token made of digits and their OCR look-alikes."""
    s = t.strip()
    for ch in STAR_CHARS:
        s = s.replace(ch, "")
    if _DASH_OCR_RE.fullmatch(s.strip()):
        return True  # OCR's reading of a printed dash
    s = clean_token(s)
    if s in DASHES:
        return True
    if not re.search(r"\d", s):
        return False
    return bool(_NUMERICISH_RE.fullmatch(s))


def parse_number(raw: str) -> NumberParse:
    """Read a printed number, repairing common OCR confusions.

    The flags say what happened: ``star`` (marker removed), ``minus_guess``
    (a leading ``~`` or ``_`` read as a minus sign), ``comma`` (decimal comma),
    ``char_fix`` (letters repaired to digits), ``empty``, ``dash`` (with
    ``dash_variant`` when the dash was read as ``~``, ``_`` or ``=``) or
    ``unparseable``. A dash and an empty cell both give no value.
    """
    flags: set[str] = set()
    s = raw.strip()
    if any(ch in s for ch in STAR_CHARS):
        flags.add(FLAG_STAR)
        for ch in STAR_CHARS:
            s = s.replace(ch, "")
    s = re.sub(
        r"\(cid:\d+\)$", "", s
    )  # unmapped glyph after a number (usually the marker)
    s = s.strip().strip('[](){}:;,"` ')
    if s and _DASH_OCR_RE.fullmatch(s):
        return NumberParse(
            None, frozenset(flags | {FLAG_DASH, FLAG_DASH_VARIANT}), None, ""
        )
    for d in _DASH_VARIANTS:
        s = s.replace(d, "-")  # dash variants are a minus sign, not a decimal problem
    if re.match(r"^[~_¬]+\s*\d", s):  # a minus sign read as ~ or _ (common on z-scores)
        s = "-" + re.sub(r"^[~_¬]+", "", s)
        flags.add(FLAG_MINUS_GUESS)
    s = s.strip("~_' ").replace(" ", "")
    if s.startswith("+") and re.fullmatch(r"\+[\d.,]+%?", s):
        s = s[1:]
    if s == "":
        return NumberParse(None, frozenset(flags | {FLAG_EMPTY}), None, "")
    if s in DASHES:
        return NumberParse(None, frozenset(flags | {FLAG_DASH}), None, "")
    s = s.rstrip("%")
    soft = s.replace(",", ".").replace("·", ".")
    if soft != s and _PLAIN_NUMBER_RE.fullmatch(soft):
        flags.add(FLAG_COMMA)
        fixed = soft
    else:
        fixed = soft.translate(_CONF)
        if fixed != s:
            flags.add(FLAG_CHAR_FIX)
    fixed = re.sub(r"\.{2,}", ".", fixed)
    if not _PLAIN_NUMBER_RE.fullmatch(fixed):
        return NumberParse(None, frozenset(flags | {FLAG_UNPARSEABLE}), None, "")
    dec = len(fixed.split(".")[1]) if "." in fixed else 0
    return NumberParse(float(fixed), frozenset(flags), dec, fixed)


UNIT_RE = re.compile(r"^[\[\(][^\[\]()]{0,14}[\]\)]?$|^[^\[\]()]{1,14}[\]\)]$")


def is_unit(t: str) -> bool:
    """Unit text printed between the row label and the values (``[L]``, ``(L]``, ``[%]``).

    OCR can read ``[L]`` as ``[1]``, which would otherwise look like a column
    of numbers; a bracketed decimal number is still a number.
    """
    t = t.strip()
    return bool(UNIT_RE.match(t)) and not re.fullmatch(r"[\(\[]?-?\d+[.,]\d+[\)\]]?", t)


def parse_date(s: str) -> dt.date | None:
    """Read an ISO or a day-first date (``dd/mm/yyyy``, two-digit years as 20yy)."""
    if not s:
        return None
    iso = re.search(r"(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)", s)
    if iso:
        y, mo, d = (int(x) for x in iso.groups())
        try:
            return dt.date(y, mo, d)
        except ValueError:
            return None
    m = re.search(r"(?<!\d)(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4}|\d{2})(?!\d)", s)
    if not m:
        return None
    d, mo, y = (int(x) for x in m.groups())
    if y < 100:
        y += 2000
    try:
        return dt.date(y, mo, d)  # day first
    except ValueError:
        return None
